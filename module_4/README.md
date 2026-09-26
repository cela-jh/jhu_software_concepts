# Module 4: Testing and Documentation

Cameron Ela, cela1@jh.edu

> Builds on the module_2 scraper and module_3's database/webapp work, reorganized under `src/`. There is no single combined entry point; scraping, loading, querying, and the webpage each run directly from their own file (see [CLI Usage](#3-cli-usage)).

## Table of Contents

1. [Overview](#1-overview)
2. [Setup](#2-setup)
3. [CLI Usage](#3-cli-usage)
4. [Cloudflare Workaround](#4-cloudflare-workaround)
5. [Function Reference](#5-function-reference)
6. [Loading Into PostgreSQL](#6-loading-into-postgresql)
7. [SQL vs. SQLAlchemy](#7-sql-vs-sqlalchemy)
8. [Local LLM Standardization](#8-local-llm-standardization)
9. [Robots.txt Compliance](#9-robotstxt-compliance)
10. [Known Bugs / Limitations](#10-known-bugs--limitations)
11. [Citations](#11-citations)
12. [Testing](#12-testing)

## 1. Overview

Four files, each independently executable, cover this project's work:

1. `src/scraping/scrape.py` - Scrapes publicly posted graduate admissions results from GradCafe (thegradcafe.com/survey) into a JSON file (`data/applicant_data.json`).
2. `src/database/load_data.py` - Loads a results file (`applicant_data.json`, or the LLM-standardized `llm_extend_applicant_data.json`) into a PostgreSQL table called `applicants`.
3. `src/database/query_data.py` - Runs the Part 2 SQL analysis queries against the `applicants` table and prints each answer to the console.
4. `src/run.py` - A Flask app displaying every analysis answer on one webpage, read live through the SQLAlchemy `Applicant` model rather than `query_data.py`'s raw-SQL path. Its Pull Data button runs `scrape.py` in the background to fetch newly submitted entries and load them into PostgreSQL; Update Analysis re-renders the page with current results without starting a scrape.

### File tree

```
module_4/
|-- requirements.txt
|-- venv/                  : project virtual environment
|-- data/
|   |-- applicant_data.json
|   |-- llm_extend_applicant_data.json
|   `-- .state/
|       `-- applicant_data.state.json : resumable-crawl sidecar (section 5)
|-- docs/
|   |-- source/             : Sphinx project (conf.py, index.rst, autodoc module stubs)
|   `-- build/               : generated HTML output (`sphinx-build -b html docs/source docs/build`)
`-- src/
    |-- paths.py           : shared DATA_DIR/STATE_DIR/SCRAPE_SCRIPT locations, resolved from this file
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
    `-- llm_hosting/       : provided local-LLM standardizer, extended (section 8), kept as its own installable tool
```

`scrape.py` imports `clean.py` and `storage.py` by name; Python adds a script's own directory to its import path when run directly, and all three live in `scraping/`. Any file that needs a sibling module in another package (`load_data.py` reusing `storage.py`'s `validate_filepath`, `pull_control.py` reusing `load_data.py`, `routes.py` reusing `database`'s modules, or anything needing `paths.py`) inserts `src/` onto its import path at startup, the same technique module_3 used for `module_2_files/`, just repointed at the new layout. `paths.py` centralizes `data/`, `data/.state/`, and `scrape.py`'s own location as constants so no file hardcodes a path to another directory more than once.

## 2. Setup

1. Requires Python 3.10+, Google Chrome installed locally, and a running PostgreSQL server with a database (this project uses `cam_db`) and an `applicants` table already created (schema in [section 6](#6-loading-into-postgresql)).
2. From `module_4`, create and activate a virtual environment:
   ```
   python3 -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   ```
3. Install dependencies: `pip install -r requirements.txt`
4. Locate your Chrome binary's absolute path (needed for `--chrome_binary`):
   - macOS: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
   - Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe`
   - Linux: usually `google-chrome` on PATH
5. Set `DATABASE_URL` (needed for `load_data.py`, `run.py`, `query_data.py`, `orm_queries.py`) to a `postgresql://user:password@host:port/dbname` connection string:
   ```
   export DATABASE_URL=postgresql://your_postgres_user:your_postgres_password@localhost:5432/cam_db
   ```
   On a locally trust-authed PostgreSQL install (no password needed), the password segment can be omitted entirely: `postgresql://your_postgres_user@localhost:5432/cam_db`.
6. `run.py`'s Pull Data button also needs `CHROME_BINARY` set to the path from step 4.

## 3. CLI Usage

Each command below is run on its own from `module_4`; none depend on a shared entry point. Every script resolves `data/` from its own file location via `paths.py`, so these all work the same regardless of current directory.

**Scraping:**
```
python src/scraping/scrape.py --num_results <N> --chrome_binary "<path to Chrome>" [output.json]
```
`--num_results` is the cumulative target for the whole crawl, including a resumed run's prior results, not "collect N more." A real Chrome window opens and navigates to GradCafe; if Cloudflare's challenge appears, solve it manually once (the script polls for it to clear rather than waiting on a keypress, so this also works with no terminal attached, as during a Pull Data run). Transient page failures (including Cloudflare 522s) are retried with exponential backoff instead of stopping the run. If interrupted, re-running the same command with the same output file resumes from saved state (`data/.state/`).

**Loading into PostgreSQL:**
```
DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/yourdb python src/database/load_data.py <file.json>
```
Validates every result, skips and reports any missing required fields, and upserts the rest (see [section 6](#6-loading-into-postgresql) for details). Prints a summary of loaded/updated/skipped counts at the end, and exits with a non-zero status if the file couldn't be read or the database couldn't be reached at all, so a calling script or CI step can tell an unsuccessful load apart from a completed one.

**Running the Part 2 SQL analysis:** `DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/yourdb python src/database/query_data.py`

**Running the Part 6 SQLAlchemy ORM analysis:** `DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/yourdb python src/database/orm_queries.py`

**Running the analysis webpage:**
```
DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/yourdb CHROME_BINARY="<path to Chrome>" python src/run.py [--file path/to/results.json]
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

## 4. Cloudflare Workaround

A plain urllib scrape returns HTTP 403, and a normal Selenium-launched Chrome fares no better, since Selenium's own browser-launch carries automation fingerprints that trigger a repeating "verify you are human" loop. The fix: launch a real Chrome process independently via `subprocess` (not through Selenium) with remote debugging enabled and a persistent profile, then attach Selenium to it over the DevTools Protocol. Since Selenium never launches the browser itself, it never carries the fingerprint that triggers the loop. If Cloudflare's challenge still appears, a human solves it once in the visible window; the script polls the page title until it clears rather than waiting on a keypress, so this works the same whether run directly or as `run.py`'s background Pull Data subprocess, which has no terminal. The cleared session then persists in that Chrome profile for the rest of the run and future runs.

## 5. Function Reference

Every function listed is public (no leading underscore).

### `paths.py`
- `DATA_DIR`, `STATE_DIR`, `SCRAPE_SCRIPT`, `DEFAULT_DATA_FILE`, `DEFAULT_LLM_DATA_FILE` - Constants resolved from this file's own location, so they hold regardless of the current working directory.
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
- `parse_args()` - Optional positional filepath (default `paths.DEFAULT_DATA_FILE`). Reads `DATABASE_URL` from the environment when run directly, exiting with a message (and non-zero status) if it's unset or the load itself fails.

### `database/query_data.py`
Holds `QUESTION_QUERY`, the list of (question, SQL, format_result) tuples for the Part 2 analysis.
- `analyze(question_query, database_url)` - Runs each query and prints its formatted answer; a failing query prints its error in place without stopping the rest.
- `_database_url()` - Reads `DATABASE_URL` from the environment, raising `EnvironmentError` if it's unset.

### `database/models.py`
- `Applicant` - SQLAlchemy model mapping the same `applicants` table `load_data.py` writes to (`p_id` as primary key). No separate table or copy of data is created.
- `get_engine(database_url)` / `get_session(database_url)` - Build a SQLAlchemy engine/session from a `DATABASE_URL`-style connection string, selecting the `psycopg` driver explicitly.

### `database/orm_queries.py`
- `orm_q1` through `orm_q9`, `orm_a1`, `orm_a2` - Repeat the matching Part 2 question with SQLAlchemy's `select()`/`where()`/`func()`/`and_()`/`or_()`, returning the same formatted answer as `query_data.py`. Term/status/nationality comparisons use case-insensitive `ilike()` rather than `==`, so a mixed-case value (e.g. "fall 2026") still matches; percentage denominators are computed independently of whatever column the numerator's `CASE` expression checks, so a blank or unusual value in that column doesn't silently drop a row from the total. `ALL_ORM_ANSWERS` lists all eleven for `run.py`; `ORM_QUESTIONS` lists Q1, Q4, Q5, Q8, Q9, and A1 for `run_orm_queries()`.
- `run_orm_queries(database_url)` / `_database_url()` - Same pattern as `query_data.py`.

`run.py` imports and runs the Flask app from `app/`, calling `pull_control.kill_stale_chrome()` on startup and shutdown so an orphaned Chrome process never blocks the next Pull Data click.

### `app/routes.py`
- `analysis()` - Route for `/analysis`. Runs every `orm_queries.ALL_ORM_ANSWERS` function against a fresh SQLAlchemy session, pairs each with its question text, and renders `analysis.html` with the Pull Data button's current state. Returns a plain error message if `DATABASE_URL` is unset (500), or a plain "database unavailable" message if PostgreSQL can't actually be reached (503), rather than an unhandled crash either way.
- `pull_start()` / `pull_cancel()` / `pull_status()` - Routes behind the Pull Data button (`POST /pull-data`, `POST /pull/cancel`, `GET /pull/status`), handing off to `pull_control` and returning JSON status. `pull_start()` and `update_analysis()` both include `ok`/`busy` boolean keys in their JSON responses alongside the existing `status`/`message` fields.

### `app/pull_control.py`
Tracks the single background pull `run.py` may have running, guarded by a lock.
- `kill_stale_chrome()` - Kills any process left listening on Chrome's remote debugging port from an earlier ungraceful exit.
- `is_running()` / `recent_lines()` - Whether a pull (scrape or its upload) is active, and its last five status lines.
- `start(chrome_binary, credentials)` - Starts `scrape.py` in pull mode if none is running, streams its output into `recent_lines()`, and loads results into PostgreSQL once it exits.
- `cancel()` - Sends SIGTERM to the running subprocess if still scraping; the upload step still runs on whatever was collected.

There is no `main.py`; `scrape.py`, `load_data.py`, `query_data.py`, and `run.py` each define their own `parse_args()` (or, for `run.py`, take no arguments) and run when executed directly.

## 6. Loading Into PostgreSQL

### Table schema

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

### Credentials

PostgreSQL credentials are never hardcoded and are always passed as a single `DATABASE_URL` connection string (`postgresql://user:password@host:port/dbname`). `load_data.py`, `run.py`, `query_data.py`, and `orm_queries.py` all read it from the environment at runtime rather than a CLI flag, since a flag's value is visible to other users (via `ps`) and saved in shell history. This also means tests can point the whole application at a different database (`cam_db_test`, in this project's own test suite) just by setting `DATABASE_URL` differently, with no other configuration to override.

### Validation and missing values

A result missing `program`, `date_added`, `url`, `status`, `term`, `us_or_international`, or `degree` (or with an unparseable `date_added`) is skipped and its id reported. `gpa`, `gre`, `gre_v`, `gre_aw`, `comments`, and the `llm_generated_*` fields are optional and become `NULL` when absent, covering both `llm_extend_applicant_data.json` and the plain `applicant_data.json`.

`gpa`/`gre`/`gre_v`/`gre_aw` are also range-checked (0-4.0, 130-170, 130-170, 0-6; `gre` means GRE Quantitative specifically, not a combined score) and set to `NULL` if out of range, since GradCafe badges occasionally hold a mis-scaled or placeholder value. `us_or_international` is normalized to `'Other'` when the scraped value isn't exactly `'American'` or `'International'`. Both checks run against the whole table on every load, cleaning up older rows too.

### Upserting instead of skipping duplicates

Loading a result whose url already exists updates that row instead of skipping it: every column is set to `COALESCE(new value, existing value)`, so a new non-null value overwrites what's there, but a field the new file lacks leaves the existing value untouched. This means loading `applicant_data.json` then `llm_extend_applicant_data.json` fills in the LLM fields on the same rows, and the reverse order doesn't wipe them back out.

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

Adds `llm-generated-program` / `llm-generated-university` to every row via a self-hosted TinyLlama model, leaving the original `program` field intact. From `module_4`:

```
cd src/llm_hosting && pip install -r requirements.txt
python app.py --file ../../../data/applicant_data.json --out ../../../data/llm_extend_applicant_data.json --parallel --n_workers 10 --n_threads 1
```

`--n_workers 10` is tuned for a 14-core machine (higher caused CPU oversubscription, see below); lower it on a machine with fewer cores. Progress can be checked while running via `wc -l chunk_*.jsonl` inside `llm_hosting/`.

### Changes made on top of the provided `app.py`
- **Parallelization** (new file `llm_helper.py`): the provided CLI processed rows one at a time. `split_and_run()` splits the input into `--n_workers` chunks, runs `app.py` on each in its own subprocess, and merges the JSONL outputs into one JSON array, still as a single CLI command via new `--parallel`/`--n_workers`/`--n_threads` flags.
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

## 11. Citations

### CLAUDE

- Wrote test cases in small sets, stopping for human review after each test file with back-and-forth questions and explanations for understanding and covering edge cases
- Considered edge cases and helped develop error-catching methods
- Played major role in refactoring code into organized directories, repairing broken filepaths and imports and ensuring they wouldn't break with future refactoring
- Created most of this README

## 12. Testing

### Setup

1. Create and activate `module_4/venv`, then `pip install -r requirements.txt` (already covers `pytest`, `pytest-cov`, `pytest-randomly`, and every runtime dependency, including `llm_hosting`'s).
2. Create a disposable `cam_db_test` PostgreSQL database with the same schema as `cam_db` (see [section 6](#6-loading-into-postgresql)) - the test suite never touches `cam_db`'s real data. `tests/conftest.py` builds a `DATABASE_URL` pointing at `cam_db_test` from the current OS user (`postgresql://<user>@localhost:5432/cam_db_test`, via `getpass.getuser()` rather than a hardcoded name, so this works on whatever machine the suite runs on) and sets it as the `DATABASE_URL` environment variable for the whole test session.
3. Local trust-authed PostgreSQL doesn't check the password's contents at all, which is why the test `DATABASE_URL` omits one entirely.

### Running the suite

**Always run from the repository root** (`jhu_software_concepts/`, the parent of `module_4/`), with the `module_4/tests` path included:

```
pytest module_4/tests -m "web or buttons or analysis or db or integration"
```

This differs from the assignment instructions, which give the bare form (`pytest -m "web or buttons or analysis or db or integration"`, with no path) as the command that must run the full suite. That exact bare command does not work correctly from any single directory, for a structural reason rather than a configuration mistake: `pytest.ini` lives in `module_4/` (per the assignment's own required file tree), but its `addopts` sets `--cov=module_4/src`, a path resolved relative to the invocation directory rather than to `pytest.ini`'s own location. Pytest's config-file search only looks *upward* from the current directory, never into subdirectories, and only when at least one path argument is given does that search start from somewhere other than the bare current directory. Concretely:

- Bare `pytest -m "..."` from `module_4/`: finds `pytest.ini` (it's the current directory), but `--cov=module_4/src` then resolves to the nonexistent `module_4/module_4/src` - fails with "Total coverage: 0.00%".
- Bare `pytest -m "..."` from the repository root: `--cov=module_4/src` would resolve correctly, but `pytest.ini` is never found at all (it's in a subdirectory, not an ancestor of the repository root), so no markers or coverage settings apply.
- `pytest module_4/tests -m "..."` from the repository root: the given path's directory is where pytest's config search starts, walking upward from `module_4/tests` and finding `module_4/pytest.ini` immediately, while `--cov=module_4/src` is correct relative to the repository root (the invocation directory). This is the only invocation of the three that satisfies both at once, which is why it's what this project actually uses.

Every test is marked with exactly one of `web`, `buttons`, `analysis`, `db`, or `integration` (registered in `pytest.ini`); running the full unmarked `pytest module_4/tests` also works and is equivalent, since every test already carries one of these five marks.

### Coverage

`pytest.ini`'s `--cov-fail-under=100` enforces 100% statement coverage across every file under `module_4/src`, including `scraping/` (Selenium/subprocess mocked, never a real browser) and `llm_hosting/` (the real `Llama`/`hf_hub_download` calls mocked, never a real model load or network request). `pytest.ini`'s own `[report]` section (read via `addopts`' `--cov-config=module_4/pytest.ini`, since coverage.py otherwise only looks for a `.coveragerc` in the invocation directory) excludes each file's `if __name__ == "__main__":` guard line - and, since excluding a compound statement's header excludes its whole block, everything under it - from that count, since that code only ever runs when a script is invoked directly, never via `import`, which is all `pytest` ever does. The current terminal summary is committed at `module_4/coverage_summary.txt`.

### Notes on test design

- `llm_hosting/app.py` and `llm_hosting/llm_helper.py` are loaded via `importlib` under names other than `app` (e.g. `llm_app`), since a bare `import app` would resolve to the already-imported Flask `app` package from `src/app/` instead (whichever module claims the name `app` in `sys.modules` first wins, for the rest of the process). `llm_helper.run_parallel()`'s own lazy `from app import _get_model_path` is satisfied in tests by temporarily inserting a fake module into `sys.modules["app"]`.
- Database tests use a real local PostgreSQL connection (`cam_db_test`), not a mocked one, so schema/constraint behavior (`NOT NULL`, `UNIQUE`, upsert-on-conflict) is verified for real rather than assumed.
- Selenium, subprocess, and `urllib` calls in `scraping/scrape.py` are mocked at the point of use in every test; no test here ever launches a real Chrome instance or makes a real HTTP request.
- The Pull Data and Update Analysis buttons carry `data-testid="pull-data-btn"` / `data-testid="update-analysis-btn"` attributes (alongside the `id` attributes the page's own JS uses), so UI tests have a stable selector that doesn't break if the visible button text or styling changes.
