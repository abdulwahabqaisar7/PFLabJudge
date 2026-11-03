"""Authentication module for CPJudge."""
from flask import Blueprint

auth_bp = Blueprint("auth", __name__, url_prefix="/auth", template_folder="../templates")

from cpjudge.auth import routes  # noqa: E402, F401
