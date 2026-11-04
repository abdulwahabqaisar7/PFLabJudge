"""Integration tests for the Student UI: dashboard, assignments, problem solving,
source submission (text & file upload), 64KB limits, attempt limits,
masked hidden tests privacy, live status polling, and submission history."""
import io
from datetime import datetime, timedelta, timezone
import pytest

from cpjudge.app import create_app
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
def teacher_user(app):
    teacher = User(username="prof_knuth", name="Donald Knuth", role="teacher", force_password_change=False)
    teacher.set_password("Teacher@123")
    db.session.add(teacher)
    db.session.commit()
    return teacher


@pytest.fixture
def student1(app):
    student = User(username="bcsf20m001", roll_no="BCSF20M001", name="Alice", role="student", force_password_change=False)
    student.set_password("Student@123")
    db.session.add(student)
    db.session.commit()
    return student


@pytest.fixture
def student2(app):
    student = User(username="bcsf20m002", roll_no="BCSF20M002", name="Bob", role="student", force_password_change=False)
    student.set_password("Student@123")
    db.session.add(student)
    db.session.commit()
    return student


@pytest.fixture
def test_setup(app, teacher_user, student1, student2):
    """Sets up a class, enrollment for student1 only, problem with visible & hidden tests, and an assignment."""
    now = utc_now()
    cls = Class(code="CS101", name="Intro to CS", teacher_id=teacher_user.id)
    db.session.add(cls)
    db.session.commit()

    # Enroll only Alice in CS101
    enrollment = Enrollment(user_id=student1.id, class_id=cls.id)
    db.session.add(enrollment)

    # Problem: Sum of Two Numbers
    problem = Problem(
        title="Sum of Two Numbers",
        slug="sum-of-two-numbers",
        statement="Given two integers $A$ and $B$, compute $A + B$.\n\n### Constraints\n$1 \\le A, B \\le 1000$",
        time_limit=1.0,
        memory_limit=128,
        created_by_id=teacher_user.id,
    )
    db.session.add(problem)
    db.session.commit()

    # Tests: 1 visible sample, 1 hidden secret test
    t1 = Test(
        problem_id=problem.id,
        order_num=1,
        input_data="3 5\n",
        expected_output="8\n",
        is_hidden=False,
        marks=50,
    )
    t2 = Test(
        problem_id=problem.id,
        order_num=2,
        input_data="100 200\n",
        expected_output="300\n",
        is_hidden=True,
        marks=50,
    )
    db.session.add_all([t1, t2])

    # Assignment
    assignment = Assignment(
        class_id=cls.id,
        problem_id=problem.id,
        title="Assignment 01 - Basics",
        open_date=now - timedelta(days=1),
        due_date=now + timedelta(days=7),
        allow_late=True,
        late_penalty_percent=10,
        max_attempts=3,
    )
    db.session.add(assignment)
    db.session.commit()

    return {
        "class": cls,
        "problem": problem,
        "test_visible": t1,
        "test_hidden": t2,
        "assignment": assignment,
    }


# ==============================================================================
# ACCESS CONTROL TESTS
# ==============================================================================

def test_student_routes_require_student_role(client, teacher_user, student1):
    # Unauthenticated user redirected to login
    resp = client.get("/student/dashboard")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]

    # Teacher user gets 403 Forbidden
    client.post("/auth/login", data={"username": "prof_knuth", "password": "Teacher@123"})
    resp = client.get("/student/dashboard")
    assert resp.status_code == 403

    resp = client.get("/student/assignments")
    assert resp.status_code == 403

    client.post("/auth/logout")

    # Student user gets 200 OK
    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    resp = client.get("/student/dashboard")
    assert resp.status_code == 200


# ==============================================================================
# DASHBOARD & ASSIGNMENTS LIST TESTS
# ==============================================================================

def test_student_dashboard_and_assignments(client, student1, student2, test_setup):
    # Alice is enrolled, Bob is not
    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})

    resp = client.get("/student/dashboard")
    assert resp.status_code == 200
    assert b"CS101" in resp.data
    assert b"Assignment 01 - Basics" in resp.data

    resp = client.get("/student/assignments")
    assert resp.status_code == 200
    assert b"Assignment 01 - Basics" in resp.data
    assert b"/ 3 max" in resp.data

    client.post("/auth/logout")

    # Bob is not enrolled in CS101, so he sees no assignments
    client.post("/auth/login", data={"username": "bcsf20m002", "password": "Student@123"})
    resp = client.get("/student/assignments")
    assert resp.status_code == 200
    assert b"Assignment 01 - Basics" not in resp.data


