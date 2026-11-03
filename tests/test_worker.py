"""Integration tests for the JudgeWorker and database-backed judge execution.

Tests:
- Startup crash recovery of stuck 'judging' submissions.
- FIFO queue claiming.
- Complete execution of AC, WA, and CE submissions.
- Hidden test privacy at the database Result level.
- Late penalty calculation and Score record generation.
- Rejudge workflows via worker.
- Worker queue draining with run_once().
- Unhandled engine crash recovery (marks status as 'error').
"""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import pytest
from sqlalchemy import inspect, text

from cpjudge.app import _ensure_submission_claim_timestamp, create_app
from cpjudge.config import TestingConfig, config_by_name
from cpjudge.engine.judge import SubmissionResult, judge
from cpjudge.engine.sandbox import is_bwrap_available
from cpjudge.engine.verdicts import Verdict
from cpjudge.models import (
    Assignment,
    Class,
    Enrollment,
    Problem,
    Result,
    Score,
    Submission,
    Test,
    User,
    db,
    utc_now,
)
from cpjudge.worker import JudgeWorker

requires_bwrap = pytest.mark.skipif(
    not is_bwrap_available(),
    reason="Bubblewrap user namespaces are unavailable in this environment.",
)


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def worker(app):
    return JudgeWorker(app=app, poll_interval=0.1)


@pytest.fixture
def teacher(app):
    t = User(username="prof_turing", name="Alan Turing", role="teacher", force_password_change=False)
    t.set_password("Teacher@123")
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture
def student(app):
    s = User(username="bcsf20m001", roll_no="BCSF20M001", name="Alice", role="student", force_password_change=False)
    s.set_password("Student@123")
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture
def env_setup(app, teacher, student):
    """Creates a class, enrollment, problem with visible & hidden tests, and an assignment."""
    now = utc_now()
    cls = Class(code="CS101", name="Intro to CS", teacher_id=teacher.id)
    db.session.add(cls)
    db.session.commit()

    enrollment = Enrollment(user_id=student.id, class_id=cls.id)
    db.session.add(enrollment)

    # Problem: Sum of Two Numbers
    problem = Problem(
        title="Sum of Two Numbers",
        slug="sum-of-two",
        statement="Calculate A + B",
        time_limit=1.0,
        memory_limit=128,
        created_by_id=teacher.id,
        scoring_mode="per_test",
        tests_version=1,
    )
    db.session.add(problem)
    db.session.commit()

    # Test 1: visible (50 pts)
    t1 = Test(
        problem_id=problem.id,
        order_num=1,
        input_data="3 5\n",
        expected_output="8\n",
        marks=50.0,
        is_hidden=False,
    )
    # Test 2: hidden (50 pts)
    t2 = Test(
        problem_id=problem.id,
        order_num=2,
        input_data="100 200\n",
        expected_output="300\n",
        marks=50.0,
        is_hidden=True,
    )
    db.session.add_all([t1, t2])

    assignment = Assignment(
        class_id=cls.id,
        problem_id=problem.id,
        title="Assignment 01",
        open_date=now - timedelta(days=1),
        due_date=now + timedelta(days=7),
        allow_late=True,
        late_penalty_percent=20.0,
        max_attempts=5,
    )
    db.session.add(assignment)
    db.session.commit()

    return {
        "class": cls,
        "problem": problem,
        "tests": [t1, t2],
        "assignment": assignment,
    }


# ==============================================================================
# RECOVERY & QUEUE CLAIMING TESTS
# ==============================================================================

def test_recover_stuck_submissions(app, worker, student, env_setup):
    problem = env_setup["problem"]
    sub1 = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="cpp",
        source_code="// stuck 1",
        status="judging",
        claimed_at=utc_now() - timedelta(hours=2),
        tests_version=1,
    )
    sub2 = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="cpp",
        source_code="// stuck 2",
        status="judging",
        claimed_at=utc_now() - timedelta(hours=2),
        tests_version=1,
    )
    sub3 = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="cpp",
        source_code="// already done",
        status="done",
        tests_version=1,
    )
    sub4 = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="cpp",
        source_code="// active",
        status="judging",
        claimed_at=utc_now(),
        tests_version=1,
    )
    db.session.add_all([sub1, sub2, sub3, sub4])
    db.session.commit()

    recovered = worker.recover_stuck_submissions()
    assert recovered == 2

    # Verify both are now queued
    assert db.session.get(Submission, sub1.id).status == "queued"
    assert db.session.get(Submission, sub2.id).status == "queued"
    assert db.session.get(Submission, sub3.id).status == "done"
    assert db.session.get(Submission, sub4.id).status == "judging"


