"""
`conftest.py`
Shared pytest fixtures for the GradCafeAnalytics test suite. Puts
src/GradCafeAnalytics on the import path so tests can import `app`,
`database`, `scraping`, and `paths` the same way the application itself
does when app.py is run directly, then hands out a fresh Flask app and
test client per test.
"""
import os
import sys
from pathlib import Path

# Must be set before anything below imports database.db_helpers (which
# reads PGDATABASE at import time into CONN_PARAMS), so the whole test
# session talks to the disposable cam_db_test database, never cam_db's
# real data.
os.environ["PGDATABASE"] = "cam_db_test"

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "GradCafeAnalytics"
sys.path.insert(0, str(SRC_DIR))

import pytest

from app import create_app
from app import pull_control
from database.db_helpers import CONN_PARAMS, connect_db, disconnect_db

TEST_DB_CREDENTIALS = ("cameronela", "test_password")


@pytest.fixture
def app():
    """Returns a fresh Flask app instance for a single test."""
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    """Returns a Flask test client bound to the `app` fixture."""
    return app.test_client()


def _reset_pull_control_state():
    with pull_control._lock:
        pull_control._process = None
        pull_control._thread = None
        pull_control._lines.clear()


@pytest.fixture(autouse=True)
def reset_pull_control():
    """
    Resets pull_control's module-level pull-tracking state before and
    after every test. That state is shared across the whole process, so
    without this a pull left "running" by one test would leak into the
    next regardless of test order (pytest-randomly).
    """
    _reset_pull_control_state()
    yield
    _reset_pull_control_state()


@pytest.fixture
def db_credentials():
    """(user, password) for the local trust-authed cam_db_test database.
    The password value itself is ignored by trust auth; it only needs to
    be non-empty, since _pg_credentials()-style checks elsewhere treat an
    empty string the same as unset."""
    return TEST_DB_CREDENTIALS


@pytest.fixture
def db_connection(db_credentials):
    """
    Connects to cam_db_test and truncates the applicants table before
    and after the test, so every db-marked test starts and ends with an
    empty table regardless of what other tests did.
    Refuses to run at all if CONN_PARAMS somehow isn't pointed at the
    disposable test database, so a broken PGDATABASE override can never
    truncate real data.
    """
    assert CONN_PARAMS["dbname"] == "cam_db_test", (
        "Refusing to run db tests against a non-test database: "
        f"CONN_PARAMS['dbname'] is {CONN_PARAMS['dbname']!r}"
    )

    conn = connect_db(CONN_PARAMS, db_credentials)
    assert conn is not None, "Could not connect to cam_db_test"

    conn.execute("TRUNCATE applicants")
    conn.commit()

    yield conn

    conn.execute("TRUNCATE applicants")
    conn.commit()
    disconnect_db(conn)
