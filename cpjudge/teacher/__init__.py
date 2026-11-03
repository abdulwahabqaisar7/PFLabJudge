"""Teacher blueprint for CPJudge."""
from flask import Blueprint

teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher", template_folder="../templates")

from cpjudge.teacher import routes  # noqa: E402, F401
