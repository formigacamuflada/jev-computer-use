"""Configuracao carregada de env vars, com defaults sensatos."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_secret_file(name: str) -> str | None:
    """Le um segredo de arquivo na raiz do projeto.

    Conveniencia para desenvolvimento local. Em producao use a variavel de
    ambiente: o SKILL.md do cua pede que a chave nunca fique em fonte, argumento
    de comando, log ou artefato.
    """
    path = PROJECT_ROOT / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return value or None


def load_typesafe_key() -> str | None:
    return os.environ.get("TYPESAFE_API_KEY") or _read_secret_file("jev-api-token.txt")


@dataclass(frozen=True)
class Config:
    # --- decisao ---
    model: str = "jev-latest"
    # Acima disso o agente age sozinho.
    act_threshold: float = 0.85
    # Abaixo disso nem vale escalar: reobserva.
    floor_threshold: float = 0.40
    # Rede ruim nao pode travar a sessao: o Jev responde em ~900 ms.
    jev_timeout: float = 8.0

    # --- loop ---
    max_steps: int = 12
    max_candidates: int = 24

    # --- voz ---
    stt_backend: str = "text"  # text | winrt | whisper
    tts_voice: str = "Microsoft Maria Desktop"
    speak: bool = True
    language: str = "pt-BR"

    # --- driver ---
    driver_backend: str = "mock"  # mock | cli
    driver_binary: str = "cua-driver"

    @classmethod
    def from_env(cls) -> "Config":
        def _f(name: str, default: float) -> float:
            raw = os.environ.get(name)
            return float(raw) if raw else default

        def _i(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return int(raw) if raw else default

        def _s(name: str, default: str) -> str:
            return os.environ.get(name) or default

        return cls(
            model=_s("JEVCU_MODEL", cls.model),
            act_threshold=_f("JEVCU_ACT_THRESHOLD", cls.act_threshold),
            floor_threshold=_f("JEVCU_FLOOR_THRESHOLD", cls.floor_threshold),
            jev_timeout=_f("JEVCU_JEV_TIMEOUT", cls.jev_timeout),
            max_steps=_i("JEVCU_MAX_STEPS", cls.max_steps),
            max_candidates=_i("JEVCU_MAX_CANDIDATES", cls.max_candidates),
            stt_backend=_s("JEVCU_STT", cls.stt_backend),
            tts_voice=_s("JEVCU_TTS_VOICE", cls.tts_voice),
            speak=_s("JEVCU_SPEAK", "1") not in {"0", "false", "no"},
            language=_s("JEVCU_LANG", cls.language),
            driver_backend=_s("JEVCU_DRIVER", cls.driver_backend),
            driver_binary=_s("JEVCU_DRIVER_BIN", cls.driver_binary),
        )
