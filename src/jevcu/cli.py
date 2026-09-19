"""Entrypoint: python -m jevcu"""

from __future__ import annotations

import argparse
import sys

from .candidates import build_candidates, describe_table
from .config import Config, load_typesafe_key
from .driver import CuaDriver, DriverError, MockDriver
from .jev import get_chooser
from .loop import Agent
from .voice.stt import get_listener
from .voice.tts import get_speaker

OUTCOME_SPEECH = {
    "done": "Feito.",
    "abstained": "Nao fiz nada, nenhuma acao parecia segura.",
    "exhausted": "Desisti, passos demais.",
    "escalate": "Preciso de confirmacao.",
    "error": "Deu erro.",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jevcu", description="Computer use por voz com Jev")
    parser.add_argument("goal", nargs="*", help="comando (se vazio, entra em modo interativo)")
    parser.add_argument("--app", help="limitar a observacao a um aplicativo")
    parser.add_argument("--driver", choices=["mock", "cli"], help="backend do Driver")
    parser.add_argument("--decide", choices=["mock", "live"], default="mock", help="backend Jev")
    parser.add_argument("--stt", choices=["text", "winrt", "whisper"], help="backend de voz")
    parser.add_argument("--dry-run", action="store_true", help="decidir sem executar")
    parser.add_argument("--no-speak", action="store_true", help="nao falar as respostas")
    parser.add_argument("--show-table", action="store_true", help="imprimir a tabela e sair")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.from_env()

    driver_backend = args.driver or config.driver_backend
    stt_backend = args.stt or config.stt_backend
    speak = config.speak and not args.no_speak

    # --- Driver ---
    try:
        driver = (
            CuaDriver(config.driver_binary) if driver_backend == "cli" else MockDriver()
        )
    except DriverError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    # --- Jev ---
    try:
        chooser = get_chooser(
            args.decide, api_key=load_typesafe_key(), model=config.model
        )
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    speaker = get_speaker(speak, config.tts_voice)

    if args.show_table:
        observation = driver.observe(args.app)
        print(f"{observation.app} -- {observation.window_title}\n")
        print(describe_table(build_candidates(observation)))
        return 0

    agent = Agent(driver, chooser, config, on_event=lambda kind, text: print(f"[{kind}] {text}"))

    def handle(goal: str) -> None:
        run = agent.run(goal, app=args.app, dry_run=args.dry_run)
        line = f"{run.outcome}: {run.message}"
        print(f"\n=> {line}")
        speaker.say(OUTCOME_SPEECH.get(run.outcome, "") + " " + run.message)

    if args.goal:
        handle(" ".join(args.goal))
        return 0

    # Modo interativo / por voz
    listener = get_listener(stt_backend, language=config.language)
    print(f"modo interativo (stt={stt_backend}, driver={driver_backend}, jev={args.decide})")
    print("Ctrl+C ou linha vazia para sair.\n")
    while True:
        goal = listener.listen()
        if not goal:
            break
        handle(goal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
