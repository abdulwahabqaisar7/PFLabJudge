"""Unit tests for CPJudge database models."""
from datetime import datetime, timedelta, timezone
import pytest

from cpjudge.app import create_app
from cpjudge.models import (
    Assignment,
    AuditLog,
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
from seed import seed_database


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_user_password_hashing(app):
    user = User(username="testuser", name="Test User", role="student")
    user.set_password("Secret123!")
    db.session.add(user)
    db.session.commit()

    assert user.password_hash != "Secret123!"
    assert user.check_password("Secret123!") is True
    assert user.check_password("WrongPassword") is False
    assert user.is_student is True
    assert user.is_teacher is False


def test_teacher_role(app):
    teacher = User(username="prof_turing", name="Alan Turing", role="teacher")
    teacher.set_password("Pass@123")
    db.session.add(teacher)
    db.session.commit()

    assert teacher.is_teacher is True
    assert teacher.is_student is False


def test_class_and_enrollment(app):
    teacher = User(username="teacher1", name="Prof Smith", role="teacher")
    teacher.set_password("Pass@123")
    student = User(username="student1", name="Alice", role="student")
    student.set_password("Pass@123")
    db.session.add_all([teacher, student])
    db.session.commit()

    classroom = Class(name="CS101", code="CS101-2024", teacher_id=teacher.id)
    db.session.add(classroom)
    db.session.commit()

    enrollment = Enrollment(user_id=student.id, class_id=classroom.id)
    db.session.add(enrollment)
    db.session.commit()

    assert classroom.student_count == 1
    assert len(student.enrollments) == 1
    assert student.enrollments[0].classroom.code == "CS101-2024"


def test_problem_and_tests_versioning(app):
    teacher = User(username="teacher2", name="Teacher 2", role="teacher")
    teacher.set_password("Pass@123")
    db.session.add(teacher)
    db.session.commit()

    problem = Problem(
        title="Sample Problem",
        slug="sample-problem",
        statement="# Statement",
        created_by_id=teacher.id,
        tests_version=1,
    )
    db.session.add(problem)
    db.session.commit()

    t1 = Test(problem_id=problem.id, order_num=1, input_data="1\n", expected_output="1\n", marks=10.0, is_hidden=False)
    t2 = Test(problem_id=problem.id, order_num=2, input_data="2\n", expected_output="2\n", marks=20.0, is_hidden=True)
    db.session.add_all([t1, t2])
    db.session.commit()

    assert problem.total_marks == 30.0
    assert len(problem.visible_tests) == 1
    assert len(problem.hidden_tests) == 1

    # Test submission staleness tracking
    student = User(username="student2", name="Bob", role="student")
    student.set_password("Pass@123")
    db.session.add(student)
    db.session.commit()

    sub = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="cpp",
        source_code="int main(){}",
        status="done",
        verdict="AC",
        tests_version=problem.tests_version,
    )
    db.session.add(sub)
    db.session.commit()

    assert sub.is_stale is False

    # Increment problem tests version (e.g. teacher edited tests)
    problem.increment_tests_version()
    db.session.commit()

    # Submission should now be flagged as stale
    assert sub.is_stale is True


def test_assignment_deadlines_and_status(app):
    teacher = User(username="teacher3", name="Teacher 3", role="teacher")
    teacher.set_password("Pass@123")
    problem = Problem(title="P1", slug="p1", statement="S", created_by_id=1)
    db.session.add_all([teacher, problem])
    db.session.commit()

    classroom = Class(name="C1", code="C1", teacher_id=teacher.id)
    db.session.add(classroom)
    db.session.commit()

    now = utc_now()
    assignment = Assignment(
        class_id=classroom.id,
        problem_id=problem.id,
        title="Lab 1",
        open_date=now - timedelta(days=2),
        due_date=now + timedelta(days=5),
        allow_late=False,
    )
    db.session.add(assignment)
    db.session.commit()

    assert assignment.is_active() is True
    assert assignment.is_late() is False

    past_due_time = now + timedelta(days=6)
    assert assignment.is_late(past_due_time) is True


def test_submission_results_and_scores(app):
    teacher = User(username="teacher4", name="Teacher 4", role="teacher")
    teacher.set_password("Pass@123")
    student = User(username="student4", name="Student 4", role="student")
    student.set_password("Pass@123")
    db.session.add_all([teacher, student])
    db.session.commit()

    problem = Problem(title="P2", slug="p2", statement="S", created_by_id=teacher.id)
    db.session.add(problem)
    db.session.commit()

    sub = Submission(
        user_id=student.id,
        problem_id=problem.id,
        language="python",
        source_code="print(42)",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    db.session.add(sub)
    db.session.commit()

    r1 = Result(
        submission_id=sub.id,
        test_order=1,
        verdict="AC",
        cpu_time=0.01,
        memory_kb=15000,
        marks_awarded=50.0,
        is_hidden=False,
        student_output="42\n",
    )
    r2 = Result(
        submission_id=sub.id,
        test_order=2,
        verdict="AC",
        cpu_time=0.02,
        memory_kb=15200,
        marks_awarded=50.0,
        is_hidden=True,
        student_output=None, # Strictly hidden
    )
    db.session.add_all([r1, r2])

    score = Score(
        submission_id=sub.id,
        user_id=student.id,
        problem_id=problem.id,
        raw_score=100.0,
        late_penalty_percent=10.0,
        late_penalty_deduction=10.0,
        final_score=90.0,
        max_possible_score=100.0,
    )
    db.session.add(score)
    db.session.commit()

    assert len(sub.results) == 2
    assert sub.score.final_score == 90.0
    assert sub.score.percentage == 90.0


def test_audit_log(app):
    user = User(username="auditor", name="Auditor", role="teacher")
    user.set_password("Pass@123")
    db.session.add(user)
    db.session.commit()

    entry = AuditLog.log(
        action="rejudge_submission",
        user_id=user.id,
        target_type="submission",
        target_id=42,
        details={"reason": "Test case corrected"},
        ip_address="192.168.1.100",
    )
    db.session.commit()

    fetched = AuditLog.query.filter_by(action="rejudge_submission").first()
    assert fetched is not None
    assert fetched.user_id == user.id
    assert fetched.target_id == "42"
    assert "Test case corrected" in fetched.details
