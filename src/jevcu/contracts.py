"""Tipos e validacao do loop de decisao.

Espelha o contrato de `libs/cua-driver/examples/jev-use/python/core.py` do cua:
a aplicacao e dona da tabela de candidatos; o Jev so devolve um ID dela.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

# IDs reservados que devem existir em toda tabela de candidatos.
REOBSERVE = "reobserve"
ABSTAIN = "abstain"


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _freeze(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class Candidate:
    """Uma acao completa e executavel. O Jev escolhe entre estas, nunca inventa."""

    id: str
    description: str
    tool: str | None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    capture_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise ValueError("candidate id vazio ou invalido")
        if not self.description:
            raise ValueError(f"candidate {self.id!r} sem descricao")
        object.__setattr__(self, "arguments", _freeze(dict(self.arguments)))

    @property
    def is_terminal(self) -> bool:
        return self.tool is None


@dataclass(frozen=True)
class Choice:
    """Resposta normalizada do provider de decisao."""

    selected_id: str
    confidence: float
    probabilities: dict[str, float]
    model: str | None = None
    source: str = "mock"


class DecisionError(ValueError):
    """O provider devolveu algo que nao da para confiar."""


def reserved_candidates() -> list[Candidate]:
    return [
        Candidate(
            REOBSERVE,
            "Descartar esta decisao e obter uma observacao nova do Driver.",
            None,
        ),
        Candidate(
            ABSTAIN,
            "Nao agir: nenhuma das acoes propostas e segura para o estado observado.",
            None,
        ),
    ]


def criteria_from(candidates: list[Candidate]) -> dict[str, str]:
    criteria = {c.id: c.description for c in candidates}
    if len(criteria) != len(candidates):
        raise DecisionError("tabela de candidatos tem IDs duplicados")
    return criteria


def validate_choice(
    choice: str,
    candidates: list[Candidate],
    *,
    current_capture_id: str | None = None,
) -> Candidate:
    """Resolve o ID devolvido contra a tabela original imutavel. Falha fechado."""
    if not isinstance(choice, str) or not choice:
        raise DecisionError("provider devolveu um ID malformado")

    ids = [c.id for c in candidates]
    if len(ids) != len(set(ids)):
        raise DecisionError("tabela de candidatos tem IDs duplicados")

    candidate = next((c for c in candidates if c.id == choice), None)
    if candidate is None:
        raise DecisionError(f"provider escolheu um candidato desconhecido: {choice!r}")

    # Uma acao ligada a uma captura so vale para aquela captura exata.
    if candidate.capture_id is not None and candidate.capture_id != current_capture_id:
        raise DecisionError("candidato preso a uma captura obsoleta ou trocada")

    return candidate


def validate_probabilities(
    probabilities: Mapping[str, Any],
    criteria: Mapping[str, str],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for candidate_id, value in probabilities.items():
        if candidate_id not in criteria:
            raise DecisionError(f"probabilidade para candidato desconhecido: {candidate_id!r}")
        probability = float(value)
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise DecisionError("probabilidade fora de [0,1]")
        out[candidate_id] = probability
    return out


def validate_confidence(value: Any) -> float:
    confidence = float(value)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise DecisionError("confianca fora de [0,1]")
    return confidence
