"""Integration tests for the Teacher UI, Problem CRUD, ZIP test upload, and CSV student import."""
import io
import zipfile
import pytest

from cpjudge.app import create_app
from cpjudge.models import (
    Assignment,
    AuditLog,
    Class,
    Enrollment,
    Problem,
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
    teacher = User(username="prof_turing", name="Alan Turing", role="teacher", force_password_change=False)
    teacher.set_password("Teacher@123")
    db.session.add(teacher)
    db.session.commit()
    return teacher


@pytest.fixture
def student_user(app):
    student = User(username="bcsf20m001", roll_no="BCSF20M001", name="Alice", role="student", force_password_change=False)
    student.set_password("Student@123")
    db.session.add(student)
    db.session.commit()
    return student


def test_teacher_dashboard_access(client, teacher_user, student_user):
    # Student receives 403
    client.post("/auth/login", data={"username": "bcsf20m001", "password": "Student@123"})
    resp_student = client.get("/teacher/dashboard")
    assert resp_student.status_code == 403

    client.post("/auth/logout")

    # Teacher receives 200
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})
    resp_teacher = client.get("/teacher/dashboard")
    assert resp_teacher.status_code == 200
    assert b"Instructor Dashboard" in resp_teacher.data


def test_teacher_cannot_access_another_teachers_resources(client, teacher_user):
    other_teacher = User(
        username="other_prof",
        name="Other Professor",
        role="teacher",
        force_password_change=False,
    )
    other_teacher.set_password("Other@123")
    db.session.add(other_teacher)
    db.session.commit()

    classroom = Class(code="OTHER-101", name="Other Class", teacher_id=other_teacher.id)
    problem = Problem(
        title="Other Problem",
        slug="other-problem",
        statement="Statement",
        created_by_id=other_teacher.id,
    )
    db.session.add_all([classroom, problem])
    db.session.commit()

    assignment = Assignment(
        class_id=classroom.id,
        problem_id=problem.id,
        title="Other Assignment",
        open_date=utc_now(),
        due_date=utc_now(),
    )
    db.session.add(assignment)
    db.session.flush()
    submission = Submission(
        user_id=teacher_user.id,
        problem_id=problem.id,
        assignment_id=assignment.id,
        language="python",
        source_code="print(1)",
        status="queued",
        tests_version=1,
    )
    db.session.add(submission)
    db.session.commit()

    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})

    forbidden_gets = [
        f"/teacher/classes/{classroom.id}",
        f"/teacher/classes/{classroom.id}/edit",
        f"/teacher/classes/{classroom.id}/gradebook",
        f"/teacher/classes/{classroom.id}/gradebook.csv",
        f"/teacher/classes/{classroom.id}/import-students",
        f"/teacher/assignments/{assignment.id}/edit",
        f"/teacher/assignments/{assignment.id}/gradebook",
        f"/teacher/assignments/{assignment.id}/gradebook.csv",
        f"/teacher/problems/{problem.id}/edit",
        f"/teacher/problems/{problem.id}/tests",
        f"/teacher/submissions/{submission.id}",
    ]
    for path in forbidden_gets:
        assert client.get(path).status_code == 404

    forbidden_posts = [
        f"/teacher/classes/{classroom.id}/delete",
        f"/teacher/assignments/{assignment.id}/delete",
        f"/teacher/assignments/{assignment.id}/rejudge-all",
        f"/teacher/problems/{problem.id}/delete",
        f"/teacher/problems/{problem.id}/rejudge-all",
        f"/teacher/submissions/{submission.id}/rejudge",
    ]
    for path in forbidden_posts:
        assert client.post(path).status_code == 404

    assert db.session.get(Class, classroom.id) is not None
    assert db.session.get(Assignment, assignment.id) is not None
    assert db.session.get(Problem, problem.id) is not None
    assert db.session.get(Submission, submission.id).status == "queued"


