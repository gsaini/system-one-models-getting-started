"""`systemone demo | parallel | calibration | wikirace`: offline by default; --live, --llm, --ollama add arms.

`systemone ask | race | scoreboard | ui` are for showing the idea to a person: your own text, a race
followed hop by hop, one leaderboard, and a web playground.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from systemone import scoreboard
from systemone.arms import (
    DEFAULT_LLM,
    DEFAULT_OLLAMA,
    OLLAMA_URL,
    Arm,
    MissingCredentials,
    baseline_arm,
    jev_arm,
    llm_arm,
    ollama_arm,
    summary_table,
)
from systemone.data import load_races, load_sms, load_snapshot
from systemone.experiments import calibration, demo, parallel, wikirace
from systemone.playground import FORMS, ask
from systemone.views import ask_text, race_live

OFFLINE_NOTE = (
    "Offline: the keyword baseline answers, not Jev. It shows the mechanics and gives a baseline, nothing more."
)


def build_arms(args: argparse.Namespace, answerer) -> list[Arm]:
    arms = [baseline_arm(answerer)]
    if args.live:
        arms.append(jev_arm())
    if args.llm:
        arms.append(llm_arm(args.model, effort=None if args.effort == "default" else args.effort))
    if args.ollama:
        arms.append(ollama_arm(args.ollama, base_url=args.ollama_url))
    return arms


def gate(args: argparse.Namespace, what: str) -> bool:
    """Live runs spend money: say roughly how much and require --yes."""
    if not (args.live or args.llm) or args.yes:
        return True
    print(f"Live run: {what}. Re-run with --yes to confirm.", file=sys.stderr)
    return False


def save(args: argparse.Namespace, name: str, report: dict[str, Any], text: str) -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    mode = "+".join(
        ["baseline"]
        + (["jev"] if args.live else [])
        + (["llm"] if args.llm else [])
        + (["ollama"] if args.ollama else [])
    )
    out = args.out / f"{name}-{mode}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(text + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nSaved to {out}/", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="systemone", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_ in [
        ("demo", "one state, eight typed questions, one request"),
        ("parallel", "N questions in one request vs N requests: latency, tokens, agreement"),
        ("calibration", "spam Nouls graded against labels: accuracy, Brier, ECE, reliability"),
        ("wikirace", "Wikiracing on a bundled link snapshot: Choice, and two-stage above 255 options"),
        ("ask", "fill in a form about your own message, every player side by side"),
        ("race", "one Wikirace, printed hop by hop with each player's top picks"),
        ("scoreboard", "a short run of every graded experiment, as one leaderboard"),
        ("ui", "a local web playground: type a message, watch each player fill in the form"),
    ]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--live", action="store_true", help="add Jev (TYPESAFE_API_KEY)")
        p.add_argument(
            "--llm", action="store_true", help="add Claude through TypeSafe's adapter (Anthropic credentials)"
        )
        p.add_argument("--model", default=DEFAULT_LLM, help=f"LLM for --llm (default {DEFAULT_LLM})")
        p.add_argument("--effort", default="low", help="effort for --llm: low|medium|high|xhigh|max|default")
        p.add_argument(
            "--ollama",
            nargs="?",
            const=DEFAULT_OLLAMA,
            metavar="MODEL",
            help=f"add a local model served by Ollama, free (default {DEFAULT_OLLAMA})",
        )
        p.add_argument(
            "--ollama-url", default=OLLAMA_URL, help=f"Ollama's OpenAI-compatible URL (default {OLLAMA_URL})"
        )
        p.add_argument("--yes", action="store_true", help="confirm a live run")
        p.add_argument("--out", type=Path, default=Path("runs"))
        if name == "parallel":
            p.add_argument("--repeats", type=int, default=1)
        if name == "calibration":
            p.add_argument("--limit", type=int, default=1000, help="messages to grade (of 1,000)")
        if name in ("wikirace", "scoreboard"):
            p.add_argument("--races", type=int, default=None, help="only the first N races")
        if name == "ask":
            p.add_argument("message", nargs="?", default="-", help="the message; '-' or nothing reads stdin")
            p.add_argument("--form", choices=sorted(FORMS), default="support", help="which questions to ask")
        if name == "race":
            p.add_argument("--race", type=int, default=DEFAULT_RACE, help=f"race number (default {DEFAULT_RACE})")
            p.add_argument("--list", action="store_true", help="list the races and stop")
        if name == "scoreboard":
            p.add_argument("--limit", type=int, default=200, help="spam messages to grade (default 200)")
        if name == "ui":
            p.add_argument("--port", type=int, default=8765)
            p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args(argv)

    if args.cmd in SHOW:
        try:
            return SHOW[args.cmd](args)
        except MissingCredentials as exc:
            print(exc, file=sys.stderr)
            return 2
    if not (args.live or args.llm):
        print(f"▸ {OFFLINE_NOTE}\n", file=sys.stderr)
    try:
        if args.cmd == "demo":
            arms = build_arms(args, demo.answerer)
            report = demo.run(arms)
            text = demo.markdown(report) + "\n" + summary_table(arms)
        elif args.cmd == "parallel":
            n_requests = (len(parallel.SIZES) + sum(parallel.SIZES)) * args.repeats
            if not gate(
                args,
                f"about {n_requests} requests per model arm; Jev ≈ ${n_requests * 450 * 42e-9:.4f}, "
                "Claude under a dollar at low effort",
            ):
                return 2
            arms = build_arms(args, parallel.answerer)
            report = parallel.run(arms, repeats=args.repeats)
            text = parallel.markdown(report) + "\n\n" + summary_table(arms)
        elif args.cmd == "calibration":
            messages = load_sms(limit=args.limit)
            if not gate(
                args,
                f"{len(messages)} requests per model arm; Jev ≈ ${len(messages) * 120 * 42e-9:.4f}, "
                f"Claude roughly ${len(messages) * 0.003:.2f} at low effort",
            ):
                return 2
            arms = build_arms(args, calibration.answerer)
            report = calibration.run(arms, messages)
            text = calibration.markdown(report) + "\n\n" + summary_table(arms)
        else:
            snapshot, races = load_snapshot(), load_races()
            if args.races:
                races = races[: args.races]
            if not gate(
                args,
                f"{len(races)} races per model arm, a handful of requests each; "
                "Jev well under a cent, Claude a few cents",
            ):
                return 2
            arms = build_arms(args, wikirace.answerer)
            report = wikirace.run(arms, snapshot, races)
            text = wikirace.markdown(report) + "\n\n" + summary_table(arms)
    except MissingCredentials as exc:
        print(exc, file=sys.stderr)
        return 2
    print(text)
    save(args, args.cmd, report, text)
    return 0


DEFAULT_RACE = 9  # Bayes' theorem → Garry Kasparov: needs knowing that Turing links the two


def cmd_ask(args: argparse.Namespace) -> int:
    message = (sys.stdin.read() if args.message == "-" else args.message).strip()
    if not message:
        print('Give a message: systemone ask "I want my money back"', file=sys.stderr)
        return 2
    if not gate(args, "one request per model arm, well under a cent"):
        return 2
    form = FORMS[args.form]
    results = [ask(arm, form, message) for arm in build_arms(args, form.answerer)]
    print(ask_text(form, message, results))
    return 0


def cmd_race(args: argparse.Namespace) -> int:
    races = load_races()
    if args.list:
        for i, r in enumerate(races, 1):
            print(f"{i:>3}  {r.start} → {r.target}  ({r.shortest} hops)")
        return 0
    if not 1 <= args.race <= len(races):
        print(f"--race must be 1 to {len(races)}; see systemone race --list", file=sys.stderr)
        return 2
    if not gate(args, "a handful of requests per model arm, well under a cent"):
        return 2
    snapshot, race = load_snapshot(), races[args.race - 1]
    for arm in build_arms(args, wikirace.answerer):
        race_live(arm, snapshot, race)
    return 0


def cmd_scoreboard(args: argparse.Namespace) -> int:
    messages, snapshot, races = load_sms(limit=args.limit), load_snapshot(), load_races()
    if args.races:
        races = races[: args.races]
    if not gate(
        args,
        f"1 + {len(messages)} requests plus {len(races)} races per model arm; "
        f"Jev well under a cent, Claude roughly ${len(messages) * 0.003 + 0.1:.2f} at low effort",
    ):
        return 2
    report = scoreboard.run(lambda answerer: build_arms(args, answerer), messages, snapshot, races)
    text = scoreboard.markdown(report)
    print(text)
    save(args, "scoreboard", report, text)
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from systemone.ui.server import Playground, serve

    if not gate(args, "every click is a request per model arm; Claude costs about a cent per click"):
        return 2
    serve(
        Playground(lambda answerer: build_arms(args, answerer), load_snapshot(), load_races()),
        port=args.port,
        open_browser=not args.no_browser,
    )
    return 0


SHOW = {"ask": cmd_ask, "race": cmd_race, "scoreboard": cmd_scoreboard, "ui": cmd_ui}


if __name__ == "__main__":
    raise SystemExit(main())
