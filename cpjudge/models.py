"""Database models for CPJudge.

Tables:
- users
- classes
- enrollments
- problems
- tests
- assignments
- submissions
- results
- scores
- audit_log

Designed for both SQLite and PostgreSQL. All timestamps stored in UTC.
"""
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from cpjudge.utils.auth import hash_password, verify_password
from cpjudge.utils.timezone import (
    PKT_TZ,
    ensure_pkt,
    format_pkt,
    now_pkt,
    to_pkt,
    utc_now,
    ensure_utc,
)

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """User account model for Teachers and Students."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    roll_no = Column(String(64), unique=True, nullable=True, index=True)
    name = Column(String(128), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="student")  # 'teacher' or 'student'
    force_password_change = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    enrollments = relationship("Enrollment", back_populates="user", cascade="all, delete-orphan")
    classes_taught = relationship("Class", back_populates="teacher", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="user", cascade="all, delete-orphan")
    scores = relationship("Score", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user")

    def set_password(self, password: str) -> None:
        """Hashes and sets the user's password."""
        self.password_hash = hash_password(password)

    def check_password(self, password: str) -> bool:
        """Verifies a plain-text password against the stored hash."""
        return verify_password(password, self.password_hash)

    @property
    def is_teacher(self) -> bool:
        return self.role == "teacher"

    @property
    def is_student(self) -> bool:
        return self.role == "student"

    def __repr__(self) -> str:
        return f"<User id={self.id} username='{self.username}' role='{self.role}'>"


class Class(db.Model):
    """Academic class / section created by a Teacher."""
    __tablename__ = "classes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    code = Column(String(32), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    teacher_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    teacher = relationship("User", back_populates="classes_taught")
    enrollments = relationship("Enrollment", back_populates="classroom", cascade="all, delete-orphan")
    assignments = relationship("Assignment", back_populates="classroom", cascade="all, delete-orphan")

    @property
    def student_count(self) -> int:
        return len(self.enrollments)

    def __repr__(self) -> str:
        return f"<Class id={self.id} code='{self.code}' name='{self.name}'>"


class Enrollment(db.Model):
    """Enrollment mapping students to classes."""
    __tablename__ = "enrollments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id = Column(Integer, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("user_id", "class_id", name="uq_user_class"),
    )

    # Relationships
    user = relationship("User", back_populates="enrollments")
    classroom = relationship("Class", back_populates="enrollments")

    def __repr__(self) -> str:
        return f"<Enrollment user_id={self.user_id} class_id={self.class_id}>"


class Problem(db.Model):
    """Programming problem specification and statement."""
    __tablename__ = "problems"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(128), nullable=False)
    slug = Column(String(128), unique=True, nullable=False, index=True)
    statement = Column(Text, nullable=False)  # Markdown format
    time_limit = Column(Float, nullable=False, default=1.0)  # seconds
    memory_limit = Column(Integer, nullable=False, default=256)  # MB
    output_limit_bytes = Column(Integer, nullable=False, default=10 * 1024 * 1024)  # 10 MB
    checker_type = Column(String(20), nullable=False, default="token")  # exact, token, float, custom
    checker_code = Column(Text, nullable=True)  # custom checker script source if custom
    float_tolerance = Column(Float, nullable=False, default=1e-6)
    scoring_mode = Column(String(20), nullable=False, default="per_test")  # per_test, all_or_nothing, grouped
    tests_version = Column(Integer, nullable=False, default=1)  # Incremented when tests are modified
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    created_by = relationship("User")
    tests = relationship("Test", back_populates="problem", cascade="all, delete-orphan", order_by="Test.order_num")
    assignments = relationship("Assignment", back_populates="problem")
    assignment_links = relationship("AssignmentProblem", back_populates="problem", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="problem", cascade="all, delete-orphan")

    @property
    def total_marks(self) -> float:
        return sum(t.marks for t in self.tests)

    @property
    def visible_tests(self) -> List["Test"]:
        return [t for t in self.tests if not t.is_hidden]

    @property
    def hidden_tests(self) -> List["Test"]:
        return [t for t in self.tests if t.is_hidden]

    def increment_tests_version(self) -> int:
        """Increments tests_version to flag previous submission results as stale."""
        self.tests_version += 1
        return self.tests_version

    def __repr__(self) -> str:
        return f"<Problem id={self.id} slug='{self.slug}' version={self.tests_version}>"


