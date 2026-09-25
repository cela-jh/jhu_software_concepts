"""
`app.py`
Starts the Flask analysis webpage; the app itself lives in app/.
"""
import argparse
import atexit
from pathlib import Path

from app import app, pull_control, routes
from paths import DEFAULT_DATA_FILE


def parse_args():
    """
    Parses CLI arguments for starting the Flask server.
    """
    parser = argparse.ArgumentParser(
        description="Start the GradCafeAnalytics analysis webpage."
    )
    parser.add_argument(
        "--file", type=Path, default=DEFAULT_DATA_FILE,
        help=f"Results file Pull Data writes to and Update Analysis reads "
        f"from (default: `{DEFAULT_DATA_FILE}`)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    # Both reference this as a plain module-level global looked up at call
    # time, so reassigning it here before the server starts propagates to
    # every request Pull Data / Update Analysis handle afterward.
    pull_control.DATA_FILE = cli_args.file
    routes.DEFAULT_DATA_FILE = cli_args.file

    pull_control.kill_stale_chrome()
    atexit.register(pull_control.kill_stale_chrome)
    # threaded so a Pull Data poll isn't blocked by the analysis page's own
    # request, and use_reloader off so the pull subprocess's state isn't
    # tracked by two separate processes
    app.run(debug=True, threaded=True, use_reloader=False)
