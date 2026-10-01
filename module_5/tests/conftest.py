"""
`conftest.py`
Shared pytest fixtures for the GradCafeAnalytics test suite. Puts
src/ on the import path so tests can import `app`, `database`,
`scraping`, and `paths` the same way the application itself does when
run.py is run directly, then hands out a fresh Flask app and test
client per test.
"""
import getpass
import os
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import pytest

from app import create_app
from app import pull_control
from database.db_helpers import connect_db, database_url_from_env, disconnect_db

# The disposable cam_db_test database, never cam_db's real data: DB_NAME
# is always forced to it, whatever the shell exports. Host, port, user,
# and password come from DB_* when set (as CI sets them for its own
# Postgres service container); otherwise they default to a local server
# with trust auth, which authenticates by OS user name and ignores the
# password. The user default comes from the OS rather than a hardcoded
# name so this works on whatever machine the suite runs on.
TEST_DATABASE_NAME = "cam_db_test"
TEST_DB_DEFAULTS = {
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_USER": getpass.getuser(),
    "DB_PASSWORD": "",
}

# Set once for the whole session; db_helpers reads the DB_* variables at
# call time (not at import time), so this just needs to be in place
# before any test actually makes a request or opens a connection.
for _name, _default in TEST_DB_DEFAULTS.items():
    os.environ.setdefault(_name, _default)
os.environ["DB_NAME"] = TEST_DATABASE_NAME
TEST_DATABASE_URL = database_url_from_env()


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
        pull_control._state.process = None
        pull_control._state.thread = None
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
def database_url():
    """The disposable test database's connection URL."""
    return TEST_DATABASE_URL


@pytest.fixture
def db_connection(database_url):
    """
    Connects to cam_db_test and truncates the applicants table before
    and after the test, so every db-marked test starts and ends with an
    empty table regardless of what other tests did.
    Refuses to run at all if the connection somehow isn't pointed at the
    disposable test database, so a broken override can never truncate
    real data.
    """
    assert "cam_db_test" in database_url, (
        "Refusing to run db tests against a non-test database: "
        f"the connection URL is {database_url!r}"
    )

    conn = connect_db(database_url)
    assert conn is not None, "Could not connect to cam_db_test"

    conn.execute("TRUNCATE applicants")
    conn.commit()

    yield conn

    conn.execute("TRUNCATE applicants")
    conn.commit()
    disconnect_db(conn)
