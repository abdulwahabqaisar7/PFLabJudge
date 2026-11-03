"""Tests for Gradebook (matrix and per-assignment views, CSV exports), Rejudge endpoints, and Audit Logs."""
import csv
import io
from datetime import timedelta
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


@pytest.fixture
def teacher(app):
    t = User(username="prof_hopper", name="Grace Hopper", role="teacher", force_password_change=False)
    t.set_password("Teacher@123")
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture
def students(app):
    s1 = User(username="alice", roll_no="BCSF20M001", name="Alice Wonderland", role="student", force_password_change=False)
    s1.set_password("Student@123")
    s2 = User(username="bob", roll_no="BCSF20M002", name="Bob Builder", role="student", force_password_change=False)
    s2.set_password("Student@123")
    db.session.add_all([s1, s2])
    db.session.commit()
    return [s1, s2]


@pytest.fixture
def test_setup(app, teacher, students):
    """Sets up a class, 2 students enrolled, a problem, and 2 assignments."""
    classroom = Class(name="Data Structures", code="CS201", teacher_id=teacher.id)
    db.session.add(classroom)
    db.session.flush()

    for s in students:
        db.session.add(Enrollment(class_id=classroom.id, user_id=s.id))

    p1 = Problem(
        title="Sum of Two",
        slug="sum-of-two",
        statement="Compute a + b",
        created_by_id=teacher.id,
        tests_version=1,
    )
    p2 = Problem(
        title="Product of Two",
        slug="product-of-two",
        statement="Compute a * b",
        created_by_id=teacher.id,
        tests_version=1,
    )
    db.session.add_all([p1, p2])
    db.session.flush()

    # Add tests to give problems total_marks
    db.session.add(Test(problem_id=p1.id, order_num=1, input_data="1 2", expected_output="3", marks=10.0))
    db.session.add(Test(problem_id=p2.id, order_num=1, input_data="3 4", expected_output="12", marks=20.0))

    now = utc_now()
    a1 = Assignment(
        title="Homework 1",
        class_id=classroom.id,
        problem_id=p1.id,
        open_date=now - timedelta(days=2),
        due_date=now + timedelta(days=2),
        allow_late=True,
        late_penalty_percent=15,
        max_attempts=0,
    )
    a2 = Assignment(
        title="Homework 2",
        class_id=classroom.id,
        problem_id=p2.id,
        open_date=now - timedelta(days=2),
        due_date=now - timedelta(hours=2),  # Past due
        allow_late=True,
        late_penalty_percent=20,
        max_attempts=5,
    )
    db.session.add_all([a1, a2])
    db.session.commit()

    return {
        "classroom": classroom,
        "problem1": p1,
        "problem2": p2,
        "assignment1": a1,
        "assignment2": a2,
    }


