"""Scorer module for CPJudge.

Supports scoring policies:
- per_test: partial marks awarded for each passed test case.
- all_or_nothing: full score awarded only if ALL tests are accepted.
- grouped: tests grouped into subtasks; each subtask awarded only if all its tests pass.
- late penalty: percentage deduction applied to raw score.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from cpjudge.engine.verdicts import Verdict


class ScoringMode(str, Enum):
    PER_TEST = "per_test"
    ALL_OR_NOTHING = "all_or_nothing"
    GROUPED = "grouped"


@dataclass
class TestCaseScoreItem:
    test_id: str | int
    verdict: Verdict
    marks: float
    subtask_id: Optional[str | int] = None
    __test__: bool = False


@dataclass
class ScoreResult:
    raw_score: float
    final_score: float
    max_score: float
    late_penalty_percent: float
    late_penalty_deduction: float
    test_marks_awarded: Dict[str | int, float]
    subtask_marks_awarded: Dict[str | int, float]


class Scorer:
    def __init__(
        self,
        mode: ScoringMode = ScoringMode.PER_TEST,
        late_penalty_percent: float = 0.0,
        subtask_weights: Optional[Dict[str | int, float]] = None,
    ):
        self.mode = mode
        self.late_penalty_percent = max(0.0, min(100.0, late_penalty_percent))
        self.subtask_weights = subtask_weights or {}

    def calculate_score(
        self,
        test_items: List[TestCaseScoreItem],
    ) -> ScoreResult:
        """Calculates score based on test results, scoring mode, and late penalty."""
        if not test_items:
            return ScoreResult(
                raw_score=0.0,
                final_score=0.0,
                max_score=0.0,
                late_penalty_percent=self.late_penalty_percent,
                late_penalty_deduction=0.0,
                test_marks_awarded={},
                subtask_marks_awarded={},
            )

        test_marks_awarded: Dict[str | int, float] = {}
        subtask_marks_awarded: Dict[str | int, float] = {}
        max_score = 0.0
        raw_score = 0.0

        if self.mode == ScoringMode.PER_TEST:
            for item in test_items:
                max_score += item.marks
                if item.verdict == Verdict.AC:
                    test_marks_awarded[item.test_id] = item.marks
                    raw_score += item.marks
                else:
                    test_marks_awarded[item.test_id] = 0.0

        elif self.mode == ScoringMode.ALL_OR_NOTHING:
            all_passed = all(item.verdict == Verdict.AC for item in test_items)
            total_possible = sum(item.marks for item in test_items)
            max_score = total_possible
            if all_passed:
                raw_score = total_possible
                for item in test_items:
                    test_marks_awarded[item.test_id] = item.marks
            else:
                raw_score = 0.0
                for item in test_items:
                    test_marks_awarded[item.test_id] = 0.0

        elif self.mode == ScoringMode.GROUPED:
            # Group tests by subtask_id (fallback to test_id if None)
            groups: Dict[str | int, List[TestCaseScoreItem]] = {}
            for item in test_items:
                gid = item.subtask_id if item.subtask_id is not None else item.test_id
                groups.setdefault(gid, []).append(item)

            for gid, items in groups.items():
                group_weight = self.subtask_weights.get(gid, sum(it.marks for it in items))
                max_score += group_weight
                group_passed = all(it.verdict == Verdict.AC for it in items)

                if group_passed:
                    subtask_marks_awarded[gid] = group_weight
                    raw_score += group_weight
                    for it in items:
                        test_marks_awarded[it.test_id] = it.marks
                else:
                    subtask_marks_awarded[gid] = 0.0
                    for it in items:
                        test_marks_awarded[it.test_id] = 0.0

        # Apply late penalty deduction
        deduction = (raw_score * self.late_penalty_percent) / 100.0
        final_score = max(0.0, raw_score - deduction)

        return ScoreResult(
            raw_score=round(raw_score, 2),
            final_score=round(final_score, 2),
            max_score=round(max_score, 2),
            late_penalty_percent=self.late_penalty_percent,
            late_penalty_deduction=round(deduction, 2),
            test_marks_awarded=test_marks_awarded,
            subtask_marks_awarded=subtask_marks_awarded,
        )
