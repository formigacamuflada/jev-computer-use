"""Camada de percepcao e acao: Cua Driver.

O Driver e dono da captura, das coordenadas, da execucao e da verificacao.
Esta camada so o embrulha e compacta a observacao para caber no state do Jev
(32k tokens para state + maior pergunta).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Element:
    """Um elemento interativo observado na tela."""

    ref: str
    role: str
    name: str
    enabled: bool = True
    bounds: tuple[int, int, int, int] | None = None

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

    def compact(self, limit: int = 40) -> dict[str, Any]:
        return {
            "app": self.app,
            "window": self.window_title,
            "elements": [e.compact() for e in self.elements[:limit]],
            "truncated": len(self.elements) > limit,
        }


class DriverError(RuntimeError):
    pass


class Driver(Protocol):
    def observe(self, app: str | None = None) -> Observation: ...
    def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class CuaDriver:
    """Fala com o binario `cua-driver` por JSON no stdout.

    Instale antes (PowerShell):  irm https://cua.ai/driver/install.ps1 | iex
    """

    def __init__(self, binary: str = "cua-driver", *, timeout: float = 30.0) -> None:
        resolved = shutil.which(binary)
        if resolved is None:
            raise DriverError(
                f"binario {binary!r} nao encontrado no PATH. "
                "Instale com:  irm https://cua.ai/driver/install.ps1 | iex"
            )
        self._binary = resolved
        self._timeout = timeout

    def _run(self, args: list[str]) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                [self._binary, *args, "--json"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise DriverError(f"cua-driver estourou o timeout em: {' '.join(args)}") from None

        if proc.returncode != 0:
            raise DriverError(f"cua-driver falhou ({proc.returncode}): {proc.stderr.strip()[:300]}")

        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise DriverError(f"cua-driver devolveu JSON invalido: {proc.stdout[:200]}") from None

    def observe(self, app: str | None = None) -> Observation:
        args = ["snapshot", "-i"]
        if app:
            args += ["--app", app]
        payload = self._run(args)
        return parse_observation(payload)

    def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        args = [tool]
        for key, value in arguments.items():
            if key == "ref":
                args.append(str(value))
            else:
                args += [f"--{key.replace('_', '-')}", str(value)]
        return self._run(args)


def parse_observation(payload: dict[str, Any]) -> Observation:
    """Normaliza a resposta do Driver. Tolerante ao formato exato do snapshot."""
    data = payload.get("data", payload)
    raw_elements = data.get("elements") or data.get("nodes") or []

    elements: list[Element] = []
    for raw in raw_elements:
        if not isinstance(raw, dict):
            continue
        ref = raw.get("ref") or raw.get("id")
        if not ref:
            continue
        bounds = raw.get("bounds")
        parsed_bounds = None
        if isinstance(bounds, dict):
            parsed_bounds = (
                int(bounds.get("x", 0)),
                int(bounds.get("y", 0)),
                int(bounds.get("width", 0)),
                int(bounds.get("height", 0)),
            )
        elements.append(
            Element(
                ref=str(ref),
                role=str(raw.get("role") or raw.get("type") or "Unknown"),
                name=str(raw.get("name") or raw.get("title") or raw.get("text") or ""),
                enabled=bool(raw.get("enabled", True)),
                bounds=parsed_bounds,
            )
        )

    return Observation(
        snapshot_id=str(data.get("snapshot_id") or data.get("snapshot") or "s0"),
        app=str(data.get("app") or "desconhecido"),
        window_title=str(data.get("window") or data.get("title") or ""),
        elements=elements,
        capture_id=data.get("capture_id"),
    )


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
            Element("e1", "Button", "Salvar"),
            Element("e2", "Button", "Cancelar"),
            Element("e3", "Edit", "Nome do arquivo"),
            Element("e4", "Button", "Nova pasta"),
            Element("e5", "MenuItem", "Arquivo"),
            Element("e6", "MenuItem", "Editar"),
        ],
    )
