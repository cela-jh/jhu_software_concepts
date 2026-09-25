"""
`test_app_entrypoint.py`
Exercises app.py's own top-level imports and its --file CLI flag. app.py
and the app/ package share the name "app", so app.py the file is never
reachable through a normal `import app` (Python always resolves that to
the package) - it's loaded here by file path instead, the same way
Python loads it when run directly, minus actually starting a dev server.
"""
import importlib.util
from pathlib import Path

import pytest

APP_ENTRYPOINT = Path(__file__).resolve().parent.parent / "src" / "GradCafeAnalytics" / "app.py"


def _load_app_entrypoint():
    spec = importlib.util.spec_from_file_location("app_entrypoint", APP_ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.web
def test_app_entrypoint_imports_cleanly():
    """app.py's module-level imports (the Flask app package, pull_control,
    and routes) must resolve without error. Its __main__ guard is never
    entered here, since this loads it as an ordinary module."""
    module = _load_app_entrypoint()

    assert hasattr(module, "app")
    assert hasattr(module.pull_control, "kill_stale_chrome")
    assert hasattr(module.routes, "DEFAULT_DATA_FILE")


@pytest.mark.web
def test_parse_args_defaults_to_default_data_file(monkeypatch):
    module = _load_app_entrypoint()
    monkeypatch.setattr("sys.argv", ["app.py"])

    args = module.parse_args()

    assert args.file == module.DEFAULT_DATA_FILE


@pytest.mark.web
def test_parse_args_accepts_explicit_file(monkeypatch):
    module = _load_app_entrypoint()
    monkeypatch.setattr("sys.argv", ["app.py", "--file", "custom_file.json"])

    args = module.parse_args()

    assert str(args.file) == "custom_file.json"
