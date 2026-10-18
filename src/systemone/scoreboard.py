"""`systemone scoreboard`: a short run of every graded experiment, boiled down to one leaderboard.

Each player gets the eight-question demo form, a sample of the spam messages, and the Wikiraces.
The board keeps only what a person needs to compare them: right answers, honest confidence,
broken answers, speed, cost. The full numbers are still in each experiment's own report.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from typing import Any

from systemone.arms import Arm, Call
from systemone.baseline import Answerer
from systemone.data import Message, Race, Snapshot
from systemone.experiments import calibration, demo, wikirace

# (key, column, how to print it, True when higher is better)
COLUMNS: list[tuple[str, str, Callable[[Any], str], bool]] = [
    ("spam_accuracy", "spam spotted right", lambda v: f"{v:.0%}", True),
    ("ece", "honest confidence (gap, lower is better)", lambda v: f"{v:.3f}", False),
    ("races_solved", "Wikiraces won", lambda v: f"{v[0]}/{v[1]}", True),
    ("broken", "broken answers", lambda v: f"{v:.0%}", False),
    ("p50_ms", "typical answer time", lambda v: f"{v:,.0f} ms", False),
    ("cost_usd", "cost at list price", lambda v: f"${v:.4f}", False),
]


def run(
    make_arms: Callable[[Answerer], list[Arm]], messages: list[Message], snapshot: Snapshot, races: list[Race]
) -> dict[str, Any]:
    demo_arms = make_arms(demo.answerer)
    demo.run(demo_arms)
    spam_arms = make_arms(calibration.answerer)
    spam = calibration.run(spam_arms, messages)
    race_arms = make_arms(wikirace.answerer)
    races_report = wikirace.run(race_arms, snapshot, races)

    rows = []
    for i, name in enumerate(a.name for a in demo_arms):
        calls: list[Call] = demo_arms[i].calls + spam_arms[i].calls + race_arms[i].calls
        ok = [c for c in calls if c.ok]
        m = spam["metrics"][name]
        rows.append(
            {
                "arm": name,
                "spam_accuracy": m.get("accuracy"),
                "ece": m.get("ece"),
                "races_solved": (sum(r["success"] for r in races_report["results"][name]), len(races)),
                "broken": (len(calls) - len(ok)) / len(calls) if calls else 0.0,
                "p50_ms": statistics.median(c.latency_ms for c in ok) if ok else None,
                "cost_usd": sum(c.cost_usd for c in ok),
                "calls": len(calls),
            }
        )
    return {"messages": len(messages), "races": len(races), "rows": rows}


def winners(rows: list[dict[str, Any]], key: str, higher: bool) -> set[str]:
    def value(r: dict[str, Any]) -> float | None:
        v = r[key]
        return v[0] if isinstance(v, tuple | list) else v

    values = [value(r) for r in rows if value(r) is not None]
    if len(rows) < 2 or not values:
        return set()
    best = max(values) if higher else min(values)
    return {r["arm"] for r in rows if value(r) == best}


def markdown(report: dict[str, Any]) -> str:
    rows = report["rows"]
    lines = [
        f"**Scoreboard**: the 8-question form, {report['messages']} spam messages, {report['races']} Wikiraces. "
        "🏆 marks the best in each column.",
        "",
        "| player | " + " | ".join(label for _, label, _, _ in COLUMNS) + " |",
        "|---|" + "---|" * len(COLUMNS),
    ]
    best = {key: winners(rows, key, higher) for key, _, _, higher in COLUMNS}
    for r in rows:
        cells = []
        for key, _, fmt, _ in COLUMNS:
            cell = "—" if r[key] is None else fmt(r[key])
            cells.append(f"🏆 **{cell}**" if r["arm"] in best[key] else cell)
        lines.append(f"| {r['arm']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "- **honest confidence** is the calibration gap (ECE): when a player says 70%, how far off 70% it really is.",
        "- **broken answers**: requests that came back unusable, such as a probability of 141.",
        "- The keyword rules have no intelligence; a model that can't beat them on races isn't using what it knows.",
    ]
    return "\n".join(lines)