class Test(db.Model):
    """Individual test case for a problem."""
    __tablename__ = "tests"
    __test__ = False

    id = Column(Integer, primary_key=True, autoincrement=True)
    problem_id = Column(Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False, index=True)
    order_num = Column(Integer, nullable=False, default=1)
    input_data = Column(Text, nullable=False)
    expected_output = Column(Text, nullable=False)
    marks = Column(Float, nullable=False, default=10.0)
    is_hidden = Column(Boolean, nullable=False, default=False)
    subtask_id = Column(String(64), nullable=True)
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    problem = relationship("Problem", back_populates="tests")
    results = relationship("Result", back_populates="test")

    @property
    def is_visible(self) -> bool:
        return not self.is_hidden

    def __repr__(self) -> str:
        return f"<Test id={self.id} problem_id={self.problem_id} hidden={self.is_hidden} marks={self.marks}>"


class AssignmentProblem(db.Model):
    """Association linking an Assignment to multiple Problems with ordering."""
    __tablename__ = "assignment_problems"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    problem_id = Column(Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False, index=True)
    order_num = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("assignment_id", "problem_id", name="uq_assignment_problem"),
    )

    # Relationships
    assignment = relationship("Assignment", back_populates="assignment_problems")
    problem = relationship("Problem", back_populates="assignment_links")

    def __repr__(self) -> str:
        return f"<AssignmentProblem assignment_id={self.assignment_id} problem_id={self.problem_id} order={self.order_num}>"


class Assignment(db.Model):
    """Assignment linking one or more problems to a class with deadlines and rules."""
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_id = Column(Integer, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    problem_id = Column(Integer, ForeignKey("problems.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(128), nullable=False)
    open_date = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    max_attempts = Column(Integer, nullable=False, default=0)  # 0 = unlimited
    late_penalty_percent = Column(Float, nullable=False, default=0.0)
    allow_late = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    classroom = relationship("Class", back_populates="assignments")
    problem = relationship("Problem", back_populates="assignments")
    assignment_problems = relationship("AssignmentProblem", back_populates="assignment", cascade="all, delete-orphan", order_by="AssignmentProblem.order_num")
    submissions = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")
    scores = relationship("Score", back_populates="assignment", cascade="all, delete-orphan")

    @property
    def problems(self) -> List["Problem"]:
        """Returns the list of problems in this assignment in configured order."""
        if self.assignment_problems:
            return [ap.problem for ap in self.assignment_problems if ap.problem is not None]
        elif self.problem:
            return [self.problem]
        return []

    @property
    def total_marks(self) -> float:
        """Total possible marks across all problems in this assignment."""
        return sum(p.total_marks for p in self.problems)

    def is_active(self, now: Optional[datetime] = None) -> bool:
        """Checks if assignment is currently accessible (open and not past final due)."""
        if now is None:
            now = utc_now()
        now = ensure_utc(now)
        open_dt = ensure_utc(self.open_date)
        due_dt = ensure_utc(self.due_date)

        if open_dt and now < open_dt:
            return False
        if not self.allow_late and due_dt and now > due_dt:
            return False
        return True

    def is_late(self, timestamp: Optional[datetime] = None) -> bool:
        """Checks if a submission timestamp is past due."""
        if timestamp is None:
            timestamp = utc_now()
        timestamp = ensure_utc(timestamp)
        due_dt = ensure_utc(self.due_date)
        return bool(due_dt and timestamp > due_dt)

    def __repr__(self) -> str:
        return f"<Assignment id={self.id} class_id={self.class_id} problem_id={self.problem_id}>"


class Submission(db.Model):
    """Student code submission record."""
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    problem_id = Column(Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=True, index=True)
    language = Column(String(20), nullable=False)  # 'c', 'cpp', 'python'
    source_code = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="queued", index=True)  # queued, judging, done, error
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    verdict = Column(String(10), nullable=True)  # AC, WA, TLE, MLE, RE, CE, OLE
    tests_version = Column(Integer, nullable=False)  # Problem tests_version at time of submission
    max_time = Column(Float, nullable=True)  # Maximum execution time across tests (seconds)
    max_memory_kb = Column(Integer, nullable=True)  # Peak memory usage across tests (KB)
    compile_error = Column(Text, nullable=True)
    is_late = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    judged_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="submissions")
    problem = relationship("Problem", back_populates="submissions")
    assignment = relationship("Assignment", back_populates="submissions")
    results = relationship("Result", back_populates="submission", cascade="all, delete-orphan", order_by="Result.test_order")
    score = relationship("Score", back_populates="submission", uselist=False, cascade="all, delete-orphan")

    @property
    def is_stale(self) -> bool:
        """Returns True if the problem tests have been modified since this submission was judged."""
        if not self.problem:
            return False
        return self.problem.tests_version != self.tests_version

    @property
    def has_current_score(self) -> bool:
        """Whether the persisted score reflects a completed evaluation of current tests."""
        return (
            self.status == "done"
            and self.score is not None
            and not self.score.is_stale
            and not self.is_stale
        )

    def __repr__(self) -> str:
        return f"<Submission id={self.id} user_id={self.user_id} status='{self.status}' verdict='{self.verdict}'>"


class Result(db.Model):
    """Detailed per-test execution result for a submission."""
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True)
    test_id = Column(Integer, ForeignKey("tests.id", ondelete="SET NULL"), nullable=True, index=True)
    test_order = Column(Integer, nullable=False)
    verdict = Column(String(10), nullable=False)  # AC, WA, TLE, MLE, RE, CE, OLE
    cpu_time = Column(Float, nullable=False, default=0.0)
    wall_time = Column(Float, nullable=False, default=0.0)
    memory_kb = Column(Integer, nullable=False, default=0)
    marks_awarded = Column(Float, nullable=False, default=0.0)
    is_hidden = Column(Boolean, nullable=False, default=False)
    # Output and diff are ONLY saved for visible tests; strictly NULL for hidden tests
    student_output = Column(Text, nullable=True)
    diff = Column(Text, nullable=True)
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    submission = relationship("Submission", back_populates="results")
    test = relationship("Test", back_populates="results")

    @property
    def execution_time(self) -> float:
        return self.cpu_time

    @property
    def memory_used_kb(self) -> int:
        return self.memory_kb

    @property
    def score_awarded(self) -> float:
        return self.marks_awarded

    @property
    def checker_diff(self) -> Optional[str]:
        return self.diff

    def __repr__(self) -> str:
        return f"<Result id={self.id} submission_id={self.submission_id} verdict='{self.verdict}'>"


