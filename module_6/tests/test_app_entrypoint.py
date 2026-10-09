"""
`test_app_entrypoint.py`
Exercises run.py's top-level imports and the Flask app it exposes.
In module_6, run.py no longer manages a Chrome subprocess or imports
pull_control; it binds 0.0.0.0:8080 and reads FLASK_SECRET from the
environment.
"""
import pytest

import run


@pytest.mark.web
def test_app_entrypoint_imports_cleanly():
    """run.py's module-level imports must resolve without error. The
    __main__ guard is never entered here since this loads it as an
    ordinary module."""
    assert hasattr(run, "app")


@pytest.mark.web
def test_app_is_a_flask_app():
    """The app attribute on run must be a Flask application instance."""
    from flask import Flask
    assert isinstance(run.app, Flask)


@pytest.mark.web
def test_run_does_not_expose_pull_control():
    """pull_control was removed from run.py in module_6 because the web
    service no longer manages data-pull subprocesses."""
    assert not hasattr(run, "pull_control")
