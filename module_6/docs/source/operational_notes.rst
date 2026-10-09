Operational Notes
==================

Busy-state policy
------------------

Only one Grad Cafe pull may run at a time, process-wide. ``app/pull_control.py``
tracks this with a single module-level ``_thread``, guarded by a lock:

- ``is_running()`` reports ``True`` only while that thread is alive, covering
  both the scrape subprocess itself and the database upload that follows it.
- ``POST /pull-data`` refuses to start a second pull while one is active,
  returning ``409`` with ``{"ok": false, "busy": true, "status": "already_running"}``.
- ``POST /update-analysis`` is gated the same way, returning ``409`` with
  ``{"ok": false, "busy": true, "status": "busy"}``, since a running pull's own
  upload step already owns the same table - an Update Analysis running
  concurrently could read a half-written state.
- State is observable (``is_running()``) and injectable in tests (a fake
  thread stood in for ``pull_control._thread``), rather than inferred by
  sleeping and hoping enough time has passed - the SHALL NOT on arbitrary
  ``sleep()`` for busy-state checks is designed around exactly this.
- Reloading the page while a pull is running still shows the current status
  correctly, since ``GET /analysis`` reads the same ``is_running()`` /
  ``recent_lines()`` state on every request rather than caching it.

Idempotency strategy
----------------------

Loading a results file - whether from Pull Data, Update Analysis, or the
``load_data.py`` CLI directly - is always an upsert, never a plain insert:

.. code-block:: sql

   INSERT INTO applicants (...)
   VALUES (...)
   ON CONFLICT (url) DO UPDATE SET
       program = COALESCE(EXCLUDED.program, applicants.program),
       ...
   RETURNING url, (xmax = 0) AS inserted;

A result whose ``url`` already exists in the table updates that row instead
of being skipped or duplicated. Each column is set to
``COALESCE(new value, existing value)``, so a new non-null value overwrites
what's there, but a field the new file lacks (or provides as null) leaves
the existing value untouched. This is what makes running Pull Data twice
against overlapping data safe: the second run's already-seen rows simply
update themselves in place with whatever's new (usually nothing), rather
than erroring or producing duplicate rows.

Uniqueness keys
------------------

Two constraints, enforced by PostgreSQL itself rather than assumed by
application code:

- ``p_id INTEGER PRIMARY KEY`` - not auto-incrementing. It's derived
  deterministically from the numeric Grad Cafe result id embedded in each
  entry's url (``.../result/1020482`` -> ``p_id`` ``1020482``), so the same
  scraped result always maps to the same row, run after run.
- ``url TEXT UNIQUE NOT NULL`` - the actual conflict target for the upsert
  above. Since ``p_id`` is derived from ``url``, the two constraints agree by
  construction; ``url`` is what ``ON CONFLICT`` keys off, since it's the
  natural identity of a scraped result.

Troubleshooting
================

Local setup
------------

**"could not connect to server" / `connect_db` prints an error and returns None**
    PostgreSQL isn't running, or one of ``DB_HOST``, ``DB_PORT``,
    ``DB_NAME``, ``DB_USER``, or ``DB_PASSWORD`` is wrong. Confirm the
    server is up and ``psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d
    "$DB_NAME" -c '\dt'`` succeeds on its own before running the app.

**"Set DB_HOST, ... before running"**
    A required ``DB_*`` variable is missing. Copy ``.env.example`` to
    ``.env`` in ``module_5`` and fill it in, or export the variables in
    your shell.

**"permission denied for table applicants"**
    The app is connected as a role without the needed privilege. Run
    ``least_privilege.sql`` against that database as the table owner, and
    check ``DB_USER`` is ``gradcafe_app``.

**`db_connection` fixture raises "Refusing to run db tests against a non-test database"**
    the connection URL doesn't contain ``cam_db_test``. This guard exists so a
    misconfigured environment variable can never point the test suite's
    ``TRUNCATE`` calls at real data; fix the environment variable, don't
    remove the guard.

**`relation "applicants" does not exist`**
    The schema hasn't been loaded into that database yet. Run
    ``psql -d <dbname> -f schema.sql`` from ``module_5`` first (see
    :doc:`overview_setup`).

**Bare `pytest -m "..."` reports 0% coverage, or errors with a `ConfigError` about `pytest.ini`**
    See :doc:`testing_guide` - use
    ``pytest module_5/tests -m "web or buttons or analysis or db or integration"``
    from the repository root, which is the one invocation that resolves
    both the marker config and the coverage path correctly.

**Pull Data hangs on a real (non-test) run, Chrome window shows "Just a moment..."**
    That's Cloudflare's challenge page, not a bug. Solve it once in the
    visible Chrome window; the scraper polls for the title to clear rather
    than waiting on a keypress, so this works the same whether run directly
    or as Pull Data's background subprocess.

CI
---

**The "Install dependencies" step takes several minutes with no visible progress**
    Most dependencies install from prebuilt wheels in seconds. The
    exception is ``llama-cpp-python``, which falls back to compiling
    ``llama.cpp`` from source via CMake if no matching prebuilt wheel exists
    for the runner's platform - that can take several minutes on a 2-core
    GitHub-hosted runner. This is expected, not a stall; check the log for
    compiler output to confirm it's still running.

**Workflow logs show a Node.js 20 deprecation warning**
    Cosmetic - it's about the Node runtime GitHub Actions uses internally to
    execute action wrapper code, unrelated to this project's Python/Postgres
    pipeline. Fixed by using current major versions of the actions involved
    (``actions/checkout@v5``, ``actions/setup-python@v6``).

**A Postgres-dependent step fails immediately with "connection refused"**
    The ``postgres`` service container's health check
    (``pg_isready``) may not have passed yet before a later step ran. Confirm
    the workflow's ``services.postgres.options`` includes a health check and
    that no step bypasses the wait.

Read the Docs
---------------

**The RTD build fails trying to install `psycopg` or another compiled dependency**
    ``module_5/docs/requirements.txt`` is a deliberately smaller,
    docs-only dependency list - it uses ``psycopg[binary]`` specifically so
    the build doesn't depend on a system ``libpq`` install being present on
    RTD's image, and it omits ``huggingface_hub``/``llama-cpp-python``
    entirely, since no module that successfully autodoc-imports needs them.
    If autodoc needs a new import satisfied, add it there, not to the full
    application ``requirements.txt``, to keep the docs build fast.
