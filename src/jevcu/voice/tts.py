"""Sintese de voz em pt-BR via SAPI.

Usa a voz "Microsoft Maria Desktop", que ja vem instalada no Windows pt-BR.
Confirmado nesta maquina junto com "Microsoft Zira Desktop" [en-US].
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Protocol


class Speaker(Protocol):
    def say(self, text: str) -> None: ...


class SapiSpeaker:
    """Fala via System.Speech (SAPI). Sintese existe mesmo sem recognizer de STT.

    Nao bloqueia. Medido nesta maquina: falar "Feito." custava 2,1 s e uma
    frase com a descricao do candidato custava 5,9 s -- tempo que nao aparecia
    em metrica nenhuma e que o usuario sentia como lentidao do sistema. A fala
    e aviso, nao etapa do ciclo: ela sai enquanto a proxima escuta ja comecou.
    """

    def __init__(self, voice: str = "Microsoft Maria Desktop", *, rate: int = 1) -> None:
        self._voice = voice
        self._rate = rate
        self._powershell = shutil.which("powershell") or shutil.which("pwsh")
        if self._powershell is None:
            raise RuntimeError("powershell nao encontrado no PATH")
        self._pendentes: list[subprocess.Popen] = []

    def say(self, text: str) -> None:
        if not text.strip():
            return
        # Recolhe as falas ja terminadas para os processos nao se acumularem
        # numa sessao longa.
        self._pendentes = [p for p in self._pendentes if p.poll() is None]
        # Passa o texto por stdin para nao precisar escapar aspas no comando.
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"try {{ $s.SelectVoice('{self._voice}') }} catch {{ }}; "
            f"$s.Rate = {self._rate}; "
            "$t = [Console]::In.ReadToEnd(); "
            "$s.Speak($t); $s.Dispose()"
        )
        processo = subprocess.Popen(
            [self._powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if processo.stdin is not None:
            processo.stdin.write(text)
            processo.stdin.close()
        self._pendentes.append(processo)


class SilentSpeaker:
    """Imprime em vez de falar. Default nos testes e no CI."""

    def say(self, text: str) -> None:
        print(f"[voz] {text}")


def get_speaker(enabled: bool, voice: str) -> Speaker:
    if not enabled:
        return SilentSpeaker()
    try:
        return SapiSpeaker(voice)
    except RuntimeError:
        return SilentSpeaker()
