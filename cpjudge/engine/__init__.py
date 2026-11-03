"""CPJudge Engine package."""
from cpjudge.engine.checker import Checker, CheckerType, CheckResult
from cpjudge.engine.compiler import Compiler, CompileResult
from cpjudge.engine.judge import (
    JudgeConfig,
    SubmissionResult,
    TestCase,
    TestResult,
    judge,
    judge_submission,
)
from cpjudge.engine.runner import Runner, RunResult
from cpjudge.engine.scorer import Scorer, ScoringMode, ScoreResult
from cpjudge.engine.verdicts import Verdict

__all__ = [
    "Verdict",
    "Compiler",
    "CompileResult",
    "Runner",
    "RunResult",
    "Checker",
    "CheckerType",
    "CheckResult",
    "Scorer",
    "ScoringMode",
    "ScoreResult",
    "TestCase",
    "TestResult",
    "SubmissionResult",
    "JudgeConfig",
    "judge_submission",
    "judge",
]
