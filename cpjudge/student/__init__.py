"""Student blueprint for CPJudge."""
from flask import Blueprint

student_bp = Blueprint("student", __name__, url_prefix="/student", template_folder="../templates")

from cpjudge.student import routes  # noqa: E402, F401
