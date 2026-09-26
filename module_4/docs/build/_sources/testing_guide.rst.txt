Testing Guide
=============

Setup
-----

1. Create and activate ``module_4/venv``, then ``pip install -r requirements.txt``
   (already covers ``pytest``, ``pytest-cov``, ``pytest-randomly``, and
   every runtime dependency).
2. Create a disposable ``cam_db_test`` PostgreSQL database and load the
   schema: ``psql -d cam_db_test -f schema.sql``. The test suite never
   touches ``cam_db``'s real data. If ``DATABASE_URL`` is already set (as
   CI sets it, pointing at its own Postgres service container),
   ``tests/conftest.py`` uses it as-is; otherwise it builds one pointing
   at ``cam_db_test`` from the current OS user
   (``postgresql://<user>@localhost:5432/cam_db_test``, via
   ``getpass.getuser()`` rather than a hardcoded name) and sets it as the
   ``DATABASE_URL`` environment variable for the whole test session.

Running marked tests
---------------------

**Always run from the repository root** (the parent of ``module_4/``),
with the ``module_4/tests`` path included:

.. code-block:: console

   pytest module_4/tests -m "web or buttons or analysis or db or integration"

This differs from a bare ``pytest -m "..."`` with no path, because
``pytest.ini`` lives in ``module_4/`` and its ``addopts`` sets
``--cov=module_4/src``, a path resolved relative to the invocation
directory rather than to ``pytest.ini``'s own location. Concretely:

- Bare ``pytest -m "..."`` from ``module_4/``: finds ``pytest.ini``, but
  ``--cov=module_4/src`` then resolves to the nonexistent
  ``module_4/module_4/src`` - fails with "Total coverage: 0.00%".
- Bare ``pytest -m "..."`` from the repository root: ``--cov=module_4/src``
  would resolve correctly, but ``pytest.ini`` is never found at all.
- ``pytest module_4/tests -m "..."`` from the repository root: pytest's
  config search starts from ``module_4/tests`` and walks upward to find
  ``module_4/pytest.ini``, while ``--cov=module_4/src`` is correct
  relative to the repository root. This is the only invocation that
  satisfies both at once.

Markers
-------

Every test is marked with exactly one of the following (registered in
``pytest.ini``); running the full unmarked ``pytest module_4/tests``
also works and is equivalent, since every test already carries one:

- ``web`` - Flask route/page tests
- ``buttons`` - "Pull Data" and "Update Analysis" behavior
- ``analysis`` - formatting/rounding of analysis output
- ``db`` - database schema/inserts/selects
- ``integration`` - end-to-end flows

To run a single subset, filter on just that marker, e.g.
``pytest module_4/tests -m db``.

Coverage
--------

``pytest.ini``'s ``--cov-fail-under=100`` enforces 100% statement
coverage across every file under ``module_4/src``, including
``scraping/`` (Selenium/subprocess mocked, never a real browser) and
``llm_hosting/`` (the real ``Llama``/``hf_hub_download`` calls mocked,
never a real model load or network request). Its own ``[report]``
section (read via ``--cov-config=module_4/pytest.ini``) excludes each
file's ``if __name__ == "__main__":`` guard from that count, since that
code only ever runs when a script is invoked directly, never via
``import``. The current terminal summary is committed at
``module_4/coverage_summary.txt``.

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
- ``database_url`` - the disposable test database's ``DATABASE_URL`` connection string.
- ``db_connection`` - connects to ``cam_db_test`` and truncates the
  ``applicants`` table before and after the test, refusing to run at all
  if ``DATABASE_URL`` somehow isn't pointed at the disposable test
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
- ``llm_hosting/app.py`` and ``llm_hosting/llm_helper.py`` are loaded via
  ``importlib`` under names other than ``app``, since a bare ``import app``
  would resolve to the already-imported Flask ``app`` package instead.
