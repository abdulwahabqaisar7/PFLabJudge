"""Student route handlers for CPJudge."""
from pathlib import Path
from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select, update

from cpjudge.auth.decorators import ensure_submission_access, student_required
from cpjudge.models import (
    Assignment,
    Class,
    Enrollment,
    Problem,
    Submission,
    User,
    db,
    ensure_utc,
    utc_now,
)
from cpjudge.utils.timezone import format_pkt
from cpjudge.app import limiter
from cpjudge.student import student_bp
from cpjudge.student.forms import CodeSubmissionForm


# ==============================================================================
# DASHBOARD
# ==============================================================================

@student_bp.route("/dashboard")
@student_required
def dashboard():
    """Student dashboard displaying enrolled classes, pending assignments, and recent activity."""
    enrollments = Enrollment.query.filter_by(user_id=current_user.id).all()
    class_ids = [e.class_id for e in enrollments]

    # Active and upcoming assignments
    assignments = (
        Assignment.query.filter(Assignment.class_id.in_(class_ids))
        .order_by(Assignment.due_date.asc())
        .all()
        if class_ids
        else []
    )

    # Recent submissions by this student
    recent_submissions = (
        Submission.query.filter_by(user_id=current_user.id)
        .order_by(Submission.created_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "student/dashboard.html",
        enrollments=enrollments,
        assignments=assignments,
        recent_submissions=recent_submissions,
    )


# ==============================================================================
# ASSIGNMENTS
# ==============================================================================

@student_bp.route("/assignments")
@student_required
def assignments():
    """Lists all assignments available to the student across their enrolled classes."""
    enrollments = Enrollment.query.filter_by(user_id=current_user.id).all()
    class_ids = [e.class_id for e in enrollments]

    all_assignments = (
        Assignment.query.filter(Assignment.class_id.in_(class_ids))
        .order_by(Assignment.due_date.desc())
        .all()
        if class_ids
        else []
    )

    # Attach student's submission count and best score for each assignment
    assignment_stats = {}
    for a in all_assignments:
        all_subs = (
            Submission.query.filter_by(user_id=current_user.id, assignment_id=a.id)
            .order_by(Submission.created_at.desc())
            .all()
        )
        problems = a.problems
        if problems:
            has_any_score = False
            total_best_score = 0.0
            best_problem_submissions = []
            for p in problems:
                p_subs = [s for s in all_subs if s.problem_id == p.id]
                scored_subs = [s for s in p_subs if s.has_current_score]
                if scored_subs:
                    has_any_score = True
                    best_submission = max(
                        scored_subs,
                        key=lambda s: (
                            s.score.final_score,
                            s.verdict == "AC",
                        ),
                    )
                    total_best_score += best_submission.score.final_score
                    best_problem_submissions.append(best_submission)
            best_score = round(total_best_score, 1) if has_any_score else None
            if len(problems) == 1:
                best_verdict = (
                    best_problem_submissions[0].verdict
                    if best_problem_submissions
                    else (all_subs[0].verdict if all_subs else None)
                )
            elif best_problem_submissions and all(
                submission.verdict == "AC" for submission in best_problem_submissions
            ) and len(best_problem_submissions) == len(problems):
                best_verdict = "AC"
            else:
                best_verdict = None
        else:
            scored_subs = [s for s in all_subs if s.has_current_score]
            best_submission = max(
                scored_subs,
                key=lambda s: (s.score.final_score, s.verdict == "AC"),
                default=None,
            )
            best_score = best_submission.score.final_score if best_submission else None
            best_verdict = (
                best_submission.verdict if best_submission else
                (all_subs[0].verdict if all_subs else None)
            )

        assignment_stats[a.id] = {
            "attempts": len(all_subs),
            "best_score": best_score,
            "best_verdict": best_verdict,
        }

    return render_template(
        "student/assignments.html",
        assignments=all_assignments,
        stats=assignment_stats,
    )


@student_bp.route("/assignments/<int:assignment_id>")
@student_required
def assignment_detail(assignment_id: int):
    """Assignment overview listing all problems in the assignment with per-problem progress."""
    assignment = db.session.get(Assignment, assignment_id)
    if not assignment:
        abort(404)

    # Verify student is enrolled in the class offering this assignment
    enrolled = Enrollment.query.filter_by(user_id=current_user.id, class_id=assignment.class_id).first()
    if not enrolled:
        abort(403, description="You are not enrolled in the class for this assignment.")

    problems = assignment.problems
    problem_stats = []
    total_earned = 0.0

    for prob in problems:
        subs = (
            Submission.query.filter_by(
                user_id=current_user.id,
                assignment_id=assignment.id,
                problem_id=prob.id,
            )
            .order_by(Submission.created_at.desc())
            .all()
        )
        scored_subs = [s for s in subs if s.has_current_score]
        best_submission = max(
            scored_subs,
            key=lambda s: (s.score.final_score, s.verdict == "AC"),
            default=None,
        )
        best_score = best_submission.score.final_score if best_submission else None
        best_verdict = (
            best_submission.verdict if best_submission else
            (subs[0].verdict if subs else None)
        )
        if best_score is not None:
            total_earned += best_score

        problem_stats.append({
            "problem": prob,
            "attempts": len(subs),
            "best_verdict": best_verdict,
            "best_score": best_score,
        })

    return render_template(
        "student/assignment_detail.html",
        assignment=assignment,
        problem_stats=problem_stats,
        total_earned=round(total_earned, 1),
    )


# ==============================================================================
# PROBLEM SOLVING & SUBMISSION
# ==============================================================================

@student_bp.route("/assignments/<int:assignment_id>/problem", methods=["GET", "POST"])
@student_bp.route("/assignments/<int:assignment_id>/problems/<int:problem_id>", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
@student_required
def assignment_problem(assignment_id: int, problem_id: int | None = None):
    """Problem statement view and submission portal for a specific assignment problem."""
    assignment = db.session.get(Assignment, assignment_id)
    if not assignment:
        abort(404)

    # Verify student is enrolled in the class offering this assignment
    enrolled = Enrollment.query.filter_by(user_id=current_user.id, class_id=assignment.class_id).first()
    if not enrolled:
        abort(403, description="You are not enrolled in the class for this assignment.")

    problems = assignment.problems
    if not problems:
        abort(404, description="No problems associated with this assignment.")

    if problem_id is not None:
        problem = next((p for p in problems if p.id == problem_id), None)
        if not problem:
            abort(404, description="Problem not found in this assignment.")
    else:
        problem = problems[0]

    now = utc_now()

    # Check assignment availability
    open_dt = ensure_utc(assignment.open_date)
    is_not_open = bool(open_dt and now < open_dt)
    is_past_due = assignment.is_late(now)
    can_submit = True
    notice_message = None
    notice_type = "info"

    if is_not_open:
        can_submit = False
        notice_message = f"This assignment opens on {format_pkt(assignment.open_date, '%Y-%m-%d %H:%M PKT')}."
        notice_type = "secondary"
    elif is_past_due and not assignment.allow_late:
        can_submit = False
        notice_message = f"This assignment closed on {format_pkt(assignment.due_date, '%Y-%m-%d %H:%M PKT')}. Late submissions are not accepted."
        notice_type = "danger"
    elif is_past_due and assignment.allow_late:
        notice_message = f"Deadline has passed ({format_pkt(assignment.due_date, '%Y-%m-%d %H:%M PKT')}). Late submission penalty of {assignment.late_penalty_percent}% will be applied."
        notice_type = "warning"

    # Check max attempts limit for this specific problem
    if request.method == "POST":
        if db.engine.dialect.name == "sqlite":
            db.session.execute(
                update(Assignment)
                .where(Assignment.id == assignment.id)
                .values(id=Assignment.id, updated_at=Assignment.updated_at)
            )
        else:
            db.session.execute(
                select(Assignment.id)
                .where(Assignment.id == assignment.id)
                .with_for_update()
            )

    attempts_made = Submission.query.filter_by(
        user_id=current_user.id,
        assignment_id=assignment.id,
        problem_id=problem.id,
    ).count()
    if assignment.max_attempts > 0 and attempts_made >= assignment.max_attempts:
        can_submit = False
        notice_message = f"You have reached the maximum allowed attempts ({assignment.max_attempts}) for this problem."
        notice_type = "warning"

    form = CodeSubmissionForm()

    if request.method == "POST" and can_submit:
        if form.validate_on_submit():
            code = ""
            lang = form.language.data

            # Check if file was uploaded
            if form.code_file.data:
                file_obj = form.code_file.data
                filename = file_obj.filename.lower()
                # Auto-detect language if obvious from extension
                if filename.endswith(".py"):
                    lang = "python"
                elif filename.endswith((".cpp", ".cc", ".cxx")):
                    lang = "cpp"
                elif filename.endswith(".c"):
                    lang = "c"

                raw_bytes = file_obj.read()
                if len(raw_bytes) > 64 * 1024:
                    flash("Uploaded file exceeds the 64 KB size limit.", "danger")
                    return redirect(request.url)
                code = raw_bytes.decode("utf-8", errors="replace")
            elif form.source_code.data:
                code = form.source_code.data

            code_clean = code.strip()
            if not code_clean:
                flash("Please provide your code either by typing/pasting or uploading a source file.", "danger")
                return redirect(request.url)

            if len(code_clean.encode("utf-8")) > 64 * 1024:
                flash("Source code exceeds the 64 KB size limit.", "danger")
                return redirect(request.url)

            # Create new queued submission
            submission = Submission(
                user_id=current_user.id,
                problem_id=problem.id,
                assignment_id=assignment.id,
                language=lang,
                source_code=code_clean,
                status="queued",
                tests_version=problem.tests_version,
                is_late=is_past_due,
            )
            db.session.add(submission)
            db.session.commit()

            flash("Solution submitted successfully! It has been queued for evaluation.", "success")
            return redirect(url_for("student.submission_detail", submission_id=submission.id))

    return render_template(
        "student/problem_view.html",
        problem=problem,
        assignment=assignment,
        form=form,
        can_submit=can_submit,
        notice_message=notice_message,
        notice_type=notice_type,
        attempts_made=attempts_made,
    )


# ==============================================================================
# SUBMISSION DETAIL & LIVE POLLING
# ==============================================================================

@student_bp.route("/submissions/<int:submission_id>")
@student_required
def submission_detail(submission_id: int):
    """Submission detail page with live 2-second status polling and masked hidden tests."""
    submission = db.session.get(Submission, submission_id)
    if not submission:
        abort(404)

    # Server-side ownership check: students can ONLY view their own submissions!
    ensure_submission_access(submission)

    return render_template(
        "student/submission_detail.html",
        submission=submission,
    )


@student_bp.route("/submissions/<int:submission_id>/status")
@student_required
def submission_status(submission_id: int):
    """JSON polling endpoint returning submission evaluation status every 2 seconds."""
    submission = db.session.get(Submission, submission_id)
    if not submission:
        abort(404)

    # Strict server-side ownership enforcement
    ensure_submission_access(submission)

    return jsonify({
        "id": submission.id,
        "status": submission.status,
        "verdict": submission.verdict,
        "is_done": submission.status in ("done", "error"),
        "final_score": submission.score.final_score if submission.score else None,
        "max_score": submission.score.max_possible_score if submission.score else None,
    })


# ==============================================================================
# SUBMISSION HISTORY
# ==============================================================================

@student_bp.route("/history")
@student_required
def history():
    """Lists the authenticated student's full submission history with filters."""
    query = Submission.query.filter_by(user_id=current_user.id)

    problem_id = request.args.get("problem_id", type=int)
    assignment_id = request.args.get("assignment_id", type=int)
    verdict = request.args.get("verdict")

    if problem_id:
        query = query.filter_by(problem_id=problem_id)
    if assignment_id:
        query = query.filter_by(assignment_id=assignment_id)
    if verdict:
        query = query.filter_by(verdict=verdict)

    submissions_list = query.order_by(Submission.created_at.desc()).all()

    # Get problems the student has submitted to for filter dropdown
    student_problems = (
        Problem.query.join(Submission, Submission.problem_id == Problem.id)
        .filter(Submission.user_id == current_user.id)
        .distinct()
        .all()
    )

    return render_template(
        "student/history.html",
        submissions=submissions_list,
        problems=student_problems,
        selected_problem=problem_id,
        selected_assignment=assignment_id,
        selected_verdict=verdict,
    )
