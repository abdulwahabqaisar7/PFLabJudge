"""Unit and integration tests for authentication, roles, and ownership checks."""
import pytest
from flask import url_for
from flask_login import current_user

from cpjudge.app import create_app
from cpjudge.auth.decorators import ensure_submission_access, student_required, teacher_required
from cpjudge.config import ProductionConfig
from cpjudge.models import Problem, Submission, User, db
from seed import seed_database


def test_production_requires_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY must be configured"):
        create_app("production")


def test_production_rejects_disabled_sandbox(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setattr(ProductionConfig, "USE_BWRAP", False)
    with pytest.raises(RuntimeError, match="USE_BWRAP must remain enabled"):
        create_app("production")


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()

        # Add dummy test routes protected by our decorators
        @app.route("/test-teacher-only")
        @teacher_required
        def teacher_only():
            return "Teacher Secret Data", 200

        @app.route("/test-student-only")
        @student_required
        def student_only():
            return "Student Secret Data", 200

        @app.route("/test-submission/<int:sub_id>")
        def view_submission(sub_id):
            sub = db.session.get(Submission, sub_id)
            ensure_submission_access(sub)
            return f"Submission {sub.id} Source: {sub.source_code}", 200

        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_users(app):
    """Creates teacher, student1, and student2 (force_change)."""
    teacher = User(username="teacher", name="Prof. Turing", role="teacher", force_password_change=False)
    teacher.set_password("Teacher@123")

    student1 = User(
        username="bcsf20m001",
        roll_no="BCSF20M001",
        name="Alice",
        role="student",
        force_password_change=False,
    )
    student1.set_password("Student@123")

    student2 = User(
        username="bcsf20m002",
        roll_no="BCSF20M002",
        name="Bob",
        role="student",
        force_password_change=False,
    )
    student2.set_password("Student@123")

    student_force = User(
        username="bcsf20m003",
        roll_no="BCSF20M003",
        name="Charlie",
        role="student",
        force_password_change=True,
    )
    student_force.set_password("Student@123")

    db.session.add_all([teacher, student1, student2, student_force])
    db.session.commit()

    return {
        "teacher": teacher,
        "student1": student1,
        "student2": student2,
        "student_force": student_force,
    }


def test_login_success_username(client, seeded_users):
    resp = client.post(
        "/auth/login",
        data={"username": "teacher", "password": "Teacher@123"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Prof. Turing" in resp.data
    assert b"Teacher" in resp.data


def test_login_rejects_external_next_url(client, seeded_users):
    response = client.post(
        "/auth/login?next=//attacker.example",
        data={"username": "teacher", "password": "Teacher@123"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/teacher/dashboard")


def test_login_success_roll_no(client, seeded_users):
    resp = client.post(
        "/auth/login",
        data={"username": "BCSF20M001", "password": "Student@123"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Alice" in resp.data
    assert b"Student" in resp.data


def test_login_invalid_password(client, seeded_users):
    resp = client.post(
        "/auth/login",
        data={"username": "teacher", "password": "WrongPassword!"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


def test_login_nonexistent_user(client, seeded_users):
    resp = client.post(
        "/auth/login",
        data={"username": "nobody_here", "password": "AnyPassword"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


def test_logout(client, seeded_users):
    # Log in first
    client.post("/auth/login", data={"username": "teacher", "password": "Teacher@123"})

    # Log out
    resp = client.post("/auth/logout", follow_redirects=True)
    assert resp.status_code == 200
    assert b"signed out successfully" in resp.data

    # Profile should now redirect to login
    resp_prof = client.get("/auth/profile")
    assert resp_prof.status_code == 302
    assert "/auth/login" in resp_prof.location


def test_force_password_change_redirection(client, seeded_users):
    # Log in as Charlie who has force_password_change=True
    resp = client.post(
        "/auth/login",
        data={"username": "bcsf20m003", "password": "Student@123"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Update Account Password" in resp.data
    assert b"Password Change Required" in resp.data

    # Attempt to access profile -> should redirect back to change-password
    resp_profile = client.get("/auth/profile", follow_redirects=False)
    assert resp_profile.status_code == 302
    assert "/auth/change-password" in resp_profile.location


def test_password_change_flow(client, seeded_users):
    # Log in as Charlie
    client.post("/auth/login", data={"username": "bcsf20m003", "password": "Student@123"})

    # Change password with wrong current password
    resp_bad = client.post(
        "/auth/change-password",
        data={"current_password": "WrongOldPassword", "new_password": "NewSecret123!", "confirm_password": "NewSecret123!"},
        follow_redirects=True,
    )
    assert b"Current password is incorrect" in resp_bad.data

    # Change password with mismatched passwords
    resp_mismatch = client.post(
        "/auth/change-password",
        data={"current_password": "Student@123", "new_password": "NewSecret123!", "confirm_password": "DifferentPassword!"},
        follow_redirects=True,
    )
    assert b"Passwords do not match" in resp_mismatch.data

    # Successful password change
    resp_ok = client.post(
        "/auth/change-password",
        data={"current_password": "Student@123", "new_password": "NewSecret123!", "confirm_password": "NewSecret123!"},
        follow_redirects=True,
    )
    assert resp_ok.status_code == 200
    assert b"password has been changed successfully" in resp_ok.data

    # Check user record in DB: force_password_change should now be False
    charlie = User.query.filter_by(username="bcsf20m003").first()
    assert charlie.force_password_change is False
    assert charlie.check_password("NewSecret123!") is True

    # Accessing profile is now allowed
    resp_profile = client.get("/auth/profile")
    assert resp_profile.status_code == 200
    assert b"Charlie" in resp_profile.data


def test_role_authorization_teacher_required(client, seeded_users):
    # Anonymous: redirect to login
    resp_anon = client.get("/test-teacher-only")
    assert resp_anon.status_code == 302
    assert "/auth/login" in resp_anon.location

    # Student: 403 Forbidden
    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    resp_student = client.get("/test-teacher-only")
    assert resp_student.status_code == 403
    assert b"403" in resp_student.data
    assert b"Teacher privileges required" in resp_student.data

    # Log out student
    client.post("/auth/logout")

    # Teacher: 200 OK
    client.post("/auth/login", data={"username": "teacher", "password": "Teacher@123"})
    resp_teacher = client.get("/test-teacher-only")
    assert resp_teacher.status_code == 200
    assert b"Teacher Secret Data" in resp_teacher.data


def test_role_authorization_student_required(client, seeded_users):
    # Anonymous: redirect to login
    resp_anon = client.get("/test-student-only")
    assert resp_anon.status_code == 302

    # Teacher: 403 Forbidden
    client.post("/auth/login", data={"username": "teacher", "password": "Teacher@123"})
    resp_teacher = client.get("/test-student-only")
    assert resp_teacher.status_code == 403
    assert b"Student privileges required" in resp_teacher.data

    # Log out teacher
    client.post("/auth/logout")

    # Student: 200 OK
    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    resp_student = client.get("/test-student-only")
    assert resp_student.status_code == 200
    assert b"Student Secret Data" in resp_student.data


def test_submission_ownership_enforcement(client, seeded_users):
    student1 = seeded_users["student1"]
    student2 = seeded_users["student2"]
    teacher = seeded_users["teacher"]

    problem = Problem(title="P", slug="p", statement="S", created_by_id=teacher.id)
    db.session.add(problem)
    db.session.commit()

    # Submission owned by Student 1 (Alice)
    sub1 = Submission(
        user_id=student1.id,
        problem_id=problem.id,
        language="cpp",
        source_code="// Alice's secret solution",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    db.session.add(sub1)
    db.session.commit()

    # Case 1: Student 1 (Alice) accesses her own submission -> Allowed (200)
    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    resp_alice = client.get(f"/test-submission/{sub1.id}")
    assert resp_alice.status_code == 200
    assert b"Alice's secret solution" in resp_alice.data

    # Log out Alice
    client.post("/auth/logout")

    # Case 2: Student 2 (Bob) tries to access Alice's submission -> FORBIDDEN (403)
    client.post("/auth/login", data={"username": "bcsf20m002", "password": "Student@123"})
    resp_bob = client.get(f"/test-submission/{sub1.id}")
    assert resp_bob.status_code == 403
    assert b"Access denied: You do not own this submission" in resp_bob.data

    # Log out Bob
    client.post("/auth/logout")

    # Case 3: Teacher accesses Alice's submission -> Allowed (200)
    client.post("/auth/login", data={"username": "teacher", "password": "Teacher@123"})
    resp_teacher = client.get(f"/test-submission/{sub1.id}")
    assert resp_teacher.status_code == 200
    assert b"Alice's secret solution" in resp_teacher.data
