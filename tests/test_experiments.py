import pytest
from typesafe_sdk import Noul

from systemone.arms import baseline_arm
from systemone.data import load_sms
from systemone.experiments import calibration, demo, parallel


def test_demo_answers_all_eight_questions_in_one_request():
    arm = baseline_arm(demo.answerer)
    report = demo.run([arm])
    answers = report["answers"][arm.name]
    assert set(answers) == set(demo.QUESTIONS)
    assert arm.summary()["calls"] == 1
    assert answers["refund_requested"]["answer"] >= 0.5  # "want it reversed"
    assert answers["mentions_competitor"]["answer"] >= 0.5  # "trialling Lumen"
    assert answers["security_concern"]["answer"] < 0.5
    assert answers["next_action"]["answer"] in demo.QUESTIONS["next_action"].criteria
    assert "| `churn_risk` | score |" in demo.markdown(report)


def test_parallel_batches_once_and_singles_n_times():
    arm = baseline_arm(parallel.answerer)
    report = parallel.run([arm], sizes=(1, 4), repeats=1)
    rows = report["rows"]
    assert [r["n"] for r in rows] == [1, 4]
    assert arm.summary()["calls"] == (1 + 1) + (1 + 4)
    for r in rows:  # a deterministic answerer agrees with itself, batched or not
        assert r["agreement"] == 1.0 and r["errors"] == 0 and 0 <= r["accuracy"] <= 1
    assert "speed-up" in parallel.markdown(report)


def test_parallel_questions_are_labelled_and_balanced():
    assert len(parallel.QUESTIONS) == 32
    yes = sum(label for _, label in parallel.QUESTIONS)
    assert 12 <= yes <= 20


def test_calibration_metrics_on_known_rows():
    perfect = [{"id": str(i), "spam": i % 2 == 0, "p": 1.0 if i % 2 == 0 else 0.0} for i in range(20)]
    m = calibration.metrics(perfect)
    assert m["accuracy"] == 1.0 and m["brier"] == 0.0 and m["ece"] == pytest.approx(0.0) and m["auc"] == 1.0
    coin = [{"id": str(i), "spam": i % 2 == 0, "p": 0.5} for i in range(20)]
    m = calibration.metrics(coin)
    assert m["brier"] == pytest.approx(0.25) and m["ece"] == pytest.approx(0.0) and m["auc"] == 0.5
    overconfident = [{"id": str(i), "spam": i % 2 == 0, "p": 0.95} for i in range(20)]
    assert calibration.metrics(overconfident)["ece"] == pytest.approx(0.45)


def test_calibration_sweep_is_monotonic():
    rows = [{"id": str(i), "spam": i < 5, "p": i / 19} for i in range(20)]
    sweep = calibration.sweep(rows)
    flagged = [s["flagged"] for s in sweep]
    assert flagged == sorted(flagged, reverse=True)


def test_calibration_runs_offline_on_the_sample():
    messages = load_sms(limit=120)
    assert any(m.spam for m in messages) and any(not m.spam for m in messages)
    arm = baseline_arm(calibration.answerer)
    report = calibration.run([arm], messages)
    m = report["metrics"][arm.name]
    assert m["n"] == 120 and sum(row["n"] for row in m["reliability"]) == 120
    assert m["auc"] > 0.6  # keywords beat chance on spam, as they should
    text = calibration.markdown(report)
    assert "Reliability" in text and "Threshold sweep" in text


def test_sms_sample_is_well_formed():
    messages = load_sms()
    assert len(messages) == 1000 and len({m.id for m in messages}) == 1000
    assert 120 <= sum(m.spam for m in messages) <= 140


def test_noul_criteria_accept_true_false_descriptions():
    q = calibration.QUESTION["spam"]
    assert isinstance(q, Noul) and set(q.criteria) == {"true", "false"}
