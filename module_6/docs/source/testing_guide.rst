Testing Guide
=============

Setup
-----

1. Install as described in the setup guide (pip or uv, then
   ``pip install -e .``); ``requirements.txt`` already covers ``pytest``,
   ``pytest-cov``, ``pytest-randomly``, and every runtime dependency.
2. Create a disposable ``cam_db_test`` PostgreSQL database and load the
   schema: ``psql -d cam_db_test -f schema.sql``. The test suite never
   touches ``cam_db``'s real data: ``tests/conftest.py`` always sets
   ``DB_NAME=cam_db_test`` and never loads ``.env``. ``DB_HOST``,
   ``DB_PORT``, ``DB_USER``, and ``DB_PASSWORD`` are used as-is when set
   (as CI sets them for its own Postgres service container); otherwise
   they default to ``localhost``, ``5432``, the current OS user (via
   ``getpass.getuser()`` rather than a hardcoded name), and a blank
   password. The suite connects as the table owner, since it truncates
   ``applicants`` between tests and ``gradcafe_app`` has no ``TRUNCATE``.

Running marked tests
---------------------

**Always run from the repository root** (the parent of ``module_5/``),
with the ``module_5/tests`` path included:

.. code-block:: console

   pytest module_5/tests -m "web or buttons or analysis or db or integration"

A bare ``pytest -m "..."`` with no path, run from the repository root,
does correctly run and pass the entire marked suite - marker filtering
doesn't require ``pytest.ini`` to be found at all. What it doesn't do is
enforce coverage, since ``pytest.ini``'s ``addopts`` (which sets
``--cov=module_5/src --cov-fail-under=100``) is never loaded without the
config file being found, and pytest's config-file search only looks
*upward* from the current directory - ``pytest.ini`` lives in
``module_5/``, which isn't an ancestor of the repository root. It also
emits a mark-registration warning per test. Concretely:

- Bare ``pytest -m "..."`` from the repository root: runs and passes the
  full marked suite, but with no coverage enforcement.
- Bare ``pytest -m "..."`` from ``module_5/``: ``pytest.ini`` *is* found,
  but its ``--cov-config=module_5/pytest.ini`` then resolves to the
  nonexistent ``module_5/module_5/pytest.ini`` and coverage.py raises a
  hard ``ConfigError``, so the run doesn't complete at all.
- ``pytest module_5/tests -m "..."`` from the repository root: pytest's
  config search starts from ``module_5/tests`` and walks upward to find
  ``module_5/pytest.ini``, while ``--cov=module_5/src`` is correct
  relative to the repository root. This is the only invocation that also
  enforces the 100% coverage gate, which is why it's what this project
  actually uses and what CI runs.

Markers
-------

Every test is marked with exactly one of the following (registered in
``pytest.ini``); running the full unmarked ``pytest module_5/tests``
also works and is equivalent, since every test already carries one:

- ``web`` - Flask route/page tests
- ``buttons`` - "Pull Data" and "Update Analysis" behavior
- ``analysis`` - formatting/rounding of analysis output
- ``db`` - database schema/inserts/selects
- ``integration`` - end-to-end flows

To run a single subset, filter on just that marker, e.g.
``pytest module_5/tests -m db``.

Coverage
--------

``pytest.ini``'s ``--cov-fail-under=100`` enforces 100% statement
coverage across every file under ``module_5/src``, including
``scraping/`` (Selenium/subprocess mocked, never a real browser) and
``llm_hosting/`` (the real ``Llama``/``hf_hub_download`` calls mocked,
never a real model load or network request). Its own ``[report]``
section (read via ``--cov-config=module_5/pytest.ini``) excludes each
file's ``if __name__ == "__main__":`` guard from that count, since that
code only ever runs when a script is invoked directly, never via
``import``. The current terminal summary is committed at
``module_5/coverage_summary.txt``.

Selectors
---------

The Pull Data and Update Analysis buttons carry stable
``data-testid="pull-data-btn"`` / ``data-testid="update-analysis-btn"``
attributes (alongside the ``id`` attributes the page's own JS uses), so
UI tests don't break if the visible button text or styling changes.

Fixtures and test doubles
--------------------------

Defined in ``tests/conftest.py``:

- ``app`` - a fresh Flask app instance (``create_app()``) for a single test.
- ``client`` - a Flask test client bound to the ``app`` fixture.
- ``database_url`` - the disposable test database's connection URL.
- ``db_connection`` - connects to ``cam_db_test`` and truncates the
  ``applicants`` table before and after the test, refusing to run at all
  if the connection somehow isn't pointed at the disposable test
  database.
- ``reset_pull_control`` (autouse) - resets ``pull_control``'s
  module-level pull-tracking state before and after every test, since
  that state is shared across the whole process and would otherwise leak
  between tests under ``pytest-randomly``.

Individual test files also define their own test doubles where needed,
for example a ``_FakeProcess`` standing in for the scraper subprocess
(``test_buttons.py``) and a ``_FakeSession`` standing in for a SQLAlchemy
session (``test_flask_page.py``), so tests never launch a real Chrome
instance, make a real HTTP request, or depend on a particular database
state beyond what a fixture sets up.

Notes on test design
---------------------

- Database tests use a real local PostgreSQL connection (``cam_db_test``),
  not a mocked one, so schema/constraint behavior (``NOT NULL``,
  ``UNIQUE``, upsert-on-conflict) is verified for real rather than assumed.
- Selenium, subprocess, and ``urllib`` calls in ``scraping/scrape.py``
  are mocked at the point of use in every test.
- ``llm_hosting/app.py`` and ``llm_hosting/llm_helper.py`` are imported
  by their full package names (``import llm_hosting.app as llm_app``),
  which never collide with the Flask ``app`` package.
- Structural page assertions (button presence, "Answer:" labeling) parse
  the rendered HTML with BeautifulSoup and query by selector
  (``data-testid``, ``.answer``) rather than searching the raw response
  body for substrings. Percentage-formatting assertions use a regex
  instead, since a percentage is a text value, not a structural element.
