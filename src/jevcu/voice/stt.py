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

# 0x800455A0: o motor entrou em estado ruim, nao e pedido invalido.
_INTERNAL_SPEECH_ERROR = -2147199584


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

    Dois cuidados que o motor de fala cobra caro:

    O recognizer antigo PRECISA ser fechado antes de criar outro. Ele segura o
    dispositivo de captura, e um segundo com o primeiro vivo falha com
    0x800455A0 "Internal Speech Error". Isso aparece quando o vocabulario muda
    entre uma escuta e outra, que e o caso normal ao trocar de tela.

    O event loop e um so para toda a sessao. Um `asyncio.run` por escuta deixa
    o recognizer preso a um loop ja fechado na chamada seguinte.
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
        self._loop = None
        self._stage = "ocioso"

    # -- ciclo de vida -----------------------------------------------------

    def _get_loop(self):
        import asyncio

        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def _dispose(self) -> None:
        """Libera o recognizer atual e, com ele, o microfone."""
        if self._recognizer is None:
            return
        try:
            self._recognizer.close()
        except Exception:
            # Ja fechado ou em estado ruim: seguir e soltar a referencia.
            pass
        self._recognizer = None
        self._compiled = None

    def close(self) -> None:
        self._dispose()
        if self._loop is not None and not self._loop.is_closed():
            self._loop.close()
        self._loop = None

    def __enter__(self) -> "WinRtListener":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- reconhecimento ----------------------------------------------------

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

        # Fecha antes de abrir: dois recognizers vivos = Internal Speech Error.
        self._dispose()

        self._stage = "criando o recognizer"
        recognizer = SpeechRecognizer(Language(self._language))
        recognizer.timeouts.initial_silence_timeout = timedelta(seconds=self._timeout_s)
        recognizer.constraints.append(SpeechRecognitionListConstraint(phrases))

        self._stage = "compilando a gramatica"
        result = await recognizer.compile_constraints_async()
        if result.status != SpeechRecognitionResultStatus.SUCCESS:
            try:
                recognizer.close()
            except Exception:
                pass
            raise RuntimeError(f"gramatica nao compilou: {result.status!r}")

        self._recognizer = recognizer
        self._compiled = key
        return recognizer

    def listen(self, phrases: list[str] | None = None) -> str | None:
        """Escuta uma vez. Erro interno do motor gera UMA nova tentativa limpa.

        0x800455A0 costuma significar que o motor ficou em estado ruim, nao que
        o pedido era invalido. Descartar e refazer resolve na maioria das vezes;
        se falhar de novo, o problema e do ambiente e o erro sobe com o estagio
        em que aconteceu.
        """
        if not phrases:
            raise ValueError("o backend winrt precisa de um vocabulario fechado")

        for tentativa in (1, 2):
            self._stage = "preparando"
            try:
                return self._get_loop().run_until_complete(self._listen(phrases))
            except OSError as exc:
                codigo = getattr(exc, "winerror", None)
                self._dispose()
                if tentativa == 1 and codigo == _INTERNAL_SPEECH_ERROR:
                    continue
                raise RuntimeError(
                    f"motor de fala falhou em '{self._stage}' "
                    f"(WinError {codigo}): {exc}"
                ) from None
        return None

    async def _listen(self, phrases: list[str]) -> str | None:
        from winrt.windows.media.speechrecognition import SpeechRecognitionResultStatus

        recognizer = await self._ensure(phrases)
        self._stage = "capturando audio"
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
