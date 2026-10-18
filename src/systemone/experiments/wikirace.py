"""Claim 4, the fun one: Wikiracing — get from one article to another by following links.

The post's demo picks each hop with a Choice (up to 255 options) and falls back to "scoring
independently then making an explicit choice" when a page has more links than that. Same here:

- Code does what code can: if the target is linked from the current page, take it. No model call.
- Otherwise the candidates are the linked pages the snapshot knows (so the race can continue from
  them), minus pages already visited.
- ≤ 255 candidates: **one Choice** — pick the best next hop.
- > 255 candidates: **two stages** — one Noul per candidate ("is this likely to link to or be about
  the target?") in requests of 300, keep the top 100, then one Choice over those.

Everything runs on a bundled snapshot of real Wikipedia link lists (see data/README.md), so the
race is reproducible and never touches the live site.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from typesafe_sdk import Choice, Noul

from systemone.arms import Arm
from systemone.baseline import choice_answer, noul_answer
from systemone.data import Race, Snapshot

MAX_OPTIONS = 255  # a Choice accepts up to 255 options (https://docs.typesafe.ai/api)
STAGE1_CHUNK = 300
STAGE1_KEEP = 100
MAX_HOPS = 6
_STOP = {"the", "of", "and", "a", "in", "on", "to", "for", "at", "by", "an", "or", "s", "de", "la", "von"}


@dataclass
class Step:
    page: str
    candidates: int
    mode: str  # "direct" (code found the link) | "choice" | "two-stage"
    chosen: str
    confidence: float | None
    requests: int
    top: list[tuple[str, float]] = field(default_factory=list)  # the final Choice's best options, for viewers


@dataclass
class RaceResult:
    start: str
    target: str
    success: bool
    reason: str
    path: list[str]
    steps: list[Step] = field(default_factory=list)

    @property
    def hops(self) -> int:
        return len(self.path) - 1


def words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in _STOP}


def answerer(name: str, question: dict[str, Any], state: Any) -> dict[str, Any] | None:
    """Offline stand-in: word overlap between a candidate's title and the target's. Ties go to the first."""
    target = words(str(state.get("target", ""))) if isinstance(state, dict) else set()
    if question["type"] == "choice":
        return choice_answer(list(question["criteria"]), {t: len(words(t) & target) for t in question["criteria"]})
    if question["type"] == "noul" and name.startswith("c"):
        try:
            candidate = state["candidates"][int(name[1:])]
        except (KeyError, ValueError, IndexError, TypeError):
            return None
        return noul_answer(0.9 if words(candidate) & target else 0.1)
    return None


def choose(
    arm: Arm, page: str, candidates: list[str], target: str
) -> tuple[str | None, str, float | None, int, list[tuple[str, float]]]:
    """Pick the next hop. Returns (chosen, mode, confidence, requests_made, top three options)."""
    pool, requests, mode = candidates, 0, "choice"
    if len(candidates) > MAX_OPTIONS:
        mode = "two-stage"
        scored: list[tuple[float, str]] = []
        for start in range(0, len(candidates), STAGE1_CHUNK):
            chunk = candidates[start : start + STAGE1_CHUNK]
            questions = {
                f"c{i}": Noul(
                    instructions=f"Is the Wikipedia article `candidates[{i}]` likely to link directly to the article "
                    f"`target`, or to be about closely the same topic?"
                )
                for i in range(len(chunk))
            }
            response = arm.ask({"target": target, "candidates": chunk}, questions)
            requests += 1
            if response is None:
                return None, mode, None, requests, []
            scored += [(response.nouls[f"c{i}"].noul, title) for i, title in enumerate(chunk)]
        scored.sort(key=lambda s: -s[0])
        pool = [title for _, title in scored[:STAGE1_KEEP]]
    question = Choice(
        instructions=(
            "You are playing Wikiracing: you are on the Wikipedia article `current` and must reach the article "
            "`target` by following links. Which of these linked articles is the best next step — the one most "
            "likely to link directly to `target`, or the closest to it in topic?"
        ),
        criteria={title: None for title in pool},
    )
    response = arm.ask({"current": page, "target": target}, {"next": question})
    requests += 1
    if response is None:
        return None, mode, None, requests, []
    answer = response.choices["next"]
    top = sorted(answer.probabilities.items(), key=lambda kv: -kv[1])[:3]
    return answer.choice, mode, answer.confidence, requests, top


def navigate(
    arm: Arm,
    snapshot: Snapshot,
    race: Race,
    max_hops: int = MAX_HOPS,
    *,
    on_think: Callable[[str, int], None] | None = None,
    on_step: Callable[[Step], None] | None = None,
) -> RaceResult:
    """Race one arm. `on_think(page, candidates)` fires before a model decision, `on_step` after every hop."""
    result = RaceResult(race.start, race.target, False, "", [race.start])
    visited = {race.start}
    for _ in range(max_hops):
        page = result.path[-1]
        links = snapshot.links(page)
        if race.target in links:  # exact lookup is code's job, not the model's
            result.path.append(race.target)
            result.steps.append(Step(page, len(links), "direct", race.target, None, 0))
            if on_step:
                on_step(result.steps[-1])
            result.success, result.reason = True, "reached"
            return result
        candidates = [t for t in links if snapshot.known(t) and t not in visited]
        if not candidates:
            result.reason = f"dead end at {page!r}"
            return result
        if on_think:
            on_think(page, len(candidates))
        chosen, mode, confidence, requests, top = choose(arm, page, candidates, race.target)
        if chosen is None:
            result.reason = f"arm error at {page!r}: {arm.calls[-1].error}"
            return result
        result.steps.append(Step(page, len(candidates), mode, chosen, confidence, requests, top))
        if on_step:
            on_step(result.steps[-1])
        visited.add(chosen)
        result.path.append(chosen)
    result.reason = f"hop budget ({max_hops}) spent"
    return result


def run(arms: list[Arm], snapshot: Snapshot, races: list[Race]) -> dict[str, Any]:
    results: dict[str, list[RaceResult]] = {}
    for arm in arms:
        results[arm.name] = [navigate(arm, snapshot, race) for race in races]
    return {
        "races": [asdict(r) for r in races],
        "results": {name: [asdict(r) | {"hops": r.hops} for r in rs] for name, rs in results.items()},
        "arms": [a.summary() for a in arms],
    }


def markdown(report: dict[str, Any]) -> str:
    names = list(report["results"])
    lines = [
        "| arm | solved | hops on solved (shortest possible) | model decisions | two-stage decisions |",
        "|---|---|---|---|---|",
    ]
    for name in names:
        rs = report["results"][name]
        solved = [r for r in rs if r["success"]]
        shortest = sum(race["shortest"] for race, r in zip(report["races"], rs, strict=True) if r["success"])
        decisions = [s for r in rs for s in r["steps"] if s["mode"] != "direct"]
        two_stage = sum(s["mode"] == "two-stage" for s in decisions)
        lines.append(
            f"| {name} | **{len(solved)}/{len(rs)}** | {sum(r['hops'] for r in solved)} ({shortest}) | "
            f"{len(decisions)} | {two_stage} |"
        )
    lines += ["", "| race | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for i, race in enumerate(report["races"]):
        cells = []
        for name in names:
            r = report["results"][name][i]
            path = " → ".join(p if j in (0, len(r["path"]) - 1) else f"_{p}_" for j, p in enumerate(r["path"]))
            cells.append(f"✅ {path}" if r["success"] else f"❌ {path} ({r['reason']})")
        lines.append(f"| {race['start']} → {race['target']} ({race['shortest']} hops) | " + " | ".join(cells) + " |")
    return "\n".join(lines)
