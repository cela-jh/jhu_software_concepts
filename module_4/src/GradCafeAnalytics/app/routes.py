"""
`routes.py`
The analysis page route, and the Pull Data / Update Analysis endpoints
behind its two buttons.
"""
import os

from flask import Blueprint, jsonify, render_template

from database.models import get_session
from database.orm_queries import ALL_ORM_ANSWERS
from database.query_data import QUESTION_QUERY

from . import pull_control

bp = Blueprint("analysis", __name__)


def _pg_credentials():
    """Returns a (user, password) tuple from PGUSER/PGPASSWORD, or None if unset."""
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    if not user or not password:
        return None
    return user, password


@bp.route("/")
def analysis():
    """
    Runs every Part 2 analysis question through the SQLAlchemy ORM and
    renders the results page, along with the Pull Data status so a page
    reload during a pull still shows the Cancel button and its log.
    Returns the rendered HTML, or a plain error message if PGUSER or
    PGPASSWORD isn't set.
    """
    credentials = _pg_credentials()
    if credentials is None:
        return (
            "Set the PGUSER and PGPASSWORD environment variables before "
            "running app.py, then restart the server.",
            500,
        )

    session = get_session(credentials)
    try:
        questions = [question for question, _, _ in QUESTION_QUERY]
        answers = [answer_fn(session) for answer_fn in ALL_ORM_ANSWERS]
    finally:
        session.close()

    return render_template(
        "analysis.html",
        results=list(zip(questions, answers)),
        pull_running=pull_control.is_running(),
        pull_lines=pull_control.recent_lines(),
    )


@bp.route("/pull/start", methods=["POST"])
def pull_start():
    """
    Starts a Grad Cafe pull in the background if one isn't already
    running.
    Returns JSON: {status, message}. status is "started" or
    "already_running" on success, or "error" if CHROME_BINARY or
    PGUSER/PGPASSWORD aren't set.
    """
    chrome_binary = os.getenv("CHROME_BINARY")
    if not chrome_binary:
        return jsonify(status="error", message=(
            "Set the CHROME_BINARY environment variable to your Chrome "
            "binary's path before using Pull Data."
        ))

    credentials = _pg_credentials()
    if credentials is None:
        return jsonify(status="error", message=(
            "Set the PGUSER and PGPASSWORD environment variables before "
            "using Pull Data."
        ))

    started = pull_control.start(chrome_binary, credentials)
    if not started:
        return jsonify(status="already_running", message="A pull is already in progress.")
    return jsonify(status="started", message="Pull started.")


@bp.route("/pull/cancel", methods=["POST"])
def pull_cancel():
    """
    Cancels the running pull, if the scrape itself is still going.
    Whatever it already collected is still uploaded to PostgreSQL
    afterward.
    Returns JSON: {status, message}. status is "cancelling", "finishing",
    or "not_running".
    """
    result = pull_control.cancel()
    messages = {
        "cancelling": "Cancelling: finishing the current page and uploading collected results.",
        "finishing": "The scrape has already finished; results are still being uploaded.",
        "not_running": "No pull is currently running.",
    }
    return jsonify(status=result, message=messages[result])


@bp.route("/pull/status")
def pull_status():
    """
    Reports whether a pull is currently running and its most recent
    status lines, for the page to poll while a pull is active.
    Returns JSON: {running, lines}.
    """
    return jsonify(running=pull_control.is_running(), lines=pull_control.recent_lines())
