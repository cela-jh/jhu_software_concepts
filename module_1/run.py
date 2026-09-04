"""
run.py: entry point for Flask web application, running Flask application
along with blueprints
"""
from flask import Flask
from app.core.views import core


# create app instance and register Blueprints (only one currently)
app = Flask(__name__)
app.register_blueprint(core)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
