"""Flask application factory for CPJudge."""
import os
from flask import Flask, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import DateTime, inspect, update
from sqlalchemy.exc import DBAPIError

from cpjudge.config import config_by_name
from cpjudge.models import Submission, User, db, utc_now

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))


def create_app(config_name: str | None = None) -> Flask:
    """Creates and configures the Flask application."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__)
    config_class = config_by_name.get(config_name, config_by_name["default"])
    app.config.from_object(config_class)
    if config_name == "production":
        secret_key = os.environ.get("SECRET_KEY")
        if not secret_key:
            raise RuntimeError("SECRET_KEY must be configured when FLASK_ENV=production.")
        app.config["SECRET_KEY"] = secret_key
        sandbox_backend = app.config.get("SANDBOX_BACKEND", "bwrap")
        if sandbox_backend not in ("bwrap", "docker"):
            raise RuntimeError(
                "Production requires SANDBOX_BACKEND=bwrap or SANDBOX_BACKEND=docker."
            )
        if sandbox_backend == "bwrap" and not app.config.get("USE_BWRAP"):
            raise RuntimeError("USE_BWRAP must remain enabled when SANDBOX_BACKEND=bwrap.")

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    with app.app_context():
        _ensure_submission_claim_timestamp()

    # Register blueprints
    from cpjudge.auth import auth_bp
    from cpjudge.auth.decorators import register_auth_hooks
    from cpjudge.student import student_bp
    from cpjudge.teacher import teacher_bp
    from cpjudge.utils.markdown import render_markdown
    from cpjudge.utils.timezone import format_pkt, to_pkt

    app.register_blueprint(auth_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(student_bp)
    register_auth_hooks(app)

    # Register template filters
    app.jinja_env.filters["render_markdown"] = render_markdown
    app.jinja_env.filters["format_pkt"] = format_pkt
    app.jinja_env.filters["to_pkt"] = to_pkt

    # Global template context
    @app.context_processor
    def inject_timezone():
        return {
            "TIMEZONE_LABEL": app.config.get("TIMEZONE_LABEL", "PKT"),
            "APP_TIMEZONE": app.config.get("APP_TIMEZONE", "Asia/Karachi"),
        }

    # Root route
    @app.route("/")
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if current_user.force_password_change:
            return redirect(url_for("auth.change_password"))
        if current_user.is_teacher:
            try:
                return redirect(url_for("teacher.dashboard"))
            except Exception:
                return redirect(url_for("auth.profile"))
        else:
            try:
                return redirect(url_for("student.dashboard"))
            except Exception:
                return redirect(url_for("auth.profile"))

    # Error handlers
    @app.errorhandler(403)
    def forbidden_error(e):
        return render_template("errors/403.html", error=e), 403

    @app.errorhandler(404)
    def not_found_error(e):
        return render_template("errors/404.html", error=e), 404

    @app.errorhandler(429)
    def ratelimit_error(e):
        return render_template("errors/429.html", error=e), 429

    return app


def _ensure_submission_claim_timestamp() -> None:
    """Adds the worker lease column to databases created before it existed."""
    try:
        with db.engine.begin() as connection:
            inspector = inspect(connection)
            if not inspector.has_table("submissions"):
                return
            columns = {column["name"] for column in inspector.get_columns("submissions")}
            if "claimed_at" not in columns:
                column_type = DateTime(timezone=True).compile(dialect=connection.dialect)
                connection.exec_driver_sql(
                    f"ALTER TABLE submissions ADD COLUMN claimed_at {column_type}"
                )
            connection.execute(
                update(Submission.__table__)
                .where(
                    Submission.status == "judging",
                    Submission.claimed_at.is_(None),
                )
                .values(claimed_at=utc_now())
            )
    except DBAPIError:
        # Concurrent web/worker startup may race while adding the same column.
        with db.engine.connect() as connection:
            inspector = inspect(connection)
            if not inspector.has_table("submissions"):
                raise
            columns = {column["name"] for column in inspector.get_columns("submissions")}
        if "claimed_at" not in columns:
            raise
        with db.engine.begin() as connection:
            connection.execute(
                update(Submission.__table__)
                .where(
                    Submission.status == "judging",
                    Submission.claimed_at.is_(None),
                )
                .values(claimed_at=utc_now())
            )