def test_assignment_best_verdict_matches_best_scoring_submission(
    client, student1, test_setup
):
    assignment = test_setup["assignment"]
    problem = test_setup["problem"]
    accepted = Submission(
        user_id=student1.id,
        problem_id=problem.id,
        assignment_id=assignment.id,
        language="cpp",
        source_code="accepted",
        status="done",
        verdict="AC",
        tests_version=problem.tests_version,
        created_at=utc_now() - timedelta(minutes=1),
    )
    later_wrong_answer = Submission(
        user_id=student1.id,
        problem_id=problem.id,
        assignment_id=assignment.id,
        language="cpp",
        source_code="wrong answer",
        status="done",
        verdict="WA",
        tests_version=problem.tests_version,
        created_at=utc_now(),
    )
    db.session.add_all([accepted, later_wrong_answer])
    db.session.flush()
    db.session.add_all([
        Score(
            submission_id=accepted.id,
            assignment_id=assignment.id,
            user_id=student1.id,
            problem_id=problem.id,
            raw_score=100,
            final_score=100,
            max_possible_score=100,
        ),
        Score(
            submission_id=later_wrong_answer.id,
            assignment_id=assignment.id,
            user_id=student1.id,
            problem_id=problem.id,
            raw_score=0,
            final_score=0,
            max_possible_score=100,
        ),
    ])
    db.session.commit()

    client.post(
        "/auth/login",
        data={"username": "bcsf20m001", "password": "Student@123"},
    )

    detail = client.get(f"/student/assignments/{assignment.id}")
    assert detail.status_code == 200
    assert b"Best Verdict" in detail.data
    assert b">AC</span>" in detail.data
    assert b">WA</span>" not in detail.data

    assignments = client.get("/student/assignments")
    assert assignments.status_code == 200
    assert b">AC</span>" in assignments.data
    assert b">WA</span>" not in assignments.data


# ==============================================================================
# PROBLEM STATEMENT & ENROLLMENT PERMISSIONS
# ==============================================================================

def test_problem_statement_and_permissions(client, student1, student2, test_setup):
    assignment_id = test_setup["assignment"].id

    # Bob tries to access Assignment 01 for a class he is not enrolled in -> 403
    client.post("/auth/login", data={"username": "bcsf20m002", "password": "Student@123"})
    resp = client.get(f"/student/assignments/{assignment_id}/problem")
    assert resp.status_code == 403
    client.post("/auth/logout")

    # Alice accesses the problem -> 200 OK
    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    resp = client.get(f"/student/assignments/{assignment_id}/problem")
    assert resp.status_code == 200
    # Problem statement with rendered Markdown
    assert b"Sum of Two Numbers" in resp.data
    assert b"Constraints" in resp.data
    # Visible sample test is displayed
    assert b"3 5" in resp.data
    assert b"8" in resp.data
    # Hidden test is NOT displayed
    assert b"100 200" not in resp.data
    assert b"300" not in resp.data


# ==============================================================================
# SUBMISSION: TEXTAREA & FILE UPLOAD & 64KB LIMIT
# ==============================================================================

def test_submission_via_textarea(client, student1, test_setup):
    assignment_id = test_setup["assignment"].id
    problem = test_setup["problem"]

    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})

    code = "#include <iostream>\nint main() { int a, b; std::cin >> a >> b; std::cout << a + b << std::endl; return 0; }"
    resp = client.post(
        f"/student/assignments/{assignment_id}/problem",
        data={
            "language": "cpp",
            "source_code": code,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"queued for evaluation" in resp.data

    sub = Submission.query.filter_by(user_id=student1.id).first()
    assert sub is not None
    assert sub.language == "cpp"
    assert sub.status == "queued"
    assert sub.tests_version == problem.tests_version
    assert not sub.is_late


def test_submission_via_file_upload(client, student1, test_setup):
    assignment_id = test_setup["assignment"].id

    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})

    py_code = b"a, b = map(int, input().split())\nprint(a + b)\n"
    data = {
        "language": "cpp",  # upload .py should auto-detect as python
        "code_file": (io.BytesIO(py_code), "solution.py"),
    }
    resp = client.post(
        f"/student/assignments/{assignment_id}/problem",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200

    sub = Submission.query.filter_by(user_id=student1.id).order_by(Submission.id.desc()).first()
    assert sub is not None
    assert sub.language == "python"
    assert "map(int, input().split())" in sub.source_code


def test_submission_size_limit_64kb(client, student1, test_setup):
    assignment_id = test_setup["assignment"].id
    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})

    # Large text submission > 64 KB
    huge_code = "// comment\n" * 6000  # ~66 KB
    assert len(huge_code.encode("utf-8")) > 64 * 1024

    resp = client.post(
        f"/student/assignments/{assignment_id}/problem",
        data={
            "language": "cpp",
            "source_code": huge_code,
        },
        follow_redirects=True,
    )
    assert resp.status_code in (413, 200)
    if resp.status_code == 200:
        assert b"exceeds the 64 KB size limit" in resp.data


