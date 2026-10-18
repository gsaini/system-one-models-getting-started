"""The demo features: forms, `ask`, the race view, the scoreboard, and the playground's server logic."""

import pytest

from systemone.arms import baseline_arm
from systemone.data import Message, Race, Snapshot
from systemone.experiments import wikirace
from systemone.playground import FORMS, SPAM, SUPPORT, ask, picked
from systemone.scoreboard import markdown as board_markdown
from systemone.scoreboard import run as board_run
from systemone.ui.server import BadRequest, Playground
from systemone.views import ask_text, race_live

SNAP = Snapshot(roots=("Start",), pages={"Start": ["Cats", "Dogs"], "Cats": ["Cat food"], "Dogs": ["Start"]})
RACE = Race("Start", "Cat food", 2)


def test_every_form_question_has_a_label_and_options():
    for form in FORMS.values():
        for q in form.describe()["questions"]:
            assert q["label"] != q["name"] and len(q["options"]) >= 2


def test_ask_fills_the_support_form_with_your_own_text():
    result = ask(baseline_arm(SUPPORT.answerer), SUPPORT, "Please refund me, this is the third time it broke")
    assert set(result["answers"]) == set(SUPPORT.questions)
    assert picked(SUPPORT, "refund_requested", result["answers"]["refund_requested"]) == ("yes", 0.9)
    text = ask_text(SUPPORT, "Please refund me", [result])
    assert "Do they want money back?" in text and "keyword baseline" in text


def test_a_score_ticks_its_most_likely_level_not_the_rounded_average():
    answer = {"type": "score", "answer": 1.37, "probabilities": {"0": 0.16, "1": 0.31, "2": 0.52, "3": 0.01}}
    assert picked(SUPPORT, "urgency", answer) == ("today", 0.52)


def test_a_broken_answer_is_shown_not_raised():
    text = ask_text(SPAM, "hi", [{"arm": "tiny", "ms": 5, "error": "Invalid response data"}])
    assert "broken answer" in text and "Invalid response data" in text


def test_race_view_prints_each_hop_and_the_finish():
    lines: list[str] = []
    result = race_live(baseline_arm(wikirace.answerer), SNAP, RACE, out=lines.append)
    printed = "\n".join(lines)
    assert result.success and "▸ Cats" in printed and "reached Cat food in 2 hops" in printed
    assert result.steps[0].top[0][0] == "Cats"  # word overlap with the target


def test_scoreboard_ranks_every_player():
    messages = [Message("1", "WIN a FREE prize, call 0906170146", True), Message("2", "see you at lunch", False)]
    report = board_run(lambda answerer: [baseline_arm(answerer)], messages, SNAP, [RACE])
    (row,) = report["rows"]
    assert row["spam_accuracy"] == 1.0 and row["races_solved"] == (1, 1) and row["broken"] == 0.0
    assert "| keyword baseline |" in board_markdown(report)


def test_playground_answers_and_rejects_bad_requests():
    pg = Playground(lambda answerer: [baseline_arm(answerer)], SNAP, [RACE])
    assert pg.config()["players"] == ["keyword baseline"]
    assert pg.ask({"form": "spam", "player": 0, "message": "Free prize! Call 09061701461"})["answers"]["spam"]
    race = pg.race({"race": 0, "player": 0})
    assert race["success"] and all("ms" in s for s in race["steps"])
    empty, unknown_form, unknown_player = (
        {"form": "spam", "player": 0, "message": "  "},
        {"form": "nope"},
        {"form": "spam", "player": 7, "message": "x"},
    )
    for bad in (empty, unknown_form, unknown_player):
        with pytest.raises(BadRequest):
            pg.ask(bad)
