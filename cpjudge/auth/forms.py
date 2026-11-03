"""WTForms models for authentication."""
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length


class LoginForm(FlaskForm):
    """User login form."""
    username = StringField(
        "Username or Roll Number",
        validators=[DataRequired(message="Please enter your username or roll number."), Length(max=64)],
        render_kw={"placeholder": "e.g. teacher or bcsf20m001", "autofocus": True},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Please enter your password.")],
        render_kw={"placeholder": "Enter your password"},
    )
    remember = BooleanField("Remember Me")
    submit = SubmitField("Sign In")


class ChangePasswordForm(FlaskForm):
    """Password change form."""
    current_password = PasswordField(
        "Current Password",
        validators=[DataRequired(message="Current password is required.")],
        render_kw={"placeholder": "Enter current password"},
    )
    new_password = PasswordField(
        "New Password",
        validators=[
            DataRequired(message="New password is required."),
            Length(min=6, message="New password must be at least 6 characters."),
        ],
        render_kw={"placeholder": "At least 6 characters"},
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[
            DataRequired(message="Please confirm your new password."),
            EqualTo("new_password", message="Passwords do not match."),
        ],
        render_kw={"placeholder": "Repeat new password"},
    )
    submit = SubmitField("Update Password")
