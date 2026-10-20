"""The baseline must look exactly like Jev to the official SDK, and Arm must account for every call."""

import httpx2
import pytest
from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer, RetryPolicy, Score, ScoreAnswer, TypeSafeClient

from systemone.arms import PRICES, Arm, MissingCredentials, baseline_arm, jev_arm
from systemone.baseline import KeywordBaseline, choice_answer, noul_answer, score_answer, uncertain
from systemone.confidence import choice_confidence, expected_score, score_confidence


def test_confidence_matches_the_documented_example():
    # docs.typesafe.ai quick start: technical 0.85, billing 0.15, sales 0.0 → confidence 0.78
    assert choice_confidence([0.85, 0.15, 0.0]) == pytest.approx(0.775)
    assert choice_confidence([1 / 3] * 3) == pytest.approx(0.0)
    assert score_confidence([0.0, 1.0, 0.0]) == pytest.approx(1.0)
    assert expected_score([0.0, 1.0, 0.0]) == pytest.approx(1.0)


def test_baseline_answers_through_the_real_sdk():
    def rules(name, question, state):
        if name == "billing":
            return noul_answer(0.9)
        if name == "tone":
            return choice_answer(list(question["criteria"]), {"angry": 3.0})
        if name == "urgency":
            return score_answer(question["criteria"], [0.0, 0.0, 1.0])
        return None

    arm = baseline_arm(rules)
    response = arm.ask(
        {"ticket": "I was charged twice. Fix it ASAP."},
        {
            "billing": Noul(instructions="Is this about billing?"),
            "tone": Choice(instructions="Tone?", criteria={"calm": None, "angry": None}),
            "urgency": Score(instructions="How urgent?", criteria=["later", "soon", "now"]),
            "unknown": Noul(instructions="No rule for this one"),
        },
    )
    assert isinstance(response.answers["billing"], NoulAnswer) and response.nouls["billing"].noul == 0.9
    assert isinstance(response.answers["tone"], ChoiceAnswer) and response.choices["tone"].choice == "angry"
    assert isinstance(response.answers["urgency"], ScoreAnswer) and response.scores["urgency"].score > 1.8
    assert response.nouls["unknown"].noul == 0.5  # no rule → maximally uncertain
    assert response.model == "keyword-baseline"


def test_uncertain_answers_are_uniform():
    assert uncertain({"type": "noul"})["noul"] == 0.5
    c = uncertain({"type": "choice", "criteria": {"a": None, "b": None}})
    assert c["confidence"] == pytest.approx(0.0) and c["choice"] == "a"
    s = uncertain({"type": "score", "criteria": ["x", "y", "z"]})
    assert s["score"] == pytest.approx(1.0)


def test_arm_records_latency_tokens_cost_and_errors():
    arm = baseline_arm(lambda name, q, s: None)
    arm.price = PRICES["jev"]
    assert arm.ask("hello", {"q": Noul(instructions="?")}) is not None
    (call,) = arm.calls
    assert call.ok and call.input_tokens > 0 and call.cost_usd == pytest.approx(call.input_tokens * 42e-9)

    def down(request):
        return httpx2.Response(503, json={"detail": "overloaded"})

    broken = Arm(
        "broken",
        TypeSafeClient(api_key="k", transport=httpx2.MockTransport(down), retry=RetryPolicy(max_retries=0)),
        PRICES["jev"],
    )
    assert broken.ask("hello", {"q": Noul(instructions="?")}) is None
    assert (broken.calls[0].ok is False and "503" in broken.calls[0].error) or "Error" in broken.calls[0].error
    s = broken.summary()
    assert (s["calls"], s["errors"]) == (1, 1)


def test_jev_arm_needs_a_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(MissingCredentials):
        jev_arm()


def test_models_endpoint_is_served_too():
    baseline = KeywordBaseline(lambda n, q, s: None)
    client = TypeSafeClient(api_key="k", transport=baseline.transport(), retry=RetryPolicy(max_retries=0))
    assert client.models.list().models[0].name == "keyword-baseline"


def test_ollama_arm_fails_once_up_front_when_no_server_is_running():
    import pytest

    from systemone.arms import MissingCredentials, ollama_arm

    with pytest.raises(MissingCredentials, match="No Ollama server"):
        ollama_arm("tinyllama", base_url="http://127.0.0.1:9/v1")


def test_cloud_models_get_prompted_json_and_local_ones_the_schema():
    from systemone.arms import constrained_by_default

    assert constrained_by_default("qwen2.5:7b") and constrained_by_default("tinyllama")
    assert not constrained_by_default("minimax-m3.1-flash:cloud")
