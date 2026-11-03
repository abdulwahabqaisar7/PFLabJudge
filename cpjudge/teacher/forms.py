"""WTForms form classes for the Teacher UI."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    BooleanField,
    DateTimeLocalField,
    FloatField,
    IntegerField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class ProblemForm(FlaskForm):
    """Form to create or edit a problem."""
    title = StringField("Title", validators=[DataRequired(), Length(max=128)])
    slug = StringField("Slug (URL identifier)", validators=[Optional(), Length(max=128)])
    statement = TextAreaField("Problem Statement (Markdown)", validators=[DataRequired()])
    time_limit = FloatField("CPU Time Limit (seconds)", default=1.0, validators=[DataRequired(), NumberRange(min=0.1, max=60.0)])
    memory_limit = IntegerField("Memory Limit (MB)", default=256, validators=[DataRequired(), NumberRange(min=16, max=2048)])
    output_limit_mb = IntegerField("Output Limit (MB)", default=10, validators=[DataRequired(), NumberRange(min=1, max=100)])
    checker_type = SelectField(
        "Checker Type",
        choices=[
            ("token", "Token (Whitespace & line-ending insensitive)"),
            ("exact", "Exact match (Strict)"),
            ("float", "Floating point tolerance"),
            ("custom", "Custom script checker"),
        ],
        default="token",
    )
    float_tolerance = FloatField("Float Tolerance (e.g. 0.000001)", default=1e-6, validators=[Optional()])
    checker_code = TextAreaField("Custom Checker Python Code", validators=[Optional()])
    scoring_mode = SelectField(
        "Scoring Mode",
        choices=[
            ("per_test", "Per-Test Partial Marks"),
            ("all_or_nothing", "All or Nothing (100% or 0)"),
            ("grouped", "Grouped Subtasks"),
        ],
        default="per_test",
    )
    submit = SubmitField("Save Problem")


class TestForm(FlaskForm):
    """Form to create or edit a single test case."""
    order_num = IntegerField("Order Number", default=1, validators=[DataRequired(), NumberRange(min=1)])
    input_data = TextAreaField("Standard Input (stdin)", validators=[DataRequired()])
    expected_output = TextAreaField("Expected Output (stdout)", validators=[DataRequired()])
    marks = FloatField("Marks", default=10.0, validators=[DataRequired(), NumberRange(min=0.0)])
    is_hidden = BooleanField("Hidden Test (Only verdict shown to students, diff obscured)")
    subtask_id = StringField("Subtask Group ID (optional)", validators=[Optional(), Length(max=64)])
    explanation = TextAreaField("Explanation / Sample Notes (optional)", validators=[Optional()])
    submit = SubmitField("Save Test Case")


class ZipUploadForm(FlaskForm):
    """Form to upload test cases as a ZIP archive."""
    zip_file = FileField("ZIP File", validators=[FileRequired(), FileAllowed(["zip"], "ZIP files only.")])
    default_marks = FloatField("Default Marks per Test", default=10.0, validators=[DataRequired(), NumberRange(min=0.0)])
    visibility_mode = SelectField(
        "Test Visibility",
        choices=[
            ("auto", "Auto-detect (file names containing 'hidden' will be hidden)"),
            ("all_visible", "All Visible"),
            ("all_hidden", "All Hidden"),
        ],
        default="auto",
    )
    overwrite = BooleanField("Replace existing test cases (delete old tests first)", default=False)
    submit = SubmitField("Upload and Import Tests")


class ClassForm(FlaskForm):
    """Form to create or edit a Class."""
    name = StringField("Class Name", validators=[DataRequired(), Length(max=128)], render_kw={"placeholder": "e.g. BSCS Fall 2024 - Section A"})
    code = StringField("Class Code (Unique)", validators=[DataRequired(), Length(max=32)], render_kw={"placeholder": "e.g. CS101-FA24"})
    description = TextAreaField("Description", validators=[Optional()], render_kw={"rows": 3})
    submit = SubmitField("Save Class")


class StudentImportForm(FlaskForm):
    """Form to bulk import students via CSV upload or pasted text."""
    csv_file = FileField("Upload CSV File", validators=[Optional(), FileAllowed(["csv", "txt"], "CSV or TXT files only.")])
    csv_text = TextAreaField("Or Paste CSV Text (Columns: roll_no, name)", validators=[Optional()], render_kw={"rows": 6, "placeholder": "roll_no,name\nBCSF20M001,Alice Johnson\nBCSF20M002,Bob Smith"})
    submit = SubmitField("Import Students")


class AssignmentForm(FlaskForm):
    """Form to create or edit an Assignment."""
    class_id = SelectField("Class", coerce=int, validators=[DataRequired()])
    problem_ids = SelectMultipleField("Problems in Assignment", coerce=int, validators=[Optional()])
    problem_id = SelectField("Problem", coerce=int, validators=[Optional()])
    title = StringField("Assignment Title", validators=[DataRequired(), Length(max=128)])
    open_date = DateTimeLocalField("Open Date & Time", format=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"], validators=[DataRequired()])
    due_date = DateTimeLocalField("Due Date & Time", format=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"], validators=[DataRequired()])
    max_attempts = IntegerField("Max Attempts (0 for unlimited)", default=0, validators=[NumberRange(min=0)])
    late_penalty_percent = FloatField("Late Penalty % (0 - 100)", default=0.0, validators=[NumberRange(min=0.0, max=100.0)])
    allow_late = BooleanField("Allow Late Submissions", default=True)
    submit = SubmitField("Save Assignment")
