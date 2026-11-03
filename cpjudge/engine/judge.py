"""Judge orchestrator module for CPJudge.

Compiles, executes against test cases, evaluates checkers, and calculates scores.
Can be used as a standalone library:
    result = judge_submission(source_code, language, test_cases, config)
"""
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
import time
from typing import Dict, List, Optional

from flask import current_app, has_app_context
from sqlalchemy import select

from cpjudge.engine.checker import Checker, CheckerType
from cpjudge.engine.compiler import Compiler
from cpjudge.engine.runner import Runner
from cpjudge.engine.scorer import Scorer, ScoringMode, TestCaseScoreItem
from cpjudge.engine.verdicts import Verdict


@dataclass
class TestCase:
    id: str | int
    input_data: str
    expected_output: str
    marks: float = 1.0
    is_hidden: bool = False
    subtask_id: Optional[str | int] = None
    __test__: bool = False


@dataclass
class JudgeConfig:
    time_limit: float = 1.0
    memory_limit_mb: int = 256
    output_limit_bytes: int = 10 * 1024 * 1024  # 10 MB
    compile_timeout: float = 10.0
    time_multipliers: Optional[Dict[str, float]] = None
    checker_type: CheckerType = CheckerType.TOKEN
    custom_checker_path: Optional[str] = None
    float_tolerance: float = 1e-6
    scoring_mode: ScoringMode = ScoringMode.PER_TEST
    late_penalty_percent: float = 0.0
    use_bwrap: bool = True
    sandbox_user: Optional[str] = "judge_sandbox"


@dataclass
class TestResult:
    test_id: str | int
    verdict: Verdict
    cpu_time: float
    wall_time: float
    memory_kb: int
    marks_awarded: float
    is_hidden: bool
    subtask_id: Optional[str | int] = None
    student_output: Optional[str] = None
    diff: Optional[str] = None
    error_message: Optional[str] = None
    feedback: Optional[str] = None


@dataclass
class SubmissionResult:
    verdict: Verdict
    total_score: float
    raw_score: float
    max_score: float
    late_penalty_deduction: float
    compile_error: Optional[str] = None
    compile_time: float = 0.0
    test_results: List[TestResult] = field(default_factory=list)
    max_time: float = 0.0
    max_memory_kb: int = 0


