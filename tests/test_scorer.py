"""Unit tests for the CPJudge scorer module."""
import pytest

from cpjudge.engine.scorer import Scorer, ScoringMode, TestCaseScoreItem
from cpjudge.engine.verdicts import Verdict


def test_scorer_per_test():
    scorer = Scorer(mode=ScoringMode.PER_TEST)
    items = [
        TestCaseScoreItem(test_id=1, verdict=Verdict.AC, marks=20.0),
        TestCaseScoreItem(test_id=2, verdict=Verdict.WA, marks=30.0),
        TestCaseScoreItem(test_id=3, verdict=Verdict.AC, marks=50.0),
    ]
    res = scorer.calculate_score(items)
    assert res.max_score == 100.0
    assert res.raw_score == 70.0
    assert res.final_score == 70.0
    assert res.test_marks_awarded[1] == 20.0
    assert res.test_marks_awarded[2] == 0.0
    assert res.test_marks_awarded[3] == 50.0


def test_scorer_all_or_nothing():
    scorer = Scorer(mode=ScoringMode.ALL_OR_NOTHING)
    items_fail = [
        TestCaseScoreItem(test_id=1, verdict=Verdict.AC, marks=50.0),
        TestCaseScoreItem(test_id=2, verdict=Verdict.WA, marks=50.0),
    ]
    res_fail = scorer.calculate_score(items_fail)
    assert res_fail.max_score == 100.0
    assert res_fail.raw_score == 0.0
    assert res_fail.final_score == 0.0

    items_pass = [
        TestCaseScoreItem(test_id=1, verdict=Verdict.AC, marks=50.0),
        TestCaseScoreItem(test_id=2, verdict=Verdict.AC, marks=50.0),
    ]
    res_pass = scorer.calculate_score(items_pass)
    assert res_pass.max_score == 100.0
    assert res_pass.raw_score == 100.0
    assert res_pass.final_score == 100.0


def test_scorer_grouped_subtasks():
    scorer = Scorer(mode=ScoringMode.GROUPED)
    items = [
        # Subtask 1: both pass -> awarded 40 marks
        TestCaseScoreItem(test_id=1, verdict=Verdict.AC, marks=20.0, subtask_id="st1"),
        TestCaseScoreItem(test_id=2, verdict=Verdict.AC, marks=20.0, subtask_id="st1"),
        # Subtask 2: one fails -> 0 marks for subtask 2
        TestCaseScoreItem(test_id=3, verdict=Verdict.AC, marks=30.0, subtask_id="st2"),
        TestCaseScoreItem(test_id=4, verdict=Verdict.WA, marks=30.0, subtask_id="st2"),
    ]
    res = scorer.calculate_score(items)
    assert res.max_score == 100.0
    assert res.raw_score == 40.0
    assert res.final_score == 40.0
    assert res.subtask_marks_awarded["st1"] == 40.0
    assert res.subtask_marks_awarded["st2"] == 0.0


def test_scorer_late_penalty():
    scorer = Scorer(mode=ScoringMode.PER_TEST, late_penalty_percent=20.0)
    items = [
        TestCaseScoreItem(test_id=1, verdict=Verdict.AC, marks=100.0),
    ]
    res = scorer.calculate_score(items)
    assert res.raw_score == 100.0
    assert res.late_penalty_percent == 20.0
    assert res.late_penalty_deduction == 20.0
    assert res.final_score == 80.0
