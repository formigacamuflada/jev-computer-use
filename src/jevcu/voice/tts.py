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
    """Fala via System.Speech (SAPI). Sintese existe mesmo sem recognizer de STT."""

    def __init__(self, voice: str = "Microsoft Maria Desktop", *, rate: int = 1) -> None:
        self._voice = voice
        self._rate = rate
        self._powershell = shutil.which("powershell") or shutil.which("pwsh")
        if self._powershell is None:
            raise RuntimeError("powershell nao encontrado no PATH")

    def say(self, text: str) -> None:
        if not text.strip():
            return
        # Passa o texto por stdin para nao precisar escapar aspas no comando.
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"try {{ $s.SelectVoice('{self._voice}') }} catch {{ }}; "
            f"$s.Rate = {self._rate}; "
            "$t = [Console]::In.ReadToEnd(); "
            "$s.Speak($t); $s.Dispose()"
        )
        subprocess.run(
            [self._powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            input=text,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )


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
