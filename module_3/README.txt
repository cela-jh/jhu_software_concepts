Cameron Ela, cela1@jh.edu
Module Info: Module 3 - Database Queries Assignmemt, Due: [FILL IN due date]
NOTE: Module 3 is built on top of module 2. Information about module 2
      functionalities is included so `main` is a complete app with scraping and
      database actions.

================================================================================
TABLE OF CONTENTS
================================================================================
1. Overview
2. Setup
3. CLI Usage
4. Cloudflare Workaround
5. Function Reference
6. Loading Into PostgreSQL
7. Local LLM Standardization
8. Robots.txt Compliance
9. Known Bugs / Limitations
10. Citations


================================================================================
1. OVERVIEW
================================================================================
This module has two functions, both driven from one CLI entry point
(main.py --scrape or main.py --load):
  1. Scrape publicly posted graduate admissions results from GradCafe
     (thegradcafe.com/survey) into a JSON file (applicant_data.json).
  2. Load a results file (applicant_data.json, or the LLM-standardized
     llm_extend_applicant_data.json) into a PostgreSQL table called
     applicants.

Files:
  - scrape.py        : browser automation and HTML/table extraction
  - clean.py          : converts raw rows into structured dictionaries
  - data.py           : JSON persistence, resumable-crawl state, CLI validation
  - db_connection.py  : reusable PostgreSQL connect/disconnect helpers
  - load_data.py       : validates and loads a results file into PostgreSQL
  - main.py           : CLI entry point dispatching to scraping or loading
  - llm_hosting/       : provided local-LLM standardizer, extended with
    parallelization (see section 7)


================================================================================
2. SETUP
================================================================================
    1. Requires Python 3.10+, Google Chrome installed locally, and a
       running PostgreSQL server with a database (this project uses one
       named cam_db) and an "applicants" table already created (see
       section 6 for the schema).
    2. From the module_3 folder, create and activate a virtual environment:
           python3 -m venv venv
           source venv/bin/activate        (Windows: venv\Scripts\activate)
    3. Install dependencies:
           pip install -r requirements.txt
    4. Locate your Chrome binary's absolute path (needed for --chrome_binary
       when scraping):
           macOS:   /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
           Windows: C:\Program Files\Google\Chrome\Application\chrome.exe
           Linux:   usually `google-chrome` on PATH
    5. Set PostgreSQL credentials as environment variables (needed for
       --load; see section 6 for why):
           export PGUSER=your_postgres_user
           export PGPASSWORD=your_postgres_password


