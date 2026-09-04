"""
core/views.py: holds all routes for main Flask web application function.
            Provides basic information about the application creator.
"""
from flask import Blueprint, render_template


# Blueprint for rendering the main static pages
core = Blueprint("core", __name__, template_folder="templates", 
                 static_folder="static", static_url_path="/core/static")

# home page
@core.route("/")
def index():
    return render_template("home.html")

# contact page
@core.route("/contact")
def contact():
    return render_template("contact.html")

# projects page
@core.route("/projects")
def projects():
    return render_template("projects.html")