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

from dataclasses import dataclass, field
from typing import Any, Literal

from .candidates import build_candidates
from .config import Config
from .contracts import ABSTAIN, REOBSERVE, Candidate, Choice, DecisionError, validate_choice
from .driver import Driver, DriverError, Observation
from .jev import Chooser

Outcome = Literal["done", "abstained", "exhausted", "escalate", "error"]


@dataclass
class Step:
    index: int
    observation: Observation
    choice: Choice
    candidate: Candidate | None
    executed: bool
    note: str = ""


@dataclass
class Run:
    goal: str
    outcome: Outcome
    steps: list[Step] = field(default_factory=list)
    message: str = ""

    @property
    def actions_taken(self) -> int:
        return sum(1 for step in self.steps if step.executed)


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
    ) -> Run:
        history: list[dict[str, Any]] = []
        steps: list[Step] = []
        # Reobservar so ajuda se a tela mudar. Sem progresso, para de girar.
        stalled = 0
        max_stalled = 3

        for index in range(self._config.max_steps):
            # (1) observacao nova a cada iteracao -- refs sao locais a ela
            try:
                observation = self._driver.observe(app)
            except DriverError as exc:
                return Run(goal, "error", steps, f"falha ao observar: {exc}")

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
            try:
                choice = self._chooser(
                    goal=goal,
                    observation=observation.compact(),
                    history=history,
                    candidates=candidates,
                )
            except DecisionError as exc:
                return Run(goal, "error", steps, f"falha na decisao: {exc}")

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
                steps.append(Step(index, observation, choice, candidate, False, "confianca no chao"))
                history.append(_history_entry(candidate, choice, executed=False))
                if stalled >= max_stalled:
                    self._emit("escalate", "Confianca baixa e a tela nao muda.")
                    return Run(goal, "escalate", steps, "confianca baixa apos reobservar")
                self._emit("low", f"Confianca baixa ({choice.confidence:.0%}). Reobservando.")
                continue

            if choice.confidence < self._config.act_threshold:
                steps.append(Step(index, observation, choice, candidate, False, "escalado"))
                self._emit(
                    "escalate",
                    f"Nao tenho certeza ({choice.confidence:.0%}): {candidate.description}",
                )
                return Run(goal, "escalate", steps, candidate.description)

            if candidate.id == ABSTAIN:
                steps.append(Step(index, observation, choice, candidate, False, "abstain"))
                self._emit("abstain", "Nenhuma acao segura para esta tela.")
                return Run(goal, "abstained", steps, "abstencao")

            if candidate.id == REOBSERVE:
                stalled += 1
                steps.append(Step(index, observation, choice, candidate, False, "reobserve"))
                history.append(_history_entry(candidate, choice, executed=False))
                if stalled >= max_stalled:
                    self._emit("escalate", "Pedi observacao nova varias vezes sem avancar.")
                    return Run(goal, "escalate", steps, "sem progresso apos reobservar")
                continue

            if dry_run:
                steps.append(Step(index, observation, choice, candidate, False, "dry-run"))
                self._emit("dry", f"[dry-run] {candidate.tool} {dict(candidate.arguments)}")
                return Run(goal, "done", steps, candidate.description)

            # (7) no maximo UMA acao por iteracao
            assert candidate.tool is not None
            try:
                self._driver.execute(candidate.tool, dict(candidate.arguments))
            except DriverError as exc:
                steps.append(Step(index, observation, choice, candidate, False, str(exc)))
                return Run(goal, "error", steps, f"falha ao executar: {exc}")

            steps.append(Step(index, observation, choice, candidate, True))
            history.append(_history_entry(candidate, choice, executed=True))
            self._emit("acted", candidate.description)

            # (8) a verificacao da pos-condicao acontece na proxima observacao
            return Run(goal, "done", steps, candidate.description)

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
