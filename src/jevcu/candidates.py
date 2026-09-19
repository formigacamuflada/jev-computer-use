"""Construcao da tabela de candidatos.

Esta e a camada que faz o papel de "cerebro" no sentido estrito: ela enumera
o que e possivel fazer agora. O Jev so pontua o que sai daqui.

Enquanto o espaco de acoes for enumeravel a partir da observacao, nao ha
necessidade de um LLM no loop.
"""

from __future__ import annotations

from .contracts import Candidate, reserved_candidates
from .driver import Element, Observation

# Papeis que aceitam clique.
CLICKABLE = {"Button", "MenuItem", "CheckBox", "RadioButton", "Link", "TabItem", "ListItem"}
# Papeis que aceitam texto.
TYPEABLE = {"Edit", "TextBox", "ComboBox", "Document"}


def build_candidates(
    observation: Observation,
    *,
    text_to_type: str | None = None,
    max_candidates: int = 24,
) -> list[Candidate]:
    """Monta a tabela imutavel de acoes completas para esta observacao."""
    candidates: list[Candidate] = []

    for element in observation.elements:
        if len(candidates) >= max_candidates:
            break
        if not element.enabled or not element.name:
            continue
        candidate = _candidate_for(element, observation, text_to_type)
        if candidate is not None:
            candidates.append(candidate)

    # reobserve e abstain sempre presentes: sao a saida segura quando a
    # evidencia esta velha, incompleta ou ambigua.
    candidates.extend(reserved_candidates())
    return candidates


def _candidate_for(
    element: Element,
    observation: Observation,
    text_to_type: str | None,
) -> Candidate | None:
    if element.role in CLICKABLE:
        return Candidate(
            id=f"click-{element.ref}",
            description=f"Clicar em {element.role} \"{element.name}\".",
            tool="click",
            arguments={"ref": f"@{observation.snapshot_id}:{element.ref}"},
        )

    if element.role in TYPEABLE and text_to_type:
        return Candidate(
            id=f"type-{element.ref}",
            description=f"Escrever \"{text_to_type}\" no campo \"{element.name}\".",
            tool="type",
            arguments={
                "ref": f"@{observation.snapshot_id}:{element.ref}",
                "text": text_to_type,
            },
        )

    return None


def describe_table(candidates: list[Candidate]) -> str:
    """Rendericao legivel, para log e para o modo --dry-run."""
    lines = []
    for candidate in candidates:
        marker = " " if candidate.is_terminal else "*"
        lines.append(f"  {marker} {candidate.id:<28} {candidate.description}")
    return "\n".join(lines)