def test_problem_crud(client, teacher_user):
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})

    # 1. Create Problem
    resp_create = client.post(
        "/teacher/problems/new",
        data={
            "title": "Reverse Array",
            "slug": "reverse-array",
            "statement": "# Reverse Array\n\nGiven an array, print it in reverse.",
            "time_limit": 1.5,
            "memory_limit": 128,
            "output_limit_mb": 5,
            "checker_type": "token",
            "scoring_mode": "per_test",
        },
        follow_redirects=True,
    )
    assert resp_create.status_code == 200
    problem = Problem.query.filter_by(slug="reverse-array").first()
    assert problem is not None
    assert problem.title == "Reverse Array"
    assert problem.time_limit == 1.5
    assert problem.memory_limit == 128
    assert problem.tests_version == 1

    # Verify AuditLog created
    log = AuditLog.query.filter_by(action="create_problem").first()
    assert log is not None
    assert log.target_id == str(problem.id)

    # 2. Edit Problem
    resp_edit = client.post(
        f"/teacher/problems/{problem.id}/edit",
        data={
            "title": "Reverse Array (Updated)",
            "slug": "reverse-array",
            "statement": "Updated statement",
            "time_limit": 2.0,
            "memory_limit": 256,
            "output_limit_mb": 10,
            "checker_type": "exact",
            "scoring_mode": "all_or_nothing",
        },
        follow_redirects=True,
    )
    assert resp_edit.status_code == 200
    db.session.refresh(problem)
    assert problem.title == "Reverse Array (Updated)"
    assert problem.checker_type == "exact"
    assert problem.scoring_mode == "all_or_nothing"

    # 3. Delete Problem
    resp_del = client.post(f"/teacher/problems/{problem.id}/delete", follow_redirects=True)
    assert resp_del.status_code == 200
    assert Problem.query.filter_by(slug="reverse-array").first() is None


def test_manual_test_cases_and_version_bumping(client, teacher_user):
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})

    problem = Problem(
        title="P1",
        slug="p1",
        statement="S",
        created_by_id=teacher_user.id,
        tests_version=1,
    )
    db.session.add(problem)
    db.session.commit()

    # Add single test
    resp_add = client.post(
        f"/teacher/problems/{problem.id}/tests",
        data={
            "order_num": 1,
            "input_data": "1 2\n",
            "expected_output": "3\n",
            "marks": 25.0,
            "is_hidden": "y",
            "explanation": "Hidden sample",
        },
        follow_redirects=True,
    )
    assert resp_add.status_code == 200
    db.session.refresh(problem)
    assert len(problem.tests) == 1
    assert problem.tests_version == 2  # Incremented!

    t = problem.tests[0]
    assert t.marks == 25.0
    assert t.is_hidden is True

    # Edit test
    resp_edit = client.post(
        f"/teacher/problems/{problem.id}/tests/{t.id}/edit",
        data={
            "order_num": 1,
            "input_data": "1 2\n",
            "expected_output": "3\n",
            "marks": 30.0,
            "is_hidden": "",
        },
        follow_redirects=True,
    )
    assert resp_edit.status_code == 200
    db.session.refresh(problem)
    db.session.refresh(t)
    assert t.marks == 30.0
    assert t.is_hidden is False
    assert problem.tests_version == 3  # Incremented again!

    # Delete test
    resp_del = client.post(f"/teacher/problems/{problem.id}/tests/{t.id}/delete", follow_redirects=True)
    assert resp_del.status_code == 200
    db.session.refresh(problem)
    assert len(problem.tests) == 0
    assert problem.tests_version == 4  # Incremented on delete!


