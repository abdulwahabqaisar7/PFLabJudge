"""Tests for multi-problem assignments across models, teacher management, student views, and gradebooks."""
import csv
import io
from datetime import timedelta
import pytest

from cpjudge.app import create_app
from cpjudge.models import (
    Assignment,
    AssignmentProblem,
    Class,
    Enrollment,
    Problem,
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
    t = User(username="prof_turing", name="Alan Turing", role="teacher", force_password_change=False)
    t.set_password("Teacher@123")
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture
def students(app):
    s1 = User(username="alice", roll_no="BCSF20M001", name="Alice Liddell", role="student", force_password_change=False)
    s1.set_password("Student@123")
    s2 = User(username="bob", roll_no="BCSF20M002", name="Bob Builder", role="student", force_password_change=False)
    s2.set_password("Student@123")
    db.session.add_all([s1, s2])
    db.session.commit()
    return [s1, s2]


@pytest.fixture
def test_setup(app, teacher, students):
    classroom = Class(name="Algorithms 101", code="CS201", teacher_id=teacher.id)
    db.session.add(classroom)
    db.session.flush()

    for s in students:
        db.session.add(Enrollment(user_id=s.id, class_id=classroom.id))

    # Problem 1: Two Sum (50 pts)
    p1 = Problem(
        title="Two Sum",
        slug="two-sum",
        statement="Find two numbers.",
        time_limit=1.0,
        memory_limit=256,
        created_by_id=teacher.id,
    )
    # Problem 2: Reverse String (50 pts)
    p2 = Problem(
        title="Reverse String",
        slug="reverse-string",
        statement="Reverse a string.",
        time_limit=1.0,
        memory_limit=256,
        created_by_id=teacher.id,
    )
    db.session.add_all([p1, p2])
    db.session.flush()

    # Tests for p1 (50 pts)
    t1 = Test(problem_id=p1.id, order_num=1, input_data="1 2\n", expected_output="3\n", marks=50.0, is_hidden=False)
    # Tests for p2 (50 pts)
    t2 = Test(problem_id=p2.id, order_num=1, input_data="abc\n", expected_output="cba\n", marks=50.0, is_hidden=False)
    db.session.add_all([t1, t2])
    db.session.commit()

    return {
        "class": classroom,
        "p1": p1,
        "p2": p2,
    }


def test_assignment_problem_model_association(app, test_setup):
    """Verifies AssignmentProblem model, ordering, and backward compatibility properties."""
    classroom = test_setup["class"]
    p1 = test_setup["p1"]
    p2 = test_setup["p2"]

    now = utc_now()
    assignment = Assignment(
        class_id=classroom.id,
        title="Multi Problem Lab",
        open_date=now - timedelta(days=1),
        due_date=now + timedelta(days=7),
    )
    db.session.add(assignment)
    db.session.flush()

    ap1 = AssignmentProblem(assignment_id=assignment.id, problem_id=p1.id, order_num=1)
    ap2 = AssignmentProblem(assignment_id=assignment.id, problem_id=p2.id, order_num=2)
    db.session.add_all([ap1, ap2])
    db.session.commit()

    # Verify problems property returns ordered list
    problems = assignment.problems
    assert len(problems) == 2
    assert problems[0].id == p1.id
    assert problems[1].id == p2.id

    # Verify total_marks sums across all problems in assignment
    assert assignment.total_marks == 100.0

    # Backward compatibility: assignment with single problem_id and no AssignmentProblem records
    legacy_assign = Assignment(
        class_id=classroom.id,
        problem_id=p1.id,
        title="Legacy Assignment",
        open_date=now - timedelta(days=1),
        due_date=now + timedelta(days=7),
    )
    db.session.add(legacy_assign)
    db.session.commit()

    assert legacy_assign.problems == [p1]
    assert legacy_assign.total_marks == 50.0


def test_teacher_create_and_edit_multi_problem_assignment(client, teacher, test_setup):
    """Verifies teacher can create an assignment with multiple problems and update it."""
    # Login as teacher
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"}, follow_redirects=True)

    classroom = test_setup["class"]
    p1 = test_setup["p1"]
    p2 = test_setup["p2"]

    now = utc_now()
    create_data = {
        "class_id": classroom.id,
        "title": "HW 1: Arithmetic & Strings",
        "open_date": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "due_date": (now + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
        "max_attempts": 3,
        "allow_late": "y",
        "late_penalty_percent": 15.0,
        "problem_ids": [p1.id, p2.id],
    }

    res = client.post("/teacher/assignments/new", data=create_data, follow_redirects=True)
    assert res.status_code == 200
    assert b"created successfully" in res.data

    # Check assignment in DB
    assign = Assignment.query.filter_by(title="HW 1: Arithmetic & Strings").first()
    assert assign is not None
    assert len(assign.assignment_problems) == 2
    assert assign.total_marks == 100.0

    # Check assignments list view shows 2 Problems
    list_res = client.get("/teacher/assignments")
    assert b"2 Problems" in list_res.data

    # Edit assignment to have only p2
    edit_data = {
        "class_id": classroom.id,
        "title": "HW 1: Only Strings",
        "open_date": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "due_date": (now + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
        "max_attempts": 3,
        "allow_late": "y",
        "late_penalty_percent": 15.0,
        "problem_ids": [p2.id],
    }
    res_edit = client.post(f"/teacher/assignments/{assign.id}/edit", data=edit_data, follow_redirects=True)
    assert res_edit.status_code == 200
    db.session.refresh(assign)
    assert len(assign.assignment_problems) == 1
    assert assign.problems[0].id == p2.id
    assert assign.total_marks == 50.0


def test_student_multi_problem_views_and_navigation(client, students, test_setup):
    """Verifies student assignment detail view and problem switcher navigation."""
    classroom = test_setup["class"]
    p1 = test_setup["p1"]
    p2 = test_setup["p2"]

    now = utc_now()
    assignment = Assignment(
        class_id=classroom.id,
        title="Multi Problem Lab",
        open_date=now - timedelta(days=1),
        due_date=now + timedelta(days=7),
    )
    db.session.add(assignment)
    db.session.flush()
    db.session.add(AssignmentProblem(assignment_id=assignment.id, problem_id=p1.id, order_num=1))
    db.session.add(AssignmentProblem(assignment_id=assignment.id, problem_id=p2.id, order_num=2))
    db.session.commit()

    # Login as student Alice
    client.post("/auth/login", data={"username": "alice", "password": "Student@123"}, follow_redirects=True)

    # Dashboard should show multi-problem badge
    dash_res = client.get("/student/dashboard")
    assert dash_res.status_code == 200
    assert b"2 Problems" in dash_res.data
    assert b"View Problems" in dash_res.data

    # Assignments list should show multi-problem badge and link
    assigns_res = client.get("/student/assignments")
    assert assigns_res.status_code == 200
    assert b"2 Problems" in assigns_res.data

    # Assignment detail overview page
    detail_res = client.get(f"/student/assignments/{assignment.id}")
    assert detail_res.status_code == 200
    assert b"Problems in this Assignment" in detail_res.data
    assert b"Two Sum" in detail_res.data
    assert b"Reverse String" in detail_res.data

    # Problem solving portal - default defaults to first problem
    prob_res = client.get(f"/student/assignments/{assignment.id}/problem")
    assert prob_res.status_code == 200
    assert b"Two Sum" in prob_res.data
    # Problem switcher buttons exist
    assert b"P1: Two Sum" in prob_res.data
    assert b"P2: Reverse String" in prob_res.data

    # Problem solving portal - direct navigation to problem 2
    prob2_res = client.get(f"/student/assignments/{assignment.id}/problems/{p2.id}")
    assert prob2_res.status_code == 200
    assert b"Reverse String" in prob2_res.data


def test_student_independent_submissions_and_attempts_limit(client, students, test_setup):
    """Verifies attempt limits are enforced per-problem within a multi-problem assignment."""
    classroom = test_setup["class"]
    p1 = test_setup["p1"]
    p2 = test_setup["p2"]
    student = students[0]

    now = utc_now()
    assignment = Assignment(
        class_id=classroom.id,
        title="Multi Problem Lab",
        open_date=now - timedelta(days=1),
        due_date=now + timedelta(days=7),
        max_attempts=2,  # Limit: 2 attempts per problem
    )
    db.session.add(assignment)
    db.session.flush()
    db.session.add(AssignmentProblem(assignment_id=assignment.id, problem_id=p1.id, order_num=1))
    db.session.add(AssignmentProblem(assignment_id=assignment.id, problem_id=p2.id, order_num=2))
    db.session.commit()

    # Login as student Alice
    client.post("/auth/login", data={"username": "alice", "password": "Student@123"}, follow_redirects=True)

    # Submit 1st attempt to problem 1
    sub1_res = client.post(
        f"/student/assignments/{assignment.id}/problems/{p1.id}",
        data={"language": "python", "source_code": "print(3)"},
        follow_redirects=True,
    )
    assert sub1_res.status_code == 200
    assert b"Solution submitted successfully" in sub1_res.data

    # Submit 2nd attempt to problem 1
    sub2_res = client.post(
        f"/student/assignments/{assignment.id}/problems/{p1.id}",
        data={"language": "python", "source_code": "print(3)"},
        follow_redirects=True,
    )
    assert sub2_res.status_code == 200
    assert b"Solution submitted successfully" in sub2_res.data

    # Attempt 3rd submission to problem 1 -> Should be blocked!
    sub3_res = client.get(f"/student/assignments/{assignment.id}/problems/{p1.id}")
    assert b"You have reached the maximum allowed attempts" in sub3_res.data

    # But Problem 2 has 0 attempts made! Student should still be allowed to submit to problem 2!
    sub_p2_res = client.post(
        f"/student/assignments/{assignment.id}/problems/{p2.id}",
        data={"language": "python", "source_code": "print('cba')"},
        follow_redirects=True,
    )
    assert sub_p2_res.status_code == 200
    assert b"Solution submitted successfully" in sub_p2_res.data


def test_multi_problem_gradebook_and_csv_export(client, teacher, students, test_setup):
    """Verifies class and assignment gradebooks calculate multi-problem scores correctly."""
    classroom = test_setup["class"]
    p1 = test_setup["p1"]
    p2 = test_setup["p2"]
    alice, bob = students[0], students[1]

    now = utc_now()
    assignment = Assignment(
        class_id=classroom.id,
        title="Multi Problem Lab",
        open_date=now - timedelta(days=1),
        due_date=now + timedelta(days=7),
    )
    db.session.add(assignment)
    db.session.flush()
    db.session.add(AssignmentProblem(assignment_id=assignment.id, problem_id=p1.id, order_num=1))
    db.session.add(AssignmentProblem(assignment_id=assignment.id, problem_id=p2.id, order_num=2))
    db.session.commit()

    # Alice scores 50 on p1 and 50 on p2 -> Total = 100.0 / 100.0
    sub_a1 = Submission(user_id=alice.id, problem_id=p1.id, assignment_id=assignment.id, language="python", source_code="x", status="done", verdict="AC", tests_version=1)
    sub_a2 = Submission(user_id=alice.id, problem_id=p2.id, assignment_id=assignment.id, language="python", source_code="y", status="done", verdict="AC", tests_version=1)
    db.session.add_all([sub_a1, sub_a2])
    db.session.flush()
    db.session.add(Score(submission_id=sub_a1.id, user_id=alice.id, problem_id=p1.id, assignment_id=assignment.id, raw_score=50.0, late_penalty_percent=0.0, final_score=50.0, max_possible_score=50.0))
    db.session.add(Score(submission_id=sub_a2.id, user_id=alice.id, problem_id=p2.id, assignment_id=assignment.id, raw_score=50.0, late_penalty_percent=0.0, final_score=50.0, max_possible_score=50.0))

    # Bob scores 25 on p1, no submission on p2 -> Total = 25.0 / 100.0
    sub_b1 = Submission(user_id=bob.id, problem_id=p1.id, assignment_id=assignment.id, language="python", source_code="z", status="done", verdict="WA", tests_version=1)
    db.session.add(sub_b1)
    db.session.flush()
    db.session.add(Score(submission_id=sub_b1.id, user_id=bob.id, problem_id=p1.id, assignment_id=assignment.id, raw_score=25.0, late_penalty_percent=0.0, final_score=25.0, max_possible_score=50.0))
    db.session.commit()

    # Login as teacher
    client.post("/auth/login", data={"username": "prof_turing", "password": "Teacher@123"}, follow_redirects=True)

    # 1. Class Gradebook View
    cgb_res = client.get(f"/teacher/classes/{classroom.id}/gradebook")
    assert cgb_res.status_code == 200
    assert b"100.0" in cgb_res.data
    assert b"25.0" in cgb_res.data

    # 2. Class Gradebook CSV
    cgb_csv = client.get(f"/teacher/classes/{classroom.id}/gradebook.csv")
    assert cgb_csv.status_code == 200
    reader = csv.reader(io.StringIO(cgb_csv.data.decode("utf-8")))
    rows = list(reader)
    # Header: Roll No, Student Name, Username, HW (100.0 pts), Total Score, Max Score, Percentage (%)
    assert any("100.0" in r[3] for r in rows if len(r) > 3 and "BCSF20M001" in r[0])
    assert any("25.0" in r[3] for r in rows if len(r) > 3 and "BCSF20M002" in r[0])

    # 3. Assignment Gradebook View
    agb_res = client.get(f"/teacher/assignments/{assignment.id}/gradebook")
    assert agb_res.status_code == 200
    assert b"2 problems" in agb_res.data
    assert b"100.0" in agb_res.data

    # 4. Assignment Gradebook CSV
    agb_csv = client.get(f"/teacher/assignments/{assignment.id}/gradebook.csv")
    assert agb_csv.status_code == 200
    reader2 = csv.reader(io.StringIO(agb_csv.data.decode("utf-8")))
    rows2 = list(reader2)
    # Alice row should have final score 100.0, max score 100.0
    alice_row = next(r for r in rows2 if len(r) > 2 and r[0] == "BCSF20M001")
    assert alice_row[6] == "100.0"
    assert alice_row[7] == "100.0"
