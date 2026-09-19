"""Camada de percepcao e acao: Cua Driver.

O Driver e dono da captura, das coordenadas, da execucao e da verificacao.
Esta camada so o embrulha e compacta a observacao para caber no state do Jev.

Backends:
  CuaDriver   binario cua-driver via daemon. Observa e AGE.
  UiaDriver   UI Automation por PowerShell. So observa; nao instala nada.
  MockDriver  em memoria, para testes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Protocol

from .tree import Node, estimate_tokens, fit, interactive_nodes


@dataclass(frozen=True)
class Element:
    """Um elemento interativo observado na tela."""

    ref: str
    role: str
    name: str
    enabled: bool = True
    bounds: tuple[int, int, int, int] | None = None
    # Identificadores do Cua Driver. Valem so para o snapshot que os produziu.
    index: int | None = None
    token: str | None = None

    def compact(self) -> dict[str, Any]:
        """Forma enxuta que vai para o Jev. Sem coordenada: ele nao precisa."""
        item: dict[str, Any] = {"ref": self.ref, "role": self.role, "name": self.name}
        if not self.enabled:
            item["enabled"] = False
        return item


@dataclass(frozen=True)
class Observation:
    """Uma leitura da tela, valida so enquanto a UI nao mudar."""

    snapshot_id: str
    app: str
    window_title: str
    elements: list[Element] = field(default_factory=list)
    capture_id: str | None = None
    tree: Node | None = None
    pid: int | None = None
    window_id: int | None = None

    def compact(self, limit: int = 40, *, budget_tokens: int = 6000) -> dict[str, Any]:
        """Forma que vai no state do Jev.

        Com arvore, usa esqueleto ajustado ao orcamento. Sem arvore, cai na
        lista plana de elementos.
        """
        base: dict[str, Any] = {"app": self.app, "window": self.window_title}

        if self.tree is not None:
            payload, depth = fit(self.tree, budget_tokens=budget_tokens)
            base["skeleton"] = payload
            base["skeleton_depth"] = depth
            base["est_tokens"] = estimate_tokens(payload)
            return base

        base["elements"] = [e.compact() for e in self.elements[:limit]]
        base["truncated"] = len(self.elements) > limit
        return base


class DriverError(RuntimeError):
    pass


class Driver(Protocol):
    def observe(self, app: str | None = None) -> Observation: ...
    def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


# --------------------------------------------------------------------------
# Cua Driver
# --------------------------------------------------------------------------

DEFAULT_BINARY = "cua-driver"


def build_tree(elements: list[dict[str, Any]], *, window_title: str) -> Node:
    """Reconstroi a arvore a partir da lista plana e dos `parent_index`.

    O Driver devolve os elementos achatados, cada um apontando para o pai. A
    hierarquia importa para o esqueleto, entao remontamos aqui.
    """
    children: dict[int | None, list[dict[str, Any]]] = {}
    for element in elements:
        children.setdefault(element.get("parent_index"), []).append(element)

    def build(raw: dict[str, Any]) -> Node:
        index = raw.get("element_index")
        return Node(
            ref=str(raw.get("element_token") or index),
            role=str(raw.get("role") or "Unknown"),
            name=str(raw.get("label") or ""),
            enabled=bool(raw.get("enabled", True)),
            children=tuple(build(child) for child in children.get(index, [])),
        )

    roots = children.get(None, [])
    if len(roots) == 1:
        return build(roots[0])
    # Sem raiz unica: pendura tudo sob uma raiz sintetica.
    return Node("root", "Window", window_title, children=tuple(build(r) for r in roots))


class CuaDriver:
    """Fala com o binario `cua-driver` pelo daemon.

    Instale:  irm https://cua.ai/driver/install.ps1 | iex
    Suba o daemon:  cua-driver autostart kick

    A CLI recebe os argumentos como um unico JSON posicional:
        cua-driver call <tool> '{"pid":123,...}'
    """

    def __init__(
        self,
        binary: str = DEFAULT_BINARY,
        *,
        timeout: float = 60.0,
        max_elements: int = 1500,
    ) -> None:
        resolved = shutil.which(binary) or (binary if "/" in binary or "\\" in binary else None)
        if resolved is None:
            raise DriverError(
                f"binario {binary!r} nao encontrado no PATH. "
                "Instale com:  irm https://cua.ai/driver/install.ps1 | iex"
            )
        self._binary = resolved
        self._timeout = timeout
        self._max_elements = max_elements

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = json.dumps(arguments or {}, ensure_ascii=False)
        try:
            proc = subprocess.run(
                [self._binary, "call", tool, payload],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=self._timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            raise DriverError(f"timeout em {tool}") from None

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()[:300]
            raise DriverError(f"{tool} falhou: {detail}")

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise DriverError(f"{tool} devolveu JSON invalido: {proc.stdout[:200]}") from None

        if result.get("isError"):
            raise DriverError(f"{tool}: {str(result)[:300]}")
        return result

    def list_windows(self, pid: int | None = None) -> list[dict[str, Any]]:
        result = self.call("list_windows", {"pid": pid} if pid else {})
        content = result.get("structuredContent", result)
        return content.get("windows") or []

    def _pick_window(self, app: str | None) -> dict[str, Any]:
        windows = self.list_windows()
        if not windows:
            raise DriverError("nenhuma janela visivel")
        if app:
            needle = app.lower()
            for window in windows:
                haystack = f"{window.get('app_name','')} {window.get('title','')}".lower()
                if needle in haystack:
                    return window
            raise DriverError(f"nenhuma janela casa com {app!r}")
        return windows[0]

    def observe(self, app: str | None = None) -> Observation:
        window = self._pick_window(app)
        pid = window.get("pid")
        window_id = window.get("window_id")

        result = self.call("get_window_state", {
            "pid": pid,
            "window_id": window_id,
            "include_screenshot": False,
            "max_elements": self._max_elements,
        })
        content = result.get("structuredContent", result)
        raw_elements = content.get("elements") or []

        elements = [
            Element(
                ref=str(raw.get("element_token") or raw.get("element_index")),
                role=str(raw.get("role") or "Unknown"),
                name=str(raw.get("label") or ""),
                enabled=bool(raw.get("enabled", True)),
                index=raw.get("element_index"),
                token=raw.get("element_token"),
            )
            for raw in raw_elements
        ]
        window_title = str(content.get("window_title") or "")

        return Observation(
            snapshot_id=str(content.get("snapshot_id") or "s0"),
            app=str(content.get("app_name") or "desconhecido"),
            window_title=window_title,
            elements=elements,
            tree=build_tree(raw_elements, window_title=window_title) if raw_elements else None,
            pid=pid,
            window_id=window_id,
        )

    def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.call(tool, arguments)


# --------------------------------------------------------------------------
# UI Automation direto (somente leitura)
# --------------------------------------------------------------------------

class UiaDriver:
    """Le a arvore de UI Automation via PowerShell.

    Nao instala nada, mas nao age: `execute` falha de proposito em vez de
    fingir sucesso. Util para inspecionar telas sem o daemon do Cua.
    """

    def __init__(self, *, process: str | None = None, max_nodes: int = 1200) -> None:
        self._process = process
        self._max_nodes = max_nodes
        self._counter = 0

    def observe(self, app: str | None = None) -> Observation:
        from .uia import UiaError, capture

        target = app or self._process
        try:
            snapshot = capture(
                process=target,
                foreground=target is None,
                max_nodes=self._max_nodes,
            )
        except (UiaError, ValueError) as exc:
            raise DriverError(str(exc)) from None

        self._counter += 1
        elements = [
            Element(ref=node.ref, role=node.role, name=node.name, enabled=node.enabled)
            for node in interactive_nodes(snapshot.root)
        ]
        return Observation(
            snapshot_id=f"s_uia_{self._counter}",
            app=snapshot.app,
            window_title=snapshot.window,
            elements=elements,
            tree=snapshot.root,
        )

    def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise DriverError(
            "UiaDriver e somente leitura. Use --driver cua para executar acoes."
        )


# --------------------------------------------------------------------------
# Mock
# --------------------------------------------------------------------------

class MockDriver:
    """Driver falso para desenvolver e testar sem instalar nada.

    Guarda o que foi executado para os testes verificarem a pos-condicao de
    forma independente, em vez de confiar na resposta da acao.
    """

    def __init__(self, observations: list[Observation] | None = None) -> None:
        self._observations = observations or [_default_observation()]
        self._index = 0
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def observe(self, app: str | None = None) -> Observation:
        observation = self._observations[min(self._index, len(self._observations) - 1)]
        self._index += 1
        return observation

    def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.executed.append((tool, dict(arguments)))
        return {"ok": True, "tool": tool, "arguments": arguments}


def _default_observation() -> Observation:
    return Observation(
        snapshot_id="s_mock_1",
        app="Bloco de Notas",
        window_title="Sem titulo - Bloco de Notas",
        elements=[
            Element("e1", "Button", "Salvar", index=1),
            Element("e2", "Button", "Cancelar", index=2),
            Element("e3", "Edit", "Nome do arquivo", index=3),
            Element("e4", "Button", "Nova pasta", index=4),
            Element("e5", "MenuItem", "Arquivo", index=5),
            Element("e6", "MenuItem", "Editar", index=6),
        ],
        pid=1234,
        window_id=5678,
    )
