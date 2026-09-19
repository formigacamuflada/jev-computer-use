"""Entrada de voz.

Tres backends, porque a disponibilidade varia:

  text     Digitado. Sempre funciona. Default para desenvolver o loop.
  winrt    Windows.Media.SpeechRecognition com gramatica offline em pt-BR.
           Verificado nesta maquina: compila e roda de um processo Python
           desktop nao empacotado. Precisa dos pacotes winrt-* (o `winsdk`
           antigo nao tem wheel para 3.14 e exige Visual Studio para compilar).
  whisper  faster-whisper local na GPU. Portugues aberto, sem nuvem.

`System.Speech` nao serve: esta maquina nao tem nenhum recognizer instalado.
O ditado online tambem esta fora -- a politica de fala online nao foi aceita,
e por isso o modo gramatica e o caminho.
"""

from __future__ import annotations

from typing import Protocol


class Listener(Protocol):
    def listen(self, phrases: list[str] | None = None) -> str | None: ...


class TextListener:
    """Le comandos do stdin. Devolve None no fim da entrada."""

    def __init__(self, prompt: str = "\ncomando> ") -> None:
        self._prompt = prompt

    def listen(self, phrases: list[str] | None = None) -> str | None:
        try:
            line = input(self._prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return line or None


class WinRtListener:
    """Reconhecimento nativo do Windows, offline, com vocabulario fechado.

    A gramatica e recompilada quando o conjunto de frases muda -- normalmente
    a cada tela nova. Compilar custa tempo, entao o conjunto anterior fica em
    cache e so recompila de fato quando ha diferenca.
    """

    def __init__(self, language: str = "pt-BR", timeout_s: float = 8.0) -> None:
        try:
            import winrt.windows.media.speechrecognition as _sr  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "backend 'winrt' exige:\n"
                "  pip install winrt-runtime winrt-Windows.Media.SpeechRecognition "
                "winrt-Windows.Globalization"
            ) from exc
        self._language = language
        self._timeout_s = timeout_s
        self._recognizer = None
        self._compiled: tuple[str, ...] | None = None

    async def _ensure(self, phrases: list[str]):
        from datetime import timedelta

        from winrt.windows.globalization import Language
        from winrt.windows.media.speechrecognition import (
            SpeechRecognitionListConstraint,
            SpeechRecognitionResultStatus,
            SpeechRecognizer,
        )

        key = tuple(phrases)
        if self._recognizer is not None and self._compiled == key:
            return self._recognizer

        recognizer = SpeechRecognizer(Language(self._language))
        recognizer.timeouts.initial_silence_timeout = timedelta(seconds=self._timeout_s)
        recognizer.constraints.append(SpeechRecognitionListConstraint(phrases))

        result = await recognizer.compile_constraints_async()
        if result.status != SpeechRecognitionResultStatus.SUCCESS:
            raise RuntimeError(f"gramatica nao compilou: {result.status!r}")

        self._recognizer = recognizer
        self._compiled = key
        return recognizer

    def listen(self, phrases: list[str] | None = None) -> str | None:
        import asyncio

        if not phrases:
            raise ValueError("o backend winrt precisa de um vocabulario fechado")
        return asyncio.run(self._listen(phrases))

    async def _listen(self, phrases: list[str]) -> str | None:
        from winrt.windows.media.speechrecognition import SpeechRecognitionResultStatus

        recognizer = await self._ensure(phrases)
        result = await recognizer.recognize_async()
        if result.status != SpeechRecognitionResultStatus.SUCCESS:
            return None
        text = (result.text or "").strip()
        return text or None


class WhisperListener:
    """faster-whisper local. Portugues aberto, sem vocabulario fechado."""

    def __init__(self, model_size: str = "small", language: str = "pt") -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "backend 'whisper' exige:  pip install faster-whisper sounddevice numpy"
            ) from exc
        self._model = WhisperModel(model_size, device="cuda", compute_type="float16")
        self._language = language

    def listen(self, phrases: list[str] | None = None, seconds: float = 5.0) -> str | None:
        import numpy as np
        import sounddevice as sd

        audio = sd.rec(int(seconds * 16000), samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        segments, _ = self._model.transcribe(
            np.squeeze(audio), language=self._language, beam_size=1
        )
        text = " ".join(segment.text for segment in segments).strip()
        return text or None


def get_listener(backend: str, *, language: str = "pt-BR") -> Listener:
    if backend == "text":
        return TextListener()
    if backend == "winrt":
        return WinRtListener(language)
    if backend == "whisper":
        return WhisperListener(language=language.split("-")[0])
    raise ValueError(f"backend de STT desconhecido: {backend!r}")
