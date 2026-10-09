"""
`test_buttons.py`
Verifies the Pull Data and Update Analysis endpoints under module_6's
stub pull_control. In module_6, Pull Data enqueues a task via RabbitMQ
(Section 4); until then the stub's start() always returns False, so the
endpoint always responds 409 when CHROME_BINARY is set. Update Analysis
still calls load_data directly (also replaced in Section 4).
"""
import pytest

from app import pull_control


@pytest.mark.buttons
def test_pull_start_returns_error_when_chrome_binary_missing(client, monkeypatch):
    """POST /pull-data should report a clear error when CHROME_BINARY
    is not set, without touching pull_control at all."""
    monkeypatch.delenv("CHROME_BINARY", raising=False)

    response = client.post("/pull-data")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is False
    assert body["status"] == "error"
    assert "CHROME_BINARY" in body["message"]


@pytest.mark.buttons
def test_pull_start_returns_409_stub_never_starts(client, monkeypatch):
    """POST /pull-data with CHROME_BINARY set returns 409 in module_6
    because the stub's start() always returns False (tasks are queued
    via RabbitMQ, not spawned in-process)."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")

    response = client.post("/pull-data")

    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert body["busy"] is True
    assert body["status"] == "already_running"


@pytest.mark.buttons
def test_pull_start_returns_error_when_database_unconfigured(client, monkeypatch):
    """POST /pull-data should report a clear error when DATABASE_URL and
    all DB_* variables are absent."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for var in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"):
        monkeypatch.delenv(var, raising=False)

    response = client.post("/pull-data")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is False
    assert body["status"] == "error"


@pytest.mark.buttons
def test_update_analysis_returns_200_when_idle(client, monkeypatch):
    """POST /update-analysis should load the current data file and
    return 200 when no pull is running."""
    monkeypatch.setattr("app.routes.load_data", lambda filepath, url: True)

    response = client.post("/update-analysis")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["status"] == "ok"


@pytest.mark.buttons
def test_update_analysis_returns_error_when_database_unconfigured(client, monkeypatch):
    """POST /update-analysis should return 500 when DATABASE_URL and
    all DB_* variables are absent."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for var in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"):
        monkeypatch.delenv(var, raising=False)
    load_calls = []
    monkeypatch.setattr(
        "app.routes.load_data",
        lambda filepath, url: load_calls.append((filepath, url)),
    )

    response = client.post("/update-analysis")

    assert response.status_code == 500
    body = response.get_json()
    assert body["ok"] is False
    assert body["status"] == "error"
    assert load_calls == []


@pytest.mark.buttons
def test_pull_cancel_route_reports_not_running_when_idle(client):
    """POST /pull/cancel with no pull active should report "not_running"
    through the real HTTP route."""
    response = client.post("/pull/cancel")

    assert response.status_code == 200
    assert response.get_json()["status"] == "not_running"


@pytest.mark.buttons
def test_pull_status_route_reports_idle_state(client):
    """GET /pull/status with no pull active should report running=False
    and an empty log."""
    response = client.get("/pull/status")

    assert response.status_code == 200
    body = response.get_json()
    assert body["running"] is False
    assert body["lines"] == []


@pytest.mark.buttons
def test_pull_start_returns_ok_when_start_succeeds(client, monkeypatch):
    """POST /pull-data should return 200 ok when start() returns True.
    In module_6 start() is a stub, but the route's success branch must be
    reachable once Section 4 replaces the stub."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.setattr(pull_control, "start", lambda *a, **kw: True)

    response = client.post("/pull-data")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["status"] == "started"


@pytest.mark.buttons
def test_update_analysis_returns_409_when_pull_is_running(client, monkeypatch):
    """POST /update-analysis should return 409 when is_running() is True
    so callers know to wait before reloading data."""
    monkeypatch.setattr(pull_control, "is_running", lambda: True)
    monkeypatch.setattr("app.routes.load_data", lambda filepath, url: True)

    response = client.post("/update-analysis")

    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert body["status"] == "busy"
