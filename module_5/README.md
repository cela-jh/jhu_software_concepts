# Module 5: Software Assurance and Secure SQL

Cameron Ela, cela1@jh.edu

> Builds on the module_2 scraper and module_3's database/webapp work, reorganized under `src/`. There is no single combined entry point; scraping, loading, querying, and the webpage each run directly from their own file (see [CLI Usage](#3-cli-usage)).

## Table of Contents

1. [Overview](#1-overview)
2. [Fresh Install](#2-fresh-install)
3. [CLI Usage](#3-cli-usage)
4. [Cloudflare Workaround](#4-cloudflare-workaround)
5. [Function Reference](#5-function-reference)
6. [Loading Into PostgreSQL](#6-loading-into-postgresql)
7. [SQL vs. SQLAlchemy](#7-sql-vs-sqlalchemy)
8. [Local LLM Standardization](#8-local-llm-standardization)
9. [Robots.txt Compliance](#9-robotstxt-compliance)
10. [Known Bugs / Limitations](#10-known-bugs--limitations)
11. [Linting and Dependency Graph](#11-linting-and-dependency-graph)
12. [Testing](#12-testing)
13. [Documentation](#13-documentation)
14. [Citations](#14-citations)

## 1. Overview

Four files, each independently executable, cover this project's work:

1. `src/scraping/scrape.py` - Scrapes publicly posted graduate admissions results from GradCafe (thegradcafe.com/survey) into a JSON file (`data/applicant_data.json`).
2. `src/database/load_data.py` - Loads a results file (`applicant_data.json`, or the LLM-standardized `llm_extend_applicant_data.json`) into a PostgreSQL table called `applicants`.
3. `src/database/query_data.py` - Runs the Part 2 SQL analysis queries against the `applicants` table and prints each answer to the console.
4. `src/run.py` - A Flask app displaying every analysis answer on one webpage, read live through the SQLAlchemy `Applicant` model rather than `query_data.py`'s raw-SQL path. Its Pull Data button runs `scrape.py` in the background to fetch newly submitted entries and load them into PostgreSQL; Update Analysis re-renders the page with current results without starting a scrape.

### File tree

```
module_5/
|-- README.md
|-- setup.py               : makes src/ an installable package (section 2)
|-- requirements.in        : hand-edited top-level dependencies
|-- requirements.txt       : every dependency pinned, generated from requirements.in
|-- pytest.ini
|-- schema.sql             : applicants table DDL, loaded locally and by CI
|-- least_privilege.sql    : creates the app's least-privilege database role (section 6)
|-- .env.example           : DB_* and CHROME_BINARY variable names with placeholders
|-- dependency.svg         : pydeps import graph (section 11)
|-- pylint_report.txt      : Pylint 10.00/10 output (section 11)
|-- coverage_summary.txt   : committed terminal coverage report (section 12)
|-- venv/                  : project virtual environment
|-- tests/                 : all test code (markers: web, buttons, analysis, db, integration)
|-- data/
|   |-- applicant_data.json
|   |-- llm_extend_applicant_data.json
|   `-- .state/
|       `-- applicant_data.state.json : resumable-crawl sidecar (section 5)
|-- docs/
|   |-- source/             : Sphinx project (conf.py, index.rst, autodoc module stubs)
|   `-- build/               : generated HTML output (`sphinx-build -b html docs/source docs/build`)
`-- src/
    |-- paths.py           : shared PACKAGE_DIR/DATA_DIR/STATE_DIR locations, resolved from this file
    |-- run.py             : starts the Flask server
    |-- app/               : the Flask presentation layer
    |   |-- __init__.py     : builds the Flask app and registers its routes
    |   |-- routes.py       : the analysis page route, read live through the ORM
    |   |-- pull_control.py : tracks/controls the background Pull Data subprocess
    |   |-- templates/analysis.html : the page template
    |   `-- static/css/style.css    : the page's styling
    |-- database/          : everything that talks to the `applicants` table
    |   |-- db_helpers.py   : PostgreSQL connect/disconnect helpers, SQL pretty-printer
    |   |-- models.py       : SQLAlchemy Applicant model, engine/session
    |   |-- load_data.py    : validates and loads a results file into PostgreSQL
    |   |-- query_data.py   : Part 2 questions, SQL, formatters, and the runner
    |   `-- orm_queries.py  : Part 2 analysis expressed with the SQLAlchemy ORM
    |-- scraping/          : browser automation and JSON persistence
    |   |-- scrape.py       : browser automation, extraction, scraping CLI
    |   |-- clean.py        : converts raw rows into structured dictionaries
    |   `-- storage.py      : JSON persistence, resumable-crawl state
    `-- llm_hosting/       : provided local-LLM standardizer, extended (section 8)
```

Every module imports its dependencies by their full package path rooted at `src/` (for example `from database.db_helpers import connect_db` or `from scraping.clean import clean_data`), and no file edits `sys.path`. Scripts under a package are therefore run as modules from `src/` (`python -m database.load_data`), which puts `src/` on the import path the same way for every entry point. Background subprocesses follow the same rule: Pull Data launches `python -m scraping.scrape` and the parallel LLM standardizer launches `python -m llm_hosting.app` workers, each with `src/` as the working directory. `paths.py` centralizes `src/`, `data/`, and `data/.state/` as constants so no file hardcodes a path to another directory more than once.

## 2. Fresh Install

### Prerequisites

- Python 3.12 or newer
- PostgreSQL (server running; the `psql` and `createdb` commands available)
- Google Chrome, for scraping and Pull Data
- Graphviz, only for regenerating `dependency.svg` (`brew install graphviz` or `sudo apt-get install graphviz`)
- [uv](https://docs.astral.sh/uv/), only for the uv install path (`brew install uv` or `pip install uv`)

Every command below runs from `module_5`.

### Option A: pip + venv

```
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### Option B: uv

```
uv venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
uv pip sync requirements.txt
uv pip install -e .
```

`uv pip sync` makes the environment match `requirements.txt` exactly, installing anything missing and removing anything not listed, so run it before `uv pip install -e .` (otherwise it would uninstall the project again).

**Why both steps:** `requirements.txt` pins every package, including indirect ones, to the exact versions this project is tested with; it is generated from the short, hand-edited `requirements.in` with `uv pip compile requirements.in --universal --python-version 3.12 -o requirements.txt`. `pip install -e .` then installs this project itself from `setup.py` as an editable package, so `app`, `database`, `scraping`, `llm_hosting`, and `paths` import the same way from any directory, for local runs, tests, and CI alike, while code changes take effect without reinstalling. Use the editable install: `paths.py` locates `data/` relative to the source tree, which a regular install would copy away from.

### Database and credentials

1. Create the database and the `applicants` table, as your PostgreSQL admin account (this project uses `cam_db`; any name works):
   ```
   createdb <your_database_name>
   psql -d <your_database_name> -f schema.sql
   ```
2. Create the least-privilege role the app connects as (see [Credentials and least privilege](#credentials-and-least-privilege)), then set its password; psql prompts for it, so it never appears in a file or your shell history:
   ```
   psql -d <your_database_name> -f least_privilege.sql
   psql -d <your_database_name> -c "\password gradcafe_app"
   ```
3. Copy `.env.example` to `.env` and fill in `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` (`gradcafe_app`), `DB_PASSWORD`, and, for Pull Data, `CHROME_BINARY`, the absolute path to Chrome:
   - macOS: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
   - Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe`
   - Linux: the output of `which google-chrome`

   `.env` is gitignored. `run.py` and every CLI load it automatically at startup; variables already exported in your shell take precedence over it.
4. Optionally load the bundled results: `cd src && python -m database.load_data ../data/applicant_data.json`

### Verify

```
cd src && python run.py
```

Open http://127.0.0.1:5000/analysis. To run the tests, see [Testing](#12-testing).

## 3. CLI Usage

Each command below is run on its own from `module_5/src`; none depend on a shared entry point. Database credentials come from the `DB_*` variables in `.env` (see [Fresh Install](#2-fresh-install)), never from the command line. Package scripts run as modules (`python -m package.module`) so their package imports resolve. Every script resolves `data/` from its own file location via `paths.py`, so the default data paths are the same regardless of current directory.

**Scraping:**
```
python -m scraping.scrape --num_results <N> --chrome_binary "<path to Chrome>" [output.json]
```
`--num_results` is the cumulative target for the whole crawl, including a resumed run's prior results, not "collect N more." A real Chrome window opens and navigates to GradCafe; if Cloudflare's challenge appears, solve it manually once (the script polls for it to clear rather than waiting on a keypress, so this also works with no terminal attached, as during a Pull Data run). Transient page failures (including Cloudflare 522s) are retried with exponential backoff instead of stopping the run. If interrupted, re-running the same command with the same output file resumes from saved state (`data/.state/`).

**Loading into PostgreSQL:**
```
python -m database.load_data <file.json>
```
Validates every result, skips and reports any missing required fields, and upserts the rest (see [section 6](#6-loading-into-postgresql) for details). Prints a summary of loaded/updated/skipped counts at the end, and exits with a non-zero status if the file couldn't be read or the database couldn't be reached at all, so a calling script or CI step can tell an unsuccessful load apart from a completed one.

**Running the Part 2 SQL analysis:** `python -m database.query_data`

**Running the Part 6 SQLAlchemy ORM analysis:** `python -m database.orm_queries`

**Running the analysis webpage:**
```
python run.py [--file path/to/results.json]
```
Open http://127.0.0.1:5000/analysis. Every answer is read live from PostgreSQL through the `Applicant` model on each page load; if PostgreSQL itself is unreachable, the page shows a plain "database is currently unavailable" message (HTTP 503) rather than crashing. `CHROME_BINARY` is only needed for Pull Data. `--file` is optional and defaults to `data/applicant_data.json`; when set, both Pull Data (what it writes to and loads from) and Update Analysis (what it re-syncs) use that file instead - for example, pointing at `data/llm_extend_applicant_data.json` to keep the LLM-standardized fields flowing through Update Analysis.

### Pull Data and Update Analysis

- Pull Data starts `scrape.py` in the background, scraping from page 1 until it finds `--pull_seen_limit` consecutive already-known results, or until Cancel is clicked, then loads whatever it collected into PostgreSQL. The button becomes Cancel while running, and the page polls and shows the last five status lines.
- Only one pull runs at a time; clicking Pull Data while one is active (even from another tab, or after a reload) reports it's already in progress instead of starting a second.
- Cancel stops the pull cleanly; whatever was already collected is still loaded into PostgreSQL afterward.
- If the scraper subprocess itself exits with an error partway through, whatever it collected before stopping is still uploaded, but the final status line reports the failure instead of announcing "Pull complete" unconditionally.
- A Cloudflare challenge during a pull shows up in the status lines; solve it in Chrome's visible window and the pull continues on its own once cleared.
- Update Analysis re-runs the analysis and reloads the page. It never starts a scrape; if a pull is running, it reports that new data is being retrieved and leaves the page as is.
- Reloading the page while a pull is running shows Cancel and the current status lines immediately.

### A3 school search

The last answer box, A3, lists accepted results from 2024 terms onward at any school whose name contains the text typed into the box on its right (University of Southern California by default), newest first and at most 50 rows. Submit calls `GET /analysis/accepted-since-2024?school=...` and replaces only that list; nothing else on the page is re-queried. A blank box falls back to the default school, and a name over 100 characters or containing control characters is rejected with HTTP 400. This is the one place user input reaches SQL, and it is always a bound parameter (see [section 6](#6-loading-into-postgresql)).

## 4. Cloudflare Workaround

A plain urllib scrape returns HTTP 403, and a normal Selenium-launched Chrome fares no better, since Selenium's own browser-launch carries automation fingerprints that trigger a repeating "verify you are human" loop. The fix: launch a real Chrome process independently via `subprocess` (not through Selenium) with remote debugging enabled and a persistent profile, then attach Selenium to it over the DevTools Protocol. Since Selenium never launches the browser itself, it never carries the fingerprint that triggers the loop. If Cloudflare's challenge still appears, a human solves it once in the visible window; the script polls the page title until it clears rather than waiting on a keypress, so this works the same whether run directly or as `run.py`'s background Pull Data subprocess, which has no terminal. The cleared session then persists in that Chrome profile for the rest of the run and future runs.

## 5. Function Reference

Every function listed is public (no leading underscore).

### `paths.py`
- `PACKAGE_DIR`, `DATA_DIR`, `STATE_DIR`, `DEFAULT_DATA_FILE`, `DEFAULT_LLM_DATA_FILE` - Constants resolved from this file's own location, so they hold regardless of the current working directory. `PACKAGE_DIR` is `src/`, the working directory for background subprocesses.
- `state_path_for(data_filepath)` - Returns the sidecar state-file path in `STATE_DIR` matching a data file's basename, creating `STATE_DIR` if needed.

### `scraping/scrape.py`
- `create_profile_dir()` / `cleanup_profile()` - Create/delete the persistent Chrome profile directory that lets a cleared Cloudflare session survive restarts.
- `terminate_process(process)` - Terminates a Chrome process, force-killing it if unresponsive.
- `chrome_helper(url, host_port, chrome_bin, profile_dir)` - Launches Chrome independently, attaches Selenium with an "eager" page load strategy (so a hanging tracker resource can't stall navigation), and blocks known ad/tracker domains via Chrome DevTools Protocol before navigating, since GradCafe's ad auction re-runs from scratch on every fresh, cookie-less profile and can otherwise stall loads for minutes. Retries on failed loads, and polls the page title for a Cloudflare challenge to clear (raising `TimeoutError` after `CLOUDFLARE_WAIT_TIMEOUT` seconds) instead of waiting on keyboard input.
- `check_robots_allowed(url)` - Reports whether scraping the given URL is currently permitted by robots.txt.
- `scrape_data(driver, url=None)` - Loads a page, confirms a results table is present (retrying otherwise), reads every row, clicks "Next" via JavaScript, and returns the rows plus the next-page URL (or `None`).
- `format_duration(seconds)` - Formats a duration as "Xh Ym Zs" for progress messages.
- `parse_args()` - `--chrome_binary` required; `--num_results` and `--pull_seen_limit` optional; positional output filepath (default `paths.DEFAULT_DATA_FILE`, i.e. `data/applicant_data.json`).
- `run_scrape(args)` - Validates the Chrome path and robots.txt, then scrapes until stopped. With `--num_results`, resumes from saved pagination state (via `paths.state_path_for()`) and never re-adds known urls, stopping at that target or when pages run out. Without it ("pull mode", used by Pull Data), always starts at page 1 and ignores saved state, stopping once `--pull_seen_limit` consecutive results are already known. Restarts the browser periodically to clear session state, shuts it down cleanly on exit or error, and in pull mode also stops cleanly on SIGTERM (the Cancel button) without losing saved progress.

### `scraping/clean.py`
- `clean_data(results, url)` - Pairs each entry's main row with its trailing tag/comment rows, extracts school, program, degree, date, status, and URL from the main row, and term, nationality, GRE/GPA scores, and comments from the trailing rows via pattern matching. Returns one dictionary per entry with whichever fields it had.

### `scraping/storage.py`
- `save_data(parsed_results, filepath)` - Appends new results directly onto the existing JSON array on disk instead of rewriting the whole file.
- `load_existing_urls(filepath)` - Reads which urls are already saved, so a scrape can skip duplicates.
- `validate_filepath(filepath, must_exist)` - Confirms a path is a `.json` file, raising a clear error otherwise.
- `save_state(state, filepath)` / `load_state(filepath)` - Persist and read the pagination sidecar file so an interrupted scrape resumes instead of restarting.

### `database/db_helpers.py`
- `connect_db(database_url)` - Opens a PostgreSQL connection from a `postgresql://user:password@host:port/dbname` connection string, printing a clear message and returning `None` instead of raising if it fails.
- `disconnect_db(conn)` - Closes a connection opened by `connect_db`.
- `pretty_print_query(query)` - Reformats a SQL string so each clause starts its own line in uppercase. Standalone utility; not currently called by `query_data.py`.

### `database/load_data.py`
- `load_data(filepath, database_url)` - Reads a JSON file and loads it into PostgreSQL: skips and collects ids for results missing a required field, converts/validates dates and GPA/GRE values, upserts valid results in batches, and prints a load/update/skip summary. Returns `True` if the file was read and the database was reached, `False` otherwise (used by the CLI entry point to exit non-zero on failure rather than always exiting 0). See [section 6](#6-loading-into-postgresql) for the full logic.
- `parse_args()` - Optional positional filepath (default `paths.DEFAULT_DATA_FILE`). When run directly, `main()` loads `.env` and builds the connection from the `DB_*` variables, exiting with a message (and non-zero status) if any are missing or the load itself fails.

### `database/query_data.py`
Holds `QUESTION_QUERY`, the list of (question, `Query`, format_result) tuples for the Part 2 analysis, where each `Query` pairs a composed `sql.SQL` statement with its bound parameters. `CLI_QUESTION_QUERY` adds A3 for the default school.
- `normalize_school(raw_school)` / `build_accepted_since_query(school)` / `fetch_accepted_since(database_url, school)` - Validate the A3 school input, compose its statement, and run it, returning one formatted line per result.
- `analyze(question_query, database_url)` - Runs each query and prints its formatted answer; a failing query prints its error in place without stopping the rest.

### `database/models.py`
- `Applicant` - SQLAlchemy model mapping the same `applicants` table `load_data.py` writes to (`p_id` as primary key). No separate table or copy of data is created.
- `get_engine(database_url)` / `get_session(database_url)` - Build a SQLAlchemy engine/session from the connection URL `db_helpers.database_url_from_env()` builds, selecting the `psycopg` driver explicitly.

### `database/orm_queries.py`
- `orm_q1` through `orm_q9`, `orm_a1`, `orm_a2` - Repeat the matching Part 2 question with SQLAlchemy's `select()`/`where()`/`func()`/`and_()`/`or_()`, returning the same formatted answer as `query_data.py`. Term/status/nationality comparisons use case-insensitive `ilike()` rather than `==`, so a mixed-case value (e.g. "fall 2026") still matches; percentage denominators are computed independently of whatever column the numerator's `CASE` expression checks, so a blank or unusual value in that column doesn't silently drop a row from the total. `ALL_ORM_ANSWERS` lists all eleven for `run.py`; `ORM_QUESTIONS` lists Q1, Q4, Q5, Q8, Q9, and A1 for `run_orm_queries()`.
- `run_orm_queries(database_url)` - Prints the answer to each question in `ORM_QUESTIONS`.

`run.py` imports and runs the Flask app from `app/`, calling `pull_control.kill_stale_chrome()` on startup and shutdown so an orphaned Chrome process never blocks the next Pull Data click.

### `app/routes.py`
- `analysis()` - Route for `/analysis`. Runs every `orm_queries.ALL_ORM_ANSWERS` function against a fresh SQLAlchemy session, pairs each with its question text, and renders `analysis.html` with the Pull Data button's current state. Returns a plain error message naming any missing `DB_*` variable (500), or a plain "database unavailable" message if PostgreSQL can't actually be reached (503), rather than an unhandled crash either way.
- `pull_start()` / `pull_cancel()` / `pull_status()` - Routes behind the Pull Data button (`POST /pull-data`, `POST /pull/cancel`, `GET /pull/status`), handing off to `pull_control` and returning JSON status. `pull_start()` and `update_analysis()` both include `ok`/`busy` boolean keys in their JSON responses alongside the existing `status`/`message` fields.

### `app/pull_control.py`
Tracks the single background pull `run.py` may have running, guarded by a lock.
- `kill_stale_chrome()` - Kills any process left listening on Chrome's remote debugging port from an earlier ungraceful exit.
- `is_running()` / `recent_lines()` - Whether a pull (scrape or its upload) is active, and its last five status lines.
- `start(chrome_binary, database_url)` - Starts `python -m scraping.scrape` in pull mode (from `src/`) if none is running, streams its output into `recent_lines()`, and loads results into PostgreSQL once it exits.
- `cancel()` - Sends SIGTERM to the running subprocess if still scraping; the upload step still runs on whatever was collected.

There is no `main.py`; `scrape.py`, `load_data.py`, `query_data.py`, and `run.py` each define their own `parse_args()` (or, for `query_data.py`, take no arguments) and run when executed as described in [CLI Usage](#3-cli-usage).

## 6. Loading Into PostgreSQL

### Table schema

Checked in at `module_5/schema.sql` (also loaded by CI to set up the test
database):

```sql
CREATE TABLE IF NOT EXISTS applicants (
    p_id INTEGER PRIMARY KEY,
    program TEXT NOT NULL,
    comments TEXT,
    date_added DATE NOT NULL,
    url TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL,
    term TEXT NOT NULL,
    us_or_international TEXT NOT NULL,
    gpa FLOAT,
    gre FLOAT,
    gre_v FLOAT,
    gre_aw FLOAT,
    degree TEXT NOT NULL,
    llm_generated_program TEXT,
    llm_generated_university TEXT
);
```

`p_id` is a plain integer, not auto-incrementing, derived from the numeric GradCafe result id in each entry's url (e.g. `.../result/1020482` becomes `p_id` 1020482), so the same result always gets the same `p_id`. `url` is `UNIQUE NOT NULL` so PostgreSQL enforces "no duplicate results" itself.

### Credentials and least privilege

No credentials appear anywhere in the code. `db_helpers.database_url_from_env()` builds the connection from `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` (blank allowed for servers that don't require one), escaping each part, and stops with a message naming every missing variable instead of falling back to a default. `run.py` and each CLI call `db_helpers.load_env_file()` first, which reads `module_5/.env` without overriding anything already exported. `.env` is gitignored; `.env.example` lists the variables with placeholder values. Credentials are read from the environment rather than CLI flags, since a flag's value is visible to other users (via `ps`) and saved in shell history.

The app connects as `gradcafe_app`, a role created by `least_privilege.sql` with only what the app uses:

| Privilege | Why |
|---|---|
| `LOGIN`, `CONNECT` on the database, `USAGE` on schema `public` | Connect and find the `applicants` table |
| `SELECT` on `applicants` | Every analysis query, A3, and the upsert's conflict check |
| `INSERT` on `applicants` | New results from Pull Data, Update Analysis, and `load_data` |
| `UPDATE` on `applicants` | Upserting existing results, and the score/nationality cleanup |

It is explicitly `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`, has no `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER`, can't create objects in `public`, and doesn't own the table, so it can't `DROP` or `ALTER` it. Reading alone wouldn't be enough: the database checks the connecting role, not which button was pressed, and Pull Data and Update Analysis write through the same role. The table itself stays owned by the administrative account used to run `schema.sql` and `least_privilege.sql`.

### Validation and missing values

A result missing `program`, `date_added`, `url`, `status`, `term`, `us_or_international`, or `degree` (or with an unparseable `date_added`) is skipped and its id reported. `gpa`, `gre`, `gre_v`, `gre_aw`, `comments`, and the `llm_generated_*` fields are optional and become `NULL` when absent, covering both `llm_extend_applicant_data.json` and the plain `applicant_data.json`.

`gpa`/`gre`/`gre_v`/`gre_aw` are also range-checked (0-4.0, 130-170, 130-170, 0-6; `gre` means GRE Quantitative specifically, not a combined score) and set to `NULL` if out of range, since GradCafe badges occasionally hold a mis-scaled or placeholder value. `us_or_international` is normalized to `'Other'` when the scraped value isn't exactly `'American'` or `'International'`. Both checks run against the whole table on every load, cleaning up older rows too.

### Upserting instead of skipping duplicates

Loading a result whose url already exists updates that row instead of skipping it: every column is set to `COALESCE(new value, existing value)`, so a new non-null value overwrites what's there, but a field the new file lacks leaves the existing value untouched. This means loading `applicant_data.json` then `llm_extend_applicant_data.json` fills in the LLM fields on the same rows, and the reverse order doesn't wipe them back out.

### SQL composition and LIMIT

No SQL in this project is built with f-strings, `+`, or `.format()` on raw SQL text:

- **Composition:** every psycopg statement is built with `psycopg.sql`: the `applicants` table and any dynamic column names go through `sql.Identifier` (quoted by psycopg), and every value, from filter patterns like `'Accepted%'` to the A3 school name, is a placeholder bound at execution (`cursor.execute(statement, params)`). Building a statement (`_limited_query()`, `build_accepted_since_query()`, `_build_upsert()`, `_build_clear_invalid()`) is kept separate from running it.
- **User input:** the A3 school name is validated (length, printable characters), its LIKE wildcards (`%`, `_`, `\`) are escaped so it only matches literally, and it is only ever sent as a parameter. Injection strings such as `' OR '1'='1` or `'; DROP TABLE applicants; --` therefore match nothing and change nothing, and `%` can't return every row.
- **LIMIT:** every SELECT (psycopg and SQLAlchemy alike) runs with `LIMIT` bound to `QUERY_LIMIT` (50), fixed in code rather than taken from a request, and passed through `clamp_limit()` so it can never leave the range 1-100. PostgreSQL has no LIMIT clause for INSERT or UPDATE; inserts are instead capped at `BATCH_SIZE` rows per statement, and the two cleanup UPDATEs intentionally cover the whole table.
- **Bad scraped data:** A1 only counts terms with both a season (Spring, Summer, Fall, or Winter) and a 4-digit year, such as `"Fall 2026"`, in its listed terms and its total alike; malformed terms such as `"Fall"` or `"Autumn 2026"` are excluded. Term years are read with a regex that yields NULL rather than failing a cast, so a malformed term can't crash A3 either.

### Batching

Rows are written `BATCH_SIZE` (1,000) at a time in one multi-row statement per batch. Each batch runs inside its own savepoint; a failed batch is split in half and retried, recursing down to `SMALL_BATCH_SIZE` (10) and finally individual rows, so one bad row only costs itself. Each statement reports exactly which urls were inserted versus updated.

## 7. SQL vs. SQLAlchemy

`query_data.py` answers each question with handwritten SQL; `orm_queries.py` repeats a subset using the SQLAlchemy ORM. Below is A1 ("What percentage of total acceptances come from each term found in the data?") answered both ways.

**Raw SQL (`query_data.py`):**

```sql
WITH accepted AS (
    SELECT term, COUNT(*) AS cnt
    FROM applicants
    WHERE status ILIKE 'Accepted%'
    GROUP BY term
),
total_accepted AS (
    SELECT COUNT(*) AS cnt
    FROM applicants
    WHERE status ILIKE 'Accepted%'
)
SELECT accepted.term,
        ROUND(accepted.cnt * 100.0 / total_accepted.cnt, 2) || '%' AS pct_of_acceptances
FROM accepted, total_accepted
ORDER BY split_part(accepted.term, ' ', 2)::int,
        CASE WHEN accepted.term LIKE 'Spring%' THEN 0 ELSE 1 END
```

**SQLAlchemy (`orm_queries.py`):**

```python
accepted_filter = Applicant.status.ilike("Accepted%")

total_accepted = session.execute(
    select(func.count()).select_from(Applicant).where(accepted_filter)
).scalar_one()

rows = session.execute(
    select(Applicant.term, func.count().label("cnt"))
    .where(accepted_filter)
    .group_by(Applicant.term)
).all()
```

**Comparison:** An advantage of the ORM version is it expresses `accepted_filter` once and reuses it across both queries as an ordinary Python value, and a typo in a column name fails immediately as an `AttributeError` rather than surfacing later as a SQL error string, making it easier to compose and safer to refactor than raw SQL. The raw SQL version, however, computes both counts and the final percentage in a single round trip to PostgreSQL via two CTEs, giving exact control over the one query plan that runs, whereas the ORM version needs two separate queries and finishes the percentage math and chronological ordering back in Python. Raw SQL is also more portable, since it can be pasted directly into `psql` or a BI tool to verify by hand, while the ORM query only exists as Python that needs the rest of this project to run.

## 8. Local LLM Standardization

Adds `llm-generated-program` / `llm-generated-university` to every row via a self-hosted TinyLlama model, leaving the original `program` field intact. From `module_5/src`:

```
python -m llm_hosting.app --file ../data/applicant_data.json --out ../data/llm_extend_applicant_data.json --parallel --n_workers 10 --n_threads 1
```

`--n_workers 10` is tuned for a 14-core machine (higher caused CPU oversubscription, see below); lower it on a machine with fewer cores. Progress can be checked while running via `wc -l chunk_*.jsonl` inside `llm_hosting/.llm_state/`.

### Changes made on top of the provided `app.py`
- **Parallelization** (new file `llm_helper.py`): the provided CLI processed rows one at a time. `run_parallel()` splits the input into `--n_workers` chunks, runs a `python -m llm_hosting.app` worker on each in its own subprocess, and merges the JSONL outputs into one JSON array, still as a single CLI command via new `--parallel`/`--n_workers`/`--n_threads` flags. `llm_helper.py` also owns `get_model_path()`, so `app.py` imports from it and the two files never import each other.
- **Fixed a model-download race**: every worker independently downloaded the same ~669MB model file at once, corrupting it. Fixed by downloading once up front and checking for an existing file before ever calling the Hub downloader.
- **Fixed CPU oversubscription**: `--n_threads=1` alone didn't stop one worker from using 540% CPU, since llama.cpp's BLAS backend (Accelerate/vecLib on macOS) ignores that setting. Fixed by also setting `VECLIB_MAXIMUM_THREADS`, `OMP_NUM_THREADS`, and `OPENBLAS_NUM_THREADS` to 1 per worker.
- **Added resumability and failure visibility**: a chunk with partial output resumes instead of reprocessing, and a worker that exits non-zero is now reported by name instead of silently contributing nothing.

### Canonical lists / post-processing

No edits were made to `canon_universities.txt` / `canon_programs.txt`. Reviewing ~4,500 standardized rows surfaced three issues upstream of the canonical-list step: blind Title Case wrongly capitalizes small connector words ("University At Buffalo" instead of "at"); it also mangles acronyms ("SUNY Albany" -> "Suny Albany"); and the model occasionally introduces its own typos ("Pratt Institute" -> "Praitt Institute"). A more robust fix would replace the blind `.title()` calls with a small-word exception list and an acronym-preservation check, but none was made for this submission.

Cross-checking against `canon_universities.txt` also found a fixable bug: "Eth Zurich" fails to canonicalize even though the list has the correctly-cased "ETH Zurich," because both the exact-match check and the `difflib` fuzzy fallback (cutoff 0.86) are case-sensitive, and the casing difference alone drops the similarity to ~0.80. Comparing case-insensitively before both checks would fix it. Separately, common names like "University of Minnesota" (31 occurrences) and "Rutgers University" (27 occurrences) never canonicalize because the list only has campus-qualified variants, not the bare parent name applicants actually write; a list built for this dataset should probably include those directly.

## 9. Robots.txt Compliance

GradCafe's robots.txt was reviewed manually before writing any scraping code and captured in `screenshot.jpg`, confirming `/survey` is not disallowed. This is also enforced automatically: `scrape.py`'s `check_robots_allowed()` checks `can_fetch("*", admissions_url)` before any browser launches, raising immediately if disallowed. Only the public `/survey` results listing is accessed.

## 10. Known Bugs / Limitations

- Explicit Selenium waits (`WebDriverWait`) aren't used; page-readiness is inferred from a results-table check plus a jittered delay, a deliberate tradeoff that means a page could in principle be read slightly before fully rendering.
- `storage.py`'s `save_data()` assumes the file it's appending to ends in exactly the bytes it last wrote; a file edited by hand or another tool afterward could break that assumption.
- If `run.py` is restarted mid-pull, `pull_control`'s in-memory state is lost and the page shows Pull Data as idle even though the old Chrome process may still be running. Restart cleans up that orphaned Chrome process first, so only the tracking of that run is lost.

## 11. Linting and Dependency Graph

### Pylint

Every Python file under `src/` scores 10.00/10 with Pylint's default settings, with no errors or warnings. Code outside `src/` (tests, docs) is not linted. From `module_5`, with the virtual environment active:

```
pylint src --recursive=y
```

`--recursive=y` finds every module under `src/` without needing `src/` itself to be a package. Adding `--fail-under=10` makes the command exit non-zero below a perfect score, which is how CI enforces it. The same command works from the repository root as `pylint module_5/src --recursive=y`.

A few inline `# pylint: disable=...` comments remain, each on a single line with a comment explaining why:

- `not-callable` for SQLAlchemy's `func.count` and Selenium's `webdriver.Chrome`, which are built at runtime where static analysis can't see them.
- `consider-using-with` where a subprocess or file must outlive the function that opens it (the Pull Data scraper, Chrome, the LLM workers, and the standardizer's output file, which the caller's own `with` block closes).
- `too-few-public-methods` on the SQLAlchemy model classes, which declare columns rather than methods.

### Dependency graph (pydeps + Graphviz)

`dependency.svg` in `module_5` maps the import graph starting from the Flask entry point, `src/run.py`. It needs `pydeps` (installed from `requirements.txt`) and Graphviz's `dot` on your PATH (`brew install graphviz` on macOS, `sudo apt-get install graphviz` on Ubuntu). From `module_5/src`:

```
pydeps run.py --noshow -T svg --max-bacon 3 --max-module-depth 2 -o ../dependency.svg
```

`--max-bacon 3` follows imports three hops from `run.py`, enough to reach every project module (including `scraping.clean`/`storage`, which `run.py` only reaches through `pull_control` and `scrape`) and the libraries they use directly. `--max-module-depth 2` collapses each library's internal submodules (for example every `sqlalchemy.engine.*` module into one `sqlalchemy.engine` node), so the project's own modules stay readable next to the SQLAlchemy and psycopg clusters. `--noshow` skips opening a viewer, so the same command works in CI.

## 12. Testing

### Setup

1. Install with either option in [Fresh Install](#2-fresh-install); `requirements.txt` already covers `pytest`, `pytest-cov`, `pytest-randomly`, and every runtime dependency, including `llm_hosting`'s.
2. Create a disposable `cam_db_test` PostgreSQL database and load the same schema as `cam_db`: `psql -d cam_db_test -f schema.sql` (see [section 6](#6-loading-into-postgresql)) - the test suite never touches `cam_db`'s real data. `tests/conftest.py` always sets `DB_NAME=cam_db_test`, whatever your shell exports, and never loads `.env`. `DB_HOST`, `DB_PORT`, `DB_USER`, and `DB_PASSWORD` are used as-is when set (as CI sets them for its own Postgres service container); otherwise they default to `localhost`, `5432`, the current OS user (via `getpass.getuser()` rather than a hardcoded name, so local runs work on whatever machine the suite runs on), and a blank password. `db_connection` also refuses to run unless `cam_db_test` appears in the connection URL, so a misconfigured override can never truncate real data.
3. The suite truncates `applicants` between tests, so it connects as the table's owner, not as `gradcafe_app` (which deliberately has no `TRUNCATE`). Local trust-authed PostgreSQL doesn't check passwords at all, which is why the default test password is blank.

### Running the suite

**Always run from the repository root** (`jhu_software_concepts/`, the parent of `module_5/`), with the `module_5/tests` path included:

```
pytest module_5/tests -m "web or buttons or analysis or db or integration"
```

The assignment instructions give the bare form (`pytest -m "web or buttons or analysis or db or integration"`, with no path) as the command that must run the full suite. Run from the repository root, that bare command does correctly run and pass the entire marked suite (`271 passed`) - pytest's `-m` marker filtering works off marks actually present on each test at collection time, and doesn't require `pytest.ini` to be found at all to do that. What it does *not* do is enforce coverage, since `pytest.ini`'s `addopts` (`--cov=module_5/src --cov-fail-under=100 ...`) is never loaded without the config file being found, and pytest's config-file search only looks *upward* from the current directory, never into subdirectories - `pytest.ini` lives in `module_5/`, which isn't an ancestor of the repository root. It also emits a `PytestUnknownMarkWarning` per mark, since registering marks (to suppress that warning) is a separate ini-only effect from `-m` filtering itself. Concretely:

- Bare `pytest -m "..."` from the repository root: runs and passes the full marked suite, but with no coverage enforcement and a mark-registration warning per test.
- Bare `pytest -m "..."` from `module_5/`: `pytest.ini` *is* found (it's the current directory), but its `--cov-config=module_5/pytest.ini` then resolves to the nonexistent `module_5/module_5/pytest.ini` and coverage.py raises a hard `ConfigError`, so the run doesn't complete at all.
- `pytest module_5/tests -m "..."` from the repository root: pytest's config search starts from the given path's directory, walking upward from `module_5/tests` and finding `module_5/pytest.ini` immediately, while `--cov=module_5/src` and `--cov-config=module_5/pytest.ini` are both correct relative to the repository root (the invocation directory). This is the only one of the three that also enforces the 100% coverage gate, which is why it's what this project actually uses and what CI runs.

Every test is marked with exactly one of `web`, `buttons`, `analysis`, `db`, or `integration` (registered in `pytest.ini`); running the full unmarked `pytest module_5/tests` also works and is equivalent, since every test already carries one of these five marks.

This same command runs automatically in GitHub Actions on every push, against its own disposable Postgres service container (workflow at `.github/workflows/tests.yml`, in the repository root rather than under `module_5/`).

### Coverage

`pytest.ini`'s `--cov-fail-under=100` enforces 100% statement coverage across every file under `module_5/src`, including `scraping/` (Selenium/subprocess mocked, never a real browser) and `llm_hosting/` (the real `Llama`/`hf_hub_download` calls mocked, never a real model load or network request). `pytest.ini`'s own `[report]` section (read via `addopts`' `--cov-config=module_5/pytest.ini`, since coverage.py otherwise only looks for a `.coveragerc` in the invocation directory) excludes each file's `if __name__ == "__main__":` guard line - and, since excluding a compound statement's header excludes its whole block, everything under it - from that count, since that code only ever runs when a script is invoked directly, never via `import`, which is all `pytest` ever does. The current terminal summary is committed at `module_5/coverage_summary.txt`.

### Notes on test design

- `llm_hosting/app.py` and `llm_hosting/llm_helper.py` are imported by their full package names (`import llm_hosting.app as llm_app`), which never collide with the Flask `app` package in `src/app/`. `run_parallel()`'s model download is replaced in tests by monkeypatching `llm_helper.get_model_path`.
- Database tests use a real local PostgreSQL connection (`cam_db_test`), not a mocked one, so schema/constraint behavior (`NOT NULL`, `UNIQUE`, upsert-on-conflict) is verified for real rather than assumed.
- Selenium, subprocess, and `urllib` calls in `scraping/scrape.py` are mocked at the point of use in every test; no test here ever launches a real Chrome instance or makes a real HTTP request.
- The Pull Data and Update Analysis buttons carry `data-testid="pull-data-btn"` / `data-testid="update-analysis-btn"` attributes (alongside the `id` attributes the page's own JS uses), so UI tests have a stable selector that doesn't break if the visible button text or styling changes.
- Structural page assertions (button presence, "Answer:" labeling) parse the rendered HTML with BeautifulSoup and query by selector (`data-testid`, `.answer`) rather than searching the raw response body for substrings, so a test doesn't pass or fail based on incidental whitespace or unrelated text elsewhere on the page. Percentage-formatting assertions use a regex instead, since a percentage is a text value, not a structural element.

## 13. Documentation

Sphinx documentation (`docs/source/`) covers an overview and setup guide, an
architecture description of the web/ETL/DB layers, autodoc API reference
pages for every module, and a testing guide covering markers, selectors,
and fixtures.

### Building and viewing locally

From `module_5`, with the virtual environment active:

```
pip install sphinx sphinx_rtd_theme
sphinx-build -b html docs/source docs/build
open docs/build/index.html        # Linux: xdg-open docs/build/index.html
```

### Published version

[cela-jh-jhu-software-concepts.readthedocs.io](https://cela-jh-jhu-software-concepts.readthedocs.io/en/latest/)

## 14. Citations

### CLAUDE

- Wrote test cases in small sets, stopping for human review and modification after each test file with back-and-forth questions and explanations for understanding and covering edge cases
- Considered edge cases and helped develop error-catching methods
- Executed author-selected refactoring, repairing broken filepaths and imports and ensuring they wouldn't break with future refactoring
- Converted comments and docstrings to Sphinx format and generated Sphinx documentation
- Created most of this README
