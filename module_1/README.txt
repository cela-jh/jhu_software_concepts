Cameron Ela - cela1@jh.edu
256 - Modern Software Concepts
Module 1 - Personal Website
====================================

Summary
-------
A personal website built with Flask, presenting a home page, a contact
page, and a projects page. Pages share a common layout (navigation bar,
page structure) via a Jinja base template, and each page's routes and
static/template assets are organized under a single Flask Blueprint.

How to Run
----------
1. Create and activate a virtual environment:
       python3 -m venv venv
       source venv/bin/activate        (Windows: venv\Scripts\activate)

2. Install dependencies:
       pip install -r requirements.txt

3. Start the application:
       python run.py

4. Open a browser to:
       http://localhost:8080

The server runs with debug mode enabled and listens on host 0.0.0.0,
port 8080.

Blueprints
----------
core (app/core/views.py)
    Handles all of the site's main pages. Owns its own templates
    (app/core/templates/) and static assets (app/core/static/), registered
    via template_folder and static_folder on the Blueprint, with
    static_url_path set to /core/static to avoid colliding with Flask's
    default app-level static route.

    Routes:
        /          -> home()    -> renders home.html
        /contact   -> contact()  -> renders contact.html
        /projects  -> projects() -> renders projects.html

    Pages that inherit from this blueprint's base template
    (app/core/templates/base.html, via {% extends "base.html" %}):
        - home.html     (homepage: name, bio, and photos)
        - contact.html  (contact information)
        - projects.html (Module 1 project title, description, and link)

    base.html provides the shared page shell: document head/meta tags,
    the linked stylesheet, and the top-right navigation bar (with the
    current page highlighted), so each page template only needs to fill
    in its own {% block content %}.

Project Structure
------------------
run.py                     entry point; creates the Flask app and
                            registers the core blueprint
app/
    __init__.py             marks app/ as a Python package
    core/
        __init__.py         marks app/core/ as a Python package
        views.py             core blueprint definition and routes
        templates/
            base.html         shared layout (nav bar, page shell)
            home.html          homepage
            contact.html       contact page
            projects.html      projects page
        static/
            css/style.css      site styling
            images/            photos used on the homepage
