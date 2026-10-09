"""
`routes.py`
The analysis page route, and the Pull Data / Update Analysis endpoints
behind its two buttons. Both buttons publish tasks to RabbitMQ via
publisher.publish_task; the worker processes them asynchronously.
"""
from flask import Blueprint, current_app, jsonify, render_template, request
from sqlalchemy.exc import OperationalError

from database.db_helpers import (
    DatabaseConfigError, DatabaseUnavailableError, database_url_from_env,
)
from database.models import get_session
from database.orm_queries import ALL_ORM_ANSWERS
from database.query_data import (
    ACCEPTED_SINCE_QUESTION, ACCEPTED_SINCE_YEAR, DEFAULT_SCHOOL, MAX_SCHOOL_LENGTH,
    NO_ACCEPTED_RESULTS, QUESTION_QUERY, InvalidSchoolInput, fetch_accepted_since,
    normalize_school,
)
from publisher import publish_task

bp = Blueprint("analysis", __name__)

DATABASE_UNAVAILABLE_MESSAGE = (
    "The database is currently unavailable. Please check that "
    "PostgreSQL is running and reachable, then try again."
)


def _database_url():
    """
    Build the connection URL from environment variables, or explain
    what is missing instead of raising.

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
    Run every analysis question through the SQLAlchemy ORM and render
    the results page.

    :returns: The rendered analysis page; 500 if a database variable
        isn't set; 503 if PostgreSQL can't be reached.
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
    )


@bp.route(f"/analysis/accepted-since-{ACCEPTED_SINCE_YEAR}")
def accepted_since():
    """
    Re-run only the A3 query for the school typed into its text box.

    :returns: JSON ``{ok, school, rows, message}``: 200 with matching
        rows; 400 for an invalid school name; 500 if the database URL is
        misconfigured; 503 if PostgreSQL can't be reached.
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
    Enqueue a scrape_new_data task via RabbitMQ and return 202 so the
    request completes immediately while the worker processes the task.

    :returns: 202 JSON ``{ok, status, task, message}`` on success; 503
        if the broker is unreachable.
    :rtype: tuple(flask.Response, int)
    """
    try:
        publish_task("scrape_new_data")
        return jsonify(
            ok=True, status="queued", task="scrape_new_data",
            message="Pull queued. New data will be available shortly.",
        ), 202
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("Failed to publish scrape_new_data")
        return jsonify(
            ok=False, status="error",
            message="Could not queue the task. Please try again.",
        ), 503


@bp.route("/update-analysis", methods=["POST"])
def update_analysis():
    """
    Enqueue a recompute_analytics task via RabbitMQ and return 202 so
    the request completes immediately while the worker processes it.

    :returns: 202 JSON ``{ok, status, task, message}`` on success; 503
        if the broker is unreachable.
    :rtype: tuple(flask.Response, int)
    """
    try:
        publish_task("recompute_analytics")
        return jsonify(
            ok=True, status="queued", task="recompute_analytics",
            message="Analytics recompute queued. Data will be refreshed shortly.",
        ), 202
    except Exception:  # pylint: disable=broad-exception-caught
        current_app.logger.exception("Failed to publish recompute_analytics")
        return jsonify(
            ok=False, status="error",
            message="Could not queue the task. Please try again.",
        ), 503
