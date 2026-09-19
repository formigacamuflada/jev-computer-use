"""Gramatica de voz: o vocabulario fechado sai da tela."""

from __future__ import annotations

from jevcu.voice.grammar import COMANDOS_FIXOS, casar, frases_para, normalizar


# --- normalizacao ---

def test_remove_pontuacao_que_ninguem_fala():
    assert normalizar("Arquivo...") == "arquivo"
    assert normalizar("Salvar &como") == "salvar como"


def test_contador_entre_parenteses_sai_do_vocabulario():
    """Regressao do Internal Speech Error 0x800455A0.

    Apps como o qBittorrent atualizam contadores a todo momento. Se o numero
    entrar no vocabulario, cada observacao gera uma gramatica diferente, o
    recognizer e recriado sem parar e o motor de fala quebra.
    """
    assert normalizar("Semeando (12)") == "semeando"
    assert normalizar("Semeando (13)") == "semeando"
    assert frases_para(["Semeando (12)"]) == frases_para(["Semeando (13)"])


def test_casamento_sobrevive_ao_contador_mudar():
    # Vocabulario estavel, mas o alvo continua sendo o rotulo real da tela.
    assert casar("semeando", ["Semeando (13)"]) == "Semeando (13)"


def test_preserva_acentos():
    assert normalizar("Início") == "início"
    assert normalizar("Configurações") == "configurações"


# --- construcao do vocabulario ---

def test_comandos_fixos_sempre_presentes():
    frases = frases_para([])
    for comando in COMANDOS_FIXOS:
        assert comando in frases


def test_gera_verbo_mais_rotulo():
    frases = frases_para(["Salvar"])
    assert "clicar em salvar" in frases
    assert "salvar" in frases


def test_ignora_rotulo_curto_demais_ou_repetido():
    frases = frases_para(["X", "Salvar", "Salvar"])
    assert frases.count("clicar em salvar") == 1
    assert "clicar em x" not in frases


def test_respeita_o_teto_de_rotulos():
    muitos = [f"Item {i}" for i in range(200)]
    frases = frases_para(muitos, max_rotulos=10)
    assert len([f for f in frases if f.startswith("clicar em item")]) == 10


# --- casamento fala -> rotulo real ---

def test_casa_exato():
    assert casar("clicar em salvar", ["Salvar", "Cancelar"]) == "Salvar"


def test_casa_ignorando_o_verbo():
    for dito in ["clicar em salvar", "aperta salvar", "abrir salvar", "salvar"]:
        assert casar(dito, ["Salvar"]) == "Salvar"


def test_casa_parcial_com_contador_na_tela():
    # O usuario fala "semeando"; a tela mostra "Semeando (12)".
    assert casar("semeando", ["Semeando (12)", "Baixando (0)"]) == "Semeando (12)"


def test_devolve_o_rotulo_original_com_acento():
    # A tabela de candidatos usa o rotulo original, nao o normalizado.
    assert casar("configurações", ["Configurações"]) == "Configurações"


def test_sem_correspondencia_devolve_none():
    assert casar("voar para marte", ["Salvar", "Cancelar"]) is None


def test_prefere_a_correspondencia_mais_especifica():
    rotulos = ["Parado (0)", "Upload parado (7)"]
    assert casar("upload parado", rotulos) == "Upload parado (7)"
