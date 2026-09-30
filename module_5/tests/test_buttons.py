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

    def __init__(self, lines, exit_code=0):
        self.stdout = iter(lines)
        self._exit_code = exit_code

    def wait(self):
        return self._exit_code


class _FakeThread:
    """A pull_control._state.thread stand-in that reports as still running, for
    busy-gating tests that don't need a real background thread."""

    def is_alive(self):
        return True


def _mark_pull_running():
    pull_control._state.thread = _FakeThread()


@pytest.mark.buttons
def test_pull_start_returns_200_and_triggers_loader(client, monkeypatch, database_url):
    """POST /pull-data should start a pull and, once the faked
    scraper finishes, hand its results off to load_data."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")

    fake_scraped_rows = ["row 1 scraped", "row 2 scraped"]
    monkeypatch.setattr(
        "app.pull_control.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(fake_scraped_rows),
    )

    load_calls = []
    monkeypatch.setattr(
        "app.pull_control.load_data",
        lambda filepath, url: load_calls.append((filepath, url)) or True,
    )

    response = client.post("/pull-data")
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["status"] == "started"

    # The upload happens on a background thread; wait for it to finish
    # before checking that it ran.
    pull_control._state.thread.join(timeout=2)

    assert len(load_calls) == 1
    loaded_filepath, loaded_url = load_calls[0]
    assert loaded_filepath == pull_control.DATA_FILE
    assert loaded_url == database_url
    for row in fake_scraped_rows:
        assert row in pull_control.recent_lines()


@pytest.mark.buttons
def test_pull_reports_error_when_scraper_exits_nonzero(client, monkeypatch):
    """If the scraper subprocess exits with an error, whatever it
    collected should still be uploaded, but the final status must say so
    instead of unconditionally announcing "Pull complete"."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.setattr(
        "app.pull_control.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess([], exit_code=1),
    )
    monkeypatch.setattr("app.pull_control.load_data", lambda filepath, url: True)

    client.post("/pull-data")
    pull_control._state.thread.join(timeout=2)

    lines = pull_control.recent_lines()
    assert any("Scraper exited with an error (code 1)" in line for line in lines)
    assert any("Pull finished with errors (scraper exit code 1)" in line for line in lines)
    assert not any(line == "Pull complete." for line in lines)


@pytest.mark.buttons
def test_pull_reports_error_when_upload_fails(client, monkeypatch):
    """If the scraper succeeds but the database upload itself fails,
    the final status must say so instead of announcing "Pull complete"."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.setattr(
        "app.pull_control.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess([], exit_code=0),
    )
    monkeypatch.setattr("app.pull_control.load_data", lambda filepath, url: False)

    client.post("/pull-data")
    pull_control._state.thread.join(timeout=2)

    lines = pull_control.recent_lines()
    assert any("Pull finished with errors: the database upload failed." in line for line in lines)
    assert not any(line == "Pull complete." for line in lines)


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
def test_update_analysis_returns_409_when_busy(client, monkeypatch):
    """POST /update-analysis should refuse to run, and not touch the
    database, while a pull is in progress."""
    load_calls = []
    monkeypatch.setattr(
        "app.routes.load_data",
        lambda filepath, url: load_calls.append((filepath, url)),
    )
    _mark_pull_running()

    response = client.post("/update-analysis")

    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert body["busy"] is True
    assert body["status"] == "busy"
    assert load_calls == []


@pytest.mark.buttons
def test_pull_start_returns_409_when_busy(client, monkeypatch):
    """POST /pull-data should refuse to start a second pull, and never
    launch a new scrape, while one is already running."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    popen_calls = []
    monkeypatch.setattr(
        "app.pull_control.subprocess.Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )
    _mark_pull_running()

    response = client.post("/pull-data")

    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert body["busy"] is True
    assert body["status"] == "already_running"
    assert popen_calls == []


@pytest.mark.buttons
def test_pull_start_returns_error_when_chrome_binary_missing(client, monkeypatch):
    """POST /pull-data should report a clear error, and never touch
    pull_control at all, when CHROME_BINARY isn't set."""
    monkeypatch.delenv("CHROME_BINARY", raising=False)

    response = client.post("/pull-data")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is False
    assert body["status"] == "error"
    assert "CHROME_BINARY" in body["message"]


@pytest.mark.buttons
def test_pull_start_returns_error_when_credentials_missing(client, monkeypatch):
    """POST /pull-data should report a clear error when DATABASE_URL
    isn't set, even with CHROME_BINARY present."""
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = client.post("/pull-data")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is False
    assert body["status"] == "error"
    assert "DATABASE_URL" in body["message"]


@pytest.mark.buttons
def test_update_analysis_returns_error_when_credentials_missing(client, monkeypatch):
    """POST /update-analysis should report a clear 500 error, and never
    call load_data, when DATABASE_URL isn't set."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
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
