"""
`app.py`
Starts the Flask analysis webpage; the app itself lives in app/.
"""
import atexit

from app import app
from app.pull_control import kill_stale_chrome

if __name__ == "__main__":
    kill_stale_chrome()
    atexit.register(kill_stale_chrome)
    # threaded so a Pull Data poll isn't blocked by the analysis page's own
    # request, and use_reloader off so the pull subprocess's state isn't
    # tracked by two separate processes
    app.run(debug=True, threaded=True, use_reloader=False)
