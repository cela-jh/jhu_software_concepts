"""
`conftest.py`
Shared pytest fixtures for the GradCafeAnalytics test suite. Puts
src/GradCafeAnalytics on the import path so tests can import `app`,
`database`, `scraping`, and `paths` the same way the application itself
does when app.py is run directly, then hands out a fresh Flask app and
test client per test.
"""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "GradCafeAnalytics"
sys.path.insert(0, str(SRC_DIR))

import pytest

from app import create_app
from app import pull_control


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
