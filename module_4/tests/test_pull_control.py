"""
`test_pull_control.py`
Covers pull_control.py internals not exercised through the HTTP layer in
test_buttons.py: kill_stale_chrome()'s process-cleanup branches, and
cancel()'s three possible outcomes.
"""
from types import SimpleNamespace

import pytest

from app import pull_control


class _FakeCompletedProcess:
    def __init__(self, stdout):
        self.stdout = stdout


@pytest.mark.buttons
def test_kill_stale_chrome_does_nothing_when_no_process_listening(monkeypatch):
    """With no PIDs reported by lsof, the loop body never runs and
    nothing gets killed."""
    monkeypatch.setattr(
        "app.pull_control.subprocess.run",
        lambda *a, **kw: _FakeCompletedProcess(stdout=""),
    )
    killed = []
    monkeypatch.setattr("app.pull_control.os.kill", lambda pid, sig: killed.append(pid))

    pull_control.kill_stale_chrome()

    assert killed == []


@pytest.mark.buttons
def test_kill_stale_chrome_kills_each_reported_pid(monkeypatch):
    """Every PID lsof reports should be sent SIGKILL."""
    monkeypatch.setattr(
        "app.pull_control.subprocess.run",
        lambda *a, **kw: _FakeCompletedProcess(stdout="111 222\n"),
    )
    killed = []
    monkeypatch.setattr("app.pull_control.os.kill", lambda pid, sig: killed.append(pid))

    pull_control.kill_stale_chrome()

    assert killed == [111, 222]


@pytest.mark.buttons
def test_kill_stale_chrome_ignores_already_gone_process(monkeypatch):
    """A PID that no longer exists by the time os.kill runs (the process
    already exited on its own) should be ignored, not raise."""
    monkeypatch.setattr(
        "app.pull_control.subprocess.run",
        lambda *a, **kw: _FakeCompletedProcess(stdout="333"),
    )

    def _raise_lookup_error(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr("app.pull_control.os.kill", _raise_lookup_error)

    pull_control.kill_stale_chrome()  # must not raise


@pytest.mark.buttons
def test_kill_stale_chrome_returns_when_lsof_is_missing(monkeypatch):
    """On a system without lsof installed, subprocess.run raises
    FileNotFoundError; kill_stale_chrome should just return quietly."""
    def _raise_not_found(*a, **kw):
        raise FileNotFoundError

    monkeypatch.setattr("app.pull_control.subprocess.run", _raise_not_found)

    pull_control.kill_stale_chrome()  # must not raise


@pytest.mark.buttons
def test_cancel_reports_not_running_when_no_pull_active():
    assert pull_control.cancel() == "not_running"


@pytest.mark.buttons
def test_cancel_terminates_process_still_scraping(monkeypatch):
    """While the scrape subprocess is still running (poll() is None),
    cancel() should terminate it and report "cancelling"."""
    terminated = []
    fake_process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: terminated.append(True),
    )
    monkeypatch.setattr(pull_control, "_process", fake_process)
    monkeypatch.setattr(pull_control, "_thread", SimpleNamespace(is_alive=lambda: True))

    result = pull_control.cancel()

    assert result == "cancelling"
    assert terminated == [True]


@pytest.mark.buttons
def test_cancel_reports_finishing_when_scrape_already_exited(monkeypatch):
    """If the scrape subprocess has already exited (poll() returns a
    code) but the upload thread is still alive, there's nothing left to
    cancel except waiting for the upload."""
    fake_process = SimpleNamespace(poll=lambda: 0, terminate=lambda: None)
    monkeypatch.setattr(pull_control, "_process", fake_process)
    monkeypatch.setattr(pull_control, "_thread", SimpleNamespace(is_alive=lambda: True))

    result = pull_control.cancel()

    assert result == "finishing"
