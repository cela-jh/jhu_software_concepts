"""
`app`
Flask presentation layer for the analysis webpage.
"""
from flask import Flask

from .routes import bp


def create_app():
    """
    Builds the Flask app and registers its routes.
    Returns the app.
    """
    flask_app = Flask(__name__)
    flask_app.register_blueprint(bp)
    return flask_app


app = create_app()