def test_claim_next_submission_fifo(app, worker, student, env_setup):
    problem = env_setup["problem"]
    sub1 = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="cpp",
        source_code="// first",
        status="queued",
        tests_version=1,
    )
    db.session.add(sub1)
    db.session.commit()

    sub2 = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="cpp",
        source_code="// second",
        status="queued",
        tests_version=1,
    )
    db.session.add(sub2)
    db.session.commit()

    # Claim first
    claimed1 = worker.claim_next_submission()
    assert claimed1 == sub1.id
    assert db.session.get(Submission, sub1.id).status == "judging"
    assert db.session.get(Submission, sub1.id).claimed_at is not None

    # Claim second
    claimed2 = worker.claim_next_submission()
    assert claimed2 == sub2.id
    assert db.session.get(Submission, sub2.id).status == "judging"

    # Queue now empty
    claimed3 = worker.claim_next_submission()
    assert claimed3 is None


def test_concurrent_workers_claim_distinct_submissions(tmp_path, monkeypatch):
    database_uri = f"sqlite:///{tmp_path / 'queue.sqlite'}"
    file_testing_config = type(
        "FileTestingConfig",
        (TestingConfig,),
        {"SQLALCHEMY_DATABASE_URI": database_uri},
    )
    monkeypatch.setitem(config_by_name, "testing", file_testing_config)
    app = create_app("testing")

    with app.app_context():
        db.create_all()
        teacher = User(username="queue_teacher", name="Teacher", role="teacher")
        teacher.set_password("Teacher@123")
        db.session.add(teacher)
        db.session.flush()
        problem = Problem(
            title="Queue test",
            slug="queue-test",
            statement="",
            created_by_id=teacher.id,
        )
        db.session.add(problem)
        db.session.flush()
        submissions = [
            Submission(
                user_id=teacher.id,
                problem_id=problem.id,
                language="python",
                source_code="print(1)",
                status="queued",
                tests_version=1,
            )
            for _ in range(2)
        ]
        db.session.add_all(submissions)
        db.session.commit()
        submission_ids = {submission.id for submission in submissions}

    workers = [JudgeWorker(app=app), JudgeWorker(app=app)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed_ids = list(executor.map(lambda item: item.claim_next_submission(), workers))

    assert set(claimed_ids) == submission_ids
    with app.app_context():
        assert Submission.query.filter_by(status="judging").count() == 2
        assert Submission.query.filter_by(claimed_at=None).count() == 0


def test_legacy_database_gets_claim_timestamp(tmp_path, monkeypatch):
    database_uri = f"sqlite:///{tmp_path / 'legacy.sqlite'}"
    file_testing_config = type(
        "LegacyTestingConfig",
        (TestingConfig,),
        {"SQLALCHEMY_DATABASE_URI": database_uri},
    )
    monkeypatch.setitem(config_by_name, "testing", file_testing_config)
    app = create_app("testing")

    with app.app_context():
        with db.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE submissions (id INTEGER PRIMARY KEY, status VARCHAR(20))"
            )
            connection.exec_driver_sql(
                "INSERT INTO submissions (id, status) VALUES (1, 'judging')"
            )

        _ensure_submission_claim_timestamp()

        columns = {column["name"] for column in inspect(db.engine).get_columns("submissions")}
        claimed_at = db.session.execute(
            text("SELECT claimed_at FROM submissions WHERE id = 1")
        ).scalar_one()

    assert "claimed_at" in columns
    assert claimed_at is not None


def test_judge_uses_configured_sandbox_settings(app, student, env_setup, monkeypatch):
    problem = env_setup["problem"]
    submission = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="python",
        source_code="print(1)",
        status="judging",
        tests_version=problem.tests_version,
    )
    db.session.add(submission)
    db.session.commit()

    app.config["USE_BWRAP"] = False
    app.config["SANDBOX_USER"] = "custom_sandbox"
    captured_configs = []

    def fake_judge_submission(source_code, language, test_cases, config):
        captured_configs.append(config)
        return SubmissionResult(
            verdict=Verdict.AC,
            total_score=0.0,
            raw_score=0.0,
            max_score=sum(test_case.marks for test_case in test_cases),
            late_penalty_deduction=0.0,
        )

    judge_module = import_module("cpjudge.engine.judge")
    monkeypatch.setattr(judge_module, "judge_submission", fake_judge_submission)
    judge(submission.id)

    assert len(captured_configs) == 1
    assert captured_configs[0].use_bwrap is False
    assert captured_configs[0].sandbox_user == "custom_sandbox"
    assert db.session.get(Submission, submission.id).status == "done"


