"""
`main.py`
Entry point for scraping GradCafe admissions results, loading a results
file into the PostgreSQL applicants table, or running the Part 2 SQL
analysis queries against it.
"""
import argparse
import functools
import os
import time
from pathlib import Path

# Force every print() in this process to flush immediately for logging purposes.
# Helps prevent making a script that is working look hung.
print = functools.partial(print, flush=True)
from scrape import (
    scrape_data, chrome_helper, terminate_process, cleanup_profile,
    create_profile_dir, check_robots_allowed
)
from clean import clean_data
from data import save_data, validate_filepath, save_state, load_state, load_existing_urls
from load_data import load_data
from query_data import analyze, QUESTION_QUERY

RESTART_EVERY_N_PAGES = 500


def format_duration(seconds):
    """
    Converts seconds to hours, minutes, seconds for loop/script execution.
    """
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)

    if minutes == 0 and hours == 0:
        return f"{secs}s"
    elif minutes > 0 and hours == 0:
        return f"{minutes}m {secs}s"

    return f"{hours}h {minutes}m {round(secs, 0)}s"


def parse_args():
    """
    Parse CLI arguments for either scraping GradCafe or loading a results
    file into PostgreSQL.
    """
    parser = argparse.ArgumentParser(
        description="Scrape GradCafe admissions results, load a results "
        "file into the PostgreSQL applicants table, or run the Part 2 SQL "
        "analysis queries against it."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--scrape", action="store_true",
        help="Scrape GradCafe admissions results into a JSON file."
    )
    group.add_argument(
        "--load", action="store_true",
        help="Load a results file into the PostgreSQL applicants table."
    )
    group.add_argument(
        "--query", action="store_true",
        help="Run the Part 2 SQL analysis queries against the applicants table."
    )
    parser.add_argument(
        "--num_results", type=int,
        help="Number of results to collect. Required with --scrape."
    )
    parser.add_argument(
        "--chrome_binary", type=Path,
        help="Absolute path to the system Chrome binary. Required with --scrape."
    )
    parser.add_argument(
        "--db_user", type=str,
        help="Database username. Required with --query."
    )
    parser.add_argument(
        "--db_password", type=str,
        help="Database password. Required with --query."
    )
    parser.add_argument(
        "relative_filepath", type=Path, nargs="?", default=Path("applicant_data.json"),
        help="File to save results to when scraping, or to load into "
        "PostgreSQL with --load (default: `applicant_data.json`)"
    )
    return parser.parse_args()


def _run_load(args):
    """
    Loads a results file into the PostgreSQL applicants table, reading
    credentials from the PGUSER and PGPASSWORD environment variables so
    they never appear on the command line or in this repository.
    Returns none.
    """
    validate_filepath(args.relative_filepath, must_exist=True)

    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    if not user or not password:
        print("Set the PGUSER and PGPASSWORD environment variables before using --load.")
        return

    load_data(args.relative_filepath, (user, password))


def _run_query(args):
    """
    Runs the Part 2 SQL analysis queries against the applicants table,
    using credentials supplied directly on the command line.
    Returns none.
    """
    if not args.db_user or not args.db_password:
        print("Pass --db_user and --db_password before using --query.")
        return

    credentials = (args.db_user, args.db_password)
    analyze(QUESTION_QUERY, credentials)


