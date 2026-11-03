"""Authentication route handlers."""
from urllib.parse import urlparse
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from cpjudge.app import limiter
from cpjudge.auth import auth_bp
from cpjudge.auth.forms import ChangePasswordForm, LoginForm
from cpjudge.models import AuditLog, User, db


def is_safe_url(target: str) -> bool:
    """Validates that a redirect target is a safe relative URL to prevent open-redirect attacks."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in target):
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and parsed.path.startswith("/") and not parsed.path.startswith("//")


def get_default_redirect_url(user: User) -> str:
    """Returns role-specific landing page for the user."""
    if user.is_teacher:
        try:
            return url_for("teacher.dashboard")
        except Exception:
            return url_for("auth.profile")
    else:
        try:
            return url_for("student.dashboard")
        except Exception:
            return url_for("auth.profile")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 50 per hour")
def login():
    """Authenticates users via username or roll number."""
    if request.method == "GET" and current_user.is_authenticated:
        if current_user.force_password_change:
            return redirect(url_for("auth.change_password"))
        return redirect(get_default_redirect_url(current_user))

    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.username.data.strip()
        password = form.password.data

        # Search by username or roll_no (case-insensitive)
        user = User.query.filter(
            (db.func.lower(User.username) == identifier.lower()) |
            (db.func.lower(User.roll_no) == identifier.lower())
        ).first()

        if user and user.check_password(password):
            if current_user.is_authenticated:
                logout_user()
            login_user(user, remember=form.remember.data)
            AuditLog.log(
                action="login_success",
                user_id=user.id,
                details=f"User {user.username} logged in successfully.",
                ip_address=request.remote_addr,
            )
            db.session.commit()

            if user.force_password_change:
                flash("First-time login detected. You must change your password to continue.", "warning")
                return redirect(url_for("auth.change_password"))

            next_page = request.args.get("next")
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            return redirect(get_default_redirect_url(user))
        else:
            flash("Invalid username or password. Please try again.", "danger")
            AuditLog.log(
                action="login_failure",
                details=f"Failed login attempt for identifier: '{identifier}'",
                ip_address=request.remote_addr,
            )
            db.session.commit()

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    """Logs the user out of the session."""
    user_id = current_user.id
    username = current_user.username
    logout_user()
    AuditLog.log(
        action="logout",
        user_id=user_id,
        details=f"User {username} logged out.",
        ip_address=request.remote_addr,
    )
    db.session.commit()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Allows user to change their password, clearing force_password_change flag upon success."""
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "danger")
        elif form.new_password.data == form.current_password.data:
            flash("New password cannot be identical to your current password.", "warning")
        else:
            current_user.set_password(form.new_password.data)
            current_user.force_password_change = False
            AuditLog.log(
                action="password_change",
                user_id=current_user.id,
                details="Password updated successfully.",
                ip_address=request.remote_addr,
            )
            db.session.commit()
            flash("Your password has been changed successfully.", "success")
            return redirect(get_default_redirect_url(current_user))

    return render_template("auth/change_password.html", form=form)


@auth_bp.route("/profile")
@login_required
def profile():
    """Fallback profile page showing user details."""
    return render_template("auth/profile.html", user=current_user)
