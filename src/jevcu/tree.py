"""Compactacao de arvore de UI para caber no state do Jev.

O Jev aceita 64k tokens por requisicao, e 32k para o state mais a maior
pergunta. Uma janela real do Explorer ou do Chrome tem centenas de nos e nao
cabe. A tecnica aqui e a mesma do agent-desktop: visao rasa primeiro, com os
ramos densos truncados e marcados, e drill-down so na regiao de interesse.

O modulo nao sabe de onde a arvore veio -- UIA hoje, Cua Driver depois.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

# Papeis que representam acao do usuario, e nao estrutura.
INTERACTIVE_ROLES = {
    "Button", "MenuItem", "CheckBox", "RadioButton", "Hyperlink", "TabItem",
    "ListItem", "TreeItem", "Edit", "ComboBox", "Slider", "SplitButton",
}
# Papeis que so agrupam. Se nao tem nome, nao carregam informacao.
STRUCTURAL_ROLES = {"Pane", "Group", "Custom", "Thumb", "Separator", "ScrollBar"}


@dataclass(frozen=True)
class Node:
    ref: str
    role: str
    name: str = ""
    enabled: bool = True
    children: tuple["Node", ...] = field(default_factory=tuple)

    @property
    def interactive(self) -> bool:
        return self.role in INTERACTIVE_ROLES and self.enabled

    @property
    def descendant_count(self) -> int:
        return sum(1 + child.descendant_count for child in self.children)

    def walk(self) -> Iterator["Node"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def find(self, ref: str) -> "Node | None":
        for node in self.walk():
            if node.ref == ref:
                return node
        return None


# Calibrado contra o `usage` real do Jev em tres orcamentos diferentes:
# a razao real/estimado ficou em 2.33, 2.37 e 2.47. A regra de 4 caracteres
# por token vale para prosa em ingles; este payload e JSON com muita pontuacao,
# refs e texto em portugues, que tokeniza bem pior.
CHARS_PER_TOKEN = 1.7


def estimate_tokens(payload: Any) -> int:
    """Estimativa do custo em tokens de um payload.

    Serve para escolher a profundidade do esqueleto, nao para faturar -- o
    numero autoritativo vem no campo `usage` da resposta.
    """
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def _is_noise(node: Node) -> bool:
    """No estrutural sem nome nao ajuda a decidir nada."""
    return node.role in STRUCTURAL_ROLES and not node.name.strip()


def _render(node: Node, depth: int, max_depth: int, max_children: int) -> dict[str, Any]:
    item: dict[str, Any] = {"ref": node.ref, "role": node.role}
    if node.name:
        item["name"] = node.name
    if not node.enabled:
        item["enabled"] = False

    if not node.children:
        return item

    if depth >= max_depth:
        # Ramo cortado: informa o tamanho e deixa uma alca para o drill-down.
        item["children_count"] = node.descendant_count
        item["drill"] = node.ref
        return item

    # Nos estruturais anonimos sao atravessados sem consumir um nivel.
    visible: list[Node] = []
    for child in node.children:
        if _is_noise(child):
            visible.extend(child.children)
        else:
            visible.append(child)

    shown = visible[:max_children]
    rendered = [_render(child, depth + 1, max_depth, max_children) for child in shown]
    if rendered:
        item["children"] = rendered
    if len(visible) > len(shown):
        item["children_omitted"] = len(visible) - len(shown)
        item["drill"] = node.ref
    return item


def skeleton(root: Node, *, max_depth: int = 3, max_children: int = 12) -> dict[str, Any]:
    """Visao rasa da arvore, com ramos densos truncados e marcados."""
    return _render(root, 0, max_depth, max_children)


def drill(root: Node, ref: str, *, max_depth: int = 3, max_children: int = 20) -> dict[str, Any]:
    """Expande uma regiao especifica, identificada por um `drill` do esqueleto."""
    target = root.find(ref)
    if target is None:
        raise KeyError(f"ref desconhecida na arvore: {ref!r}")
    return _render(target, 0, max_depth, max_children)


@dataclass(frozen=True)
class Fitted:
    """Esqueleto escolhido para um orcamento, com os parametros que o geraram."""

    payload: dict[str, Any]
    depth: int
    max_children: int
    tokens: int
    nodes: int


# Grade de busca. Arvores reais variam muito de forma: qBittorrent e profunda e
# estreita, Electron e rasa e larguissima (o Discord tem um unico Group com 451
# filhos diretos). Ajustar so a profundidade nao serve para as duas.
_DEPTHS = (2, 3, 4, 6, 8, 12, 20)
_WIDTHS = (12, 25, 50, 100, 200, 400, 800)


def _count_nodes(payload: dict[str, Any]) -> int:
    total = 1
    for child in payload.get("children", []):
        total += _count_nodes(child)
    return total


def fit(root: Node, *, budget_tokens: int, max_depth: int = 20) -> Fitted:
    """Esqueleto que extrai mais informacao dentro do orcamento.

    Busca em profundidade E largura. Ajustar so a profundidade desperdica o
    orcamento em arvores largas: a do Discord fica em 256 tokens de um teto de
    6000 porque o corte real esta nos filhos, nao nos niveis.

    Escolhe o candidato com mais nos que ainda cabe, e nao simplesmente o
    menor: cortar abaixo do orcamento e perda de informacao, nao economia.
    """
    if budget_tokens <= 0:
        raise ValueError("budget_tokens deve ser positivo")

    best: Fitted | None = None
    for depth in _DEPTHS:
        if depth > max_depth:
            continue
        for width in _WIDTHS:
            payload = skeleton(root, max_depth=depth, max_children=width)
            tokens = estimate_tokens(payload)
            if tokens > budget_tokens:
                # Mais largura so piora daqui para frente nesta profundidade.
                break
            nodes = _count_nodes(payload)
            if best is None or nodes > best.nodes:
                best = Fitted(payload, depth, width, tokens, nodes)

    if best is not None:
        return best

    # Nem o menor candidato cabe: devolve o minimo viavel mesmo estourando,
    # porque cortar mais perderia a raiz.
    payload = skeleton(root, max_depth=1, max_children=_WIDTHS[0])
    return Fitted(payload, 1, _WIDTHS[0], estimate_tokens(payload), _count_nodes(payload))


def interactive_nodes(root: Node, *, limit: int | None = None) -> list[Node]:
    """Folhas acionaveis, em ordem de documento. Base da tabela de candidatos."""
    found = [node for node in root.walk() if node.interactive and node.name.strip()]
    return found[:limit] if limit else found
