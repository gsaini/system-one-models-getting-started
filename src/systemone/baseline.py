"""An offline keyword baseline that answers through the real TypeSafe SDK.

This is **not Jev**. It is the regex-and-keywords logic a team has *before* a model, served behind
an `httpx2.MockTransport` that speaks TypeSafe's `POST /v1/systemone` wire format. The experiments
can't tell the difference, so they exercise the real SDK offline and every table gets an honest
"what we had before" column.

An `Answerer` gets each question (by name, as the wire dict) plus the raw state and returns an
answer dict, or None for "no rule": the baseline then answers with maximum uncertainty
(Noul 0.5, uniform Choice/Score), which callers must treat as "don't know".
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2

from systemone.confidence import choice_confidence, expected_score, score_confidence

Answerer = Callable[[str, Mapping[str, Any], Any], dict[str, Any] | None]

SMOOTHING = 0.02


def noul_answer(p: float) -> dict[str, Any]:
    return {"type": "noul", "noul": max(0.0, min(1.0, float(p)))}


def choice_answer(labels: Sequence[str], weights: Mapping[str, float]) -> dict[str, Any]:
    """Turn non-negative per-label weights into a distribution; ties go to the first label."""
    raw = [max(0.0, float(weights.get(label, 0.0))) + SMOOTHING for label in labels]
    total = sum(raw)
    probs = [value / total for value in raw]
    best = labels[probs.index(max(probs))]
    return {
        "type": "choice",
        "choice": best,
        "confidence": choice_confidence(probs),
        "probabilities": dict(zip(labels, probs, strict=True)),
    }


def score_answer(levels: Sequence[Any], weights: Sequence[float]) -> dict[str, Any]:
    raw = [max(0.0, float(w)) + SMOOTHING for w in list(weights)[: len(levels)]]
    raw += [SMOOTHING] * (len(levels) - len(raw))
    total = sum(raw)
    probs = [value / total for value in raw]
    return {
        "type": "score",
        "score": expected_score(probs),
        "confidence": score_confidence(probs),
        "legend": {str(i): level if isinstance(level, str) else json.dumps(level) for i, level in enumerate(levels)},
        "probabilities": {str(i): p for i, p in enumerate(probs)},
    }


def uncertain(question: Mapping[str, Any]) -> dict[str, Any]:
    kind = question["type"]
    if kind == "noul":
        return noul_answer(0.5)
    if kind == "choice":
        labels = list(question["criteria"])
        return choice_answer(labels, {})
    if kind == "score":
        return score_answer(list(question["criteria"]), [])
    raise ValueError(f"unknown question type {kind!r}")


def text_of(state: Any) -> str:
    """The state as lowercase text, for keyword rules."""
    return (state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)).lower()


@dataclass
class KeywordBaseline:
    answer: Answerer
    model: str = "keyword-baseline"
    requests: list[dict[str, Any]] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET" and request.url.path.endswith("/v1/models"):
            models = [{"name": self.model, "description": "Offline keyword baseline", "release_date": "2026-10-14"}]
            return httpx2.Response(200, json={"models": models})
        body = json.loads(request.content)
        self.requests.append(body)
        answers = {}
        for name, question in body["questions"].items():
            answers[name] = self.answer(name, question, body["state"]) or uncertain(question)
        usage = {"input_tokens": max(1, len(request.content) // 4), "output_tokens": 0}
        return httpx2.Response(200, json={"model": self.model, "answers": answers, "usage": usage})


def any_of(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def count_of(text: str, *needles: str) -> int:
    return sum(needle in text for needle in needles)