# ==============================================================================
# ATTEMPT LIMITS & TIMING CONSTRAINTS
# ==============================================================================

def test_submission_attempt_limit_enforced(client, student1, test_setup):
    assignment = test_setup["assignment"]
    assignment_id = assignment.id

    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})

    # Max attempts is 3 in test_setup fixture. Create 3 submissions directly.
    for i in range(3):
        sub = Submission(
            user_id=student1.id,
            problem_id=test_setup["problem"].id,
            assignment_id=assignment_id,
            language="cpp",
            source_code=f"// attempt {i}",
            status="done",
            tests_version=1,
        )
        db.session.add(sub)
    db.session.commit()

    # Now attempt 4 should be blocked
    resp = client.get(f"/student/assignments/{assignment_id}/problem")
    assert resp.status_code == 200
    assert b"reached the maximum allowed attempts" in resp.data

    # POST should also be blocked
    resp = client.post(
        f"/student/assignments/{assignment_id}/problem",
        data={"language": "cpp", "source_code": "int main() {}"},
        follow_redirects=True,
    )
    assert Submission.query.filter_by(user_id=student1.id).count() == 3


def test_assignment_not_open_yet(client, student1, test_setup):
    assignment = test_setup["assignment"]
    assignment.open_date = utc_now() + timedelta(days=2)
    db.session.commit()

    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    resp = client.get(f"/student/assignments/{assignment.id}/problem")
    assert resp.status_code == 200
    assert b"This assignment opens on" in resp.data
    assert b"Submissions Disabled" in resp.data


def test_assignment_closed_no_late(client, student1, test_setup):
    assignment = test_setup["assignment"]
    assignment.open_date = utc_now() - timedelta(days=5)
    assignment.due_date = utc_now() - timedelta(days=1)
    assignment.allow_late = False
    db.session.commit()

    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    resp = client.get(f"/student/assignments/{assignment.id}/problem")
    assert resp.status_code == 200
    assert b"Late submissions are not accepted" in resp.data
    assert b"Submissions Disabled" in resp.data


# ==============================================================================
# SUBMISSION DETAIL & HIDDEN TEST PRIVACY
# ==============================================================================

def test_submission_detail_and_hidden_test_privacy(client, student1, student2, test_setup):
    problem = test_setup["problem"]
    t_vis = test_setup["test_visible"]
    t_hid = test_setup["test_hidden"]

    # Create evaluated submission with Result and Score objects
    sub = Submission(
        user_id=student1.id,
        problem_id=problem.id,
        assignment_id=test_setup["assignment"].id,
        language="cpp",
        source_code="#include <iostream>\nint main() { int a, b; std::cin >> a >> b; std::cout << a + b << std::endl; }",
        status="done",
        verdict="AC",
        max_time=0.015,
        max_memory_kb=1820,
        tests_version=1,
    )
    db.session.add(sub)
    db.session.commit()

    # Results for test 1 (visible) and test 2 (hidden)
    r1 = Result(
        submission_id=sub.id,
        test_id=t_vis.id,
        test_order=1,
        verdict="AC",
        cpu_time=0.010,
        memory_kb=1800,
        marks_awarded=50,
        is_hidden=False,
        student_output="8\n",
    )
    r2 = Result(
        submission_id=sub.id,
        test_id=t_hid.id,
        test_order=2,
        verdict="AC",
        cpu_time=0.015,
        memory_kb=1820,
        marks_awarded=50,
        is_hidden=True,
        student_output=None,
    )
    sc = Score(
        submission_id=sub.id,
        assignment_id=test_setup["assignment"].id,
        user_id=student1.id,
        problem_id=problem.id,
        raw_score=100,
        final_score=100,
        max_possible_score=100,
    )
    db.session.add_all([r1, r2, sc])
    db.session.commit()

    # Bob attempts to view Alice's submission -> 403 Forbidden!
    client.post("/auth/login", data={"username": "bcsf20m002", "password": "Student@123"})
    resp_bob = client.get(f"/student/submissions/{sub.id}")
    assert resp_bob.status_code == 403

    resp_bob_status = client.get(f"/student/submissions/{sub.id}/status")
    assert resp_bob_status.status_code == 403
    client.post("/auth/logout")

    # Alice views her own submission -> 200 OK
    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    resp_alice = client.get(f"/student/submissions/{sub.id}")
    assert resp_alice.status_code == 200

    html = resp_alice.data.decode("utf-8")
    assert "AC (Accepted)" in html
    assert "100" in html  # Score

    # Visible test data should be in HTML
    assert "3 5" in html
    assert "8" in html

    # CRITICAL SECURITY CHECK:
    # Hidden test input ('100 200') and expected output ('300') MUST NEVER be in student's HTML!
    assert "100 200" not in html
    assert "Protected" in html
    assert "Hidden" in html


