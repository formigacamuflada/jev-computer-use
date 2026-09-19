"""Arvore de UI Automation do Windows, via PowerShell.

Ponte temporaria: quando o Cua Driver estiver instalado, ele faz isto nativo e
bem mais rapido. Serve para trabalhar em telas reais hoje, sem dependencia de
wheel do Python nem instalacao.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .tree import Node

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "uia_tree.ps1"


@dataclass(frozen=True)
class UiaSnapshot:
    app: str
    window: str
    root: Node
    node_count: int
    truncated: bool
    elapsed_ms: int


class UiaError(RuntimeError):
    pass


def _to_node(raw: dict) -> Node:
    children = tuple(_to_node(child) for child in raw.get("children", []) or [])
    return Node(
        ref=str(raw.get("ref", "")),
        role=str(raw.get("role", "Unknown")),
        name=str(raw.get("name") or ""),
        enabled=bool(raw.get("enabled", True)),
        children=children,
    )


def capture(
    *,
    process: str | None = None,
    foreground: bool = False,
    max_nodes: int = 1200,
    max_depth: int = 12,
    timeout: float = 60.0,
) -> UiaSnapshot:
    """Le a arvore de uma janela. Informe `process` ou `foreground`."""
    if not process and not foreground:
        raise ValueError("informe process= ou foreground=True")

    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        raise UiaError("powershell nao encontrado no PATH")
    if not SCRIPT.exists():
        raise UiaError(f"script nao encontrado: {SCRIPT}")

    args = [
        powershell, "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
        "-MaxNodes", str(max_nodes), "-MaxDepth", str(max_depth),
    ]
    args += ["-Foreground"] if foreground else ["-ProcessName", str(process)]

    proc = subprocess.run(
        args, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=timeout, check=False,
    )
    if proc.returncode != 0:
        raise UiaError(f"leitura da arvore falhou: {proc.stderr.strip()[:300]}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise UiaError(f"JSON invalido do UIA: {proc.stdout[:200]}") from None

    raw_tree = payload.get("tree")
    if not raw_tree:
        raise UiaError("arvore vazia")

    return UiaSnapshot(
        app=str(payload.get("app") or "desconhecido"),
        window=str(payload.get("window") or ""),
        root=_to_node(raw_tree),
        node_count=int(payload.get("node_count", 0)),
        truncated=bool(payload.get("truncated", False)),
        elapsed_ms=int(payload.get("elapsed_ms", 0)),
    )
