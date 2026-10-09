"""
`test_pull_control.py`
Covers pull_control's stub behavior in module_6. In module_6 the web
service does not run a Chrome subprocess; data operations are handled
by the worker via RabbitMQ. These tests verify the stub satisfies the
interface routes.py depends on.
"""
import pytest

from app import pull_control


@pytest.mark.buttons
def test_is_running_always_false():
    """No in-process pull ever starts in module_6."""
    assert pull_control.is_running() is False


@pytest.mark.buttons
def test_recent_lines_returns_list():
    """recent_lines must return a list (empty by default)."""
    lines = pull_control.recent_lines()
    assert isinstance(lines, list)
    assert lines == []


@pytest.mark.buttons
def test_start_returns_false():
    """start() always returns False because pulls are enqueued, not spawned."""
    result = pull_control.start("unused-binary", "postgresql://unused")
    assert result is False


@pytest.mark.buttons
def test_cancel_reports_not_running():
    """cancel() always reports not_running in the stub."""
    assert pull_control.cancel() == "not_running"


@pytest.mark.buttons
def test_kill_stale_chrome_is_a_noop():
    """kill_stale_chrome() must not raise regardless of system state."""
    pull_control.kill_stale_chrome()