def test_zip_test_upload(client, teacher_user):
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})

    problem = Problem(
        title="Zip Problem",
        slug="zip-prob",
        statement="S",
        created_by_id=teacher_user.id,
        tests_version=1,
    )
    db.session.add(problem)
    db.session.commit()

    # Create an in-memory zip file containing test pairs
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("1.in", "10 20\n")
        zf.writestr("1.ans", "30\n")
        zf.writestr("2.in", "5 5\n")
        zf.writestr("2.out", "10\n")
        zf.writestr("3_hidden.in", "0 0\n")
        zf.writestr("3_hidden.ans", "0\n")
    zip_buffer.seek(0)

    # Post ZIP upload
    resp = client.post(
        f"/teacher/problems/{problem.id}/tests/upload-zip",
        data={
            "zip_file": (zip_buffer, "tests.zip"),
            "default_marks": 20.0,
            "visibility_mode": "auto",
            "overwrite": "y",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(problem)
    assert len(problem.tests) == 3
    assert problem.tests_version == 2

    # Check that 3_hidden is marked hidden
    t_hidden = next(t for t in problem.tests if "hidden" in (t.explanation or ""))
    assert t_hidden.is_hidden is True
    assert t_hidden.marks == 20.0


@pytest.mark.parametrize(
    ("entry_count", "member_bytes", "expected_message"),
    [
        (1, 9 * 1024 * 1024, b"must not exceed 8 MB each"),
        (9, 8 * 1024 * 1024, b"expands beyond the 64 MB limit"),
    ],
)
def test_zip_upload_rejects_oversized_uncompressed_entries(
    client, teacher_user, entry_count, member_bytes, expected_message
):
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})

    problem = Problem(
        title="Large Zip Problem",
        slug="large-zip-problem",
        statement="S",
        created_by_id=teacher_user.id,
    )
    db.session.add(problem)
    db.session.commit()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for index in range(entry_count):
            zf.writestr(f"large_{index}.in", "0" * member_bytes)
    zip_buffer.seek(0)

    response = client.post(
        f"/teacher/problems/{problem.id}/tests/upload-zip",
        data={
            "zip_file": (zip_buffer, "large-tests.zip"),
            "default_marks": 1.0,
            "visibility_mode": "auto",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert expected_message in response.data
    assert Test.query.filter_by(problem_id=problem.id).count() == 0


def test_class_crud(client, teacher_user):
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})

    # 1. Create Class
    resp_create = client.post(
        "/teacher/classes/new",
        data={
            "name": "Data Structures Lab",
            "code": "CS201-SP25",
            "description": "Lab section for CS201",
        },
        follow_redirects=True,
    )
    assert resp_create.status_code == 200
    c = Class.query.filter_by(code="CS201-SP25").first()
    assert c is not None
    assert c.name == "Data Structures Lab"

    # 2. View Class Detail
    resp_detail = client.get(f"/teacher/classes/{c.id}")
    assert resp_detail.status_code == 200
    assert b"Data Structures Lab" in resp_detail.data

    # 3. Edit Class
    resp_edit = client.post(
        f"/teacher/classes/{c.id}/edit",
        data={
            "name": "Data Structures Lab (Honors)",
            "code": "CS201-SP25",
            "description": "Updated",
        },
        follow_redirects=True,
    )
    assert resp_edit.status_code == 200
    db.session.refresh(c)
    assert c.name == "Data Structures Lab (Honors)"

    # 4. Delete Class
    resp_del = client.post(f"/teacher/classes/{c.id}/delete", follow_redirects=True)
    assert resp_del.status_code == 200
    assert Class.query.filter_by(code="CS201-SP25").first() is None


