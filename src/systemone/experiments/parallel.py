"""Claim 2: "parallel, generating all outputs in one query" — adding questions barely adds latency.

The test: ask N questions about one document in a single request, versus N requests of one question
each. If evaluation is parallel, the batched latency should stay roughly flat as N grows while the
sequential total grows linearly. We also check that batching doesn't change the answers, and we
grade them: all 32 questions have labels.

Offline, the keyword baseline answers in microseconds, so only the mechanics (requests, tokens,
agreement) mean anything. Timing needs --live or --llm.
"""

from __future__ import annotations

import statistics
from typing import Any

from typesafe_sdk import Noul

from systemone.arms import Arm
from systemone.baseline import noul_answer

REPORT = """Incident report INC-4471. On Tuesday at 09:12 UTC the checkout service began returning HTTP 502
errors for roughly 18% of requests in the eu-west region. The on-call engineer, Priya, was paged at 09:14 and
acknowledged within two minutes. Initial investigation pointed at a deploy of version 4.18.0 that had completed
at 09:05; the deploy added a new retry policy to the payment client. Error rates in us-east stayed below 0.5%
throughout. At 09:31 Priya rolled the eu-west fleet back to 4.17.2, and error rates returned to baseline by
09:38. No customer data was exposed, and no payments were double-charged, although 1,240 checkout attempts
failed and 310 of those customers did not retry within the hour. The root cause was connection-pool
exhaustion: the new retry policy retried timed-out payment calls immediately, without backoff, which tripled
the connection count under load. The fix, exponential backoff with jitter plus a per-host connection cap, was
merged on Wednesday and deployed behind a feature flag on Thursday, first to 5% of eu-west traffic. The
retrospective recommended two actions: alerting on connection-pool saturation (owner: platform team, due next
sprint) and a load test for every change to client retry behaviour (owner: payments team, due end of month).
Total customer-facing impact: 26 minutes."""

# (question, label) — 32 yes/no questions about the report, labelled by hand.
QUESTIONS: list[tuple[str, bool]] = [
    ("Did the incident affect the eu-west region?", True),
    ("Did the us-east region have an error rate above 1% during the incident?", False),
    ("Was the on-call engineer paged within five minutes of the errors starting?", True),
    ("Was the incident caused by a hardware failure?", False),
    ("Was the problem resolved by rolling back a deploy?", True),
    ("Did error rates return to baseline within ten minutes of the rollback starting?", True),
    ("Was any customer data exposed?", False),
    ("Were any customers double-charged?", False),
    ("Did more than one thousand checkout attempts fail?", True),
    ("Did every affected customer retry within the hour?", False),
    ("Was the root cause related to retry behaviour?", True),
    ("Did the faulty retry policy use exponential backoff?", False),
    ("Was the fix deployed to all eu-west traffic at once?", False),
    ("Was the fix deployed behind a feature flag?", True),
    ("Is the platform team responsible for the alerting action item?", True),
    ("Is the payments team responsible for the load-test action item?", True),
    ("Was the total customer-facing impact longer than one hour?", False),
    ("Did the deploy of version 4.18.0 complete before the errors began?", True),
    ("Was the affected service the checkout service?", True),
    ("Was the on-call engineer named Priya?", True),
    ("Does the report mention a database outage?", False),
    ("Did the incident start in the afternoon, UTC?", False),
    ("Is the alerting action item due by the end of the month?", False),
    ("Was the fix merged on the same day as the incident?", False),
    ("Did the new retry policy increase the number of connections under load?", True),
    ("Was the rollback to version 4.17.2?", True),
    ("Does the report say that failed payments were refunded?", False),
    ("Did roughly one in five requests fail in eu-west?", True),
    ("Was a per-host connection cap part of the fix?", True),
    ("Did the retrospective recommend exactly two actions?", True),
    ("Was the page acknowledged within two minutes?", True),
    ("Did the customer-facing impact last more than 26 minutes?", False),
]
SIZES = (1, 2, 4, 8, 16, 32)
STATE = {"report": REPORT}


