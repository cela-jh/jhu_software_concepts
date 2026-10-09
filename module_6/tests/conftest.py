"""
`conftest.py`
Shared pytest fixtures for the GradCafeAnalytics test suite. Puts both
src/web/ and src/worker/ on the import path so tests can import `app`,
`database`, `publisher`, and `etl` the same way the services do at runtime.
"""
import getpass
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "web"
WORKER_SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "worker"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(WORKER_SRC_DIR))

import pytest

from app import create_app
from database.db_helpers import connect_db, disconnect_db

TEST_DATABASE_NAME = "cam_db_test"


def _build_test_database_url():
    """
    Resolve the test database URL from the environment, always forcing
    the database name to cam_db_test so the suite never touches real data.

    Priority order:
    1. DATABASE_URL already set: substitute cam_db_test as the database name.
    2. POSTGRES_* vars set (matches .env.example): build from those with
       localhost:5432 as the host.
    3. DB_* vars (legacy CI / module_5 path): build from those.
    4. Defaults: localhost, OS username, no password.

    :returns: Connection URL pointing at cam_db_test.
    :rtype: str
    """
    import re as _re

    if "DATABASE_URL" in os.environ:
        url = _re.sub(r"/[^/]+$", f"/{TEST_DATABASE_NAME}", os.environ["DATABASE_URL"])
        os.environ["DATABASE_URL"] = url
        return url

    # POSTGRES_* are the credential source of truth in .env.example.
    pg_user = os.getenv("POSTGRES_USER")
    pg_pass = os.getenv("POSTGRES_PASSWORD")
    pg_db = os.getenv("POSTGRES_DB")
    if pg_user or pg_pass or pg_db:
        user = pg_user or getpass.getuser()
        password = quote_plus(pg_pass or "")
        auth = f"{user}:{password}@" if password else f"{user}@"
        return f"postgresql://{auth}localhost:5432/{TEST_DATABASE_NAME}"

    # Legacy DB_* path: used by CI service containers and module_5 setups.
    defaults = {
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_USER": getpass.getuser(),
        "DB_PASSWORD": "",
    }
    for name, default in defaults.items():
        os.environ.setdefault(name, default)
    os.environ["DB_NAME"] = TEST_DATABASE_NAME

    from database.db_helpers import database_url_from_env
    return database_url_from_env()


TEST_DATABASE_URL = _build_test_database_url()


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
