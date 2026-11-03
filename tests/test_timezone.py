"""Tests for Pakistan Standard Time (PKT, UTC+5) configuration and behavior."""
from datetime import datetime, timedelta, timezone
import pytest

from cpjudge.app import create_app
from cpjudge.models import (
    Assignment,
    Class,
    Enrollment,
    Problem,
    Submission,
    User,
    db,
)
from cpjudge.utils.timezone import PKT_TZ, format_pkt, now_pkt, to_pkt


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_pkt_timezone_offset():
    """Verifies PKT timezone offset is fixed at UTC+5 (18000s) and conversion is exact."""
    now = now_pkt()
    assert now.tzinfo is not None
    # Offset must be +05:00 (+18000 seconds)
    offset_seconds = now.utcoffset().total_seconds()
    assert offset_seconds == 5 * 3600

    # Test UTC to PKT conversion
    utc_dt = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
    pkt_dt = to_pkt(utc_dt)
    # 10:00 UTC should be 15:00 PKT
    assert pkt_dt.hour == 15
    assert pkt_dt.day == 1

    # Test naive datetime localization
    naive_dt = datetime(2026, 11, 1, 14, 30, 0)
    localized = to_pkt(naive_dt)
    assert localized.hour == 14
    assert localized.minute == 30
    assert localized.utcoffset().total_seconds() == 5 * 3600

    # Test format_pkt
    formatted = format_pkt(utc_dt, "%Y-%m-%d %H:%M %Z")
    assert "15:00" in formatted


def test_assignment_deadlines_with_pkt(app):
    """Verifies assignment active/late evaluation works properly with PKT timestamps."""
    teacher = User(username="prof_pkt", name="Prof. PKT", role="teacher", force_password_change=False)
    teacher.set_password("Teacher@123")
    classroom = Class(name="Intro to CS", code="CS100", teacher=teacher)
    problem = Problem(title="P1", slug="p1", statement="S", created_by_id=1)
    db.session.add_all([teacher, classroom, problem])
    db.session.flush()

    now = now_pkt()
    # Assignment open 1 hour ago, due in 2 hours
    assignment = Assignment(
        class_id=classroom.id,
        problem_id=problem.id,
        title="PKT Assignment",
        open_date=now - timedelta(hours=1),
        due_date=now + timedelta(hours=2),
        allow_late=False,
    )
    db.session.add(assignment)
    db.session.commit()

    assert assignment.is_active() is True
    assert assignment.is_late() is False

    # After deadline
    past_due = now + timedelta(hours=3)
    assert assignment.is_late(past_due) is True


def test_ui_and_notices_display_pkt(client, app):
    """Verifies that templates and notices display timestamps labeled with PKT."""
    teacher = User(username="teacher_pkt", name="Teacher PKT", role="teacher", force_password_change=False)
    teacher.set_password("Teacher@123")
    student = User(username="student_pkt", roll_no="BCSF24M001", name="Student PKT", role="student", force_password_change=False)
    student.set_password("Student@123")
    classroom = Class(name="Algorithms", code="CS202", teacher=teacher)
    problem = Problem(title="Sorting", slug="sorting", statement="Sort array", created_by_id=1)
    db.session.add_all([teacher, student, classroom, problem])
    db.session.flush()

    db.session.add(Enrollment(user_id=student.id, class_id=classroom.id))

    now = now_pkt()
    # Closed assignment
    assignment = Assignment(
        class_id=classroom.id,
        problem_id=problem.id,
        title="Closed HW",
        open_date=now - timedelta(days=5),
        due_date=now - timedelta(days=1),
        allow_late=False,
    )
    db.session.add(assignment)
    db.session.flush()

    sub = Submission(
        user_id=student.id,
        problem_id=problem.id,
        assignment_id=assignment.id,
        language="python",
        source_code="print(1)",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    db.session.add(sub)
    db.session.commit()

    # Login as student
    client.post("/auth/login", data={"username": "student_pkt", "password": "Student@123"}, follow_redirects=True)

    # Check student dashboard headers
    dash_res = client.get("/student/dashboard")
    assert dash_res.status_code == 200
    assert b"Due Date (PKT)" in dash_res.data
    assert b"Submitted (PKT)" in dash_res.data

    # Check student assignments list
    assigns_res = client.get("/student/assignments")
    assert assigns_res.status_code == 200
    assert b"Due Date (PKT)" in assigns_res.data

    # Check student assignment detail
    detail_res = client.get(f"/student/assignments/{assignment.id}")
    assert detail_res.status_code == 200
    assert b"Due Date (PKT)" in detail_res.data

    # Check notice message on problem view
    prob_res = client.get(f"/student/assignments/{assignment.id}/problem")
    assert prob_res.status_code == 200
    assert b"PKT" in prob_res.data
    assert b"This assignment closed on" in prob_res.data

    # Login as teacher
    client.post("/auth/login", data={"username": "teacher_pkt", "password": "Teacher@123"}, follow_redirects=True)

    # Check teacher assignments list
    t_assigns_res = client.get("/teacher/assignments")
    assert t_assigns_res.status_code == 200
    assert b"Open Date (PKT)" in t_assigns_res.data
    assert b"Due Date (PKT)" in t_assigns_res.data

    # Check teacher audit logs
    audit_res = client.get("/teacher/audit-logs")
    assert audit_res.status_code == 200
    assert b"Timestamp (PKT)" in audit_res.data

    # Check CSV export header
    csv_res = client.get(f"/teacher/assignments/{assignment.id}/gradebook.csv")
    assert csv_res.status_code == 200
    assert b"Last Submitted At (PKT)" in csv_res.data
