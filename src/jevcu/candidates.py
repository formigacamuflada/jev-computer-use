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
    must_include: str | None = None,
) -> list[Candidate]:
    """Monta a tabela imutavel de acoes completas para esta observacao.

    `must_include` e o nome de um elemento que precisa estar na tabela mesmo
    que caia fora do teto. Sem isso, a camada de voz resolve um alvo entre os
    321 elementos da tela e o Jev recebe uma lista de 24 que nao o contem --
    ele entao escolhe mal ou se abstem, e parece que errou quando na verdade
    a pergunta e que estava errada.
    """
    candidates: list[Candidate] = []
    reservado: Candidate | None = None

    if must_include:
        alvo = next(
            (e for e in observation.elements if e.name == must_include and e.enabled),
            None,
        )
        if alvo is not None:
            reservado = _candidate_for(alvo, observation, text_to_type)

    teto = max_candidates - 1 if reservado is not None else max_candidates
    for element in observation.elements:
        if len(candidates) >= teto:
            break
        if not element.enabled or not element.name:
            continue
        candidate = _candidate_for(element, observation, text_to_type)
        if candidate is not None:
            candidates.append(candidate)

    if reservado is not None and not any(c.id == reservado.id for c in candidates):
        candidates.append(reservado)

    # reobserve e abstain sempre presentes: sao a saida segura quando a
    # evidencia esta velha, incompleta ou ambigua.
    candidates.extend(reserved_candidates())
    return candidates


def _target_args(element: Element, observation: Observation) -> dict[str, object]:
    """Como o Driver identifica o alvo.

    Com pid/window_id do Cua Driver usamos element_index, que e o contrato dele.
    Sem eles (UiaDriver, mock) cai numa ref local ao snapshot.
    """
    if observation.pid is not None and element.index is not None:
        return {
            "pid": observation.pid,
            "window_id": observation.window_id,
            "element_index": element.index,
        }
    return {"ref": f"@{observation.snapshot_id}:{element.ref}"}


def _candidate_for(
    element: Element,
    observation: Observation,
    text_to_type: str | None,
) -> Candidate | None:
    target = _target_args(element, observation)

    if element.role in CLICKABLE:
        return Candidate(
            id=f"click-{element.ref}",
            description=f"Clicar em {element.role} \"{element.name}\".",
            tool="click",
            # background: nunca rouba o foco. E a primeira tentativa obrigatoria
            # segundo o contrato do Driver, nao uma sugestao.
            arguments={**target, "delivery_mode": "background"},
        )

    if element.role in TYPEABLE and text_to_type:
        return Candidate(
            id=f"type-{element.ref}",
            description=f"Escrever \"{text_to_type}\" no campo \"{element.name}\".",
            tool="type_text",
            arguments={**target, "text": text_to_type, "delivery_mode": "background"},
        )

    return None


def describe_table(candidates: list[Candidate]) -> str:
    """Rendericao legivel, para log e para o modo --dry-run."""
    lines = []
    for candidate in candidates:
        marker = " " if candidate.is_terminal else "*"
        lines.append(f"  {marker} {candidate.id:<28} {candidate.description}")
    return "\n".join(lines)