def test_submission_detail_renders_result_without_related_test(client, student1, test_setup):
    submission = Submission(
        user_id=student1.id,
        problem_id=test_setup["problem"].id,
        assignment_id=test_setup["assignment"].id,
        language="python",
        source_code="print(1)",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    db.session.add(submission)
    db.session.flush()
    db.session.add(
        Result(
            submission_id=submission.id,
            test_id=None,
            test_order=1,
            verdict="AC",
            is_hidden=False,
        )
    )
    db.session.commit()

    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    response = client.get(f"/student/submissions/{submission.id}")
    assert response.status_code == 200
    assert b"Sample" in response.data
    assert b"Test removed" in response.data


# ==============================================================================
# LIVE STATUS POLLING API
# ==============================================================================

def test_submission_status_json_polling(client, student1, test_setup):
    sub = Submission(
        user_id=student1.id,
        problem_id=test_setup["problem"].id,
        assignment_id=test_setup["assignment"].id,
        language="cpp",
        source_code="int main() {}",
        status="judging",
        tests_version=1,
    )
    db.session.add(sub)
    db.session.commit()

    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})

    resp = client.get(f"/student/submissions/{sub.id}/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == sub.id
    assert data["status"] == "judging"
    assert data["is_done"] is False

    # Transition to done
    sub.status = "done"
    sub.verdict = "AC"
    score = Score(
        submission_id=sub.id,
        assignment_id=test_setup["assignment"].id,
        user_id=student1.id,
        problem_id=test_setup["problem"].id,
        raw_score=100,
        final_score=100,
        max_possible_score=100,
    )
    db.session.add(score)
    db.session.commit()

    resp = client.get(f"/student/submissions/{sub.id}/status")
    assert resp.status_code == 200
    data2 = resp.get_json()
    assert data2["status"] == "done"
    assert data2["verdict"] == "AC"
    assert data2["is_done"] is True
    assert data2["final_score"] == 100


# ==============================================================================
# SUBMISSION HISTORY & FILTERS
# ==============================================================================

def test_submission_history_and_filters(client, student1, test_setup):
    problem = test_setup["problem"]
    assignment_id = test_setup["assignment"].id

    sub1 = Submission(
        user_id=student1.id,
        problem_id=problem.id,
        assignment_id=assignment_id,
        language="cpp",
        source_code="// sub1",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    sub2 = Submission(
        user_id=student1.id,
        problem_id=problem.id,
        assignment_id=assignment_id,
        language="python",
        source_code="// sub2",
        status="done",
        verdict="WA",
        tests_version=1,
    )
    db.session.add_all([sub1, sub2])
    db.session.commit()

    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})

    # History shows both submissions
    resp = client.get("/student/history")
    assert resp.status_code == 200
    assert f"#{sub1.id}".encode() in resp.data
    assert f"#{sub2.id}".encode() in resp.data

    # Filter by verdict=AC
    resp_ac = client.get("/student/history?verdict=AC")
    assert resp_ac.status_code == 200
    assert f"#{sub1.id}".encode() in resp_ac.data
    assert f"#{sub2.id}".encode() not in resp_ac.data

    # Filter by verdict=WA
    resp_wa = client.get("/student/history?verdict=WA")
    assert resp_wa.status_code == 200
    assert f"#{sub1.id}".encode() not in resp_wa.data
    assert f"#{sub2.id}".encode() in resp_wa.data
