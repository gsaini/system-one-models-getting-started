"""Claim 1: "a frontier-intelligence function call: unstructured state in, typed probabilistic decisions out."

One state, eight questions of all three kinds, one request. The output is typed by construction: an
option from the list you gave, a level from the rubric you wrote, a probability. Nothing to parse.
"""

from __future__ import annotations

import json
from typing import Any

from typesafe_sdk import Choice, Noul, Score

from systemone.arms import Arm
from systemone.baseline import any_of, choice_answer, count_of, noul_answer, score_answer, text_of

STATE: dict[str, Any] = {
    "account": {"plan": "Business", "seats": 40, "months_active": 19, "tickets_last_90_days": 4, "nps_last_survey": 6},
    "latest_message": (
        "Third time this quarter the export job silently drops rows. We rebuilt the report by hand again. "
        "Honestly we're trialling Lumen next month unless this is fixed for good. Also, who approved the seat "
        "price increase on our last invoice? We never agreed to that and want it reversed."
    ),
}

QUESTIONS: dict[str, Any] = {
    "next_action": Choice(
        instructions="What should the support assistant do next for the customer in `latest_message`, given `account`?",
        criteria={
            "reply_with_fix": "Answer with a concrete fix or workaround for the problem described",
            "offer_refund_or_credit": "Acknowledge a billing problem and offer to reverse or credit it",
            "escalate_to_human": "A person should take over: the account is at risk or the issue keeps recurring",
            "close_as_resolved": "Nothing is being asked; thank them and close",
            "other": "None of the above fits",
        },
    ),
    "churn_risk": Score(
        instructions="How likely is the customer in `latest_message` to leave, considering `account`?",
        criteria=[
            "Content: no sign of leaving",
            "Mildly annoyed, but not considering alternatives",
            "Frustrated and mentions or hints at alternatives",
            "States they will cancel or move unless something changes",
        ],
    ),
    "sentiment": Choice(
        instructions="What is the overall sentiment of `latest_message`?",
        criteria={"positive": None, "neutral": None, "negative": None},
    ),
    "urgency": Score(
        instructions="How urgent is `latest_message` for the business that sent it?",
        criteria=[
            "Can wait a week",
            "Within a few days",
            "Today",
            "Right now: money, data, or the account is at stake",
        ],
    ),
    "refund_requested": Noul(
        instructions="Does `latest_message` ask for a charge to be reversed, refunded, or credited?"
    ),
    "security_concern": Noul(
        instructions="Does `latest_message` report a possible security problem, such as unauthorized access or a leak?"
    ),
    "mentions_competitor": Noul(
        instructions="Does `latest_message` mention evaluating, trialling, or moving to another product or vendor?"
    ),
    "repeat_issue": Noul(instructions="Does `latest_message` say the same problem has happened before?"),
}


def answerer(name: str, question: dict[str, Any], state: Any) -> dict[str, Any] | None:
    """Keyword rules for the demo's eight questions: the offline stand-in, not Jev."""
    text = text_of(state.get("latest_message", state) if isinstance(state, dict) else state)
    if name == "next_action":
        return choice_answer(
            list(question["criteria"]),
            {
                "reply_with_fix": count_of(text, "bug", "error", "broken", "drops", "fails"),
                "offer_refund_or_credit": 2 * count_of(text, "refund", "reverse", "credit", "invoice", "charge"),
                "escalate_to_human": 2 * count_of(text, "third time", "again", "unless", "cancel", "trial"),
            },
        )
    if name == "churn_risk":
        hot = count_of(text, "cancel", "unless", "trial", "moving to", "switch")
        return score_answer(question["criteria"], [0.2, 0.6, 1.0 * (hot >= 1), 1.0 * (hot >= 2)])
    if name == "sentiment":
        neg = count_of(text, "silently", "again", "honestly", "never agreed", "unless")
        return choice_answer(
            list(question["criteria"]), {"negative": neg, "neutral": 0.5, "positive": count_of(text, "thanks", "great")}
        )
    if name == "urgency":
        return score_answer(question["criteria"], [0.3, 0.6, 1.0 * any_of(text, "unless", "invoice"), 0.0])
    if name == "refund_requested":
        return noul_answer(0.9 if any_of(text, "refund", "reverse", "credit", "money back") else 0.05)
    if name == "security_concern":
        return noul_answer(0.9 if any_of(text, "hacked", "unauthori", "leak", "breach", "phishing") else 0.05)
    if name == "mentions_competitor":
        return noul_answer(0.85 if any_of(text, "trial", "competitor", "switch", "moving to", "alternative") else 0.1)
    if name == "repeat_issue":
        return noul_answer(0.9 if any_of(text, "again", "third time", "second time", "every time", "keeps") else 0.1)
    return None


def run(arms: list[Arm]) -> dict[str, Any]:
    report: dict[str, Any] = {"state": STATE, "answers": {}}
    for arm in arms:
        response = arm.ask(STATE, QUESTIONS)
        if response is None:
            report["answers"][arm.name] = {"error": arm.calls[-1].error}
            continue
        out = {}
        for name, answer in response.answers.items():
            if answer.type == "noul":
                out[name] = {"type": "noul", "answer": round(answer.noul, 3)}
            elif answer.type == "choice":
                out[name] = {
                    "type": "choice",
                    "answer": answer.choice,
                    "confidence": round(answer.confidence, 3),
                    "probabilities": {k: round(v, 3) for k, v in answer.probabilities.items()},
                }
            else:
                out[name] = {
                    "type": "score",
                    "answer": round(answer.score, 2),
                    "confidence": round(answer.confidence, 3),
                    "probabilities": {str(k): round(v, 3) for k, v in answer.probabilities.items()},
                }
        report["answers"][arm.name] = out
    report["arms"] = [a.summary() for a in arms]
    return report


def markdown(report: dict[str, Any]) -> str:
    lines = ["**The request** (one call, eight questions):", "", "```json"]
    shape = {
        "state": STATE,
        "questions": {k: json.loads(v.model_dump_json()) for k, v in QUESTIONS.items()},
    }
    lines += [json.dumps(shape, indent=2, ensure_ascii=False)[:1400] + "\n  …", "```", ""]
    for arm, answers in report["answers"].items():
        lines += [f"**{arm}**", ""]
        if "error" in answers:
            lines += [f"error: {answers['error']}", ""]
            continue
        lines += ["| question | type | answer | confidence | distribution |", "|---|---|---|---|---|"]
        for name, a in answers.items():
            conf = f"{a['confidence']:.2f}" if "confidence" in a else "—"
            dist = ", ".join(f"{k} {v:.2f}" for k, v in a.get("probabilities", {}).items()) or "—"
            lines.append(f"| `{name}` | {a['type']} | **{a['answer']}** | {conf} | {dist} |")
        lines.append("")
    return "\n".join(lines)