def test_csv_student_bulk_import(client, teacher_user):
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})

    classroom = Class(name="Intro to CS", code="CS100", teacher_id=teacher_user.id)
    db.session.add(classroom)
    db.session.commit()

    csv_data = """roll_no,name
BCSF21M010,David Miller
BCSF21M020,Emma Watson
"""
    resp = client.post(
        f"/teacher/classes/{classroom.id}/import-students",
        data={"csv_text": csv_data},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"David Miller" in resp.data
    assert b"Emma Watson" in resp.data

    # Verify student accounts were created in DB with force_password_change = True
    david = User.query.filter_by(roll_no="BCSF21M010").first()
    assert david is not None
    assert david.name == "David Miller"
    assert david.force_password_change is True
    assert david.is_student is True

    emma = User.query.filter_by(roll_no="BCSF21M020").first()
    assert emma is not None
    assert emma.force_password_change is True

    # Verify both are enrolled in CS100
    assert Enrollment.query.filter_by(user_id=david.id, class_id=classroom.id).first() is not None
    assert Enrollment.query.filter_by(user_id=emma.id, class_id=classroom.id).first() is not None


def test_assignment_crud(client, teacher_user):
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})

    classroom = Class(name="Class A", code="CA", teacher_id=teacher_user.id)
    problem = Problem(title="Prob A", slug="prob-a", statement="S", created_by_id=teacher_user.id)
    db.session.add_all([classroom, problem])
    db.session.commit()

    # 1. Create Assignment
    resp_create = client.post(
        "/teacher/assignments/new",
        data={
            "class_id": classroom.id,
            "problem_id": problem.id,
            "title": "Assignment 01",
            "open_date": "2026-11-01 10:00:00",
            "due_date": "2026-11-10 23:59:59",
            "max_attempts": 3,
            "late_penalty_percent": 15.0,
            "allow_late": "y",
        },
        follow_redirects=True,
    )
    assert resp_create.status_code == 200
    assign = Assignment.query.filter_by(class_id=classroom.id, problem_id=problem.id).first()
    assert assign is not None
    assert assign.title == "Assignment 01"
    assert assign.max_attempts == 3
    assert assign.late_penalty_percent == 15.0

    # 2. Delete Assignment
    resp_del = client.post(f"/teacher/assignments/{assign.id}/delete", follow_redirects=True)
    assert resp_del.status_code == 200
    assert Assignment.query.filter_by(id=assign.id).first() is None


def test_teacher_submissions_and_rejudge(client, teacher_user, student_user):
    problem = Problem(title="P", slug="p", statement="S", created_by_id=teacher_user.id)
    db.session.add(problem)
    db.session.commit()

    t = Test(problem_id=problem.id, order_num=1, input_data="in\n", expected_output="out\n", marks=10.0, is_hidden=True)
    db.session.add(t)

    sub = Submission(
        user_id=student_user.id,
        problem_id=problem.id,
        language="cpp",
        source_code="int main() { return 0; }",
        status="done",
        verdict="AC",
        tests_version=1,
    )
    db.session.add(sub)
    db.session.commit()

    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})

    # View Submissions list
    resp_list = client.get("/teacher/submissions")
    assert resp_list.status_code == 200
    assert b"Alice" in resp_list.data

    # View Submission Detail (Teacher view)
    resp_detail = client.get(f"/teacher/submissions/{sub.id}")
    assert resp_detail.status_code == 200
    assert b"int main() { return 0; }" in resp_detail.data

    # Rejudge single submission
    resp_rejudge = client.post(f"/teacher/submissions/{sub.id}/rejudge", follow_redirects=True)
    assert resp_rejudge.status_code == 200
    db.session.refresh(sub)
    assert sub.status == "queued"
    assert sub.verdict is None

    # Rejudge all submissions of problem
    resp_rejudge_all = client.post(f"/teacher/problems/{problem.id}/rejudge-all", follow_redirects=True)
    assert resp_rejudge_all.status_code == 200
    db.session.refresh(sub)
    assert sub.status == "queued"


def test_audit_logs_view(client, teacher_user):
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"})
    AuditLog.log(action="test_action", user_id=teacher_user.id, details="Test details")
    db.session.commit()

    resp = client.get("/teacher/audit-logs")
    assert resp.status_code == 200
    assert b"test_action" in resp.data
    assert b"Test details" in resp.data
