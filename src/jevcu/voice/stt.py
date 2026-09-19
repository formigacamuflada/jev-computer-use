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
    """faster-whisper local, gravando pelo sounddevice.

    Nao toca no runtime de fala do Windows -- contorna o subsistema inteiro
    que produz 0x800455A0. Tambem deixa escolher o dispositivo de entrada
    explicitamente, em vez de depender do padrao do sistema.

    O vocabulario da tela nao vira gramatica fechada aqui, mas entra como
    `initial_prompt` para enviesar a transcricao rumo aos termos visiveis.
    """

    # Grava ate `max_seconds`, mas corta antes quando o silencio se estende.
    RATE = 16_000
    BLOCK = 0.1            # segundos por bloco analisado
    SILENCE_RMS = 0.012    # abaixo disto conta como silencio
    SILENCE_TO_STOP = 1.2  # segundos de silencio que encerram a fala
    MIN_SPEECH = 0.3       # fala mais curta que isto e ruido

    def __init__(
        self,
        model_size: str = "small",
        language: str = "pt",
        *,
        device: int | str | None = None,
        max_seconds: float = 12.0,
        compute: str | None = None,
    ) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "backend 'whisper' exige:  pip install faster-whisper sounddevice numpy"
            ) from exc

        self._model, self.backend = self._load(WhisperModel, model_size, compute)
        self._language = language
        self._device = device
        self._max_seconds = max_seconds

    @staticmethod
    def _load(WhisperModel, model_size: str, compute: str | None):
        """Tenta a GPU de verdade, e cai para CPU se ela nao servir.

        Ter GPU nao basta: o ctranslate2 conta os dispositivos CUDA sem checar
        se as bibliotecas de runtime existem. Numa maquina sem cuBLAS o
        contador diz 1 e a carga estoura com "cublas64_12.dll is not found".
        So construir o modelo prova que o caminho funciona.
        """
        tentativas: list[tuple[str, str]] = []
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                tentativas.append(("cuda", compute or "float16"))
        except Exception:
            pass
        tentativas.append(("cpu", compute or "int8"))

        import numpy as np

        # Meio segundo de silencio so para forcar o caminho de inferencia.
        # Construir o modelo na GPU e preguicoso: as bibliotecas CUDA so sao
        # carregadas na primeira transcricao, e e la que falta a cuBLAS.
        aquecimento = np.zeros(8000, dtype=np.float32)

        ultimo: Exception | None = None
        for dispositivo, precisao in tentativas:
            try:
                modelo = WhisperModel(model_size, device=dispositivo, compute_type=precisao)
                list(modelo.transcribe(aquecimento, language="pt", beam_size=1)[0])
                return modelo, f"{dispositivo}/{precisao}"
            except Exception as exc:
                ultimo = exc
        raise RuntimeError(f"nao foi possivel carregar o modelo {model_size!r}: {ultimo}")

    @staticmethod
    def dispositivos() -> list[tuple[int, str, bool]]:
        """(indice, nome, e_padrao) de cada entrada disponivel."""
        import sounddevice as sd

        padrao = sd.default.device[0]
        saida = []
        for indice, info in enumerate(sd.query_devices()):
            if info["max_input_channels"] > 0:
                saida.append((indice, info["name"], indice == padrao))
        return saida

    # Sem audio nenhum por este tempo, o dispositivo e considerado mudo.
    DEAD_DEVICE_S = 3.0

    def _gravar(self):
        """Grava ate a pessoa parar de falar, com prazo de parede.

        Usa callback e fila em vez de `stream.read()`: um `read` bloqueante
        nunca retorna quando o dispositivo para de entregar amostras, e a
        sessao inteira congela sem erro nenhum.
        """
        import queue
        import time

        import numpy as np
        import sounddevice as sd

        bloco = int(self.RATE * self.BLOCK)
        blocos_silencio_parar = int(self.SILENCE_TO_STOP / self.BLOCK)
        fila: queue.Queue = queue.Queue()

        def receber(indata, _frames, _time, _status):
            fila.put(indata[:, 0].copy())

        pedacos: list = []
        silencio = 0
        falou = False
        recebeu_algo = False

        with sd.InputStream(
            samplerate=self.RATE, channels=1, dtype="float32",
            blocksize=bloco, device=self._device, callback=receber,
        ):
            prazo = time.monotonic() + self._max_seconds
            while time.monotonic() < prazo:
                try:
                    amostra = fila.get(timeout=0.5)
                except queue.Empty:
                    if not recebeu_algo and time.monotonic() > prazo - self._max_seconds + self.DEAD_DEVICE_S:
                        raise RuntimeError(
                            "o dispositivo de entrada nao entregou audio nenhum. "
                            "Veja as opcoes com --list-mics e escolha outra com --mic."
                        )
                    continue

                recebeu_algo = True
                pedacos.append(amostra)
                rms = float(np.sqrt(np.mean(amostra**2)))
                if rms >= self.SILENCE_RMS:
                    falou = True
                    silencio = 0
                elif falou:
                    silencio += 1
                    if silencio >= blocos_silencio_parar:
                        break

        if not falou or not pedacos:
            return None
        audio = np.concatenate(pedacos)
        if len(audio) < self.RATE * self.MIN_SPEECH:
            return None
        return audio

    def listen(self, phrases: list[str] | None = None) -> str | None:
        audio = self._gravar()
        if audio is None:
            return None

        # As frases da tela enviesam a transcricao sem restringi-la.
        dica = ", ".join(phrases[:40]) if phrases else None

        segmentos, _info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=1,
            initial_prompt=dica,
            vad_filter=True,
        )
        texto = " ".join(s.text for s in segmentos).strip()
        return texto or None


def get_listener(
    backend: str,
    *,
    language: str = "pt-BR",
    mic: int | None = None,
    model: str = "small",
) -> Listener:
    if backend == "text":
        return TextListener()
    if backend == "winrt":
        return WinRtListener(language)
    if backend == "whisper":
        return WhisperListener(model, language=language.split("-")[0], device=mic)
    raise ValueError(f"backend de STT desconhecido: {backend!r}")
