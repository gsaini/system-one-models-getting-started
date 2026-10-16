"""`systemone demo | parallel | calibration | wikirace` — offline by default; --live adds Jev, --llm adds Claude, --ollama a local model."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        ["baseline"] + (["jev"] if args.live else []) + (["llm"] if args.llm else []) + (["ollama"] if args.ollama else [])
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
        p.add_argument("--ollama-url", default=OLLAMA_URL, help=f"Ollama's OpenAI-compatible URL (default {OLLAMA_URL})")
        p.add_argument("--yes", action="store_true", help="confirm a live run")
        p.add_argument("--out", type=Path, default=Path("runs"))
        if name == "parallel":
            p.add_argument("--repeats", type=int, default=1)
        if name == "calibration":
            p.add_argument("--limit", type=int, default=1000, help="messages to grade (of 1,000)")
        if name == "wikirace":
            p.add_argument("--races", type=int, default=None, help="only the first N races")
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
