"""O loop de decisao.

Segue os passos do skills/jev-use/SKILL.md do cua:

  1. objetivo + observacao nova do Driver
  2. preferir evidencia semantica fresca (arvore de acessibilidade)
  3. grounding visual so com capture_id valido -- senao reobservar ou abster
  4. montar tabela limitada de candidatos completos (+ reobserve/abstain)
  5. mandar ao Jev so objetivo, observacao compacta, historico e IDs
  6. resolver o ID contra a tabela original; rejeitar desconhecido/velho/inseguro
  7. executar no maximo UMA acao
  8. reobservar e verificar a pos-condicao antes da proxima tabela
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from .candidates import build_candidates
from .config import Config
from .contracts import ABSTAIN, REOBSERVE, Candidate, Choice, DecisionError, validate_choice
from .driver import Driver, DriverError, Observation
from .jev import Chooser

# "unverified": a acao foi enviada, mas nada mudou na tela. O Driver
# responde `effect: "unverifiable"` -- ele nao promete sucesso -- e
# anunciar "done" nesse caso e relatar exito que nao houve.
Outcome = Literal[
    "done", "unverified", "abstained", "exhausted", "escalate", "error"
]


@dataclass
class Step:
    index: int
    observation: Observation
    choice: Choice
    candidate: Candidate | None
    executed: bool
    note: str = ""
    # Tempo de cada etapa, para diagnostico e para uma UI mostrar depois.
    observe_ms: float = 0.0
    decide_ms: float = 0.0
    execute_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.observe_ms + self.decide_ms + self.execute_ms


@dataclass
class Run:
    goal: str
    outcome: Outcome
    steps: list[Step] = field(default_factory=list)
    message: str = ""

    @property
    def actions_taken(self) -> int:
        return sum(1 for step in self.steps if step.executed)

    @property
    def total_ms(self) -> float:
        return sum(step.total_ms for step in self.steps)

    def timing(self) -> dict[str, float]:
        """Tempo por etapa somado. A soma nao e so o Jev: observar a tela
        costuma custar mais que decidir."""
        return {
            "observe_ms": sum(s.observe_ms for s in self.steps),
            "decide_ms": sum(s.decide_ms for s in self.steps),
            "execute_ms": sum(s.execute_ms for s in self.steps),
            "total_ms": self.total_ms,
        }


class Agent:
    def __init__(
        self,
        driver: Driver,
        chooser: Chooser,
        config: Config,
        *,
        on_event: Any = None,
    ) -> None:
        self._driver = driver
        self._chooser = chooser
        self._config = config
        self._on_event = on_event or (lambda kind, text: None)

    def _emit(self, kind: str, text: str) -> None:
        self._on_event(kind, text)

    def run(
        self,
        goal: str,
        *,
        app: str | None = None,
        dry_run: bool = False,
        must_include: str | None = None,
        speech_hint: dict[str, Any] | None = None,
    ) -> Run:
        history: list[dict[str, Any]] = []
        steps: list[Step] = []
        # Reobservar so ajuda se a tela mudar. Sem progresso, para de girar.
        stalled = 0
        max_stalled = 3

        for index in range(self._config.max_steps):
            # (1) observacao nova a cada iteracao -- refs sao locais a ela
            marca = time.perf_counter()
            try:
                observation = self._driver.observe(app)
            except DriverError as exc:
                return Run(goal, "error", steps, f"falha ao observar: {exc}")
            observe_ms = (time.perf_counter() - marca) * 1000

            # (4) tabela limitada de acoes completas
            candidates = build_candidates(
                observation,
                text_to_type=_text_argument(goal),
                max_candidates=self._config.max_candidates,
                must_include=must_include,
            )
            if len(candidates) <= 2:  # so reobserve/abstain
                return Run(goal, "error", steps, "nenhuma acao possivel na tela observada")

            # (5) decisao: o Jev ve so o que precisa para escolher
            compacta = observation.compact()
            if speech_hint:
                # A dica diz o que o reconhecedor achou, sem decidir por ele.
                # Reescrever o objetivo como "clicar em X" apagava a frase
                # original, e o Jev confirmava qualquer coisa: contar uma
                # historia com a palavra "parado" virava um clique.
                compacta["speech"] = speech_hint
            marca = time.perf_counter()
            try:
                choice = self._chooser(
                    goal=goal,
                    observation=compacta,
                    history=history,
                    candidates=candidates,
                )
            except DecisionError as exc:
                return Run(goal, "error", steps, f"falha na decisao: {exc}")
            decide_ms = (time.perf_counter() - marca) * 1000

            # (6) resolver contra a tabela original imutavel -- falha fechado
            try:
                candidate = validate_choice(
                    choice.selected_id,
                    candidates,
                    current_capture_id=observation.capture_id,
                )
            except DecisionError as exc:
                return Run(goal, "error", steps, f"escolha rejeitada: {exc}")

            # (6b) politica de confianca
            if choice.confidence < self._config.floor_threshold:
                stalled += 1
                steps.append(Step(index, observation, choice, candidate, False, "confianca no chao",
                     observe_ms, decide_ms))
                history.append(_history_entry(candidate, choice, executed=False))
                if stalled >= max_stalled:
                    self._emit("escalate", "Confianca baixa e a tela nao muda.")
                    return Run(goal, "escalate", steps, "confianca baixa apos reobservar")
                self._emit("low", f"Confianca baixa ({choice.confidence:.0%}). Reobservando.")
                continue

            if choice.confidence < self._config.act_threshold:
                steps.append(Step(index, observation, choice, candidate, False, "escalado",
                     observe_ms, decide_ms))
                self._emit(
                    "escalate",
                    f"Nao tenho certeza ({choice.confidence:.0%}): {candidate.description}",
                )
                return Run(goal, "escalate", steps, candidate.description)

            if candidate.id == ABSTAIN:
                steps.append(Step(index, observation, choice, candidate, False, "abstain",
                     observe_ms, decide_ms))
                self._emit("abstain", "Nenhuma acao segura para esta tela.")
                return Run(goal, "abstained", steps, "abstencao")

            if candidate.id == REOBSERVE:
                stalled += 1
                steps.append(Step(index, observation, choice, candidate, False, "reobserve",
                     observe_ms, decide_ms))
                history.append(_history_entry(candidate, choice, executed=False))
                if stalled >= max_stalled:
                    self._emit("escalate", "Pedi observacao nova varias vezes sem avancar.")
                    return Run(goal, "escalate", steps, "sem progresso apos reobservar")
                continue

            if dry_run:
                steps.append(Step(index, observation, choice, candidate, False, "dry-run",
                     observe_ms, decide_ms))
                self._emit("dry", f"[dry-run] {candidate.tool} {dict(candidate.arguments)}")
                return Run(goal, "done", steps, candidate.description)

            # (7) no maximo UMA acao por iteracao
            assert candidate.tool is not None
            marca = time.perf_counter()
            try:
                self._driver.execute(candidate.tool, dict(candidate.arguments))
            except DriverError as exc:
                steps.append(Step(index, observation, choice, candidate, False, str(exc),
                                  observe_ms, decide_ms))
                return Run(goal, "error", steps, f"falha ao executar: {exc}")
            execute_ms = (time.perf_counter() - marca) * 1000

            # (8) verificacao da pos-condicao -- de verdade, nao como comentario.
            #
            # O Driver responde `effect: "unverifiable"`: ele entregou a acao
            # mas nao afirma que surtiu efeito. Anunciar "done" em cima disso
            # e inventar um exito. Numa sessao real, seis cliques foram
            # relatados como feitos sem nada ter acontecido na tela.
            antes = observation.signature()
            verificado = False
            nota = ""
            try:
                depois = self._driver.observe(app).signature()
                verificado = depois != antes
                if not verificado:
                    nota = "a tela nao mudou apos a acao"
            except DriverError as exc:
                nota = f"nao consegui reobservar para verificar: {exc}"

            steps.append(Step(index, observation, choice, candidate, True, nota,
                              observe_ms, decide_ms, execute_ms))
            history.append(_history_entry(candidate, choice, executed=True))

            if verificado:
                self._emit("acted", candidate.description)
                return Run(goal, "done", steps, candidate.description)

            self._emit("unverified", f"{candidate.description} ({nota})")
            return Run(goal, "unverified", steps, f"{candidate.description} -- {nota}")

        return Run(goal, "exhausted", steps, f"limite de {self._config.max_steps} passos")


def _history_entry(candidate: Candidate, choice: Choice, *, executed: bool) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "description": candidate.description,
        "confidence": round(choice.confidence, 3),
        "executed": executed,
    }


def _text_argument(goal: str) -> str | None:
    """Extrai texto entre aspas do comando, para preencher campos.

    Exemplo:  escreve "relatorio final" no nome do arquivo
    """
    for quote in ('"', "'"):
        if goal.count(quote) >= 2:
            start = goal.index(quote)
            end = goal.index(quote, start + 1)
            value = goal[start + 1 : end].strip()
            if value:
                return value
    return None
