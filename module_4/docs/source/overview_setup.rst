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

4. Set the ``DATABASE_URL`` environment variable to a
   ``postgresql://user:password@host:port/dbname`` connection string.
   ``load_data.py``, ``run.py``, ``query_data.py``, and ``orm_queries.py``
   all read it from the environment at runtime:

   .. code-block:: console

      export DATABASE_URL=postgresql://your_postgres_user:your_postgres_password@localhost:5432/cam_db

   On a locally trust-authed PostgreSQL install, the password segment
   can be omitted entirely: ``postgresql://your_postgres_user@localhost:5432/cam_db``.

5. ``run.py``'s Pull Data button also needs ``CHROME_BINARY`` set to the
   path from step 3.

Running the app
----------------

.. code-block:: console

   DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/yourdb CHROME_BINARY="<path to Chrome>" python src/run.py [--file path/to/results.json]

Open http://127.0.0.1:5000/analysis. Every answer is read live from
PostgreSQL on each page load; if PostgreSQL itself is unreachable, the
page shows a plain "database is currently unavailable" message (HTTP
503) rather than crashing. ``--file`` is optional and defaults to
``data/applicant_data.json``.

Running the other CLI scripts
------------------------------

.. code-block:: console

   # Scraping
   python src/scraping/scrape.py --num_results <N> --chrome_binary "<path to Chrome>" [output.json]

   # Loading into PostgreSQL
   DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/yourdb python src/database/load_data.py <file.json>

   # Part 2 SQL analysis
   DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/yourdb python src/database/query_data.py

   # Part 6 SQLAlchemy ORM analysis
   DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/yourdb python src/database/orm_queries.py

Running the tests
------------------

**Always run from the repository root** (the parent of ``module_4/``),
with the ``module_4/tests`` path included:

.. code-block:: console

   pytest module_4/tests -m "web or buttons or analysis or db or integration"

See :doc:`testing_guide` for why that path argument is required, how
markers work, and what fixtures and test doubles are available.
