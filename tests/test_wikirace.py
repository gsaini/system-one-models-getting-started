from systemone.arms import baseline_arm
from systemone.data import Race, Snapshot
from systemone.experiments import wikirace


def snapshot(pages: dict[str, list[str]]) -> Snapshot:
    return Snapshot(roots=(next(iter(pages)),), pages=pages)


def test_direct_link_is_taken_by_code_without_a_model_call():
    snap = snapshot({"Start": ["Target", "Other"], "Other": ["Start"]})
    arm = baseline_arm(wikirace.answerer)
    result = wikirace.navigate(arm, snap, Race("Start", "Target", 1))
    assert result.success and result.path == ["Start", "Target"] and result.hops == 1
    assert result.steps[0].mode == "direct" and arm.summary()["calls"] == 0


def test_choice_over_known_candidates_only_and_no_revisits():
    snap = snapshot(
        {
            "Start": ["Leaf", "Cats", "Dogs"],  # Leaf has no link list: it's a dead end, so not a candidate
            "Cats": ["Start", "Cat food"],
            "Dogs": ["Start", "Dog food"],
            "Cat food": ["Cats"],
            "Dog food": ["Dogs", "Cat food"],
        }
    )
    arm = baseline_arm(wikirace.answerer)
    result = wikirace.navigate(arm, snap, Race("Start", "Cat food", 2))
    assert result.success and result.path == ["Start", "Cats", "Cat food"]
    step = result.steps[0]
    assert step.mode == "choice" and step.candidates == 2  # Leaf excluded
    (request,) = arm.calls
    assert request.ok
    # the chosen page is never offered again
    snap2 = snapshot({"Start": ["Trap"], "Trap": ["Start", "Trap2"], "Trap2": ["Trap", "Start"]})
    result2 = wikirace.navigate(baseline_arm(wikirace.answerer), snap2, Race("Start", "Nowhere", 9), max_hops=4)
    assert not result2.success and "dead end" in result2.reason


def test_two_stage_kicks_in_above_255_candidates():
    many = [f"Page {i}" for i in range(400)] + ["Cat food"]
    pages = {"Start": many, "Cat food": ["Target"]}
    pages.update({f"Page {i}": ["Start"] for i in range(400)})
    snap = snapshot(pages)
    arm = baseline_arm(wikirace.answerer)
    result = wikirace.navigate(arm, snap, Race("Start", "Cat", 2))
    step = result.steps[0]
    assert step.mode == "two-stage" and step.candidates == 401
    # 401 candidates → two stage-1 requests of ≤300 Nouls, then one Choice over the top 100
    assert step.requests == 3 and arm.summary()["calls"] == 3
    assert step.chosen == "Cat food"  # the only title sharing a word with the target


def test_hop_budget_and_arm_errors_are_reported():
    snap = snapshot({"A": ["B"], "B": ["A", "C"], "C": ["B", "D"], "D": ["C", "E"], "E": ["D"]})
    result = wikirace.navigate(baseline_arm(wikirace.answerer), snap, Race("A", "Z", 9), max_hops=2)
    assert not result.success and "hop budget" in result.reason and result.hops == 2


def test_report_markdown_counts_solved_and_two_stage():
    snap = snapshot({"Start": ["Target"], "Target": []})
    arm = baseline_arm(wikirace.answerer)
    report = wikirace.run([arm], snap, [Race("Start", "Target", 1)])
    text = wikirace.markdown(report)
    assert "**1/1**" in text and "✅ Start → Target" in text
