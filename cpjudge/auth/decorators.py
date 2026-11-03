"""Authorization decorators and ownership checks for CPJudge.

Enforces:
- @teacher_required: Only teachers can access
- @student_required: Only students can access
- ensure_submission_access(): Student can only access their own submissions; teachers can access all
- before_request hook: Force password change on first login
"""
from functools import wraps
from typing import Callable, Any
from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from cpjudge.models import Submission


def teacher_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator ensuring that only authenticated Teachers can access the route."""
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if not current_user.is_teacher:
            abort(403, description="Teacher privileges required.")
        return f(*args, **kwargs)
    return decorated_function


def student_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator ensuring that only authenticated Students can access the route."""
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if not current_user.is_student:
            abort(403, description="Student privileges required.")
        return f(*args, **kwargs)
    return decorated_function


def ensure_submission_access(submission: Submission) -> bool:
    """Verifies that the current user is authorized to access the given submission.

    Rules:
    - Teacher: Can access all submissions
    - Student: Can ONLY access their own submission (submission.user_id == current_user.id)
    - Unauthenticated or unauthorized: aborts with 403 Forbidden.
    """
    if not current_user.is_authenticated:
        abort(401, description="Authentication required.")

    if current_user.is_teacher:
        return True

    if current_user.is_student and submission.user_id == current_user.id:
        return True

    abort(403, description="Access denied: You do not own this submission.")


def register_auth_hooks(app) -> None:
    """Registers global before_request hooks for authentication and password change enforcement."""
    @app.before_request
    def enforce_force_password_change():
        if not current_user.is_authenticated:
            return None

        # Exclude static assets, logout, and change-password route itself
        allowed_endpoints = {
            "auth.change_password",
            "auth.logout",
            "static",
        }

        endpoint = request.endpoint
        if endpoint in allowed_endpoints or (endpoint and endpoint.startswith("static.")):
            return None

        if current_user.force_password_change:
            flash("You are required to change your password before continuing.", "warning")
            return redirect(url_for("auth.change_password"))

        return None