class Score(db.Model):
    """Calculated score summary for a submission."""
    __tablename__ = "scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    problem_id = Column(Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_score = Column(Float, nullable=False, default=0.0)
    late_penalty_percent = Column(Float, nullable=False, default=0.0)
    late_penalty_deduction = Column(Float, nullable=False, default=0.0)
    final_score = Column(Float, nullable=False, default=0.0)
    max_possible_score = Column(Float, nullable=False, default=0.0)
    is_stale = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships
    submission = relationship("Submission", back_populates="score")
    assignment = relationship("Assignment", back_populates="scores")
    user = relationship("User", back_populates="scores")
    problem = relationship("Problem")

    @property
    def percentage(self) -> float:
        if self.max_possible_score <= 0.0:
            return 0.0
        return round((self.final_score / self.max_possible_score) * 100.0, 2)

    def __repr__(self) -> str:
        return f"<Score submission_id={self.submission_id} final={self.final_score}/{self.max_possible_score}>"


class AuditLog(db.Model):
    """Audit log tracking teacher actions (rejudge, test edit, grade export, imports)."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(64), nullable=False, index=True)
    target_type = Column(String(32), nullable=True)  # submission, problem, test, assignment, class
    target_id = Column(String(64), nullable=True)
    details = Column(Text, nullable=True)  # JSON or text description
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    # Relationships
    user = relationship("User", back_populates="audit_logs")

    @classmethod
    def log(
        cls,
        action: str,
        user_id: Optional[int] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str | int] = None,
        details: Optional[Dict[str, Any] | str] = None,
        ip_address: Optional[str] = None,
    ) -> "AuditLog":
        """Convenience method to create and save an audit log entry."""
        details_str = json.dumps(details) if isinstance(details, dict) else details
        entry = cls(
            action=action,
            user_id=user_id,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details_str,
            ip_address=ip_address,
        )
        db.session.add(entry)
        return entry

    @property
    def details_dict(self) -> Dict[str, Any]:
        """Parsed dictionary from JSON details."""
        if not self.details:
            return {}
        try:
            return json.loads(self.details)
        except Exception:
            return {"raw": self.details}

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action='{self.action}' user_id={self.user_id}>"
