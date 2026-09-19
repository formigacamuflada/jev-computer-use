"""Adaptador do TypeSafe Jev.

Fala HTTP direto (sem dependencia externa) com POST /v1/systemone.
Dois backends: `mock` (deterministico, roda sem credencial) e `live`.

Regra que vem do SKILL.md do cua e nao se quebra:
  o Jev recebe so o objetivo, a observacao compacta, o historico e os IDs dos
  candidatos com descricao. Ele devolve um ID. Nunca nome de ferramenta,
  coordenada, ref ou argumento.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Mapping, Protocol

from .contracts import (
    ABSTAIN,
    Candidate,
    Choice,
    DecisionError,
    Usage,
    criteria_from,
    margin_confidence,
    validate_confidence,
    validate_probabilities,
)

API_URL = "https://api.typesafe.ai/v1/systemone"
REQUEST_SCHEMA = "cua.jev_choice_request_v1"
RESPONSE_SCHEMA = "cua.jev_choice_v1"

INSTRUCTIONS = "Which complete executable action should the desktop driver run next?"


class Chooser(Protocol):
    def __call__(
        self,
        *,
        goal: str,
        observation: Mapping[str, Any],
        history: list[dict[str, Any]],
        candidates: list[Candidate],
    ) -> Choice: ...


def build_request(
    *,
    goal: str,
    observation: Mapping[str, Any],
    history: list[dict[str, Any]],
    candidates: list[Candidate],
    model: str,
) -> dict[str, Any]:
    """Monta o corpo da chamada. So dados de decisao entram aqui."""
    criteria = criteria_from(candidates)
    return {
        "model": model,
        "state": {
            "schema": REQUEST_SCHEMA,
            "goal": goal,
            "observation": dict(observation),
            "history": history[-5:],
        },
        "questions": {
            "driver_action": {
                "type": "choice",
                "instructions": INSTRUCTIONS,
                "criteria": criteria,
            },
            "reversible": {
                "type": "noul",
                "instructions": (
                    "The selected action is reversible and safe to perform "
                    "without asking the user to confirm first."
                ),
            },
        },
    }


def parse_response(
    payload: Mapping[str, Any],
    candidates: list[Candidate],
    latency_ms: float = 0.0,
) -> Choice:
    criteria = criteria_from(candidates)
    answers = payload.get("answers")
    if not isinstance(answers, Mapping):
        raise DecisionError("resposta sem o campo 'answers'")

    answer = answers.get("driver_action")
    if not isinstance(answer, Mapping):
        raise DecisionError("resposta sem a answer 'driver_action'")

    selected = answer.get("choice")
    if selected not in criteria:
        raise DecisionError(f"Jev escolheu candidato desconhecido: {selected!r}")

    probabilities = validate_probabilities(answer.get("probabilities") or {}, criteria)
    provider_confidence = validate_confidence(answer.get("confidence", 0.0))
    # A confianca que vale e a calculada aqui, igual a do mock: o campo da API
    # e corrigido pelo acaso e encolhe quando a tabela cresce, entao compara-lo
    # com um limiar fixo compara coisas diferentes a cada passo. Sem as
    # probabilidades nao da para calcular margem nenhuma -- ai o numero do
    # provider e melhor que zero.
    confidence = margin_confidence(probabilities) if probabilities else provider_confidence
    model = payload.get("model")

    consumo = payload.get("usage") or {}
    usage = Usage(
        latency_ms=latency_ms,
        input_tokens=int(consumo.get("input_tokens") or 0),
        output_tokens=int(consumo.get("output_tokens") or 0),
    )

    return Choice(
        selected_id=str(selected),
        confidence=confidence,
        probabilities=probabilities,
        model=model if isinstance(model, str) else None,
        source="live",
        usage=usage,
        provider_confidence=provider_confidence,
    )


class LiveJev:
    """Cliente HTTP do Jev.

    O timeout e curto de proposito. O Jev responde em cerca de 900 ms, entao
    esperar 30 segundos nao recupera nada -- so trava a sessao. Com rede ruim,
    o pior caso aqui fica em torno de 18 segundos em vez de 95, e o usuario
    recebe um erro em vez de apertar Ctrl+C no meio.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "jev-latest",
        timeout: float = 8.0,
        retries: int = 2,
    ) -> None:
        if not api_key:
            raise ValueError("TYPESAFE_API_KEY ausente")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._retries = max(1, retries)

    def __call__(
        self,
        *,
        goal: str,
        observation: Mapping[str, Any],
        history: list[dict[str, Any]],
        candidates: list[Candidate],
    ) -> Choice:
        body = build_request(
            goal=goal,
            observation=observation,
            history=history,
            candidates=candidates,
            model=self._model,
        )
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            API_URL,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        ultimo = ""
        for tentativa in range(1, self._retries + 1):
            comeco = time.perf_counter()
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                decorrido = (time.perf_counter() - comeco) * 1000
                return parse_response(payload, candidates, latency_ms=decorrido)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                # A chave nunca entra na mensagem de erro.
                if exc.code == 429 and tentativa < self._retries:
                    time.sleep(1.5)
                    continue
                raise DecisionError(f"Jev HTTP {exc.code}: {detail}") from None
            except (urllib.error.URLError, OSError) as exc:
                # TimeoutError e socket.timeout sao OSError e nao chegam
                # embrulhados em URLError; sem este ramo eles sobem crus e
                # derrubam a sessao inteira.
                ultimo = getattr(exc, "reason", None) or str(exc)
                if tentativa < self._retries:
                    time.sleep(1.0)
                    continue

        raise DecisionError(f"Jev inacessivel apos {self._retries} tentativas: {ultimo}")


