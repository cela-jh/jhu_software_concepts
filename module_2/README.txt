Cameron Ela, cela1@jh.edu
Module Info: Module 2 - Web Scraping (GradCafe Admissions Data), Due: 13 September 2026


================================================================================
APPROACH
================================================================================

Overview
--------
Scrapes publicly posted graduate admissions results from GradCafe
(thegradcafe.com/survey) into applicant_data.json (30,400 entries), then
standardizes the messy "program"/university text with a self-hosted local
LLM into llm_extend_applicant_data.json. Split across:
  - scrape.py : browser automation and HTML/table extraction
  - clean.py  : converts raw rows into structured dictionaries
  - data.py   : JSON persistence, resumable-crawl state, CLI validation
  - main.py   : CLI entry point wiring the above into a loop
  - llm_hosting/ : provided local-LLM standardizer, extended with
    parallelization (see LLM section below)

Cloudflare workaround
----------------------
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

Public (non-helper) functions per file
------------------------------------------
scrape.py:
  - scrape_data(driver, url=None) -- REQUIRED. Loads/verifies the current
    results page, extracts its rows, clicks "Next," and returns
    (rows, next_page_url).
  - chrome_helper(url, host_port, chrome_bin, profile_dir) -- launches and
    attaches to the Cloudflare-workaround Chrome session described above.
  - check_robots_allowed(url) -- see robots.txt section below.
  - create_profile_dir() / terminate_process() / cleanup_profile() --
    manage the Chrome profile/process lifecycle across restarts.

clean.py:
  - clean_data(results, url) -- REQUIRED. The only public function in this
    file; groups raw rows and parses them into a list of clean
    dictionaries (school/program, degree, date, status, URL, term,
    nationality, GRE/GPA fields, comments where present).

data.py:
  - save_data(parsed_results, filepath) -- REQUIRED. Appends one page's
    results directly into the existing JSON array on disk in O(new rows)
    time (truncate the trailing "]", write the new rows, re-close the
    array), rather than re-reading and re-serializing everything collected
    so far - this matters once the crawl reaches tens of thousands of rows.
  - load_data(filepath) -- REQUIRED. Loads and pretty-prints an existing
    results file; used by `--load` (no scraping, no Chrome).
  - validate_filepath(filepath, must_exist) -- CLI input validation.
  - save_state(state, filepath) / load_state(filepath) -- resumable-crawl
    sidecar state (next URL + running count), so an interrupted run
    resumes instead of restarting from page 1.

main.py:
  - main(args) -- CLI entry point: validates input, resumes from saved
    state if present, drives the scrape loop (scrape -> clean -> save ->
    click Next) until the requested count is reached or no pages remain,
    with periodic Chrome restarts and a running ETA printed per page.
  - parse_args() -- defines the CLI (see usage below).

Setup
--------
    1. Requires Python 3.10+ and Google Chrome installed locally.
    2. From the module_2 folder, create and activate a virtual environment:
           python3 -m venv venv
           source venv/bin/activate        (Windows: venv\Scripts\activate)
    3. Install dependencies:
           pip install -r requirements.txt
    4. Locate your Chrome binary's absolute path (needed for --chrome_binary
       below):
           macOS:   /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
           Windows: C:\Program Files\Google\Chrome\Application\chrome.exe
           Linux:   usually `google-chrome` on PATH

CLI usage
------------
Scraping:
    python main.py --num_results <N> --chrome_binary "<path to Chrome>" [output.json]
    (--num_results is the cumulative target across the whole crawl,
    including a resumed run's prior results, not "collect N more.")

Loading an existing file (no scraping):
    python main.py --load [output.json]

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


================================================================================
LOCAL LLM STANDARDIZATION (llm_hosting/)
================================================================================

Adds `llm-generated-program` / `llm-generated-university` to every row via
a self-hosted TinyLlama model, leaving the original `program` field intact
for traceability. From inside module_2, run:

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
ROBOTS.TXT COMPLIANCE
================================================================================

GradCafe's robots.txt was reviewed manually before writing any scraping
code and captured in screenshot.jpg (this folder), confirming `/survey` is
not disallowed. This is also enforced automatically on every run:
scrape.py's check_robots_allowed() fetches and parses the live robots.txt
via urllib.robotparser and checks can_fetch("*", admissions_url) before
any browser is launched; if disallowed, main.py raises immediately and
nothing is scraped. Only the public `/survey` results listing is accessed.


================================================================================
KNOWN BUGS / LIMITATIONS
================================================================================

- Explicit Selenium waits (WebDriverWait) are not used; page-readiness is
  inferred after the fact by checking for a results table in the loaded
  page, plus a jittered delay - a deliberate tradeoff given GradCafe's
  pagination behavior, but it means a page could in principle be read
  slightly before fully rendering under unusual timing.


================================================================================
CITATIONS
================================================================================

- CLAUDE: Used primarily as an advisor and guide. Considered edge cases and
  helped developed error catching methods. Built out parallelization for LLM
  and save and load states for both LLM and scraping. Audited `module_2` for
  completeness based off of assignment rubric. Created most of this README.txt.
