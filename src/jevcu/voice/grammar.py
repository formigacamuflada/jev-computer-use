"""Gramatica de comandos gerada a partir da tela.

O reconhecimento offline do Windows exige uma lista fechada de frases. Isso
parece limitacao, mas casa com a arquitetura: o espaco de acoes ja e fechado --
e a tabela de candidatos. A mesma observacao que alimenta o Jev alimenta o
vocabulario do microfone.

Vocabulario fechado tambem aumenta muito a acuracia: o motor escolhe entre N
frases conhecidas em vez de transcrever portugues aberto.
"""

from __future__ import annotations

import re

# Comandos que existem sempre, independentes do que esta na tela.
COMANDOS_FIXOS = (
    "cancelar",
    "parar",
    "esquece",
    "o que tem na tela",
    "repetir",
)

# Verbos aceitos por tipo de elemento.
VERBOS_CLIQUE = ("clicar em", "clique em", "aperta", "abrir")
VERBOS_TEXTO = ("escrever em", "digitar em")

_LIMPEZA = re.compile(r"[^\wÀ-ÿ ]+", re.UNICODE)
_ESPACOS = re.compile(r"\s+")
# Contador entre parenteses: "Semeando (12)". Muda a cada segundo em apps como
# o qBittorrent. Se entrar no vocabulario, a gramatica e recompilada sem parar.
_CONTADOR = re.compile(r"\s*\(\s*\d[\d.,]*\s*\)\s*")
# Trecho minimo para aceitar um casamento parcial. Abaixo disto, ruido
# de transcricao casaria com quase qualquer rotulo.
_MIN_CASAMENTO = 4


def normalizar(texto: str) -> str:
    """Forma falavel de um rotulo de UI.

    Remove pontuacao e contadores que ninguem fala: o usuario diz "semeando",
    nao "semeando abre parenteses doze fecha parenteses".
    """
    sem_contador = _CONTADOR.sub(" ", texto)
    limpo = _LIMPEZA.sub(" ", sem_contador)
    return _ESPACOS.sub(" ", limpo).strip().lower()


def _contem_palavras(maior: str, menor: str) -> bool:
    """`menor` aparece em `maior` como sequencia inteira de palavras.

    Substring crua casa "parado" dentro de "separado", e foi assim que dizer
    "separado" clicou em "Parado (0)". Exigir fronteira de palavra corrige.
    """
    a = maior.split()
    b = menor.split()
    if not b or len(b) > len(a):
        return False
    return any(a[i : i + len(b)] == b for i in range(len(a) - len(b) + 1))


def falavel(rotulo: str) -> bool:
    """Rotulo que uma pessoa conseguiria dizer em voz alta.

    A arvore de UI traz IDs internos gigantes como
    "Application.MainWindow.centralWidget...DownloadedPiecesBar". Eles nao sao
    comandos; poluem o vocabulario e produzem casamentos absurdos.
    """
    texto = rotulo.strip()
    if not texto or len(texto) > 60:
        return False
    if texto.count(".") >= 3 and " " not in texto:
        return False
    return True


def frases_para(rotulos: list[str], *, max_rotulos: int = 60) -> list[str]:
    """Monta o vocabulario: um verbo x rotulo para cada elemento acionavel."""
    frases: list[str] = list(COMANDOS_FIXOS)
    vistos: set[str] = set()

    for rotulo in rotulos[:max_rotulos]:
        if not falavel(rotulo):
            continue
        alvo = normalizar(rotulo)
        # Rotulo de uma letra ou vazio nao da uma frase pronunciavel.
        if len(alvo) < 2 or alvo in vistos:
            continue
        vistos.add(alvo)
        for verbo in VERBOS_CLIQUE:
            frases.append(f"{verbo} {alvo}")
        # O rotulo sozinho tambem vale como comando.
        frases.append(alvo)

    return frases


def casar(falado: str, rotulos: list[str]) -> str | None:
    """Descobre a qual rotulo uma frase reconhecida se refere.

    Devolve o rotulo original (com acentuacao e pontuacao), que e o que a
    tabela de candidatos usa nas descricoes.
    """
    dito = normalizar(falado)
    for verbo in (*VERBOS_CLIQUE, *VERBOS_TEXTO):
        if dito.startswith(verbo + " "):
            dito = dito[len(verbo) + 1 :]
            break

    melhor: tuple[int, str] | None = None
    for rotulo in rotulos:
        if not falavel(rotulo):
            continue
        alvo = normalizar(rotulo)
        if not alvo:
            continue
        if alvo == dito:
            return rotulo
        # Casamento parcial: o rotulo na tela costuma ter mais que o falado
        # ("Semeando (12)" para "semeando"). Exige trecho longo o bastante --
        # transcricao ruim produz fragmentos curtos que casariam com qualquer
        # coisa, e um falso positivo aqui vira clique errado.
        if len(dito) < _MIN_CASAMENTO or len(alvo) < _MIN_CASAMENTO:
            continue
        if _contem_palavras(alvo, dito) or _contem_palavras(dito, alvo):
            # Pontua pelo rotulo, nao pelo falado: entre varios que servem,
            # o mais especifico ganha.
            pontos = len(alvo)
            if melhor is None or pontos > melhor[0]:
                melhor = (pontos, rotulo)

    return melhor[1] if melhor else None