def mock_chooser(
    *,
    goal: str,
    observation: Mapping[str, Any],
    history: list[dict[str, Any]],
    candidates: list[Candidate],
) -> Choice:  # noqa: D401
    """Escolha deterministica por sobreposicao de palavras. Roda sem credencial.

    Existe para o loop inteiro ser exercitavel e testavel offline. Nao tenta
    imitar a qualidade do Jev -- so precisa ser estavel e previsivel.
    """
    comeco = time.perf_counter()
    criteria = criteria_from(candidates)
    goal_words = {w for w in _words(goal) if len(w) > 2}

    # Palavra que aparece em toda descricao nao distingue nada ("clicar", "em").
    # Descartar essas antes de pontuar e o que faz a margem significar algo.
    described = [set(_words(c.description)) for c in candidates if c.tool is not None]
    common: set[str] = set.intersection(*described) if described else set()

    scores: dict[str, float] = {}
    for candidate in candidates:
        if candidate.id == ABSTAIN:
            scores[candidate.id] = 0.01
            continue
        informative = set(_words(candidate.description)) - common
        overlap = goal_words & informative
        scores[candidate.id] = float(len(overlap)) + 0.02

    total = sum(scores.values()) or 1.0
    probabilities = {cid: value / total for cid, value in scores.items()}
    selected = max(probabilities, key=lambda cid: probabilities[cid])

    return Choice(
        selected_id=selected,
        confidence=margin_confidence(probabilities),
        probabilities=probabilities,
        model="mock",
        source="mock",
        usage=Usage(latency_ms=(time.perf_counter() - comeco) * 1000),
    )


def _words(text: str) -> set[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return set(cleaned.split())


def get_chooser(
    backend: str, *, api_key: str | None, model: str, timeout: float = 8.0
) -> Chooser:
    if backend == "mock":
        return mock_chooser
    if backend == "live":
        if not api_key:
            raise ValueError(
                "backend 'live' exige TYPESAFE_API_KEY (ou jev-api-token.txt na raiz)"
            )
        return LiveJev(api_key, model=model, timeout=timeout)
    raise ValueError(f"backend de decisao desconhecido: {backend!r}")