def question(i: int) -> Noul:
    return Noul(instructions=f"Based only on `report`: {QUESTIONS[i][0]}")


def answerer(name: str, question_dict: dict[str, Any], state: Any) -> dict[str, Any] | None:
    """Offline stand-in: 'yes' when most of the question's content words appear in the report."""
    text = str(state.get("report", "")).lower() if isinstance(state, dict) else str(state).lower()
    words = [w.strip("?.,:;").lower() for w in str(question_dict.get("instructions", "")).split()]
    content = [
        w
        for w in words
        if len(w) > 3
        and w
        not in {
            "based",
            "only",
            "report",
            "does",
            "did",
            "was",
            "were",
            "the",
            "that",
            "than",
            "within",
            "during",
            "incident",
        }
    ]
    if not content:
        return None
    hit = sum(w in text for w in content) / len(content)
    return noul_answer(0.9 if hit >= 0.75 else 0.2)


def run(arms: list[Arm], sizes: tuple[int, ...] = SIZES, repeats: int = 1) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for arm in arms:
        for n in sizes:
            batched_ms, single_ms, agree, correct, batched_tokens, single_tokens, errors = [], [], 0, 0, 0, 0, 0
            for _ in range(repeats):
                qs = {f"q{i}": question(i) for i in range(n)}
                before = len(arm.calls)
                response = arm.ask(STATE, qs)
                batched_call = arm.calls[-1]
                if response is None:
                    errors += 1
                    continue
                batched_ms.append(batched_call.latency_ms)
                batched_tokens += batched_call.input_tokens + batched_call.output_tokens
                batched = {k: a.noul for k, a in response.nouls.items()}

                singles: dict[str, float] = {}
                for i in range(n):
                    r = arm.ask(STATE, {f"q{i}": question(i)})
                    if r is None:
                        errors += 1
                        continue
                    singles[f"q{i}"] = r.nouls[f"q{i}"].noul
                calls = arm.calls[before + 1 :]
                single_ms.append(sum(c.latency_ms for c in calls if c.ok))
                single_tokens += sum(c.input_tokens + c.output_tokens for c in calls if c.ok)
                agree += sum((batched[k] >= 0.5) == (singles[k] >= 0.5) for k in singles)
                correct += sum((batched[f"q{i}"] >= 0.5) == QUESTIONS[i][1] for i in range(n))
            evaluated = n * max(1, repeats - errors) if repeats else n
            rows.append(
                {
                    "arm": arm.name,
                    "n": n,
                    "batched_ms": statistics.median(batched_ms) if batched_ms else None,
                    "single_total_ms": statistics.median(single_ms) if single_ms else None,
                    "batched_tokens": batched_tokens,
                    "single_tokens": single_tokens,
                    "agreement": agree / evaluated if evaluated else None,
                    "accuracy": correct / evaluated if evaluated else None,
                    "errors": errors,
                }
            )
    return {"rows": rows, "arms": [a.summary() for a in arms]}


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "| arm | questions | one request | N single requests | speed-up | tokens one / N | same answers | accuracy |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report["rows"]:
        b, s = r["batched_ms"], r["single_total_ms"]
        speed = f"{s / b:.1f}x" if b and s and b >= 2 else "—"  # sub-2 ms numbers are noise (offline)
        ms = lambda v: f"{v:.0f} ms" if v is not None else "—"  # noqa: E731
        pct = lambda v: f"{v:.0%}" if v is not None else "—"  # noqa: E731
        lines.append(
            f"| {r['arm']} | {r['n']} | {ms(b)} | {ms(s)} | {speed} | "
            f"{r['batched_tokens']:,} / {r['single_tokens']:,} | "
            f"{pct(r['agreement'])} | {pct(r['accuracy'])} |"
        )
    return "\n".join(lines)
