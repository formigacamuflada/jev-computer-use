"""Entrypoint: python -m jevcu"""

from __future__ import annotations

import argparse
import sys
import time

from .candidates import build_candidates, describe_table
from .config import Config, load_typesafe_key
from .driver import CuaDriver, DriverError, MockDriver, UiaDriver
from .jev import get_chooser
from .loop import Agent
from .voice.grammar import casar, frases_para
from .voice.stt import get_listener
from .voice.tts import get_speaker

OUTCOME_SPEECH = {
    "done": "Feito.",
    "abstained": "Nao fiz nada, nenhuma acao parecia segura.",
    "exhausted": "Desisti, passos demais.",
    "escalate": "Preciso de confirmacao.",
    "error": "Deu erro.",
}


def _metricas(run, stt_ms: float = 0.0) -> str:
    """Linha compacta de desempenho do ciclo.

    Os dados vivem em `run.timing()` e em `choice.usage`, estruturados -- isto
    aqui e so a renderizacao para terminal. Uma UI le os mesmos campos.
    """
    t = run.timing()
    partes = []
    if stt_ms:
        partes.append(f"voz {stt_ms:.0f}ms")
    partes.append(f"tela {t['observe_ms']:.0f}ms")
    partes.append(f"jev {t['decide_ms']:.0f}ms")
    if t["execute_ms"]:
        partes.append(f"acao {t['execute_ms']:.0f}ms")

    uso = next((s.choice.usage for s in reversed(run.steps) if s.choice.usage), None)
    if uso and uso.input_tokens:
        partes.append(f"{uso.input_tokens} tok")
        partes.append(f"{uso.tokens_per_second:,.0f} tok/s")
        partes.append(f"US${uso.cost_usd:.6f}")

    total = t["total_ms"] + stt_ms
    return " | ".join(partes) + f"  (total {total:.0f}ms)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jevcu", description="Computer use por voz com Jev")
    parser.add_argument("goal", nargs="*", help="comando (se vazio, entra em modo interativo)")
    parser.add_argument("--app", help="limitar a observacao a um aplicativo")
    parser.add_argument("--driver", choices=["mock", "cua", "uia"], help="backend do Driver")
    parser.add_argument("--decide", choices=["mock", "live"], default="mock", help="backend Jev")
    parser.add_argument("--stt", choices=["text", "winrt", "whisper"], help="backend de voz")
    parser.add_argument("--dry-run", action="store_true", help="decidir sem executar")
    parser.add_argument("--no-speak", action="store_true", help="nao falar as respostas")
    parser.add_argument("--show-table", action="store_true", help="imprimir a tabela e sair")
    parser.add_argument("--list-mics", action="store_true", help="listar entradas de audio e sair")
    parser.add_argument("--mic", type=int, help="indice do microfone (backend whisper)")
    parser.add_argument(
        "--quiet-metrics", action="store_true", help="nao mostrar tempos e tokens"
    )
    parser.add_argument(
        "--model", default="small",
        help="modelo do whisper. tiny NAO serve para pt-BR (medido: 0 de 5 acertos)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.from_env()

    if args.list_mics:
        from .voice.stt import WhisperListener

        print("entradas de audio disponiveis:\n")
        for indice, nome, padrao in WhisperListener.dispositivos():
            marca = "  <== padrao do sistema" if padrao else ""
            print(f"  [{indice:>2}] {nome[:52]}{marca}")
        print("\nescolha uma com:  --mic <indice>")
        return 0

    driver_backend = args.driver or config.driver_backend
    stt_backend = args.stt or config.stt_backend
    speak = config.speak and not args.no_speak

    # --- Driver ---
    try:
        if driver_backend == "cua":
            driver = CuaDriver(config.driver_binary)
        elif driver_backend == "uia":
            driver = UiaDriver(process=args.app)
        else:
            driver = MockDriver()
    except DriverError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    # --- Jev ---
    try:
        chooser = get_chooser(
            args.decide,
            api_key=load_typesafe_key(),
            model=config.model,
            timeout=config.jev_timeout,
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

    def handle(
        goal: str,
        must_include: str | None = None,
        speech_hint: dict | None = None,
        stt_ms: float = 0.0,
    ) -> bool:
        """Devolve False quando o usuario interrompeu a decisao."""
        ao_vivo = args.decide == "live"
        if ao_vivo:
            print("[decidindo] consultando o Jev...", end="", flush=True)
        try:
            run = agent.run(
                goal,
                app=args.app,
                dry_run=args.dry_run,
                must_include=must_include,
                speech_hint=speech_hint,
            )
        except KeyboardInterrupt:
            # Ctrl+C durante uma chamada lenta nao deve despejar traceback.
            print("\n[cancelado]")
            return False
        finally:
            if ao_vivo:
                print("\r" + " " * 42 + "\r", end="")

        print(f"=> {run.outcome}: {run.message}")
        if not args.quiet_metrics:
            print("   " + _metricas(run, stt_ms))
        speaker.say(OUTCOME_SPEECH.get(run.outcome, "") + " " + run.message)
        return True

    if args.goal:
        handle(" ".join(args.goal))
        return 0

    # Modo interativo / por voz
    if stt_backend == "whisper":
        # Carregar o small custa cerca de 10 s uma vez por sessao. Sem aviso,
        # parece travamento e a pessoa desiste antes de comecar.
        print(f"carregando o modelo {args.model} (uma vez por sessao)...",
              end="", flush=True)
    listener = get_listener(
        stt_backend, language=config.language, mic=args.mic, model=args.model
    )
    if stt_backend == "whisper":
        print(" pronto.")
    por_voz = stt_backend != "text"
    detalhe = stt_backend
    if stt_backend == "whisper":
        detalhe += f" {args.model} em {getattr(listener, 'backend', '?')}"
    print(f"modo interativo (stt={detalhe}, driver={driver_backend}, jev={args.decide})")
    if por_voz:
        print("Fale um comando. Ctrl+C para sair.")
        speaker.say("Estou ouvindo.")
    else:
        print("Ctrl+C ou linha vazia para sair.")
    print()

    falhas = 0
    while True:
        phrases = None
        rotulos: list[str] = []

        if por_voz:
            # O vocabulario vem da tela: o motor offline precisa de uma lista
            # fechada, e os elementos acionaveis ja sao exatamente isso.
            try:
                observation = driver.observe(args.app)
            except DriverError as exc:
                print(f"erro ao observar: {exc}")
                break
            rotulos = [e.name for e in observation.elements if e.name and e.enabled]
            phrases = frases_para(rotulos)
            print(f"[ouvindo] {observation.window_title[:50]} "
                  f"({len(rotulos)} elementos, {len(phrases)} frases)")

        marca = time.perf_counter()
        try:
            falado = listener.listen(phrases)
            stt_ms = (time.perf_counter() - marca) * 1000
            falhas = 0
        except KeyboardInterrupt:
            break
        except ValueError as exc:
            print(f"erro de uso: {exc}")
            break
        except RuntimeError as exc:
            # Falha do motor nao derruba a sessao: ele ja tentou de novo
            # internamente, entao aqui so desiste se for persistente.
            falhas += 1
            print(f"[falha {falhas}/3] {exc}")
            if falhas >= 3:
                print("\nO motor de fala falhou tres vezes seguidas.")
                print("Confira o microfone padrao em Configuracoes > Sistema > Som > Entrada.")
                print("Se 'Mixagem estereo' estiver como padrao, troque para o microfone real.")
                print(r"Alternativa: .\scripts\voz.ps1 -Texto")
                break
            continue

        if not falado:
            if por_voz:
                continue          # silencio: volta a ouvir
            break

        print(f"[ouvi] {falado!r}")
        if falado.lower() in {"parar", "cancelar", "esquece"}:
            speaker.say("Parando.")
            break

        # Traduz o falado para o rotulo exato da tela, que e o que as
        # descricoes dos candidatos usam.
        # O casamento e DICA, nao portao. Quando acerta um rotulo, reservamos
        # a vaga dele na tabela. Quando nao acerta, o pedido segue cru para o
        # decisor: "quero ver o que ja terminou de baixar" nao casa com
        # "Completado" por texto nenhum, mas o Jev resolve a intencao.
        alvo = casar(falado, rotulos) if rotulos else None
        if alvo:
            print(f"[alvo] {alvo!r}")
            # O objetivo e a frase ORIGINAL; o rotulo vai como dica. Assim o
            # Jev julga se aquilo foi mesmo um comando, em vez de receber um
            # pedido ja mastigado que ele so confirma.
            if not handle(
                falado,
                must_include=alvo,
                speech_hint={"heard": falado, "recognizer_guess": alvo},
                stt_ms=stt_ms,
            ):
                break
            continue

        if args.decide == "mock":
            # O mock nao e calibrado: ele sempre escolhe alguma coisa, entao
            # ruido viraria acao. So o decisor com confianca calibrada pode
            # receber texto que nao casou com nada.
            print("[nao entendi] nenhum elemento corresponde (use --decide live)")
            speaker.say("Nao entendi.")
            continue

        print("[intencao] sem rotulo obvio; deixando o Jev decidir")
        if not handle(falado, stt_ms=stt_ms):
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