def judge_submission(
    source_code: str,
    language: str,
    test_cases: List[TestCase],
    config: Optional[JudgeConfig] = None,
) -> SubmissionResult:
    """Judges a submission in memory.

    Args:
        source_code: Student solution source code.
        language: Programming language ('c', 'cpp', or 'python').
        test_cases: List of TestCase objects.
        config: JudgeConfig settings.

    Returns:
        SubmissionResult with comprehensive test details and scores.
    """
    if config is None:
        config = JudgeConfig()

    compiler = Compiler(
        compile_timeout=config.compile_timeout,
        use_bwrap=config.use_bwrap,
        sandbox_user=config.sandbox_user,
    )
    runner = Runner(
        time_multipliers=config.time_multipliers,
        use_bwrap=config.use_bwrap,
        sandbox_user=config.sandbox_user,
    )
    checker = Checker(
        checker_type=config.checker_type,
        float_tolerance=config.float_tolerance,
        custom_checker_path=config.custom_checker_path,
        use_bwrap=config.use_bwrap,
        sandbox_user=config.sandbox_user,
    )

    # 1. Compilation Phase
    with tempfile.TemporaryDirectory(prefix="cpjudge_build_") as build_dir:
        try:
            import os
            os.chmod(build_dir, 0o777)
        except OSError:
            pass
        comp_res = compiler.compile(source_code, language, build_dir)

        if not comp_res.success:
            total_possible = sum(tc.marks for tc in test_cases)
            return SubmissionResult(
                verdict=Verdict.CE,
                total_score=0.0,
                raw_score=0.0,
                max_score=total_possible,
                late_penalty_deduction=0.0,
                compile_error=comp_res.error_message,
                compile_time=comp_res.compile_time,
                test_results=[],
            )

        # 2. Execution & Checking Phase for Each Test Case
        test_run_items: List[TestCaseScoreItem] = []
        detailed_results: List[TestResult] = []
        max_cpu_time = 0.0
        max_memory_kb = 0

        for tc in test_cases:
            run_res = runner.run_test(
                run_cmd=comp_res.run_cmd,
                language=language,
                test_input=tc.input_data,
                time_limit=config.time_limit,
                memory_limit_mb=config.memory_limit_mb,
                output_limit_bytes=config.output_limit_bytes,
            )

            max_cpu_time = max(max_cpu_time, run_res.cpu_time)
            max_memory_kb = max(max_memory_kb, run_res.memory_kb)

            # Check if execution failed with a limit/signal verdict
            if run_res.verdict is not None:
                final_verdict = run_res.verdict
                feedback = run_res.error_message
                diff = None
                student_out = None if tc.is_hidden else run_res.stdout
            else:
                # Normal termination, run checker
                check_res = checker.check(
                    input_data=tc.input_data,
                    expected_output=tc.expected_output,
                    student_output=run_res.stdout,
                    is_visible=not tc.is_hidden,
                )
                final_verdict = check_res.verdict
                feedback = check_res.feedback
                diff = check_res.diff if not tc.is_hidden else None
                student_out = run_res.stdout if not tc.is_hidden else None

            test_run_items.append(
                TestCaseScoreItem(
                    test_id=tc.id,
                    verdict=final_verdict,
                    marks=tc.marks,
                    subtask_id=tc.subtask_id,
                )
            )

            detailed_results.append(
                TestResult(
                    test_id=tc.id,
                    verdict=final_verdict,
                    cpu_time=run_res.cpu_time,
                    wall_time=run_res.wall_time,
                    memory_kb=run_res.memory_kb,
                    marks_awarded=0.0, # Will be set by scorer below
                    is_hidden=tc.is_hidden,
                    subtask_id=tc.subtask_id,
                    student_output=student_out,
                    diff=diff,
                    error_message=run_res.error_message if not tc.is_hidden else None,
                    feedback=feedback if not tc.is_hidden else None,
                )
            )

        # 3. Scoring Phase
        scorer = Scorer(
            mode=config.scoring_mode,
            late_penalty_percent=config.late_penalty_percent,
        )
        score_res = scorer.calculate_score(test_run_items)

        # Update marks_awarded on individual test results
        for tr in detailed_results:
            tr.marks_awarded = score_res.test_marks_awarded.get(tr.test_id, 0.0)

        # 4. Overall Submission Verdict
        # AC if all tests passed; otherwise first non-AC verdict encountered
        overall_verdict = Verdict.AC
        for tr in detailed_results:
            if tr.verdict != Verdict.AC:
                overall_verdict = tr.verdict
                break

        return SubmissionResult(
            verdict=overall_verdict,
            total_score=score_res.final_score,
            raw_score=score_res.raw_score,
            max_score=score_res.max_score,
            late_penalty_deduction=score_res.late_penalty_deduction,
            compile_time=comp_res.compile_time,
            test_results=detailed_results,
            max_time=max_cpu_time,
            max_memory_kb=max_memory_kb,
        )


