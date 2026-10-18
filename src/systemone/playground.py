"""Forms you can fill in with your own text: what `systemone ask` and the web playground use.

A form is a fixed set of typed questions plus a way to wrap a message into a state. Two exist:
the demo's support-ticket questions, and the calibration experiment's spam question. Each comes
with the keyword rules that answer it offline, and a few example messages to try.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from systemone.arms import Arm
from systemone.baseline import Answerer
from systemone.experiments import calibration, demo


@dataclass(frozen=True)
class Option:
    key: str  # what the model answers with: a Choice label, a Score level index, or yes/no for a Noul
    short: str  # what a person reads
    full: str


@dataclass(frozen=True)
class Form:
    key: str
    title: str
    questions: dict[str, Any]
    answerer: Answerer
    state: Callable[[str], Any]
    labels: dict[str, str]  # question name -> plain-English question
    examples: tuple[str, ...]
    short: dict[str, list[str]]  # optional short names for Choice labels or Score levels

    def options(self, name: str) -> list[Option]:
        question = self.questions[name]
        kind = question.type
        if kind == "noul":
            return [Option("yes", "yes", "yes"), Option("no", "no", "no")]
        if kind == "choice":
            keys = list(question.criteria)
            shorts = self.short.get(name) or [k.replace("_", " ") for k in keys]
            return [Option(k, s, question.criteria[k] or s) for k, s in zip(keys, shorts, strict=True)]
        levels = [str(level) for level in question.criteria]
        shorts = self.short.get(name) or levels
        return [Option(str(i), s, full) for i, (s, full) in enumerate(zip(shorts, levels, strict=True))]

    def describe(self) -> dict[str, Any]:
        """The form as JSON for the web page."""
        return {
            "title": self.title,
            "examples": list(self.examples),
            "questions": [
                {
                    "name": name,
                    "label": self.labels.get(name, name),
                    "type": q.type,
                    "options": [vars(o) for o in self.options(name)],
                }
                for name, q in self.questions.items()
            ],
        }


SUPPORT = Form(
    key="support",
    title="Support ticket",
    questions=demo.QUESTIONS,
    answerer=demo.answerer,
    state=demo.state_for,
    labels={
        "next_action": "What should we do next?",
        "churn_risk": "Will they leave?",
        "sentiment": "What's the mood?",
        "urgency": "How urgent is it?",
        "refund_requested": "Do they want money back?",
        "security_concern": "Is it a security problem?",
        "mentions_competitor": "Do they mention a competitor?",
        "repeat_issue": "Has it happened before?",
    },
    short={
        "next_action": ["reply with a fix", "refund or credit", "hand to a person", "close it", "other"],
        "churn_risk": ["no", "a little", "likely", "says so"],
        "urgency": ["this week", "in a few days", "today", "right now"],
    },
    examples=(
        demo.STATE["latest_message"],
        "I was charged twice for October. Please refund the duplicate payment.",
        "Someone logged into our admin account at 3am and exported the customer list. Was that you?",
        "Just wanted to say the new dashboard is great. Thanks, team!",
        "We're moving to another vendor next week. Cancel our plan, please.",
    ),
)

SPAM = Form(
    key="spam",
    title="Spam check",
    questions=calibration.QUESTION,
    answerer=calibration.answerer,
    state=lambda message: {"message": message},
    labels={"spam": "Is this spam?"},
    short={},
    examples=(
        "WINNER!! You have been selected for a £900 prize. Call 09061701461 to claim. Valid 12 hours only.",
        "Hey, are we still on for dinner tonight? I'll bring dessert.",
        "URGENT: your account is locked. Verify now at http://secure-login-check.co",
        "Your package arrives tomorrow between 9 and 11am.",
    ),
)

FORMS = {f.key: f for f in (SUPPORT, SPAM)}


def ask(arm: Arm, form: Form, message: str) -> dict[str, Any]:
    """One request: the form's questions about `message`. Never raises; a broken answer comes back as `error`."""
    response = arm.ask(form.state(message), form.questions)
    call = arm.calls[-1]
    out: dict[str, Any] = {"arm": arm.name, "ms": round(call.latency_ms)}
    if response is None:
        out["error"] = call.error
    else:
        out["answers"] = demo.flatten(response)
    return out


def picked(form: Form, name: str, answer: dict[str, Any]) -> tuple[str, float]:
    """The option a person should read for one answer, and how sure the player was of it."""
    if answer["type"] == "noul":
        p = answer["answer"]
        return ("yes", p) if p >= 0.5 else ("no", 1 - p)
    options = form.options(name)
    if answer["type"] == "choice":
        option = next(o for o in options if o.key == answer["answer"])
        return option.short, answer["probabilities"].get(option.key, 0.0)
    # A Score's `answer` is the probability-weighted level (1.37); the box to tick is the most likely level.
    level, p = max(answer["probabilities"].items(), key=lambda kv: kv[1])
    return options[int(level)].short, p
