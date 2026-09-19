"""Regressoes da execucao: o clique tem que sair, e a recusa tem que doer.

Vieram de uma sessao real em que seis comandos foram anunciados como "[acted]"
e "done" sem que um unico clique tivesse acontecido.
"""

from __future__ import annotations

import pytest

from jevcu.candidates import _target_args
from jevcu.driver import DriverError, Element, Observation, raise_if_refused


def _observation(**kwargs) -> Observation:
    return Observation("s00000075", "App", "janela", [], pid=20000, window_id=66986, **kwargs)


# --- como o alvo e enderecado ---

def test_alvo_vai_pelo_token_e_nao_pelo_indice_cru():
    """`element_index` sozinho e recusado pelo Driver: "bare element_index is
    not accepted". O token carrega snapshot e indice juntos."""
    alvo = _target_args(Element("e1", "Button", "Salvar", index=3, token="s00000075:3"),
                        _observation())
    assert alvo["element_token"] == "s00000075:3"
    assert "element_index" not in alvo


def test_indice_sem_token_leva_o_snapshot_junto():
    alvo = _target_args(Element("e1", "Button", "Salvar", index=3), _observation())
    assert alvo["element_index"] == 3
    assert alvo["snapshot_id"] == "s00000075"


def test_sem_pid_cai_na_ref_local():
    observation = Observation("s1", "App", "janela", [])
    assert _target_args(Element("e1", "Button", "Salvar"), observation) == {"ref": "@s1:e1"}


# --- recusa nao pode passar por sucesso ---

def test_recusa_vira_erro_mesmo_sem_iserror():
    """O Driver nao marca `isError` numa recusa. Ler so esse campo fazia o loop
    anunciar sucesso em cima de um clique que nunca saiu."""
    payload = {"structuredContent": {"status": "refused", "refusal": {
        "code": "snapshot_id_required",
        "message": "click: bare element_index is not accepted",
    }}}
    with pytest.raises(DriverError, match="snapshot_id_required"):
        raise_if_refused("click", payload)


def test_a_mensagem_da_recusa_sobe_inteira():
    """E ela que diz o que fazer -- restaurar a janela, trocar o argumento."""
    payload = {"structuredContent": {"status": "refused", "refusal": {
        "code": "window_minimized", "message": "window 0x105aa is minimized",
    }}}
    with pytest.raises(DriverError, match="minimized"):
        raise_if_refused("click", payload)


def test_sucesso_continua_passando():
    raise_if_refused("click", {"structuredContent": {"status": "completed"}})
    raise_if_refused("click", {"ok": True})
