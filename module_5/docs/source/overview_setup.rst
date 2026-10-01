Overview & Setup
=================

Overview
--------

GradCafeAnalytics is a small pipeline plus a Flask webpage, made of four
independently-executable files with no single combined entry point:

- ``src/scraping/scrape.py`` scrapes publicly posted graduate admissions
  results from GradCafe (thegradcafe.com/survey) into a JSON file
  (``data/applicant_data.json``).
- ``src/database/load_data.py`` loads a results file into a PostgreSQL
  table called ``applicants``.
- ``src/database/query_data.py`` runs the Part 2 SQL analysis queries
  against the ``applicants`` table and prints each answer to the console.
- ``src/run.py`` starts a Flask app displaying every analysis answer on
  one webpage, read live through the SQLAlchemy ``Applicant`` model. Its
  Pull Data button runs ``scrape.py`` in the background to fetch newly
  submitted entries and load them into PostgreSQL; Update Analysis
  re-renders the page with current results without starting a scrape.

Requirements
------------

- Python 3.10+
- Google Chrome installed locally (for scraping and the Pull Data button)
- A running PostgreSQL server with a database (this project uses ``cam_db``)
  and an ``applicants`` table already created

Setup
-----

1. From ``module_4``, create and activate a virtual environment:

   .. code-block:: console

      python3 -m venv venv
      source venv/bin/activate        # Windows: venv\\Scripts\\activate

2. Install dependencies:

   .. code-block:: console

      pip install -r requirements.txt

3. Locate your Chrome binary's absolute path (needed for ``--chrome_binary``):

   - macOS: ``/Applications/Google Chrome.app/Contents/MacOS/Google Chrome``
   - Windows: ``C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe``
   - Linux: usually ``google-chrome`` on PATH

4. Create the least-privilege role the app connects as (``SELECT``,
   ``INSERT``, ``UPDATE`` on ``applicants`` only), then set its password;
   psql prompts for it, so it never appears in a file:

   .. code-block:: console

      psql -d <your_database_name> -f least_privilege.sql
      psql -d <your_database_name> -c "\password gradcafe_app"

5. Copy ``.env.example`` to ``.env`` and fill in ``DB_HOST``,
   ``DB_PORT``, ``DB_NAME``, ``DB_USER`` (``gradcafe_app``),
   ``DB_PASSWORD``, and, for Pull Data, ``CHROME_BINARY`` (the path from
   step 3). ``.env`` is gitignored. ``run.py`` and every CLI load it at
   startup; variables already exported in your shell take precedence.

Running the app
----------------

Every command in this section and the next runs from ``module_5/src``.

.. code-block:: console

   python run.py [--file path/to/results.json]

Open http://127.0.0.1:5000/analysis. Every answer is read live from
PostgreSQL on each page load; if PostgreSQL itself is unreachable, the
page shows a plain "database is currently unavailable" message (HTTP
503) rather than crashing. ``--file`` is optional and defaults to
``data/applicant_data.json``.

Running the other CLI scripts
------------------------------

Scripts inside a package run as modules (``python -m package.module``) so
their package imports resolve from ``src/``.

.. code-block:: console

   # Scraping
   python -m scraping.scrape --num_results <N> --chrome_binary "<path to Chrome>" [output.json]

   # Loading into PostgreSQL
   python -m database.load_data <file.json>

   # Part 2 SQL analysis
   python -m database.query_data

   # Part 6 SQLAlchemy ORM analysis
   python -m database.orm_queries

Running the tests
------------------

**Always run from the repository root** (the parent of ``module_4/``),
with the ``module_4/tests`` path included:

.. code-block:: console

   pytest module_4/tests -m "web or buttons or analysis or db or integration"

See :doc:`testing_guide` for why that path argument is required, how
markers work, and what fixtures and test doubles are available.