def test_judge_keeps_score_stale_if_tests_change_during_evaluation(app, student, env_setup, monkeypatch):
    problem = env_setup["problem"]
    submission = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="python",
        source_code="print(1)",
        status="judging",
        tests_version=problem.tests_version,
    )
    db.session.add(submission)
    db.session.commit()

    def update_tests_during_judging(*args, **kwargs):
        problem.increment_tests_version()
        db.session.commit()
        return SubmissionResult(
            verdict=Verdict.AC,
            total_score=0.0,
            raw_score=0.0,
            max_score=0.0,
            late_penalty_deduction=0.0,
        )

    judge_module = import_module("cpjudge.engine.judge")
    monkeypatch.setattr(judge_module, "judge_submission", update_tests_during_judging)
    judge(submission.id)

    db.session.refresh(submission)
    assert submission.status == "done"
    assert submission.tests_version == 1
    assert submission.score.is_stale is True
    assert submission.has_current_score is False


# ==============================================================================
# EVALUATION & PERSISTENCE TESTS (AC, WA, CE, HIDDEN PRIVACY)
# ==============================================================================

@requires_bwrap
def test_judge_accepted_c_cpp_python(app, worker, student, env_setup):
    problem = env_setup["problem"]
    assignment = env_setup["assignment"]

    # 1. C++ solution (AC)
    cpp_code = """
    #include <iostream>
    int main() {
        int a, b;
        if (std::cin >> a >> b) {
            std::cout << a + b << std::endl;
        }
        return 0;
    }
    """
    sub_cpp = Submission(
        user_id=student.id,
        problem_id=problem.id,
        assignment_id=assignment.id,
        language="cpp",
        source_code=cpp_code,
        status="queued",
        tests_version=problem.tests_version,
    )
    db.session.add(sub_cpp)
    db.session.commit()

    # Process via worker
    assert worker.process_one() is True

    # Verify submission status
    db.session.refresh(sub_cpp)
    assert sub_cpp.status == "done"
    assert sub_cpp.verdict == "AC"
    assert sub_cpp.judged_at is not None
    assert sub_cpp.max_time is not None and sub_cpp.max_time < 1.0
    assert sub_cpp.max_memory_kb is not None and sub_cpp.max_memory_kb > 0

    # Verify Score record
    score = sub_cpp.score
    assert score is not None
    assert score.raw_score == 100.0
    assert score.final_score == 100.0
    assert score.max_possible_score == 100.0
    assert not score.is_stale

    # Verify Result records and privacy:
    results = Result.query.filter_by(submission_id=sub_cpp.id).order_by(Result.test_order.asc()).all()
    assert len(results) == 2

    # Test 1 (visible)
    assert results[0].test_order == 1
    assert results[0].verdict == "AC"
    assert results[0].marks_awarded == 50.0
    assert results[0].is_hidden is False
    assert results[0].student_output is not None and "8" in results[0].student_output

    # Test 2 (hidden) - CRITICAL: database level privacy check
    assert results[1].test_order == 2
    assert results[1].verdict == "AC"
    assert results[1].marks_awarded == 50.0
    assert results[1].is_hidden is True
    assert results[1].student_output is None  # Strictly masked in DB!
    assert results[1].diff is None
    assert results[1].feedback is None


@requires_bwrap
def test_judge_wrong_answer_diff_and_scoring(app, worker, student, env_setup):
    problem = env_setup["problem"]
    assignment = env_setup["assignment"]

    # Hardcoded solution that passes test 1 (3+5=8) but fails test 2 (100+200=300)
    wa_code = """
    #include <iostream>
    int main() {
        int a, b;
        std::cin >> a >> b;
        if (a == 3 && b == 5) {
            std::cout << 8 << std::endl;
        } else {
            std::cout << 999999 << std::endl;
        }
        return 0;
    }
    """
    sub_wa = Submission(
        user_id=student.id,
        problem_id=problem.id,
        assignment_id=assignment.id,
        language="cpp",
        source_code=wa_code,
        status="queued",
        tests_version=problem.tests_version,
    )
    db.session.add(sub_wa)
    db.session.commit()

    assert worker.process_one() is True

    db.session.refresh(sub_wa)
    assert sub_wa.status == "done"
    assert sub_wa.verdict == "WA"

    # Only test 1 points awarded (50 / 100)
    assert sub_wa.score.raw_score == 50.0
    assert sub_wa.score.final_score == 50.0

    results = Result.query.filter_by(submission_id=sub_wa.id).order_by(Result.test_order.asc()).all()
    assert results[0].verdict == "AC"
    assert results[0].marks_awarded == 50.0

    assert results[1].verdict == "WA"
    assert results[1].marks_awarded == 0.0
    assert results[1].is_hidden is True
    # Still hidden and masked even on WA!
    assert results[1].student_output is None
    assert results[1].diff is None