def test_class_gradebook_view_and_calculations(client, teacher, students, test_setup):
    """Verifies the HTML matrix gradebook computes student totals and class averages correctly."""
    a1 = test_setup["assignment1"]
    a2 = test_setup["assignment2"]
    p1 = test_setup["problem1"]
    p2 = test_setup["problem2"]
    s1, s2 = students

    # Alice submitted to both assignments
    sub1 = Submission(
        user_id=s1.id,
        problem_id=p1.id,
        assignment_id=a1.id,
        language="cpp",
        source_code="cout << a + b;",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    db.session.add(sub1)
    db.session.flush()
    db.session.add(Score(
        submission_id=sub1.id,
        user_id=s1.id,
        problem_id=p1.id,
        assignment_id=a1.id,
        raw_score=10.0,
        late_penalty_percent=0,
        final_score=10.0,
    ))

    sub2 = Submission(
        user_id=s1.id,
        problem_id=p2.id,
        assignment_id=a2.id,
        language="cpp",
        source_code="cout << a * b;",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    db.session.add(sub2)
    db.session.flush()
    db.session.add(Score(
        submission_id=sub2.id,
        user_id=s1.id,
        problem_id=p2.id,
        assignment_id=a2.id,
        raw_score=20.0,
        late_penalty_percent=20,
        final_score=16.0,  # 20 - 20% = 16.0
    ))

    # Bob only submitted to HW1 with partial/WA
    sub3 = Submission(
        user_id=s2.id,
        problem_id=p1.id,
        assignment_id=a1.id,
        language="cpp",
        source_code="cout << 0;",
        status="done",
        verdict="WA",
        tests_version=1,
    )
    db.session.add(sub3)
    db.session.flush()
    db.session.add(Score(
        submission_id=sub3.id,
        user_id=s2.id,
        problem_id=p1.id,
        assignment_id=a1.id,
        raw_score=0.0,
        late_penalty_percent=0,
        final_score=0.0,
    ))
    db.session.commit()

    # Login teacher
    client.post("/auth/login", data={"username": "prof_hopper", "password": "Teacher@123"})

    resp = client.get(f"/teacher/classes/{test_setup['classroom'].id}/gradebook")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Class Gradebook: Data Structures" in html
    assert "BCSF20M001" in html
    assert "Alice Wonderland" in html
    assert "BCSF20M002" in html
    assert "Bob Builder" in html
    # Alice: 10.0 on HW1, 16.0 on HW2 -> 26.0 / 30.0 = 86.7%
    assert "26.0" in html
    # Bob: 0.0 on HW1, unsubmitted on HW2 -> 0.0 / 30.0 = 0.0%
    assert "0.0" in html


def test_class_gradebook_csv_export_and_audit(client, teacher, students, test_setup):
    """Verifies that downloading class gradebook CSV produces RFC-compliant CSV and an audit log."""
    students[0].name = "=1+1"
    db.session.commit()
    client.post("/auth/login", data={"username": "prof_hopper", "password": "Teacher@123"})

    cid = test_setup["classroom"].id
    resp = client.get(f"/teacher/classes/{cid}/gradebook.csv")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/csv")
    assert "attachment; filename=gradebook_CS201_" in resp.headers["Content-Disposition"]

    csv_text = resp.data.decode("utf-8")
    reader = list(csv.reader(io.StringIO(csv_text)))
    assert len(reader) >= 3  # Header + 2 students

    headers = reader[0]
    assert headers[0] == "Roll No"
    assert headers[1] == "Student Name"
    assert headers[2] == "Username"
    assert "Homework 1 (10.0 pts)" in headers[3]
    assert "Homework 2 (20.0 pts)" in headers[4]
    assert "Total Score" in headers
    assert "Max Score" in headers
    assert "Percentage (%)" in headers
    assert any(row[1] == "'=1+1" for row in reader[1:])

    # Verify audit log recorded
    log = AuditLog.query.filter_by(action="export_gradebook", target_type="class", target_id=cid).first()
    assert log is not None
    assert log.user_id == teacher.id
    assert log.details_dict["class_code"] == "CS201"
    assert log.details_dict["student_count"] == 2


def test_assignment_gradebook_view_and_csv(client, teacher, students, test_setup):
    """Verifies assignment gradebook HTML view, late penalties, and CSV export."""
    a2 = test_setup["assignment2"]
    p2 = test_setup["problem2"]
    s1, s2 = students

    # Alice submitted late with penalty
    sub = Submission(
        user_id=s1.id,
        problem_id=p2.id,
        assignment_id=a2.id,
        language="cpp",
        source_code="cout << a * b;",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    db.session.add(sub)
    db.session.flush()
    db.session.add(Score(
        submission_id=sub.id,
        user_id=s1.id,
        problem_id=p2.id,
        assignment_id=a2.id,
        raw_score=20.0,
        late_penalty_percent=20,
        final_score=16.0,
    ))
    db.session.commit()

    client.post("/auth/login", data={"username": "prof_hopper", "password": "Teacher@123"})

    # HTML view
    resp = client.get(f"/teacher/assignments/{a2.id}/gradebook")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert f"Assignment Gradebook: {a2.title}" in html
    assert "-20%" in html
    assert "16.0" in html
    assert "BCSF20M001" in html
    assert "Unsubmitted" in html  # Bob didn't submit

    # CSV export
    csv_resp = client.get(f"/teacher/assignments/{a2.id}/gradebook.csv")
    assert csv_resp.status_code == 200
    assert csv_resp.content_type.startswith("text/csv")
    assert f"attachment; filename=gradebook_assignment_{a2.id}_" in csv_resp.headers["Content-Disposition"]

    csv_rows = list(csv.reader(io.StringIO(csv_resp.data.decode("utf-8"))))
    header = csv_rows[0]
    assert "Best Raw Score" in header
    assert "Late Penalty (%)" in header
    assert "Final Score" in header
    assert "Verdict" in header

    # Alice row
    alice_row = [r for r in csv_rows if "BCSF20M001" in r][0]
    assert "20.0" in alice_row  # raw score
    assert "20%" in alice_row   # penalty
    assert "16.0" in alice_row  # final score
    assert "AC" in alice_row

    # Bob row
    bob_row = [r for r in csv_rows if "BCSF20M002" in r][0]
    assert "Unsubmitted" in bob_row

    # Check audit log
    log = AuditLog.query.filter_by(action="export_gradebook", target_type="assignment", target_id=a2.id).first()
    assert log is not None
    assert log.user_id == teacher.id


def test_rejudge_assignment_endpoint(client, teacher, students, test_setup):
    """Verifies that rejudging an assignment resets all submissions to 'queued' and marks stale scores."""
    a1 = test_setup["assignment1"]
    p1 = test_setup["problem1"]
    s1, s2 = students

    sub1 = Submission(
        user_id=s1.id,
        problem_id=p1.id,
        assignment_id=a1.id,
        language="cpp",
        source_code="cout << 1;",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    sub2 = Submission(
        user_id=s2.id,
        problem_id=p1.id,
        assignment_id=a1.id,
        language="cpp",
        source_code="cout << 2;",
        status="done",
        verdict="WA",
        tests_version=1,
    )
    db.session.add_all([sub1, sub2])
    db.session.flush()

    score1 = Score(submission_id=sub1.id, user_id=s1.id, problem_id=p1.id, assignment_id=a1.id, raw_score=10.0, final_score=10.0)
    score2 = Score(submission_id=sub2.id, user_id=s2.id, problem_id=p1.id, assignment_id=a1.id, raw_score=0.0, final_score=0.0)
    db.session.add_all([score1, score2])
    db.session.commit()

    client.post("/auth/login", data={"username": "prof_hopper", "password": "Teacher@123"})

    resp = client.post(f"/teacher/assignments/{a1.id}/rejudge-all", follow_redirects=True)
    assert resp.status_code == 200

    # Refresh submissions
    s1_sub = db.session.get(Submission, sub1.id)
    s2_sub = db.session.get(Submission, sub2.id)
    assert s1_sub.status == "queued"
    assert s1_sub.verdict is None
    assert s2_sub.status == "queued"
    assert s2_sub.verdict is None

    # Existing scores remain stale until the worker completes the new evaluation.
    assert s1_sub.score.is_stale is True
    assert s2_sub.score.is_stale is True

    # Check AuditLog
    log = AuditLog.query.filter_by(action="rejudge_assignment", target_id=a1.id).first()
    assert log is not None
    assert log.details_dict["submission_count"] == 2


def test_rejudge_single_and_problem(client, teacher, test_setup):
    """Verifies single submission rejudge and problem-wide rejudge endpoints."""
    p1 = test_setup["problem1"]
    a1 = test_setup["assignment1"]

    sub = Submission(
        user_id=teacher.id,
        problem_id=p1.id,
        assignment_id=a1.id,
        language="python",
        source_code="print('hello')",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    db.session.add(sub)
    db.session.commit()

    client.post("/auth/login", data={"username": "prof_hopper", "password": "Teacher@123"})

    # Single rejudge
    resp = client.post(f"/teacher/submissions/{sub.id}/rejudge", follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(sub)
    assert sub.status == "queued"
    assert sub.verdict is None

    # Problem-wide rejudge
    sub.status = "done"
    sub.verdict = "WA"
    p1.increment_tests_version()
    db.session.commit()

    resp2 = client.post(f"/teacher/problems/{p1.id}/rejudge-all", follow_redirects=True)
    assert resp2.status_code == 200
    db.session.refresh(sub)
    assert sub.status == "queued"
    assert sub.tests_version == 1


def test_audit_log_filtering(client, teacher, test_setup):
    """Verifies that audit log page lists distinct actions and correctly filters by action query param."""
    AuditLog.log(action="create_problem", user_id=teacher.id, details={"title": "P1"})
    AuditLog.log(action="export_gradebook", user_id=teacher.id, details={"class": "CS201"})
    AuditLog.log(action="export_gradebook", user_id=teacher.id, details={"class": "CS202"})
    db.session.commit()

    client.post("/auth/login", data={"username": "prof_hopper", "password": "Teacher@123"})

    # All logs
    resp_all = client.get("/teacher/audit-logs")
    assert resp_all.status_code == 200
    html_all = resp_all.data.decode("utf-8")
    assert "create_problem" in html_all
    assert "export_gradebook" in html_all

    # Filtered logs
    resp_filtered = client.get("/teacher/audit-logs?action=export_gradebook")
    assert resp_filtered.status_code == 200
    html_filtered = resp_filtered.data.decode("utf-8")
    assert "export_gradebook" in html_filtered
    # The table body should not have create_problem
    assert "create_problem" not in html_filtered.split("<tbody>")[1]


def test_gradebook_and_rejudge_authorization(client, students, test_setup):
    """Verifies that students and anonymous users are blocked from teacher gradebook and rejudge endpoints."""
    cid = test_setup["classroom"].id
    aid = test_setup["assignment1"].id

    # Anonymous user gets redirected to login
    assert client.get(f"/teacher/classes/{cid}/gradebook").status_code == 302
    assert client.get(f"/teacher/classes/{cid}/gradebook.csv").status_code == 302
    assert client.get(f"/teacher/assignments/{aid}/gradebook").status_code == 302
    assert client.get(f"/teacher/assignments/{aid}/gradebook.csv").status_code == 302
    assert client.post(f"/teacher/assignments/{aid}/rejudge-all").status_code == 302

    # Student user gets 403 Forbidden
    client.post("/auth/login", data={"username": "alice", "password": "Student@123"})
    assert client.get(f"/teacher/classes/{cid}/gradebook").status_code == 403
    assert client.get(f"/teacher/classes/{cid}/gradebook.csv").status_code == 403
    assert client.get(f"/teacher/assignments/{aid}/gradebook").status_code == 403
    assert client.get(f"/teacher/assignments/{aid}/gradebook.csv").status_code == 403
    assert client.post(f"/teacher/assignments/{aid}/rejudge-all").status_code == 403
