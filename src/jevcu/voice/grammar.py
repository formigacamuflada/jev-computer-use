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


def normalizar(texto: str) -> str:
    """Forma falavel de um rotulo de UI.

    Remove pontuacao e contadores que ninguem fala: o usuario diz "semeando",
    nao "semeando abre parenteses doze fecha parenteses".
    """
    limpo = _LIMPEZA.sub(" ", texto)
    return _ESPACOS.sub(" ", limpo).strip().lower()


def frases_para(rotulos: list[str], *, max_rotulos: int = 60) -> list[str]:
    """Monta o vocabulario: um verbo x rotulo para cada elemento acionavel."""
    frases: list[str] = list(COMANDOS_FIXOS)
    vistos: set[str] = set()

    for rotulo in rotulos[:max_rotulos]:
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
        alvo = normalizar(rotulo)
        if not alvo:
            continue
        if alvo == dito:
            return rotulo
        # Casamento parcial: o rotulo na tela costuma ter mais que o falado
        # ("Semeando (12)" para "semeando").
        if dito and (dito in alvo or alvo in dito):
            pontos = len(dito)
            if melhor is None or pontos > melhor[0]:
                melhor = (pontos, rotulo)

    return melhor[1] if melhor else None
