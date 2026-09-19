"""O loop inteiro, exercitado sem credencial e sem Driver instalado."""

from __future__ import annotations

import pytest

from jevcu.candidates import build_candidates
from jevcu.config import Config
from jevcu.contracts import ABSTAIN, REOBSERVE, Candidate, DecisionError, validate_choice
from jevcu.driver import Element, MockDriver, Observation
from jevcu.jev import build_request, mock_chooser, parse_response
from jevcu.loop import Agent


def _observation() -> Observation:
    return Observation(
        snapshot_id="s1",
        app="Bloco de Notas",
        window_title="Salvar como",
        elements=[
            Element("e1", "Button", "Salvar"),
            Element("e2", "Button", "Cancelar"),
            Element("e3", "Edit", "Nome do arquivo"),
        ],
    )


# --- tabela de candidatos ---

def test_tabela_sempre_tem_saidas_seguras():
    candidates = build_candidates(_observation())
    ids = {c.id for c in candidates}
    assert REOBSERVE in ids and ABSTAIN in ids


def test_elemento_desabilitado_nao_vira_candidato():
    observation = Observation("s1", "App", "", [Element("e1", "Button", "Salvar", enabled=False)])
    candidates = build_candidates(observation)
    assert not [c for c in candidates if c.tool == "click"]


def test_campo_de_texto_so_aparece_se_houver_texto():
    sem_texto = build_candidates(_observation())
    assert not [c for c in sem_texto if c.tool == "type_text"]
    com_texto = build_candidates(_observation(), text_to_type="relatorio")
    assert [c for c in com_texto if c.tool == "type_text"]


# --- validacao: o ponto em que o sistema falha fechado ---

def test_id_desconhecido_e_rejeitado():
    candidates = build_candidates(_observation())
    with pytest.raises(DecisionError, match="desconhecido"):
        validate_choice("click-e999", candidates)


def test_id_malformado_e_rejeitado():
    with pytest.raises(DecisionError):
        validate_choice("", build_candidates(_observation()))


def test_candidato_de_captura_velha_e_rejeitado():
    candidates = [Candidate("pix", "clique por pixel", "click", {"x": 1}, capture_id="cap_A")]
    with pytest.raises(DecisionError, match="obsoleta"):
        validate_choice("pix", candidates, current_capture_id="cap_B")


def test_tabela_com_ids_duplicados_e_rejeitada():
    dup = [Candidate("a", "x", "click"), Candidate("a", "y", "click")]
    with pytest.raises(DecisionError, match="duplicados"):
        validate_choice("a", dup)


# --- contrato da requisicao ao Jev ---

def test_requisicao_nao_vaza_ferramenta_nem_argumentos():
    candidates = build_candidates(_observation())
    body = build_request(
        goal="salvar", observation={}, history=[], candidates=candidates, model="jev-latest"
    )
    blob = repr(body)
    assert "arguments" not in blob
    assert "@s1:e1" not in blob  # nenhuma ref vaza
    assert set(body["questions"]["driver_action"]["criteria"]) == {c.id for c in candidates}


def test_resposta_com_id_invalido_e_rejeitada():
    candidates = build_candidates(_observation())
    payload = {"answers": {"driver_action": {"choice": "nao-existe", "probabilities": {}}}}
    with pytest.raises(DecisionError):
        parse_response(payload, candidates)


# --- loop ---

def _observation_depois() -> Observation:
    """Tela apos a acao: precisa diferir, senao nao ha o que verificar."""
    return Observation(
        snapshot_id="s2",
        app="Bloco de Notas",
        window_title="Salvo",
        elements=[Element("e1", "Button", "Fechar")],
    )


def test_loop_executa_e_verifica_a_pos_condicao():
    # Primeira observacao decide; a segunda verifica. Como a tela muda,
    # o desfecho e "done".
    driver = MockDriver([_observation(), _observation_depois()])
    agent = Agent(driver, mock_chooser, Config(act_threshold=0.0))
    run = agent.run("clicar em Salvar")
    assert run.outcome == "done"
    assert run.actions_taken == 1
    assert driver.executed[0][0] == "click"


def test_acao_sem_efeito_na_tela_nao_vira_done():
    """Regressao: o Driver responde `effect: "unverifiable"` e nao promete
    sucesso. Numa sessao real, seis cliques viraram "done" sem nada acontecer.

    Com a tela identica antes e depois, o desfecho tem que ser honesto.
    """
    driver = MockDriver([_observation()])      # sempre a mesma tela
    agent = Agent(driver, mock_chooser, Config(act_threshold=0.0))
    run = agent.run("clicar em Salvar")
    assert run.outcome == "unverified"
    assert run.actions_taken == 1              # a acao foi enviada
    assert "nao mudou" in run.message


def test_dry_run_nao_executa_nada():
    driver = MockDriver([_observation()])
    agent = Agent(driver, mock_chooser, Config(act_threshold=0.0))
    run = agent.run("clicar em Salvar", dry_run=True)
    assert run.outcome == "done"
    assert driver.executed == []


def test_confianca_baixa_escala_em_vez_de_agir():
    driver = MockDriver([_observation()])
    agent = Agent(driver, mock_chooser, Config(act_threshold=0.99, floor_threshold=0.0))
    run = agent.run("clicar em Salvar")
    assert run.outcome == "escalate"
    assert driver.executed == []


def test_must_include_garante_o_alvo_na_tabela():
    """Regressao: a voz resolvia um alvo entre 321 elementos e o Jev recebia
    uma tabela de 24 que nao o continha, entao abstinha ou escolhia mal."""
    muitos = [Element(f"e{i}", "Button", f"Botao {i}", index=i) for i in range(60)]
    observation = Observation("s1", "App", "janela", muitos, pid=1, window_id=2)

    sem = build_candidates(observation, max_candidates=10)
    assert not any("Botao 55" in c.description for c in sem)

    com = build_candidates(observation, max_candidates=10, must_include="Botao 55")
    assert any("Botao 55" in c.description for c in com)
    assert len(com) <= 10 + 2   # o teto e respeitado (fora reobserve/abstain)


def test_must_include_inexistente_nao_quebra():
    observation = Observation("s1", "App", "j", [Element("e1", "Button", "Salvar")])
    candidates = build_candidates(observation, must_include="Nao Existe")
    assert any(c.tool == "click" for c in candidates)


# --- recusa do Driver em suas tres formas -------------------------------

def test_recusa_em_qualquer_das_tres_formas_levanta():
    """As tres apareceram em uso real. Checar so uma deixa recusa virar exito."""
    from jevcu.driver import DriverError, raise_if_refused

    formas = [
        {"structuredContent": {"status": "refused",
                               "refusal": {"code": "window_minimized", "message": "x"}}},
        {"structuredContent": {"status": "refused", "code": "snapshot_id_required"}},
        {"structuredContent": {"effect": "refused", "route": None}},
    ]
    for payload in formas:
        with pytest.raises(DriverError):
            raise_if_refused("click", payload)


def test_sucesso_normal_nao_levanta():
    from jevcu.driver import raise_if_refused

    raise_if_refused("click", {"structuredContent": {
        "effect": "unverifiable", "route": "accessibility",
    }})