def _run_scrape(args):
    """
    Scrapes GradCafe admissions results into a JSON file, resuming from
    saved pagination state and skipping already-seen results when the
    output file already exists.
    Returns none.
    """
    validate_filepath(args.relative_filepath, must_exist=False)

    if args.num_results is None:
        raise ValueError("--num_results is required with --scrape.")
    if args.chrome_binary is None:
        raise ValueError("--chrome_binary is required with --scrape.")
    if not args.chrome_binary.is_file():
        raise FileNotFoundError(f"'{args.chrome_binary}' is not a valid Chrome binary path.")

    admissions_url = "https://www.thegradcafe.com/survey"
    if not check_robots_allowed(admissions_url):
        raise PermissionError(f"Scraping {admissions_url} is disallowed by robots.txt")

    # urls already on disk are the source of truth for how many unique
    # results exist and which ones to skip - this makes growing an
    # already-complete file safe even if the pagination state below is
    # stale, missing, or points back at page 1
    seen_urls = load_existing_urls(args.relative_filepath)
    result_count = len(seen_urls)

    state_path = args.relative_filepath.with_suffix(".state.json")
    state = load_state(state_path)
    if state:
        current_url = state["next_url"]
        print(f"Resuming pagination from saved state ({result_count} unique results already in file).")
    else:
        current_url = admissions_url

    if result_count >= args.num_results:
        print(f"Already have {result_count} results (>= requested {args.num_results}); nothing to do.")
        return

    chrome_process = None
    profile_dir = create_profile_dir()
    try:
        driver, chrome_process = chrome_helper(
            admissions_url, "127.0.0.1:9222", args.chrome_binary, profile_dir
        )

        pages_completed = 0
        total_start = time.time()
        # first page (fresh or resumed) needs an explicit URL navigation;
        # subsequent pages are reached by clicking "Next" inside scrape_data
        navigate_by_url = True

        while result_count < args.num_results:
            admissions_results, next_page_url = scrape_data(
                driver, current_url if navigate_by_url else None
            )
            navigate_by_url = False
            parsed_results = clean_data(admissions_results, current_url)
            pages_completed += 1

            # skip rows whose url is already on disk or already seen this
            # run, so growing a file that a prior run already completed
            # or pagination overlaps never adds duplicates
            new_results = [r for r in parsed_results if r.get("url") not in seen_urls]
            seen_urls.update(r["url"] for r in new_results if r.get("url"))
            result_count += len(new_results)

            if new_results:
                save_data(new_results, args.relative_filepath)

            # printed unconditionally for every page whether data was written
            # or not, so read pages are always visible even when they add nothing new
            print(
                f"Page {pages_completed}: read {len(parsed_results)}, "
                f"{len(new_results)} new ({result_count} total unique so far)"
            )

            if next_page_url is None:
                print(f"No additional pages available. Stopping at {result_count} results.")
                state_path.unlink(missing_ok=True)
                break

            # save pagination state even after reaching quota so later
            # runs asking for more results resume near here instead of
            # restarting the crawl from page 1
            save_state({"next_url": next_page_url}, state_path)

            if result_count >= args.num_results:
                print(f"Scraping finished with {result_count} results.")
                break

            avg_loop_time = (time.time() - total_start) / pages_completed
            remaining_results = args.num_results - result_count
            remaining_pages = -(-remaining_results // 20)  # ceiling division
            eta_seconds = remaining_pages * avg_loop_time
            print(
                f"Running total: {result_count} (ETA: {format_duration(eta_seconds)})"
            )

            current_url = next_page_url

            # periodic restart to clear accumulated browser session state
            if pages_completed % RESTART_EVERY_N_PAGES == 0:
                print("Restarting Chrome to clear accumulated session state...")
                terminate_process(chrome_process)
                driver, chrome_process = chrome_helper(
                    admissions_url, "127.0.0.1:9222", args.chrome_binary, profile_dir
                )
                navigate_by_url = True

        total_elapsed = round(time.time() - total_start, 0)
        print(f"Total scraping time: {format_duration(total_elapsed)}")
    finally:
        if chrome_process is not None:
            terminate_process(chrome_process)
        cleanup_profile(profile_dir)


def main(args):
    """
    Dispatches to scraping, loading, or querying based on which flag was given.
    Returns none.
    """
    if args.load:
        _run_load(args)
    elif args.query:
        _run_query(args)
    else:
        _run_scrape(args)

    return 0


if __name__ == "__main__":
    main(parse_args())