def judge(submission_id: int) -> SubmissionResult:
    """Evaluates a submission against database test cases and updates the DB.

    1. Retrieves submission, problem, and problem test cases.
    2. Runs judge_submission().
    3. Persists per-test Result records (strictly masking hidden test outputs/diffs).
    4. Upserts Score record (applying late penalties if applicable).
    5. Updates Submission to 'done' (or 'error' on unhandled crash).
    """
    from cpjudge.models import (
        Problem,
        Result,
        Score,
        Submission,
        Test,
        db,
        utc_now,
    )

    submission = db.session.get(Submission, submission_id)
    if not submission:
        raise ValueError(f"Submission #{submission_id} not found in database.")

    problem = submission.problem
    if not problem:
        raise ValueError(f"Problem #{submission.problem_id} associated with submission #{submission_id} not found.")

    judged_tests_version = problem.tests_version
    submission.tests_version = judged_tests_version

    # Convert tests to engine TestCase objects ordered by order_num
    db_tests = (
        Test.query.filter_by(problem_id=problem.id)
        .order_by(Test.order_num.asc())
        .all()
    )
    test_cases = [
        TestCase(
            id=t.id,
            input_data=t.input_data,
            expected_output=t.expected_output,
            marks=t.marks,
            is_hidden=t.is_hidden,
            subtask_id=t.subtask_id,
        )
        for t in db_tests
    ]

    # Calculate late penalty percent
    late_penalty = 0.0
    if submission.is_late and submission.assignment and submission.assignment.allow_late:
        late_penalty = submission.assignment.late_penalty_percent

    # Prepare custom checker file if needed
    custom_checker_dir = None
    custom_checker_path = None
    if problem.checker_type == "custom" and problem.checker_code:
        custom_checker_dir = tempfile.TemporaryDirectory(prefix="cpjudge_custom_checker_")
        cpath = Path(custom_checker_dir.name) / "checker.py"
        cpath.write_text(problem.checker_code, encoding="utf-8")
        custom_checker_path = str(cpath)

    try:
        use_bwrap = current_app.config.get("USE_BWRAP", True) if has_app_context() else True
        sandbox_user = current_app.config.get("SANDBOX_USER", "judge_sandbox") if has_app_context() else "judge_sandbox"
        config = JudgeConfig(
            time_limit=problem.time_limit,
            memory_limit_mb=problem.memory_limit,
            output_limit_bytes=problem.output_limit_bytes,
            checker_type=CheckerType(problem.checker_type),
            custom_checker_path=custom_checker_path,
            float_tolerance=problem.float_tolerance,
            scoring_mode=ScoringMode(problem.scoring_mode),
            late_penalty_percent=late_penalty,
            use_bwrap=use_bwrap,
            sandbox_user=sandbox_user,
        )

        sub_result = judge_submission(
            source_code=submission.source_code,
            language=submission.language,
            test_cases=test_cases,
            config=config,
        )

        # Clear existing Result records (supports clean rejudging)
        Result.query.filter_by(submission_id=submission.id).delete()

        # Write new Result records
        for idx, tr in enumerate(sub_result.test_results, start=1):
            r = Result(
                submission_id=submission.id,
                test_id=int(tr.test_id),
                test_order=idx,
                verdict=tr.verdict.value,
                cpu_time=tr.cpu_time,
                wall_time=tr.wall_time,
                memory_kb=tr.memory_kb,
                marks_awarded=tr.marks_awarded,
                is_hidden=tr.is_hidden,
                # Strict privacy: NULL for hidden tests
                student_output=tr.student_output if not tr.is_hidden else None,
                diff=tr.diff if not tr.is_hidden else None,
                feedback=tr.feedback if not tr.is_hidden else None,
            )
            db.session.add(r)

        # Upsert Score record
        score = submission.score
        if score is None:
            score = Score(
                submission_id=submission.id,
                assignment_id=submission.assignment_id,
                user_id=submission.user_id,
                problem_id=submission.problem_id,
            )
            db.session.add(score)

        score.raw_score = sub_result.raw_score
        score.late_penalty_percent = late_penalty
        score.late_penalty_deduction = sub_result.late_penalty_deduction
        score.final_score = sub_result.total_score
        score.max_possible_score = sub_result.max_score
        current_tests_version = db.session.execute(
            select(Problem.tests_version).where(Problem.id == problem.id)
        ).scalar_one()
        score.is_stale = judged_tests_version != current_tests_version

        # Update Submission status and metrics
        submission.status = "done"
        submission.claimed_at = None
        submission.verdict = sub_result.verdict.value
        submission.max_time = sub_result.max_time
        submission.max_memory_kb = sub_result.max_memory_kb
        submission.compile_error = sub_result.compile_error
        submission.judged_at = utc_now()

        db.session.commit()
        return sub_result

    except Exception as e:
        db.session.rollback()
        submission.status = "error"
        submission.claimed_at = None
        submission.compile_error = f"Judge Worker Execution Error: {str(e)}"
        db.session.commit()
        raise
    finally:
        if custom_checker_dir:
            custom_checker_dir.cleanup()
