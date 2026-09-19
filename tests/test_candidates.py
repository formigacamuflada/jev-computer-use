"""Regressoes da tabela de candidatos e da regua de confianca.

Os tres casos aqui vieram da leitura do tiptour-macos, que resolve o mesmo
problema no macOS: descricao repetida, confianca medida com duas reguas, e
tela sem arvore de acessibilidade.
"""

from __future__ import annotations

import pytest

from jevcu.candidates import build_candidates
from jevcu.contracts import DecisionError, margin_confidence, validate_choice
from jevcu.driver import Element, Observation
from jevcu.jev import mock_chooser, parse_response


def _observation(elements: list[Element], **kwargs) -> Observation:
    return Observation("s1", "App", "janela", elements, pid=1, window_id=2, **kwargs)


# --- descricoes repetidas ---

def test_descricao_repetida_entra_uma_vez_so():
    """Dois botoes de mesmo nome davam duas linhas identicas na tabela.

    O Jev nao responde 50/50 a um empate exato: ele desempata pela primeira
    chave e relata confianca alta. O loop lia esse numero como certeza sem
    que discriminacao nenhuma tivesse acontecido.
    """
    observation = _observation([
        Element("e1", "Button", "Salvar", index=1),
        Element("e2", "Button", "Salvar", index=2),
        Element("e3", "Button", "Cancelar", index=3),
    ])
    descricoes = [c.description for c in build_candidates(observation) if c.tool]
    assert len(descricoes) == len(set(descricoes))
    assert sum("Salvar" in d for d in descricoes) == 1


def test_mesmo_nome_em_papeis_diferentes_continua_distinguivel():
    """Deduplicar nao pode apagar uma distincao real: o menu e o botao
    'Arquivo' sao duas acoes diferentes e as descricoes ja dizem isso."""
    observation = _observation([
        Element("e1", "Button", "Arquivo", index=1),
        Element("e2", "MenuItem", "Arquivo", index=2),
    ])
    assert len([c for c in build_candidates(observation) if c.tool]) == 2


def test_must_include_sobrevive_a_deduplicacao():
    """O alvo reservado tem que vencer a copia, nao ser descartado por ela."""
    muitos = [Element(f"e{i}", "Button", "Abrir", index=i) for i in range(30)]
    candidates = build_candidates(
        _observation(muitos), max_candidates=8, must_include="Abrir"
    )
    abrir = [c for c in candidates if "Abrir" in c.description]
    assert len(abrir) == 1


# --- uma regua so de confianca ---

def _payload(probabilities: dict[str, float], confidence: float) -> dict:
    topo = max(probabilities, key=lambda k: probabilities[k])
    return {"answers": {"driver_action": {
        "choice": topo, "probabilities": probabilities, "confidence": confidence,
    }}}


def test_live_e_mock_medem_confianca_com_a_mesma_regua():
    observation = _observation([
        Element("e1", "Button", "Salvar", index=1),
        Element("e2", "Button", "Cancelar", index=2),
    ])
    candidates = build_candidates(observation)
    probabilidades = {c.id: 0.1 for c in candidates}
    probabilidades["click-e1"] = 0.6

    live = parse_response(_payload(probabilidades, confidence=0.5), candidates)
    assert live.confidence == pytest.approx(margin_confidence(live.probabilities))

    mock = mock_chooser(goal="clicar em Salvar", observation={}, history=[],
                        candidates=candidates)
    assert mock.confidence == pytest.approx(margin_confidence(mock.probabilities))


def test_confianca_do_provider_nao_decide_mais_nada():
    """O campo `confidence` da API e corrigido pelo acaso, entao encolhe
    quando a tabela cresce. Comparar isso com um limiar fixo comparava coisas
    diferentes a cada passo. Ele continua visivel, mas so para diagnostico."""
    candidates = build_candidates(_observation([
        Element("e1", "Button", "Salvar", index=1),
        Element("e2", "Button", "Cancelar", index=2),
    ]))
    # Vencedor folgado, mas o provider reporta um numero baixo.
    choice = parse_response(_payload({"click-e1": 0.9, "click-e2": 0.05}, 0.31), candidates)
    assert choice.provider_confidence == pytest.approx(0.31)
    assert choice.confidence > 0.9


def test_empate_e_duvida_mesmo_com_provider_confiante():
    candidates = build_candidates(_observation([
        Element("e1", "Button", "Salvar", index=1),
        Element("e2", "Button", "Salvar como", index=2),
    ]))
    choice = parse_response(_payload({"click-e1": 0.45, "click-e2": 0.45}, 0.95), candidates)
    assert choice.confidence == pytest.approx(0.5)


def test_sem_probabilidades_usa_o_numero_do_provider():
    """Sem distribuicao nao da para calcular margem nenhuma. Zerar a confianca
    ai faria o loop reobservar para sempre; o numero do provider e melhor."""
    candidates = build_candidates(_observation([Element("e1", "Button", "Salvar", index=1)]))
    payload = {"answers": {"driver_action": {
        "choice": "click-e1", "probabilities": {}, "confidence": 0.77,
    }}}
    assert parse_response(payload, candidates).confidence == pytest.approx(0.77)


# --- OCR: telas sem arvore de acessibilidade ---

def _ocr_observation(capture_id: str | None = "cap_1") -> Observation:
    return _observation(
        [Element("ocr0", "Text", "Baixar", bounds=(100, 40, 60, 20), source="ocr")],
        capture_id=capture_id,
    )


def test_texto_lido_por_ocr_vira_clique_por_pixel():
    """Apps UWP devolvem a arvore vazia. Sem isto a tela inteira ficava fora
    de alcance: sem elemento, nao ha candidato."""
    candidates = [c for c in build_candidates(_ocr_observation()) if c.tool]
    assert len(candidates) == 1
    alvo = candidates[0]
    assert alvo.arguments["x"] == 130 and alvo.arguments["y"] == 50
    # background primeiro: e o modo em que o Driver faz hit-test de UIA no
    # ponto antes de recorrer ao PostMessage.
    assert alvo.arguments["delivery_mode"] == "background"
    assert "OCR" in alvo.description


def test_clique_por_pixel_morre_com_a_captura():
    candidates = build_candidates(_ocr_observation("cap_1"))
    with pytest.raises(DecisionError, match="obsoleta"):
        validate_choice("click-ocr0", candidates, current_capture_id="cap_2")


def test_texto_sem_caixa_nao_vira_candidato():
    observation = _observation(
        [Element("ocr0", "Text", "Baixar", source="ocr")], capture_id="cap_1"
    )
    assert not [c for c in build_candidates(observation) if c.tool]


def test_o_jev_sabe_que_a_evidencia_veio_de_ocr():
    """Um rotulo de OCR pode ser um titulo, uma legenda ou um erro de leitura.
    Esconder a origem faria o Jev tratar os dois tipos como iguais."""
    compacta = _ocr_observation().compact()
    assert compacta["elements"][0]["source"] == "ocr"
    assert "source" not in Element("e1", "Button", "Salvar").compact()
