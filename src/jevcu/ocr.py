"""OCR nativo do Windows (Windows.Media.Ocr).

Equivalente do Vision do macOS: embutido no SO, offline, gratuito, sem instalar
nada. Medido nesta maquina em 1920x1080: ~151 ms de OCR, ~287 ms com captura e
decode incluidos. Idiomas disponiveis aqui: en-US e pt-BR.

Limitacao conhecida: erra em texto pequeno e antialiased. Por isso `upscale`
existe -- passe recortes ampliados em vez da tela inteira.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ocr.ps1"


@dataclass(frozen=True)
class OcrWord:
    text: str
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


@dataclass(frozen=True)
class OcrLine:
    text: str
    words: list[OcrWord]

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        if not self.words:
            return None
        left = min(w.x for w in self.words)
        top = min(w.y for w in self.words)
        right = max(w.x + w.width for w in self.words)
        bottom = max(w.y + w.height for w in self.words)
        return left, top, right - left, bottom - top


class OcrError(RuntimeError):
    pass


def read_image(path: str | Path, *, language: str = "pt-BR", timeout: float = 30.0) -> list[OcrLine]:
    """Roda o OCR nativo sobre um arquivo de imagem."""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        raise OcrError("powershell nao encontrado no PATH")
    if not SCRIPT.exists():
        raise OcrError(f"script nao encontrado: {SCRIPT}")

    proc = subprocess.run(
        [
            powershell, "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPT),
            "-Path", str(Path(path).resolve()),
            "-Language", language,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise OcrError(f"OCR falhou: {proc.stderr.strip()[:300]}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise OcrError(f"OCR devolveu JSON invalido: {proc.stdout[:200]}") from None

    lines: list[OcrLine] = []
    for raw in payload.get("lines", []):
        words = [
            OcrWord(w["text"], int(w["x"]), int(w["y"]), int(w["width"]), int(w["height"]))
            for w in raw.get("words", [])
        ]
        lines.append(OcrLine(raw.get("text", ""), words))
    return lines


def available_languages() -> list[str]:
    """Idiomas de OCR instalados no sistema."""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        return []
    script = (
        "$null = [Windows.Media.Ocr.OcrEngine,Windows.Media,ContentType=WindowsRuntime]; "
        "[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages "
        "| ForEach-Object { $_.LanguageTag }"
    )
    proc = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=30, check=False,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
