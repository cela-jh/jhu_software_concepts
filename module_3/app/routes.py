"""
`routes.py`
The analysis page route.
"""
import os

from flask import Blueprint, render_template

from models import get_session
from orm_queries import ALL_ORM_ANSWERS
from query_data import QUESTION_QUERY

bp = Blueprint("analysis", __name__)


@bp.route("/")
def analysis():
    """
    Runs every Part 2 analysis question through the SQLAlchemy ORM and
    renders the results page.
    Returns the rendered HTML, or a plain error message if PGUSER or
    PGPASSWORD isn't set.
    """
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    if not user or not password:
        return (
            "Set the PGUSER and PGPASSWORD environment variables before "
            "running app.py, then restart the server.",
            500,
        )

    session = get_session((user, password))
    try:
        questions = [question for question, _, _ in QUESTION_QUERY]
        answers = [answer_fn(session) for answer_fn in ALL_ORM_ANSWERS]
    finally:
        session.close()

    return render_template("analysis.html", results=list(zip(questions, answers)))
