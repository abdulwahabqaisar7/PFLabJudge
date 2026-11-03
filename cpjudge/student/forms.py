"""WTForms form classes for the Student UI."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Optional


class CodeSubmissionForm(FlaskForm):
    """Form for student code submission via paste or file upload."""
    language = SelectField(
        "Programming Language",
        choices=[
            ("cpp", "C++ (g++ -O2 -std=c++17)"),
            ("c", "C (gcc -O2 -std=c11)"),
            ("python", "Python (Python 3.10+)"),
        ],
        default="cpp",
        validators=[DataRequired()],
    )
    source_code = TextAreaField(
        "Source Code",
        validators=[Optional()],
        render_kw={"placeholder": "// Paste or write your source code here..."},
    )
    code_file = FileField(
        "Upload Code File",
        validators=[
            Optional(),
            FileAllowed(["c", "cpp", "cc", "cxx", "py"], "Allowed file extensions: .c, .cpp, .cc, .cxx, .py"),
        ],
    )
    submit = SubmitField("Submit Solution")
