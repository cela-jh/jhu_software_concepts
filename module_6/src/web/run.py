"""
`run.py`
Starts the Flask analysis webpage; the app itself lives in app/.
Binds to 0.0.0.0:8080 so it is reachable inside a Docker container.
"""
import os

from app import app
from database.db_helpers import load_env_file


if __name__ == "__main__":
    # DB credentials and FLASK_SECRET from .env for local dev;
    # Docker Compose injects these directly as environment variables.
    load_env_file()
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET", "dev-secret-change-me")
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True, use_reloader=False)
