"""
`pull_control.py`
Tracks and controls the background Grad Cafe pull (scrape) subprocess
started by the Pull Data button.
"""
import contextlib
import io
import os
import signal
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from load_data import load_data

MODULE_3_DIR = Path(__file__).resolve().parent.parent
SCRAPE_SCRIPT = MODULE_3_DIR / "module_2_files" / "scrape.py"
DATA_FILE = MODULE_3_DIR / "applicant_data.json"
RECENT_LINES = 5
CHROME_DEBUG_PORT = 9222

_lock = threading.Lock()
_process = None
_thread = None
_lines = deque(maxlen=RECENT_LINES)


def kill_stale_chrome():
    """
    Kills any process listening on Chrome's remote debugging port, left
    over from an earlier run that ended without its own cleanup running,
    so it can never block or collide with a new one. Called when the app
    starts and when it stops.
    Returns none.
    """
    try:
        result = subprocess.run(
            ["lsof", f"-tiTCP:{CHROME_DEBUG_PORT}", "-sTCP:LISTEN"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return
    for pid_text in result.stdout.split():
        try:
            os.kill(int(pid_text), signal.SIGKILL)
        except (ValueError, ProcessLookupError):
            pass


def is_running():
    """
    Returns whether a pull is active, covering both the scrape itself
    and the database upload that follows it.
    """
    with _lock:
        return _thread is not None and _thread.is_alive()


def recent_lines():
    """Returns up to the last RECENT_LINES status lines, oldest first."""
    with _lock:
        return list(_lines)


def start(chrome_binary, credentials):
    """
    Starts the pull subprocess if one isn't already running, then a
    background thread that streams its output into recent_lines() and
    uploads whatever it collected to PostgreSQL once it exits.
    Returns True if a pull was started, False if one was already running.
    """
    global _process, _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        _lines.clear()
        _lines.append("Starting pull...")
        _process = subprocess.Popen(
            [sys.executable, str(SCRAPE_SCRIPT),
             "--chrome_binary", str(chrome_binary), str(DATA_FILE)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        _thread = threading.Thread(
            target=_stream_and_upload, args=(_process, credentials), daemon=True
        )
        _thread.start()
    return True


def cancel():
    """
    Sends a termination signal to the running pull subprocess, if the
    scrape itself is still going; scrape.py catches this and stops
    cleanly, so whatever it already collected is still uploaded
    afterward. If the scrape has already finished and only the database
    upload is left, there is nothing left to cancel.
    Returns "cancelling", "finishing", or "not_running".
    """
    with _lock:
        if _thread is None or not _thread.is_alive():
            return "not_running"
        if _process is not None and _process.poll() is None:
            _process.terminate()
            return "cancelling"
        return "finishing"


def _stream_and_upload(process, credentials):
    """
    Reads the subprocess's output line by line into recent_lines() as it
    runs, then loads whatever it collected into PostgreSQL once it exits,
    also capturing that step's own printed summary into recent_lines().
    """
    for line in process.stdout:
        with _lock:
            _lines.append(line.rstrip())
    process.wait()

    with _lock:
        _lines.append("Scraping finished. Uploading new results to the database...")

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        load_data(DATA_FILE, credentials)

    with _lock:
        for line in buffer.getvalue().splitlines():
            _lines.append(line)
        _lines.append("Pull complete.")
