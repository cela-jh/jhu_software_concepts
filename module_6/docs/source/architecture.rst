Architecture
============

The project is organized into three layers, plus a standalone tool. Each
file is independently executable and there is no single combined entry
point; ``paths.py`` centralizes shared filesystem locations so no file
hardcodes a path to another directory more than once.

Web layer (``src/app/``, ``src/run.py``)
-----------------------------------------

The Flask presentation layer. ``run.py`` is the CLI entry point that
starts the server; ``app/__init__.py`` builds the Flask app via
``create_app()`` and registers its routes.

- ``app/routes.py`` defines the ``/analysis`` page (renders every Part 2
  answer, read live through the SQLAlchemy ORM) and the JSON endpoints
  behind the Pull Data / Update Analysis buttons (``/pull-data``,
  ``/pull/cancel``, ``/pull/status``, ``/update-analysis``).
- ``app/pull_control.py`` tracks and controls the background scrape
  subprocess started by Pull Data: streaming its output, handling
  cancellation, and triggering the database upload once it exits.

The web layer's only responsibility is presenting data and coordinating
a pull; it never parses HTML or writes SQL directly, delegating both to
the ETL and DB layers below.

ETL layer (``src/scraping/``)
-------------------------------

Extracts and transforms admissions results from GradCafe into structured
JSON, independent of the database.

- ``scrape.py`` drives a real Chrome browser via Selenium (routed around
  Cloudflare's bot check), paginates through results, and hands raw HTML
  rows to ``clean.py``.
- ``clean.py`` parses those raw rows into structured dictionaries
  (program, university, status, term, scores, etc.), with no I/O of its
  own.
- ``storage.py`` persists parsed results to JSON incrementally and
  tracks resumable-crawl state, so an interrupted scrape can continue
  from where it left off.

This layer's output is a plain JSON file; it never opens a database
connection.

DB layer (``src/database/``)
-------------------------------

Everything that talks to the ``applicants`` table.

- ``db_helpers.py`` provides raw psycopg connect/disconnect helpers and
  a SQL pretty-printer.
- ``models.py`` defines the SQLAlchemy ``Applicant`` model and the
  engine/session used by the ORM query path.
- ``load_data.py`` validates a results file's rows and upserts them into
  PostgreSQL, clearing implausible scores and normalizing nationality
  values already in the table.
- ``query_data.py`` answers the Part 2 questions with raw SQL.
- ``orm_queries.py`` answers a subset of the same questions with the
  SQLAlchemy ORM instead, used live by the Flask analysis page.

This layer owns every SQL statement and schema assumption in the
project; the web and ETL layers never construct SQL themselves.

LLM standardizer (``src/llm_hosting/``)
------------------------------------------

A package of the project (installed with the rest by ``setup.py``,
with its dependencies in the shared ``requirements.txt``). Adds
``llm-generated-program`` / ``llm-generated-university`` fields to a
results file via a self-hosted TinyLlama model, either as a Flask
service (``app.py``) or a CLI, with ``llm_helper.py`` providing
crash-safe parallelization across multiple worker processes. It is
never called automatically by the web or ETL layers; running it is a
separate, optional step before loading a file.

Data flow
---------

.. code-block:: text

   scrape.py --> (raw HTML rows) --> clean.py --> (JSON) --> storage.py
                                                                  |
                                                                  v
                                                      applicant_data.json
                                                                  |
                                        (optional: llm_hosting) --+--> llm_extend_applicant_data.json
                                                                  |
                                                                  v
                                                          load_data.py --> PostgreSQL (applicants)
                                                                                |
                                                              query_data.py / orm_queries.py
                                                                                |
                                                                                v
                                                                    run.py (Flask /analysis page)
