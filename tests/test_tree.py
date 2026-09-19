"""Compactacao de arvore: o que garante que a tela caiba no state do Jev."""

from __future__ import annotations

import pytest

from jevcu.tree import (
    Node,
    drill,
    estimate_tokens,
    fit,
    interactive_nodes,
    skeleton,
)


def _wide_tree(groups: int = 20, per_group: int = 30) -> Node:
    """Arvore densa, na ordem de grandeza de um Explorer ou Chrome real."""
    return Node(
        "root", "Window", "Explorador",
        children=tuple(
            Node(
                f"g{g}", "Group", f"Secao {g}",
                children=tuple(
                    Node(f"g{g}i{i}", "ListItem", f"arquivo_{g}_{i}.txt")
                    for i in range(per_group)
                ),
            )
            for g in range(groups)
        ),
    )


# --- truncamento ---

def test_profundidade_limita_a_descida():
    tree = _wide_tree(3, 5)
    shallow = skeleton(tree, max_depth=1)
    grupo = shallow["children"][0]
    assert "children" not in grupo          # nao desceu
    assert grupo["children_count"] == 5     # mas disse quanto tem
    assert grupo["drill"] == "g0"           # e deixou como chegar la


def test_largura_limita_os_irmaos():
    tree = _wide_tree(20, 2)
    shallow = skeleton(tree, max_depth=1, max_children=5)
    assert len(shallow["children"]) == 5
    assert shallow["children_omitted"] == 15


def test_no_estrutural_sem_nome_e_atravessado():
    # Pane anonimo nao deve consumir um nivel de profundidade.
    tree = Node("root", "Window", "App", children=(
        Node("p1", "Pane", "", children=(Node("b1", "Button", "Salvar"),)),
    ))
    rendered = skeleton(tree, max_depth=1)
    nomes = [c.get("name") for c in rendered["children"]]
    assert "Salvar" in nomes


def test_no_estrutural_com_nome_e_preservado():
    tree = Node("root", "Window", "App", children=(
        Node("p1", "Pane", "Barra lateral", children=(Node("b1", "Button", "Salvar"),)),
    ))
    rendered = skeleton(tree, max_depth=2)
    assert rendered["children"][0]["name"] == "Barra lateral"


# --- drill-down ---

def test_drill_expande_a_regiao_cortada():
    tree = _wide_tree(5, 10)
    shallow = skeleton(tree, max_depth=1)
    alvo = shallow["children"][0]["drill"]
    expandido = drill(tree, alvo, max_depth=2)
    assert len(expandido["children"]) == 10


def test_drill_em_ref_inexistente_falha():
    with pytest.raises(KeyError):
        drill(_wide_tree(2, 2), "nao-existe")


# --- orcamento: a razao de tudo isto existir ---

def test_fit_respeita_o_orcamento():
    tree = _wide_tree(20, 30)   # 600+ nos
    fitted = fit(tree, budget_tokens=2000)
    assert fitted.tokens <= 2000
    assert fitted.depth >= 1


def test_orcamento_impossivel_devolve_o_minimo():
    """Abaixo do menor esqueleto possivel, cortar mais perderia a raiz.

    O contrato e explicito: devolve o minimo viavel mesmo estourando, em vez
    de devolver nada.
    """
    tree = _wide_tree(20, 30)
    fitted = fit(tree, budget_tokens=10)
    assert fitted.nodes >= 1
    assert fitted.depth == 1


def test_fit_aproveita_orcamento_maior():
    tree = _wide_tree(3, 3)
    generoso = fit(tree, budget_tokens=100_000)
    apertado = fit(tree, budget_tokens=60)
    assert generoso.nodes > apertado.nodes
    assert generoso.tokens > apertado.tokens


def test_fit_alarga_quando_a_arvore_e_rasa_e_larga():
    """Regressao: arvore estilo Electron, um unico pai com centenas de filhos.

    Ajustar so a profundidade nao muda nada aqui -- o corte esta na largura.
    O fit tem que gastar o orcamento alargando.
    """
    largo = Node("root", "Document", "app", children=(
        Node("mount", "Group", "app-mount", children=tuple(
            Node(f"i{i}", "Button", f"item numero {i}") for i in range(400)
        )),
    ))
    apertado = fit(largo, budget_tokens=300)
    folgado = fit(largo, budget_tokens=6000)

    assert folgado.nodes > apertado.nodes * 5, "nao aproveitou o orcamento maior"
    assert folgado.max_children > apertado.max_children, "nao alargou"
    assert folgado.tokens <= 6000


def test_orcamento_invalido_e_rejeitado():
    with pytest.raises(ValueError):
        fit(_wide_tree(2, 2), budget_tokens=0)


def test_reducao_e_expressiva_em_arvore_densa():
    tree = _wide_tree(20, 30)
    completo = skeleton(tree, max_depth=99, max_children=999)
    raso = skeleton(tree, max_depth=1, max_children=12)
    reducao = 1 - estimate_tokens(raso) / estimate_tokens(completo)
    assert reducao > 0.90, f"reducao de apenas {reducao:.1%}"


# --- extracao de acionaveis ---

def test_interactive_ignora_estrutura_e_desabilitados():
    tree = Node("root", "Window", "App", children=(
        Node("b1", "Button", "Salvar"),
        Node("b2", "Button", "Cinza", enabled=False),
        Node("p1", "Pane", "Painel"),
        Node("b3", "Button", ""),           # sem nome: inutil para decidir
    ))
    assert [n.ref for n in interactive_nodes(tree)] == ["b1"]
