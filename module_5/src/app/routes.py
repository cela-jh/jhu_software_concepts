"""
`routes.py`
The analysis page route, and the Pull Data / Update Analysis endpoints
behind its two buttons.
"""
import contextlib
import io
import os

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy.exc import OperationalError

from database.db_helpers import (
    DatabaseConfigError, DatabaseUnavailableError, database_url_from_env,
)
from database.load_data import load_data
from database.models import get_session
from database.orm_queries import ALL_ORM_ANSWERS
from database.query_data import (
    ACCEPTED_SINCE_QUESTION, ACCEPTED_SINCE_YEAR, DEFAULT_SCHOOL, MAX_SCHOOL_LENGTH,
    NO_ACCEPTED_RESULTS, QUESTION_QUERY, InvalidSchoolInput, fetch_accepted_since,
    normalize_school,
)
from paths import DEFAULT_DATA_FILE

from . import pull_control

bp = Blueprint("analysis", __name__)

DATABASE_UNAVAILABLE_MESSAGE = (
    "The database is currently unavailable. Please check that "
    "PostgreSQL is running and reachable, then try again."
)


def _database_url():
    """
    Build the connection URL from the DB_* environment variables, or
    explain what is missing instead of raising.

    :returns: A (connection URL, None) pair, or (None, message) naming
        the missing or invalid variables.
    :rtype: tuple(str or None, str or None)
    """
    try:
        return database_url_from_env(), None
    except DatabaseConfigError as error:
        return None, str(error)


@bp.route("/analysis")
def analysis():
    """
    Run every Part 2 analysis question through the SQLAlchemy ORM and
    render the results page, along with the Pull Data status so a page
    reload during a pull still shows the Cancel button and its log.

    :returns: The rendered analysis page; a plain 500 error message if
        a DB_* variable isn't set; or a plain, readable 503 "database
        unavailable" message if PostgreSQL can't actually be reached
        (e.g. it's down), rather than an unhandled 500.
    :rtype: str or tuple(str, int)
    """
    database_url, problem = _database_url()
    if problem:
        return problem, 500

    session = get_session(database_url)
    try:
        questions = [question for question, _, _ in QUESTION_QUERY]
        answers = [answer_fn(session) for answer_fn in ALL_ORM_ANSWERS]
        accepted_rows = fetch_accepted_since(database_url, DEFAULT_SCHOOL)
    except (OperationalError, DatabaseUnavailableError):
        return DATABASE_UNAVAILABLE_MESSAGE, 503
    finally:
        session.close()

    return render_template(
        "analysis.html",
        results=list(zip(questions, answers)),
        accepted_question=ACCEPTED_SINCE_QUESTION,
        accepted_rows=accepted_rows or [NO_ACCEPTED_RESULTS],
        default_school=DEFAULT_SCHOOL,
        max_school_length=MAX_SCHOOL_LENGTH,
        pull_running=pull_control.is_running(),
        pull_lines=pull_control.recent_lines(),
    )


@bp.route(f"/analysis/accepted-since-{ACCEPTED_SINCE_YEAR}")
def accepted_since():
    """
    Re-run only the A3 query for the school typed into its text box. The
    `school` query argument is validated by normalize_school() and then
    only ever reaches PostgreSQL as a bound parameter.

    :returns: JSON ``{ok, school, rows, message}``: 200 with the
        matching result lines (at most the enforced query limit); 400
        with ``ok`` ``False`` if the school name is invalid; 500 if a
        DB_* variable isn't set; 503 if PostgreSQL can't be reached.
    :rtype: tuple(flask.Response, int)
    """
    database_url, problem = _database_url()
    if problem:
        return jsonify(ok=False, message=problem), 500

    try:
        school = normalize_school(request.args.get("school"))
        rows = fetch_accepted_since(database_url, school)
    except InvalidSchoolInput as error:
        return jsonify(ok=False, message=str(error)), 400
    except DatabaseUnavailableError:
        return jsonify(ok=False, message=DATABASE_UNAVAILABLE_MESSAGE), 503

    message = f"{len(rows)} results." if rows else NO_ACCEPTED_RESULTS
    return jsonify(ok=True, school=school, rows=rows, message=message), 200


@bp.route("/pull-data", methods=["POST"])
def pull_start():
    """
    Start a Grad Cafe pull in the background if one isn't already
    running.

    :returns: JSON ``{ok, status, message}``. ``ok``/``status`` are
        ``True``/``"started"`` on success, or ``ok`` ``False`` with
        status ``"error"`` if CHROME_BINARY or a DB_* variable isn't set.
        409 with ``ok`` ``False``, ``busy`` ``True``, and status
        ``"already_running"`` if a pull is already in progress.
    :rtype: flask.Response or tuple(flask.Response, int)
    """
    chrome_binary = os.getenv("CHROME_BINARY")
    if not chrome_binary:
        return jsonify(ok=False, status="error", message=(
            "Set the CHROME_BINARY environment variable to your Chrome "
            "binary's path before using Pull Data."
        ))

    database_url, problem = _database_url()
    if problem:
        return jsonify(ok=False, status="error", message=problem)

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
    Cancel the running pull, if the scrape itself is still going.
    Whatever it already collected is still uploaded to PostgreSQL
    afterward.

    :returns: JSON ``{status, message}``, where ``status`` is
        ``"cancelling"``, ``"finishing"``, or ``"not_running"``.
    :rtype: flask.Response
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
    Report whether a pull is currently running and its most recent
    status lines, for the page to poll while a pull is active.

    :returns: JSON ``{running, lines}``.
    :rtype: flask.Response
    """
    return jsonify(running=pull_control.is_running(), lines=pull_control.recent_lines())


@bp.route("/update-analysis", methods=["POST"])
def update_analysis():
    """
    Load whatever is currently in the results file into PostgreSQL (the
    same upsert load_data() always does) so data added by hand, by the
    LLM standardizer, or by a finished pull is reflected without
    starting a new scrape. analysis() already runs fresh queries on
    every GET /analysis, so the client reloads afterward to see the
    results. Busy-gated like Pull Data since a running pull's own upload
    step already owns the same table.

    :returns: JSON ``{ok, status, message}``. 409 with ``ok`` ``False``,
        ``busy`` ``True``, and status ``"busy"`` if a pull is running;
        500 with ``ok`` ``False`` and status ``"error"`` if a DB_*
        variable isn't set; otherwise 200 with ``ok`` ``True``,
        status ``"ok"``, and load_data()'s own summary as the message.
    :rtype: flask.Response or tuple(flask.Response, int)
    """
    if pull_control.is_running():
        return jsonify(ok=False, busy=True, status="busy", message=(
            "New data is currently being retrieved. Please wait for the "
            "pull to finish before updating."
        )), 409

    database_url, problem = _database_url()
    if problem:
        return jsonify(ok=False, status="error", message=problem), 500

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        load_data(DEFAULT_DATA_FILE, database_url)

    return jsonify(ok=True, status="ok", message=buffer.getvalue().strip() or "Analysis updated.")
