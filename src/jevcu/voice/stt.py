"""Entrada de voz.

Tres backends, porque a disponibilidade varia:

  text    Digitado. Sempre funciona. Default para desenvolver o loop.
  winrt   Windows.Media.SpeechRecognition. Tem pt-BR nesta maquina, em modo
          ditado (nuvem) e em modo gramatica (offline). Exige o pacote
          `winsdk`. System.Speech NAO serve: nao ha recognizer instalado.
  whisper faster-whisper local na GPU. Melhor qualidade em pt-BR e sem nuvem.
"""

from __future__ import annotations

from typing import Protocol


class Listener(Protocol):
    def listen(self) -> str | None: ...


class TextListener:
    """Le comandos do stdin. Devolve None no fim da entrada."""

    def __init__(self, prompt: str = "\ncomando> ") -> None:
        self._prompt = prompt

    def listen(self) -> str | None:
        try:
            line = input(self._prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return line or None


class WinRtListener:
    """Reconhecimento nativo do Windows via WinRT.

    Modo gramatica (offline) restringe o reconhecimento a uma lista de frases,
    o que aumenta muito a acuracia e casa com a filosofia do Jev: espaco de
    acoes fechado.
    """

    def __init__(self, language: str = "pt-BR", phrases: list[str] | None = None) -> None:
        try:
            import winsdk.windows.media.speechrecognition as sr  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "backend 'winrt' exige o pacote winsdk:  pip install winsdk"
            ) from exc
        self._language = language
        self._phrases = phrases or []

    def listen(self) -> str | None:
        import asyncio

        return asyncio.run(self._listen_async())

    async def _listen_async(self) -> str | None:
        import winsdk.windows.globalization as wg
        import winsdk.windows.media.speechrecognition as sr

        language = wg.Language(self._language)
        recognizer = sr.SpeechRecognizer(language)

        if self._phrases:
            constraint = sr.SpeechRecognitionListConstraint(self._phrases)
            recognizer.constraints.append(constraint)

        await recognizer.compile_constraints_async()
        result = await recognizer.recognize_async()

        if result.status != sr.SpeechRecognitionResultStatus.SUCCESS:
            return None
        text = (result.text or "").strip()
        return text or None


class WhisperListener:
    """faster-whisper local. Boa opcao para a RTX 3060 Ti."""

    def __init__(self, model_size: str = "small", language: str = "pt") -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "backend 'whisper' exige:  pip install faster-whisper sounddevice"
            ) from exc
        self._model = WhisperModel(model_size, device="cuda", compute_type="float16")
        self._language = language

    def listen(self, seconds: float = 5.0) -> str | None:
        import numpy as np
        import sounddevice as sd

        audio = sd.rec(int(seconds * 16000), samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        segments, _ = self._model.transcribe(
            np.squeeze(audio), language=self._language, beam_size=1
        )
        text = " ".join(segment.text for segment in segments).strip()
        return text or None


def get_listener(backend: str, *, language: str, phrases: list[str] | None = None) -> Listener:
    if backend == "text":
        return TextListener()
    if backend == "winrt":
        return WinRtListener(language, phrases)
    if backend == "whisper":
        return WhisperListener(language=language.split("-")[0])
    raise ValueError(f"backend de STT desconhecido: {backend!r}")
