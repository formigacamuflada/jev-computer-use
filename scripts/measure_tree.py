"""Mede a reducao de tokens do esqueleto em janelas reais.

    python scripts/measure_tree.py chrome explorer notepad
    python scripts/measure_tree.py --foreground
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jevcu.tree import estimate_tokens, fit, interactive_nodes, skeleton  # noqa: E402
from jevcu.uia import UiaError, capture  # noqa: E402

# Orcamento do state do Jev: 32k cobrem state + maior pergunta.
# Reservamos parte para perguntas, historico e candidatos.
BUDGET = 6000
JEV_STATE_LIMIT = 32_000


def report(label: str, **kwargs) -> None:
    try:
        snapshot = capture(max_nodes=2000, **kwargs)
    except (UiaError, ValueError) as exc:
        print(f"  {label}: {exc}")
        return

    full = skeleton(snapshot.root, max_depth=99, max_children=9999)
    full_tokens = estimate_tokens(full)
    fitted, depth = fit(snapshot.root, budget_tokens=BUDGET)
    fit_tokens = estimate_tokens(fitted)
    reduction = 1 - fit_tokens / full_tokens if full_tokens else 0.0
    actions = len(interactive_nodes(snapshot.root))

    cabe_inteiro = "sim" if full_tokens <= JEV_STATE_LIMIT else "NAO"

    print(f"  {label}")
    print(f"    janela        : {snapshot.window[:56]!r}")
    print(f"    nos           : {snapshot.node_count}"
          f"{'  (truncado)' if snapshot.truncated else ''}")
    print(f"    leitura UIA   : {snapshot.elapsed_ms} ms")
    print(f"    acionaveis    : {actions}")
    print(f"    arvore inteira: {full_tokens:>6} tokens   cabe nos 32k? {cabe_inteiro}")
    print(f"    esqueleto     : {fit_tokens:>6} tokens   (profundidade {depth})")
    print(f"    reducao       : {reduction:>6.1%}")
    print()


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--foreground"]
    print(f"\norcamento do esqueleto: {BUDGET} tokens | limite de state do Jev: {JEV_STATE_LIMIT}\n")
    if "--foreground" in sys.argv or not args:
        report("janela em primeiro plano", foreground=True)
    for name in args:
        report(name, process=name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
