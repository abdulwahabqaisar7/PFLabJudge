"""Database seeder script for CPJudge.

Seeds:
- 1 Teacher (Prof. Alan Turing)
- 3 Demo Students (Alice, Bob, Charlie)
- 1 Class (CS101-FA24) with enrollments
- 1 Problem ('Sum of Two Numbers') with 4 test cases (2 visible, 2 hidden)
- 1 Assignment with open/due dates and late penalty
"""
from datetime import datetime, timedelta, timezone
import sys

from cpjudge.app import create_app
from cpjudge.models import (
    Assignment,
    AssignmentProblem,
    AuditLog,
    Class,
    Enrollment,
    Problem,
    Test,
    User,
    db,
    utc_now,
)


def seed_database(drop_existing: bool = False) -> None:
    """Populates the database with initial teacher, students, and demo content."""
    app = create_app()
    with app.app_context():
        if drop_existing:
            print("Dropping existing database tables...")
            db.drop_all()

        print("Creating tables if not present...")
        db.create_all()

        # 1. Teacher Account
        teacher = User.query.filter_by(username="teacher").first()
        if not teacher:
            print("Creating Teacher account (teacher)...")
            teacher = User(
                username="teacher",
                name="Prof. Alan Turing",
                role="teacher",
                force_password_change=False,
            )
            teacher.set_password("Teacher@123")
            db.session.add(teacher)
            db.session.flush()
        else:
            print("Teacher account already exists.")

        # 2. Demo Students
        students_data = [
            ("bcsf20m001", "BCSF20M001", "Alice Johnson", "Student@123", False),
            ("bcsf20m002", "BCSF20M002", "Bob Smith", "Student@123", False),
            ("bcsf20m003", "BCSF20M003", "Charlie Davis", "Student@123", True),  # Force password change demo
        ]
        students = []
        for uname, rno, name, pwd, force_change in students_data:
            stu = User.query.filter_by(username=uname).first()
            if not stu:
                print(f"Creating Student account ({uname} - {name})...")
                stu = User(
                    username=uname,
                    roll_no=rno,
                    name=name,
                    role="student",
                    force_password_change=force_change,
                )
                stu.set_password(pwd)
                db.session.add(stu)
                db.session.flush()
            students.append(stu)

        # 3. Class
        classroom = Class.query.filter_by(code="CS101-FA24").first()
        if not classroom:
            print("Creating Class (CS101-FA24)...")
            classroom = Class(
                name="Programming Fundamentals Lab - Fall 2024",
                code="CS101-FA24",
                description="Core lab course covering programming principles, I/O handling, and logic building in C, C++, and Python.",
                teacher_id=teacher.id,
            )
            db.session.add(classroom)
            db.session.flush()

        # 4. Enrollments
        for stu in students:
            enr = Enrollment.query.filter_by(user_id=stu.id, class_id=classroom.id).first()
            if not enr:
                print(f"Enrolling {stu.name} in {classroom.code}...")
                enr = Enrollment(user_id=stu.id, class_id=classroom.id)
                db.session.add(enr)

        # 5. Problem: Sum of Two Numbers
        problem = Problem.query.filter_by(slug="sum-of-two-numbers").first()
        if not problem:
            print("Creating Problem ('Sum of Two Numbers')...")
            statement = """# Sum of Two Numbers

Given two integers $A$ and $B$, calculate and print their sum.

## Input Format
The first line contains two space-separated integers, $A$ and $B$.

## Output Format
Print a single integer: the sum $A + B$.

## Constraints
- $-10^9 \\le A, B \\le 10^9$

## Sample 1
### Input
```text
5 7
```
### Output
```text
12
```

## Sample 2
### Input
```text
100 -20
```
### Output
```text
80
```
"""
            problem = Problem(
                title="Sum of Two Numbers",
                slug="sum-of-two-numbers",
                statement=statement.strip(),
                time_limit=1.0,
                memory_limit=256,
                output_limit_bytes=10 * 1024 * 1024,
                checker_type="token",
                float_tolerance=1e-6,
                scoring_mode="per_test",
                tests_version=1,
                created_by_id=teacher.id,
            )
            db.session.add(problem)
            db.session.flush()

            # 4 Test Cases: 2 Visible, 2 Hidden
            tests = [
                Test(
                    problem_id=problem.id,
                    order_num=1,
                    input_data="5 7\n",
                    expected_output="12\n",
                    marks=25.0,
                    is_hidden=False,
                    explanation="5 + 7 = 12",
                ),
                Test(
                    problem_id=problem.id,
                    order_num=2,
                    input_data="100 -20\n",
                    expected_output="80\n",
                    marks=25.0,
                    is_hidden=False,
                    explanation="100 + (-20) = 80",
                ),
                Test(
                    problem_id=problem.id,
                    order_num=3,
                    input_data="1000000000 2000000000\n",
                    expected_output="3000000000\n",
                    marks=25.0,
                    is_hidden=True,
                    explanation="64-bit integer addition",
                ),
                Test(
                    problem_id=problem.id,
                    order_num=4,
                    input_data="0 0\n",
                    expected_output="0\n",
                    marks=25.0,
                    is_hidden=True,
                    explanation="Zero boundary case",
                ),
            ]
            db.session.add_all(tests)

        # 5b. Problem 2: Product of Two Numbers
        problem2 = Problem.query.filter_by(slug="product-of-two-numbers").first()
        if not problem2:
            print("Creating Problem ('Product of Two Numbers')...")
            statement2 = """# Product of Two Numbers

Given two integers $A$ and $B$, calculate and print their product.

## Input Format
The first line contains two space-separated integers, $A$ and $B$.

## Output Format
Print a single integer: the product $A \\times B$.

## Constraints
- $-10^6 \\le A, B \\le 10^6$

## Sample 1
### Input
```text
3 4
```
### Output
```text
12
```

## Sample 2
### Input
```text
-5 6
```
### Output
```text
-30
```
"""
            problem2 = Problem(
                title="Product of Two Numbers",
                slug="product-of-two-numbers",
                statement=statement2.strip(),
                time_limit=1.0,
                memory_limit=256,
                output_limit_bytes=10 * 1024 * 1024,
                checker_type="token",
                float_tolerance=1e-6,
                scoring_mode="per_test",
                tests_version=1,
                created_by_id=teacher.id,
            )
            db.session.add(problem2)
            db.session.flush()

            tests2 = [
                Test(
                    problem_id=problem2.id,
                    order_num=1,
                    input_data="3 4\n",
                    expected_output="12\n",
                    marks=25.0,
                    is_hidden=False,
                    explanation="3 * 4 = 12",
                ),
                Test(
                    problem_id=problem2.id,
                    order_num=2,
                    input_data="-5 6\n",
                    expected_output="-30\n",
                    marks=25.0,
                    is_hidden=False,
                    explanation="-5 * 6 = -30",
                ),
                Test(
                    problem_id=problem2.id,
                    order_num=3,
                    input_data="1000 2000\n",
                    expected_output="2000000\n",
                    marks=25.0,
                    is_hidden=True,
                    explanation="Multiplication of larger integers",
                ),
                Test(
                    problem_id=problem2.id,
                    order_num=4,
                    input_data="0 9999\n",
                    expected_output="0\n",
                    marks=25.0,
                    is_hidden=True,
                    explanation="Zero boundary case",
                ),
            ]
            db.session.add_all(tests2)

        # 6. Assignment
        assignment = Assignment.query.filter_by(class_id=classroom.id, title="Lab 01: Arithmetic Operations").first()
        if not assignment:
            assignment = Assignment.query.filter_by(class_id=classroom.id, title="Lab 01: Sum of Two Numbers").first()
        if not assignment:
            print("Creating Assignment ('Lab 01: Arithmetic Operations')...")
            now = utc_now()
            assignment = Assignment(
                class_id=classroom.id,
                problem_id=problem.id,
                title="Lab 01: Arithmetic Operations",
                open_date=now - timedelta(days=1),
                due_date=now + timedelta(days=7),
                max_attempts=0,  # Unlimited
                late_penalty_percent=10.0,
                allow_late=True,
            )
            db.session.add(assignment)
            db.session.flush()

        # Link both problems to the assignment
        for idx, p in enumerate([problem, problem2], start=1):
            ap = AssignmentProblem.query.filter_by(assignment_id=assignment.id, problem_id=p.id).first()
            if not ap:
                ap = AssignmentProblem(
                    assignment_id=assignment.id,
                    problem_id=p.id,
                    order_num=idx,
                )
                db.session.add(ap)

        # 7. Audit Log
        AuditLog.log(
            action="seed_database",
            user_id=teacher.id,
            target_type="system",
            details={"message": "Initial seed data created successfully."},
        )

        db.session.commit()
        print("\nDatabase seeded successfully!")
        print("--------------------------------------------------")
        print("Teacher Account:   teacher     / Teacher@123")
        print("Student Account 1: bcsf20m001  / Student@123")
        print("Student Account 2: bcsf20m002  / Student@123")
        print("Student Account 3: bcsf20m003  / Student@123 (Force pwd change)")
        print("Classroom:         CS101-FA24")
        print("Problems:          1) Sum of Two Numbers (4 tests, 100 marks)")
        print("                   2) Product of Two Numbers (4 tests, 100 marks)")
        print("Assignment:        Lab 01: Arithmetic Operations (2 problems, 200 marks)")
        print("--------------------------------------------------")


if __name__ == "__main__":
    drop = "--drop" in sys.argv
    seed_database(drop_existing=drop)
