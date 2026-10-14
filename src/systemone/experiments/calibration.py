"""Claim 3: "calibrated decisions" — a 0.8 should be right about 80% of the time.

One Noul per SMS message ("is this spam?"), graded against the SMS Spam Collection's labels.
Besides accuracy we measure what the claim is actually about:

- **Brier score**: mean squared error of the probability (lower is better; 0.25 is a coin flip).
- **ECE** (expected calibration error): bucket predictions by probability, compare each bucket's
  mean probability with its actual spam rate, average the gaps weighted by bucket size.
- **The reliability table**: the same thing you can read by eye.
- **AUC**: how well the probabilities rank spam above ham, independent of any threshold.

A calibrated model lets code pick a threshold that means what it says. The sweep shows the trade.
"""

from __future__ import annotations

import re
from typing import Any

from typesafe_sdk import Noul

from systemone.arms import Arm
from systemone.baseline import noul_answer, text_of
from systemone.data import Message

QUESTION = {
    "spam": Noul(
        instructions="Is `message` spam: an unsolicited commercial, promotional, or scam text sent in bulk?",
        criteria={
            "true": "Advertising, prize or lottery claims, premium-rate numbers, subscription traps, phishing, "
            "or any text sent to many people at once to sell or extract something",
            "false": "A personal message between people who know each other, or a message the recipient would "
            "expect, such as a reply, a reminder, a confirmation, or a notification they signed up for",
        },
    )
}
BINS = 10

_CUES = (
    "free", "win", "winner", "won", "prize", "claim", "cash", "award", "bonus", "offer", "selected", "voucher",
    "guaranteed", "congratulations", "urgent", "call now", "txt", "text ", "reply", "stop", "ringtone", "tone",
    "subscri", "unsubscri", "http", "www.", "18+", "mobile", "credit", "£", "$", "nokia", "camera", "latest",
    "chat", "dating", "contact", "customer service", "expires", "valid", "pobox", "p.o. box", "rate", "per msg",
)  # fmt: skip
_NUMBER = re.compile(r"\b\d{5,}\b|\b0[78]\d{8,}\b")


def answerer(name: str, question: dict[str, Any], state: Any) -> dict[str, Any] | None:
    """Offline stand-in: count spam cues, map the count to a probability bucket."""
    text = text_of(state.get("message", state) if isinstance(state, dict) else state)
    hits = sum(cue in text for cue in _CUES) + 2 * bool(_NUMBER.search(text))
    p = {0: 0.04, 1: 0.2, 2: 0.45, 3: 0.7}.get(hits, 0.92)
    return noul_answer(p)


def run(arms: list[Arm], messages: list[Message]) -> dict[str, Any]:
    results: dict[str, list[dict[str, Any]]] = {}
    for arm in arms:
        rows = []
        for m in messages:
            response = arm.ask({"message": m.text}, QUESTION)
            if response is None:
                continue
            rows.append({"id": m.id, "spam": m.spam, "p": response.nouls["spam"].noul})
        results[arm.name] = rows
    return {
        "n": len(messages),
        "results": results,
        "metrics": {name: metrics(rows) for name, rows in results.items()},
        "sweep": {name: sweep(rows) for name, rows in results.items()},
        "arms": [a.summary() for a in arms],
    }


def metrics(rows: list[dict[str, Any]], bins: int = BINS) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    tp = sum(r["spam"] and r["p"] >= 0.5 for r in rows)
    fp = sum((not r["spam"]) and r["p"] >= 0.5 for r in rows)
    fn = sum(r["spam"] and r["p"] < 0.5 for r in rows)
    tn = n - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    table = []
    ece = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        bucket = [r for r in rows if lo <= r["p"] < hi or (b == bins - 1 and r["p"] == 1.0)]
        if not bucket:
            table.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": 0, "mean_p": None, "spam_rate": None})
            continue
        mean_p = sum(r["p"] for r in bucket) / len(bucket)
        rate = sum(r["spam"] for r in bucket) / len(bucket)
        ece += len(bucket) / n * abs(rate - mean_p)
        table.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(bucket), "mean_p": mean_p, "spam_rate": rate})
    return {
        "n": n,
        "accuracy": (tp + tn) / n,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "brier": sum((r["p"] - float(r["spam"])) ** 2 for r in rows) / n,
        "ece": ece,
        "auc": auc(rows),
        "reliability": table,
    }


def auc(rows: list[dict[str, Any]]) -> float | None:
    """Probability that a random spam message gets a higher p than a random ham message (ties count half)."""
    spam = [r["p"] for r in rows if r["spam"]]
    ham = [r["p"] for r in rows if not r["spam"]]
    if not spam or not ham:
        return None
    wins = sum((s > h) + 0.5 * (s == h) for s in spam for h in ham)
    return wins / (len(spam) * len(ham))


def sweep(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        flagged = [r for r in rows if r["p"] >= t]
        out.append(
            {
                "threshold": t,
                "flagged": len(flagged),
                "spam_caught": sum(r["spam"] for r in flagged),
                "ham_flagged": sum(not r["spam"] for r in flagged),
                "spam_missed": sum(r["spam"] and r["p"] < t for r in rows),
            }
        )
    return out


def markdown(report: dict[str, Any]) -> str:
    names = list(report["metrics"])
    m = report["metrics"]
    fmt = lambda name, key, f: f.format(m[name][key]) if m[name].get(key) is not None else "—"  # noqa: E731
    lines = [
        f"{report['n']} messages (natural ratio, about 13% spam).",
        "",
        "| | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for label, key, f in [
        ("accuracy at p ≥ 0.5", "accuracy", "{:.1%}"),
        ("precision / recall", None, None),
        ("Brier score (lower is better)", "brier", "{:.3f}"),
        ("**ECE** (lower is better)", "ece", "**{:.3f}**"),
        ("AUC", "auc", "{:.3f}"),
    ]:
        if key is None:
            lines.append(
                "| precision / recall | "
                + " | ".join(f"{m[n]['precision']:.1%} / {m[n]['recall']:.1%}" for n in names)
                + " |"
            )
        else:
            lines.append(f"| {label} | " + " | ".join(fmt(n, key, f) for n in names) + " |")
    for name in names:
        lines += [
            "",
            f"**Reliability, {name}** (a calibrated model has spam rate ≈ mean p in every row)",
            "",
            "| p bucket | n | mean p | actual spam rate |",
            "|---|---|---|---|",
        ]
        for row in m[name]["reliability"]:
            if row["n"]:
                lines.append(f"| {row['bin']} | {row['n']} | {row['mean_p']:.2f} | {row['spam_rate']:.2f} |")
        lines += [
            "",
            f"**Threshold sweep, {name}**",
            "",
            "| flag as spam when p ≥ | flagged | spam caught | ham wrongly flagged | spam missed |",
            "|---|---|---|---|---|",
        ]
        for s in report["sweep"][name]:
            lines.append(
                f"| {s['threshold']:.1f} | {s['flagged']} | {s['spam_caught']} | "
                f"{s['ham_flagged']} | {s['spam_missed']} |"
            )
    return "\n".join(lines)
