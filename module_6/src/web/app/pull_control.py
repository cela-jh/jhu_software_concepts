"""
`pull_control.py`
Compatibility stub for the web service. In module_6, long-running data
operations are handled by the worker via RabbitMQ. These functions
satisfy the interface that routes.py expects until Section 4 replaces
the relevant endpoints with publisher calls.
"""
import threading
from collections import deque

# Chrome debug port kept as a reference in case it is needed for local dev.
CHROME_DEBUG_PORT = 9222
RECENT_LINES = 5

_lock = threading.Lock()
_lines = deque(maxlen=RECENT_LINES)


def kill_stale_chrome():
    """
    No-op in module_6. Chrome-based scraping runs in the worker
    service, not the web service.

    :returns: None.
    :rtype: None
    """


def is_running():
    """
    Return whether a background pull is active. Always False in module_6
    because pulls are queued as RabbitMQ tasks, not run in-process.

    :returns: False.
    :rtype: bool
    """
    return False


def recent_lines():
    """
    Return the most recent status lines. Empty in module_6; worker
    progress is not streamed back to the web tier.

    :returns: An empty list.
    :rtype: list[str]
    """
    with _lock:
        return list(_lines)


def start(_chrome_binary, _database_url):
    """
    Placeholder. Scrape tasks are enqueued via publisher.publish_task
    in Section 4; this stub is never called by the updated routes.

    :param _chrome_binary: Unused; accepted to match the interface routes.py calls.
    :type _chrome_binary: str
    :param _database_url: Unused; accepted to match the interface routes.py calls.
    :type _database_url: str
    :returns: False, indicating no in-process pull was started.
    :rtype: bool
    """
    return False


def cancel():
    """
    Placeholder. No in-process pull exists to cancel in module_6.

    :returns: ``"not_running"``.
    :rtype: str
    """
    return "not_running"