@requires_bwrap
def test_judge_compilation_error(app, worker, student, env_setup):
    problem = env_setup["problem"]
    assignment = env_setup["assignment"]

    ce_code = "int main() { syntax_error_here }"
    sub_ce = Submission(
        user_id=student.id,
        problem_id=problem.id,
        assignment_id=assignment.id,
        language="cpp",
        source_code=ce_code,
        status="queued",
        tests_version=problem.tests_version,
    )
    db.session.add(sub_ce)
    db.session.commit()

    assert worker.process_one() is True

    db.session.refresh(sub_ce)
    assert sub_ce.status == "done"
    assert sub_ce.verdict == "CE"
    assert sub_ce.compile_error is not None
    assert "error:" in sub_ce.compile_error

    assert sub_ce.score.raw_score == 0.0
    assert sub_ce.score.final_score == 0.0


# ==============================================================================
# LATE PENALTY & STALENESS & REJUDGE TESTS
# ==============================================================================

@requires_bwrap
def test_late_submission_penalty_applied(app, worker, student, env_setup):
    problem = env_setup["problem"]
    assignment = env_setup["assignment"]
    assignment.late_penalty_percent = 25.0
    db.session.commit()

    # Late submission (flagged is_late=True)
    sub = Submission(
        user_id=student.id,
        problem_id=problem.id,
        assignment_id=assignment.id,
        language="python",
        source_code="a, b = map(int, input().split())\nprint(a + b)\n",
        status="queued",
        tests_version=problem.tests_version,
        is_late=True,
    )
    db.session.add(sub)
    db.session.commit()

    assert worker.process_one() is True

    db.session.refresh(sub)
    assert sub.status == "done"
    assert sub.verdict == "AC"

    # Raw score: 100. Late penalty 25% -> 75
    score = sub.score
    assert score.raw_score == 100.0
    assert score.late_penalty_percent == 25.0
    assert score.late_penalty_deduction == 25.0
    assert score.final_score == 75.0


@requires_bwrap
def test_rejudge_updates_staleness_and_scores(app, worker, student, env_setup):
    problem = env_setup["problem"]
    assignment = env_setup["assignment"]

    # 1. Initial submission evaluated at tests_version 1
    sub = Submission(
        user_id=student.id,
        problem_id=problem.id,
        assignment_id=assignment.id,
        language="python",
        source_code="a, b = map(int, input().split())\nprint(a + b)\n",
        status="queued",
        tests_version=1,
    )
    db.session.add(sub)
    db.session.commit()
    worker.process_one()

    db.session.refresh(sub)
    assert sub.score.final_score == 100.0
    assert not sub.is_stale

    # 2. Teacher adds a 3rd test case and increments tests_version
    t3 = Test(
        problem_id=problem.id,
        order_num=3,
        input_data="10 20\n",
        expected_output="30\n",
        marks=50.0,
        is_hidden=False,
    )
    db.session.add(t3)
    problem.increment_tests_version()  # now version 2
    db.session.commit()

    # Submission is now marked stale
    db.session.refresh(sub)
    assert sub.is_stale is True

    # 3. Teacher queues rejudge
    sub.status = "queued"
    sub.tests_version = problem.tests_version
    db.session.commit()

    # Worker rejudges
    worker.process_one()

    db.session.refresh(sub)
    assert sub.status == "done"
    assert not sub.is_stale
    # Total score now reflects all 3 tests (150 pts)
    assert sub.score.final_score == 150.0
    assert sub.score.max_possible_score == 150.0
    assert len(sub.results) == 3


@requires_bwrap
def test_worker_run_once_drains_all_queued(app, worker, student, env_setup):
    problem = env_setup["problem"]

    for i in range(3):
        sub = Submission(
            user_id=student.id,
            problem_id=problem.id,
            language="python",
            source_code=f"print({i} + {i})",
            status="queued",
            tests_version=problem.tests_version,
        )
        db.session.add(sub)
    db.session.commit()

    assert Submission.query.filter_by(status="queued").count() == 3

    drained = worker.run_once()
    assert drained == 3
    assert Submission.query.filter_by(status="queued").count() == 0
    assert Submission.query.filter_by(status="done").count() == 3
