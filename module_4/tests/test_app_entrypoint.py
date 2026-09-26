"""
`test_app_entrypoint.py`
Exercises run.py's own top-level imports and its --file CLI flag.
"""
import pytest

import run


@pytest.mark.web
def test_app_entrypoint_imports_cleanly():
    """run.py's module-level imports (the Flask app package, pull_control,
    and routes) must resolve without error. Its __main__ guard is never
    entered here, since this loads it as an ordinary module."""
    assert hasattr(run, "app")
    assert hasattr(run.pull_control, "kill_stale_chrome")
    assert hasattr(run.routes, "DEFAULT_DATA_FILE")


@pytest.mark.web
def test_parse_args_defaults_to_default_data_file(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run.py"])

    args = run.parse_args()

    assert args.file == run.DEFAULT_DATA_FILE


@pytest.mark.web
def test_parse_args_accepts_explicit_file(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run.py", "--file", "custom_file.json"])

    args = run.parse_args()

    assert str(args.file) == "custom_file.json"
