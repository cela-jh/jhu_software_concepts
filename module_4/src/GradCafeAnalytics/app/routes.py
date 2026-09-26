"""
`routes.py`
The analysis page route, and the Pull Data / Update Analysis endpoints
behind its two buttons.
"""
import contextlib
import io
import os

from flask import Blueprint, jsonify, render_template
from sqlalchemy.exc import OperationalError

from database.load_data import load_data
from database.models import get_session
from database.orm_queries import ALL_ORM_ANSWERS
from database.query_data import QUESTION_QUERY
from paths import DEFAULT_DATA_FILE

from . import pull_control

bp = Blueprint("analysis", __name__)


def _database_url():
    """Returns the DATABASE_URL environment variable, or None if unset."""
    return os.getenv("DATABASE_URL") or None


@bp.route("/analysis")
def analysis():
    """
    Runs every Part 2 analysis question through the SQLAlchemy ORM and
    renders the results page, along with the Pull Data status so a page
    reload during a pull still shows the Cancel button and its log.
    Returns the rendered HTML; a plain error message if DATABASE_URL
    isn't set; or a plain, readable "database unavailable" message if
    PostgreSQL can't actually be reached (e.g. it's down), rather than an
    unhandled 500.
    """
    database_url = _database_url()
    if database_url is None:
        return (
            "Set the DATABASE_URL environment variable before running "
            "run.py, then restart the server.",
            500,
        )

    session = get_session(database_url)
    try:
        questions = [question for question, _, _ in QUESTION_QUERY]
        answers = [answer_fn(session) for answer_fn in ALL_ORM_ANSWERS]
    except OperationalError:
        return (
            "The database is currently unavailable. Please check that "
            "PostgreSQL is running and reachable, then try again.",
            503,
        )
    finally:
        session.close()

    return render_template(
        "analysis.html",
        results=list(zip(questions, answers)),
        pull_running=pull_control.is_running(),
        pull_lines=pull_control.recent_lines(),
    )


@bp.route("/pull-data", methods=["POST"])
def pull_start():
    """
    Starts a Grad Cafe pull in the background if one isn't already
    running.
    Returns JSON: {ok, status, message}. ok/status are True/"started" on
    success, or ok False with status "error" if CHROME_BINARY or
    DATABASE_URL aren't set. Returns 409 with ok False, busy True, and
    status "already_running" if a pull is already in progress.
    """
    chrome_binary = os.getenv("CHROME_BINARY")
    if not chrome_binary:
        return jsonify(ok=False, status="error", message=(
            "Set the CHROME_BINARY environment variable to your Chrome "
            "binary's path before using Pull Data."
        ))

    database_url = _database_url()
    if database_url is None:
        return jsonify(ok=False, status="error", message=(
            "Set the DATABASE_URL environment variable before using Pull Data."
        ))

    started = pull_control.start(chrome_binary, database_url)
    if not started:
        return jsonify(
            ok=False, busy=True, status="already_running",
            message="A pull is already in progress.",
        ), 409
    return jsonify(ok=True, status="started", message="Pull started.")


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


@bp.route("/update-analysis", methods=["POST"])
def update_analysis():
    """
    Loads whatever is currently in the results file into PostgreSQL (the
    same upsert load_data() always does) so data added by hand, by the
    LLM standardizer, or by a finished pull is reflected without
    starting a new scrape. analysis() already runs fresh queries on
    every GET /analysis, so the client reloads afterward to see the
    results. Busy-gated like Pull Data since a running pull's own upload
    step already owns the same table.
    Returns JSON: {ok, status, message}. 409 with ok False, busy True,
    and status "busy" if a pull is running; 500 with ok False and status
    "error" if DATABASE_URL isn't set; otherwise 200 with ok True, status
    "ok", and load_data()'s own summary as the message.
    """
    if pull_control.is_running():
        return jsonify(ok=False, busy=True, status="busy", message=(
            "New data is currently being retrieved. Please wait for the "
            "pull to finish before updating."
        )), 409

    database_url = _database_url()
    if database_url is None:
        return jsonify(ok=False, status="error", message=(
            "Set the DATABASE_URL environment variable before using Update Analysis."
        )), 500

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        load_data(DEFAULT_DATA_FILE, database_url)

    return jsonify(ok=True, status="ok", message=buffer.getvalue().strip() or "Analysis updated.")