================================================================================
3. CLI USAGE
================================================================================
Scraping:
    python main.py --scrape --num_results <N> --chrome_binary "<path to Chrome>" [output.json]
    (--num_results is the cumulative target across the whole crawl,
    including a resumed run's prior results, not "collect N more.")

    Example:
    python main.py --scrape --num_results 30000 --chrome_binary "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" applicant_data.json

Loading a results file into PostgreSQL:
    PGUSER=youruser PGPASSWORD=yourpassword python main.py --load <file.json>

    Example:
    PGUSER=cameronela PGPASSWORD=mypassword python main.py --load llm_extend_applicant_data.json

    (--scrape and --load are mutually exclusive and one is required)

Steps to run a scrape:
    1. Run the scrape command above. A separate, real Chrome window opens
       automatically and navigates to GradCafe.
    2. If Cloudflare's challenge appears (title reads "Just a moment..."),
       solve it manually in that window, then press Enter at the prompt in
       the terminal to continue. If the profile is already cleared, no
       prompt appears and the script proceeds on its own.
    3. The script loops: scrape the page, clean it, append to the output
       file, click "Next," repeat - printing a running total and ETA after
       each page.
    4. If GradCafe returns a Cloudflare 522 (origin server unreachable) or
       any other transient page-load failure, the script does NOT quit -
       it retries that page with exponential backoff (15s, 30s, 60s,
       120s, ...) up to 5 attempts before giving up. This is why 522s seen
       during a run are not a problem on their own; the run keeps going.
    5. If the script is interrupted or crashes, re-run the same command
       with the same output filename - it prints "Resuming from saved
       state" and continues from where it left off.

Steps to run a load into PostgreSQL:
    1. Make sure PGUSER and PGPASSWORD are set (see section 2) and the
       applicants table already exists.
    2. Run the load command above, pointing at either applicant_data.json
       or llm_extend_applicant_data.json.
    3. If PGUSER/PGPASSWORD aren't set, the script prints a message asking
       you to set them and exits without attempting a connection.
    4. Every result in the file is validated; results missing a required
       field are skipped and their ids are printed together at the end,
       rather than one message per bad result.
    5. Valid results are inserted (or, if their url already exists in the
       table, upserted) in batches of 1,000 rows per statement for speed.
       If a batch fails, it is automatically split in half and retried,
       continuing to split down to 10-row batches and finally individual
       rows, so one bad row only costs that one row instead of the whole
       batch around it.
    6. Loading a file whose results already exist updates those rows
       instead of skipping them, filling in any optional field (such as
       llm_generated_program) that the earlier load didn't have, without
       creating duplicate rows.
    7. A final summary line reports how many results were newly loaded,
       how many existing results were updated, and how many were skipped
       for having missing or invalid fields.


================================================================================
4. CLOUDFLARE WORKAROUND
================================================================================
A plain urllib scrape returns HTTP 403 (Cloudflare blocks non-browser
clients). A normal Selenium-launched Chrome fares no better - Selenium's
own browser-launch carries automation fingerprints that put it in a
repeating "verify you are human" loop. The fix: launch a real Chrome
process independently via `subprocess` (not through Selenium) with remote
debugging enabled and a persistent profile, then attach Selenium to that
already-running browser over the DevTools Protocol. Because Selenium never
launches the browser itself, it never carries the fingerprint that
triggers the loop. If Cloudflare's challenge still appears, the script
pauses and a human solves it once in the visible window; the cleared
session then persists in that Chrome profile across the rest of the run
and future runs.


================================================================================
5. FUNCTION REFERENCE
================================================================================
Every function listed here is public (no leading underscore). Each
description also covers what its supporting internal steps do, without
naming them individually.

scrape.py
------------
  - create_profile_dir() -- Creates a fresh, persistent Chrome user-data
    directory, reused across restarts so a cleared Cloudflare session
    survives them.
  - terminate_process(process) -- Terminates a Chrome process, force-
    killing it if it doesn't respond within a timeout.
  - cleanup_profile(profile_dir) -- Deletes a Chrome profile directory
    once it is no longer needed.
  - chrome_helper(url, host_port, chrome_bin, profile_dir) -- REQUIRED.
    Launches Chrome as an independent process (so it never carries
    Selenium's automation fingerprint), waits for its remote-debugging
    endpoint to come up, and attaches a Selenium driver to it. Navigates
    to the given URL, retrying with growing delays if the page fails to
    load, and only pauses for manual Cloudflare verification if the
    challenge page is actually shown.
  - check_robots_allowed(url) -- Fetches and parses the site's robots.txt
    and reports whether scraping the given URL is currently permitted.
  - scrape_data(driver, url=None) -- REQUIRED. Loads the given page (or
    whatever page is already open, if no URL is given), confirming a
    results table is actually present and retrying with growing delays on
    a failed or unexpected page rather than reading bad data, then reads
    every row out of that table. Afterward it clicks the "Next" link via
    JavaScript so the click carries a normal-looking referring page and
    isn't blocked by an overlapping ad, and returns the rows read plus the
    resulting next-page URL (or None once there is no further page).

clean.py
-----------
  - clean_data(results, url) -- REQUIRED. The only public function in
    this file. Pairs each entry's main data row with whatever trailing
    tag or comment rows belong to it, pulls school, program, degree,
    date, status, and the entry's own URL out of the main row, and pulls
    term, nationality, and any available GRE/GPA scores or a comment out
    of the trailing rows by matching each against a set of known text
    patterns. Returns one dictionary per entry with a consistent key
    order, containing whichever fields that entry actually had.

data.py
----------
  - save_data(parsed_results, filepath) -- REQUIRED. Appends a page's new
    results directly onto the end of the existing JSON array on disk
    (by trimming and rewriting just its closing bracket) rather than
    reading and rewriting everything collected so far, which matters once
    a file holds tens of thousands of results.
  - load_existing_urls(filepath) -- Reads which urls are already saved in
    a results file, so a scrape can skip results it has already collected
    instead of adding duplicates.
  - validate_filepath(filepath, must_exist) -- Confirms a path is a .json
    file, and optionally that it already exists, raising a clear error
    otherwise.
  - save_state(state, filepath) / load_state(filepath) -- Write and read
    the small sidecar file recording where pagination left off, so an
    interrupted scrape resumes instead of restarting from page 1.

db_connection.py
-------------------
  - connect_db(conn_params, user, password) -- REQUIRED. Opens and
    returns a PostgreSQL connection, printing a clear message and
    returning None instead of raising if the connection fails.
  - disconnect_db(conn) -- Closes a connection opened by connect_db.
  - test_connection_db(conn_params, user, password) -- Opens a
    connection, prints which user it connected as, and returns the list
    of table names in the database's public schema, closing the
    connection before returning.

load_data.py
---------------
  - load_data(filepath, user, password) -- REQUIRED. Reads the given JSON
    file and connects to the database. For every result, it checks that
    program, date added, url, status, term, nationality, and degree are
    all present, converts the date and any GPA/GRE badge text into real
    numbers and dates, and leaves genuinely optional fields (GPA, GRE
    scores, comments, and the LLM-generated fields) as NULL when a result
    doesn't have them; a result missing a required field is skipped and
    its id collected for a single combined report at the end instead of
    stopping the load. Valid results are grouped into batches and written
    with one statement per batch for speed - a new url is inserted, and a
    url that already exists in the table is updated instead of skipped,
    so a later file that adds fields such as llm_generated_program fills
    them in rather than being ignored. If a batch fails, it is
    automatically retried in progressively smaller pieces, down to one
    row at a time, so a single bad row is reported individually instead
    of losing every row around it. The connection is always closed before
    the function returns, and a summary of how many results were newly
    loaded, updated, or skipped is printed at the end.

main.py
----------
  - format_duration(seconds) -- Converts a number of seconds into a
    readable "Xh Ym Zs" string, used for the progress and timing messages
    printed while scraping.
  - parse_args() -- Defines the CLI: exactly one of --scrape or --load is
    required, --num_results and --chrome_binary apply to --scrape, and a
    positional filepath is used as the output file when scraping or the
    input file when loading.
  - main(args) -- REQUIRED. Dispatches based on which flag was given.
    With --load, it confirms the input file exists, reads PostgreSQL
    credentials from the PGUSER and PGPASSWORD environment variables
    (printing a message and doing nothing further if either is unset),
    and hands off to the database loader. With --scrape, it confirms the
    Chrome binary path is valid and that scraping is allowed by
    robots.txt, then resumes from any saved pagination state and the set
    of urls already in the output file so re-running never adds
    duplicates. It then repeatedly scrapes a page, cleans it, appends any
    genuinely new results, saves updated pagination state, and moves to
    the next page - printing a running total and an estimated completion
    time - until the requested count is reached or there are no more
    pages, periodically restarting the browser to clear accumulated
    session state, and always shutting the browser down cleanly when
    finished or if an error occurs.


================================================================================
6. LOADING INTO POSTGRESQL
================================================================================
Table schema
---------------
The applicants table must already exist before running --load:

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

p_id is a plain integer, not an auto-incrementing key, because the source
data has no id of its own - load_data.py derives it from the numeric
Grad Cafe result id embedded in each entry's url (e.g. .../result/1020482
becomes p_id 1020482), so the same result always gets the same p_id no
matter when or how many times it is loaded. url has both UNIQUE and
NOT NULL so PostgreSQL can enforce "no duplicate results" itself rather
than the application having to check first.

Credentials
--------------
Per the assignment's requirement not to commit database passwords or
other secrets, PostgreSQL credentials are never hardcoded or passed as
CLI arguments (a CLI flag would be visible in shell history). They are
read at runtime from PGUSER and PGPASSWORD environment variables inside
main.py's --load handling; CONN_PARAMS (dbname/host/port) is not a
secret and stays as a plain constant in db_connection.py.

Validation and missing values
---------------------------------
A result missing program, date_added, url, status, term,
us_or_international, or degree (or with a date_added that doesn't
actually parse) is skipped, with its id collected and reported. gpa,
gre, gre_v, gre_aw, comments, llm_generated_program, and
llm_generated_university are all optional and become NULL when a result
doesn't have them, since none of these are required by the table schema
- this covers both llm_extend_applicant_data.json and the plain
applicant_data.json, which has no llm_generated fields at all.

Upserting instead of skipping duplicates
--------------------------------------------
Loading a result whose url is already in the table updates that row
instead of leaving it untouched: every column is set to
COALESCE(new value, existing value), so a new, non-null value overwrites
what's there, but a field the new file doesn't have (for example loading
applicant_data.json after llm_extend_applicant_data.json) leaves the
existing value in place instead of erasing it. This means loading
applicant_data.json first and llm_extend_applicant_data.json afterward
correctly fills in the LLM-generated fields on the same rows, and doing
it in the opposite order doesn't wipe them back out.

Batching
-----------
Rows are written BATCH_SIZE (1,000) at a time using one multi-row
statement per batch rather than one statement per row, cutting tens of
thousands of individual round trips down to a few dozen. Each attempt
runs inside its own PostgreSQL savepoint, so if a batch fails, only that
savepoint rolls back; the batch is then split in half and retried,
recursing down to SMALL_BATCH_SIZE (10) rows, at which point rows are
written one at a time so a single bad row is reported by its url instead
of taking the rest of its batch down with it. Each statement reports
back exactly which urls were newly inserted versus updated, so no
separate lookup query is needed to tell them apart.


================================================================================
7. LOCAL LLM STANDARDIZATION
================================================================================
Adds `llm-generated-program` / `llm-generated-university` to every row via
a self-hosted TinyLlama model, leaving the original `program` field intact
for traceability. From inside module_3, run:

    cd llm_hosting && pip install -r requirements.txt
    python app.py --file ../applicant_data.json --out ../llm_extend_applicant_data.json --parallel --n_workers 10 --n_threads 1

    (--n_workers 10 is a tuned value for a 14-core machine, chosen after
    observing that going higher led to CPU oversubscription rather than a
    speedup - see "Fixed CPU oversubscription" below; adjust it down on a
    machine with fewer cores)

While it's running, each worker's progress can be checked at any time by
counting completed lines in its chunk output file, from inside
llm_hosting/:

    wc -l chunk_*.jsonl

Changes made on top of the provided app.py:
  - Parallelization (new file llm_helper.py, public functions
    split_and_run() and jsonl_to_json()): the provided CLI processes rows
    one at a time with no concurrency. split_and_run() splits the input
    into --n_workers chunks (default 12), runs app.py on each in its own
    subprocess (--n_threads=1 each), and merges the JSONL outputs into one
    JSON array. app.py's __main__ gained --parallel/--n_workers/--n_threads
    flags so this is still one CLI command.
  - Fixed a model-download race: every worker was independently
    downloading the same ~669MB model file into the same path at once,
    corrupting it. Fixed by downloading once up front in the main process,
    adding an explicit "does this file already exist" check before ever
    calling the Hub downloader, and anchoring the model path to app.py's
    own file location (it had been resolving relative to each process's
    working directory, which differed between the orchestrator and the
    workers).
  - Fixed CPU oversubscription: even with --n_threads=1, one worker was
    observed using 540% CPU because llama.cpp's underlying BLAS backend
    (Apple's Accelerate/vecLib on macOS) has its own thread pool that
    ignores that setting. Fixed by also setting VECLIB_MAXIMUM_THREADS,
    OMP_NUM_THREADS, and OPENBLAS_NUM_THREADS to 1 for every worker.
  - Added resumability and failure visibility to split_and_run(): a chunk
    with existing partial output resumes from its last completed row
    instead of reprocessing it, and any worker that exits with a
    non-zero status is now reported by name instead of silently
    contributing zero rows to the merged output.

Canonical lists / post-processing
-------------------------------------
No edits were made to canon_universities.txt / canon_programs.txt at this
time. A review of ~4,500 standardized rows surfaced three systematic issues,
none of which a canonical-list edit would fix, since they occur upstream of
that step:
  - Blind Title Case on both fields incorrectly capitalizes small
    connector words that should stay lowercase (e.g. "University At
    Buffalo", "Library And Information Science", "International Studies
    On Media Power And Difference" instead of "at"/"and"/"on").
  - Acronym-style names lose their casing to the same Title Case pass
    (e.g. "SUNY Albany" -> "Suny Albany", "Universitat Pompeu Fabra
    (UPF)" -> "...(Upf)").
  - The model occasionally introduces its own typos/truncation in text
    that should simply be passed through unchanged (e.g. "Machine
    Learning" -> "Machinie Learning", "Pratt Institute" -> "Praitt
    Institute", "University of Maryland" -> "University of Mary").
A more robust fix would replace the blind `.title()` calls in
`_post_normalize_program`/`_post_normalize_university` with a small-word
exception list (a/an/the/of/at/and/on/...) and an acronym-preservation
check, but no such change was made for this submission.

Cross-checking standardized outputs against canon_universities.txt
surfaced a concrete, fixable bug rather than a missing entry:
"Eth Zurich" (the mis-cased model output) fails to canonicalize
even though the list contains the correctly-cased "ETH Zurich" verbatim.
`_post_normalize_university`'s exact-match check (`if u in CANON_UNIS`) is
case-sensitive, so it misses this; the fuzzy fallback (`difflib`,
cutoff=0.86) is also case-sensitive, and a two-letter case difference
("Eth" vs "ETH") drops the similarity ratio to ~0.80 - just under the
cutoff - so it never reaches the canonical form despite being an obvious
match to a human. The fix would be to compare case-insensitively (e.g.
lowercasing both sides) before the exact and fuzzy checks.

Separately, several very common universities never canonicalize simply
because the list only contains campus/branch-qualified full names, not
the bare parent name applicants actually tend to write: "University of
Minnesota" (31 occurrences in this sample) has no entry, only "University
of Minnesota Twin Cities"; "Rutgers University" (27 occurrences) has no
bare entry, only hyphen-qualified campus variants ("Rutgers
University-New Brunswick", etc., using an en dash rather than a plain
hyphen). Both are real, frequently-written names that a canonical list
built for this dataset should probably include directly, rather than
relying on fuzzy-matching a shorter name against a longer, more specific
one (which falls below the 0.86 cutoff purely due to the length
difference).


================================================================================
8. ROBOTS.TXT COMPLIANCE
================================================================================
GradCafe's robots.txt was reviewed manually before writing any scraping
code and captured in screenshot.jpg (this folder), confirming `/survey` is
not disallowed. This is also enforced automatically on every run:
scrape.py's check_robots_allowed() fetches and parses the live robots.txt
via urllib.robotparser and checks can_fetch("*", admissions_url) before
any browser is launched; if disallowed, main.py raises immediately and
nothing is scraped. Only the public `/survey` results listing is accessed.


================================================================================
9. KNOWN BUGS / LIMITATIONS
================================================================================
- Explicit Selenium waits (WebDriverWait) are not used; page-readiness is
  inferred after the fact by checking for a results table in the loaded
  page, plus a jittered delay - a deliberate tradeoff given GradCafe's
  pagination behavior, but it means a page could in principle be read
  slightly before fully rendering under unusual timing.


================================================================================
10. CITATIONS
================================================================================
- CLAUDE: Used primarily as an advisor and guide. Considered edge cases and
  helped developed error catching methods. Built out parallelization for LLM
  and save and load states for both LLM and scraping. Audited `module_2` and
  the PostgreSQL loading functionality for completeness based off of
  assignment rubrics/directions. Created most of this README.txt.
