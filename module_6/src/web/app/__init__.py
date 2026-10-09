"""
`app`
Flask presentation layer for the analysis webpage.
"""
from flask import Flask

from .routes import bp


def create_app():
    """
    Build the Flask app and register its routes.

    :returns: A configured Flask application.
    :rtype: flask.Flask
    """
    flask_app = Flask(__name__)
    flask_app.register_blueprint(bp)
    return flask_app


app = create_app()
