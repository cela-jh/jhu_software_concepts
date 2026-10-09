"""
`test_app_entrypoint.py`
Exercises run.py's top-level imports and the Flask app it exposes.
In module_6, run.py no longer parses CLI arguments for a data file;
it simply binds 0.0.0.0:8080 and reads FLASK_SECRET from the environment.
"""
import pytest

import run


@pytest.mark.web
def test_app_entrypoint_imports_cleanly():
    """run.py's module-level imports (the Flask app and pull_control)
    must resolve without error. The __main__ guard is never entered here
    since this loads it as an ordinary module."""
    assert hasattr(run, "app")
    assert hasattr(run.pull_control, "kill_stale_chrome")


@pytest.mark.web
def test_app_is_a_flask_app():
    """The app attribute on run must be a Flask application instance."""
    from flask import Flask
    assert isinstance(run.app, Flask)


@pytest.mark.web
def test_pull_control_stub_is_loaded():
    """The pull_control stub must expose the interface routes.py uses."""
    assert callable(run.pull_control.is_running)
    assert callable(run.pull_control.recent_lines)
    assert callable(run.pull_control.start)
    assert callable(run.pull_control.cancel)
