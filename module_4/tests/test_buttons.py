"""
`test_buttons.py`
Verifies the Pull Data and Update Analysis endpoints: that Pull Data
triggers the loader with whatever the (faked) scraper produced, that
Update Analysis succeeds when idle, and that both endpoints refuse to do
anything (409) while a pull is already running.
"""
import pytest

from app import pull_control


class _FakeProcess:
    """Stands in for the subprocess.Popen scrape.py process: `stdout`
    yields the faked scraper's output lines, and `wait()` returns
    immediately since the fake process has already "finished"."""

    def __init__(self, lines):
        self.stdout = iter(lines)

    def wait(self):
        return 0


class _FakeThread:
    """A pull_control._thread stand-in that reports as still running, for
    busy-gating tests that don't need a real background thread."""

    def is_alive(self):
        return True


def _mark_pull_running():
    pull_control._thread = _FakeThread()


@pytest.mark.buttons
def test_pull_start_returns_200_and_triggers_loader(client, monkeypatch):
    """POST /pull/start should start a pull and, once the faked
    scraper finishes, hand its results off to load_data."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.setenv("PGUSER", "test_user")
    monkeypatch.setenv("PGPASSWORD", "test_password")

    fake_scraped_rows = ["row 1 scraped", "row 2 scraped"]
    monkeypatch.setattr(
        "app.pull_control.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(fake_scraped_rows),
    )

    load_calls = []
    monkeypatch.setattr(
        "app.pull_control.load_data",
        lambda filepath, credentials: load_calls.append((filepath, credentials)),
    )

    response = client.post("/pull/start")
    assert response.status_code == 200
    assert response.get_json()["status"] == "started"

    # The upload happens on a background thread; wait for it to finish
    # before checking that it ran.
    pull_control._thread.join(timeout=2)

    assert len(load_calls) == 1
    loaded_filepath, loaded_credentials = load_calls[0]
    assert loaded_filepath == pull_control.DATA_FILE
    assert loaded_credentials == ("test_user", "test_password")
    for row in fake_scraped_rows:
        assert row in pull_control.recent_lines()


@pytest.mark.buttons
def test_update_analysis_returns_200_when_idle(client, monkeypatch):
    """POST /update-analysis should load the current data file and
    return 200 when no pull is running."""
    monkeypatch.setenv("PGUSER", "test_user")
    monkeypatch.setenv("PGPASSWORD", "test_password")
    monkeypatch.setattr("app.routes.load_data", lambda filepath, credentials: None)

    response = client.post("/update-analysis")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


@pytest.mark.buttons
def test_update_analysis_returns_409_when_busy(client, monkeypatch):
    """POST /update-analysis should refuse to run, and not touch the
    database, while a pull is in progress."""
    monkeypatch.setenv("PGUSER", "test_user")
    monkeypatch.setenv("PGPASSWORD", "test_password")
    load_calls = []
    monkeypatch.setattr(
        "app.routes.load_data",
        lambda filepath, credentials: load_calls.append((filepath, credentials)),
    )
    _mark_pull_running()

    response = client.post("/update-analysis")

    assert response.status_code == 409
    assert response.get_json()["status"] == "busy"
    assert load_calls == []


@pytest.mark.buttons
def test_pull_start_returns_409_when_busy(client, monkeypatch):
    """POST /pull/start should refuse to start a second pull, and never
    launch a new scrape, while one is already running."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.setenv("PGUSER", "test_user")
    monkeypatch.setenv("PGPASSWORD", "test_password")
    popen_calls = []
    monkeypatch.setattr(
        "app.pull_control.subprocess.Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )
    _mark_pull_running()

    response = client.post("/pull/start")

    assert response.status_code == 409
    assert response.get_json()["status"] == "already_running"
    assert popen_calls == []


@pytest.mark.buttons
def test_pull_start_returns_error_when_chrome_binary_missing(client, monkeypatch):
    """POST /pull/start should report a clear error, and never touch
    pull_control at all, when CHROME_BINARY isn't set."""
    monkeypatch.delenv("CHROME_BINARY", raising=False)
    monkeypatch.setenv("PGUSER", "test_user")
    monkeypatch.setenv("PGPASSWORD", "test_password")

    response = client.post("/pull/start")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "error"
    assert "CHROME_BINARY" in body["message"]


@pytest.mark.buttons
def test_pull_start_returns_error_when_credentials_missing(client, monkeypatch):
    """POST /pull/start should report a clear error when PGUSER/
    PGPASSWORD aren't set, even with CHROME_BINARY present."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)

    response = client.post("/pull/start")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "error"
    assert "PGUSER" in body["message"]


@pytest.mark.buttons
def test_update_analysis_returns_error_when_credentials_missing(client, monkeypatch):
    """POST /update-analysis should report a clear 500 error, and never
    call load_data, when PGUSER/PGPASSWORD aren't set."""
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)
    load_calls = []
    monkeypatch.setattr(
        "app.routes.load_data",
        lambda filepath, credentials: load_calls.append((filepath, credentials)),
    )

    response = client.post("/update-analysis")

    assert response.status_code == 500
    assert response.get_json()["status"] == "error"
    assert load_calls == []


@pytest.mark.buttons
def test_pull_cancel_route_reports_not_running_when_idle(client):
    """POST /pull/cancel with no pull active should report "not_running"
    through the real HTTP route, not just pull_control.cancel() directly."""
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
