"""Terminal views for showing the idea to a person: `systemone ask` and `systemone race`."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any

from systemone.arms import Arm
from systemone.data import Race, Snapshot
from systemone.experiments import wikirace
from systemone.playground import Form, picked

GREEN, RED, DIM, BOLD = "32", "31", "2", "1"


def paint(text: str, code: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"\033[{code}m{text}\033[0m"


def bar(p: float, width: int = 10) -> str:
    full = round(max(0.0, min(1.0, p)) * width)
    return "█" * full + "░" * (width - full)


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


COL = 34


def ask_text(form: Form, message: str, results: list[dict[str, Any]]) -> str:
    """Rows are the form's questions, columns are the players, each cell is the ticked box and how sure."""
    label_w = max(len(label) for label in form.labels.values()) + 2
    lines = [paint(f"“{clip(message, 100)}”", DIM), ""]
    lines.append(" " * label_w + "".join(paint(clip(r["arm"], COL - 2).ljust(COL), BOLD) for r in results))
    for name in form.questions:
        row = form.labels.get(name, name).ljust(label_w)
        for r in results:
            if "error" in r:
                cell = paint("✗ broken answer".ljust(COL), RED)
            else:
                option, p = picked(form, name, r["answers"][name])
                cell = f"{clip(option, 16).ljust(17)}{bar(p, 10)} {p:>4.0%}  "
            row += cell
        lines.append(row)
    lines.append("")
    timing = "".join(f"{r['ms']:,} ms".ljust(COL) for r in results)
    lines.append(paint("Time".ljust(label_w) + timing, DIM))
    errors = [r for r in results if "error" in r]
    for r in errors:
        lines.append(paint(f"{r['arm']}: {clip(r['error'], 140)}", RED))
    return "\n".join(lines)


def race_live(arm: Arm, snapshot: Snapshot, race: Race, out: Callable[[str], None] = print) -> wikirace.RaceResult:
    """Run one race and print each hop as it happens: the links on offer, the top picks, the hop taken."""
    title = paint(f"\n{race.start}  ▸▸  {race.target}", BOLD)
    out(title + paint(f"   (shortest {race.shortest} hops, player: {arm.name})", DIM))
    hop = 0
    mark = len(arm.calls)

    def think(page: str, candidates: int) -> None:
        out(f"\n  hop {hop + 1}  on {paint(page, BOLD)}: {candidates} links to choose from…")

    def step(s: wikirace.Step) -> None:
        nonlocal hop, mark
        hop += 1
        ms = sum(c.latency_ms for c in arm.calls[mark:])
        mark = len(arm.calls)
        if s.mode == "direct":
            out(f"\n  hop {hop}  on {paint(s.page, BOLD)}: the target is linked right here, so code takes it")
            return
        if s.mode == "two-stage":
            out(paint("         over 255 links: scored each one first, then chose from the best 100", DIM))
        for title, p in s.top:
            mark_ = "▸" if title == s.chosen else " "
            out(f"       {mark_} {clip(title, 36).ljust(37)}{bar(p, 12)} {p:>4.0%}")
        calls = f"{s.requests} request" + ("s" if s.requests != 1 else "")
        out(paint(f"         → {s.chosen}   ({calls}, {ms:,.0f} ms)", DIM))

    result = wikirace.navigate(arm, snapshot, race, on_think=think, on_step=step)
    if result.success:
        out(paint(f"\n  ✓ reached {race.target} in {result.hops} hops (shortest is {race.shortest})", GREEN))
    else:
        out(paint(f"\n  ✗ stopped: {result.reason}", RED))
    return result
