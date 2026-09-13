"""
`main.py`
Runs the scraping and cleaning process for admissions results from GradCafe.
Uses a helper script to handle Cloudflare's anti-bot protection.
"""
import argparse
import json
import time
from pathlib import Path
from scrape import (
    scrape_data, chrome_helper, terminate_process, cleanup_profile,
    create_profile_dir, check_robots_allowed
)
from clean import clean_data
from data import save_data, load_data, validate_filepath, save_state, load_state

RESTART_EVERY_N_PAGES = 100


def format_duration(seconds):
    """
    Converts seconds to hours, minutes, seconds for loop/script execution.
    """
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)

    # executes in seconds
    if minutes == 0 and hours == 0:
        return f"{secs}s"
    # executes in minutes
    elif minutes > 0 and hours == 0:
        return f"{minutes}m {secs}s"
    
    return f"{hours}h {minutes}m {round(secs, 0)}s"


def parse_args():
    """
    Parse CLI arguments for defining scrape job or data to load.
    """
    parser = argparse.ArgumentParser(
        description="Scrape GradCafe admissions results or load previously " \
        "saved results data from JSON."
    )
    # --num_results and --load are mutually exclusive
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--num_results", type=int,
        help="Number of results to collect. Scraping stops when reaching this" \
        " many or when there are no more results. There may be slightly more " \
        "results than the input since results are gathered by page."
    )
    group.add_argument(
        "--load", action="store_true",
        help="Load and print an existing results file instead of scraping."
    )
    parser.add_argument(
        "--chrome_binary", type=Path,
        help="Absolute path to the system Chrome binary. Required unless" \
        " --load is given."
    )
    parser.add_argument(
        "relative_filepath", type=Path, nargs="?", default=Path("applicant_data.json"),
        help="File to save results to or to load from if --load is given "
        "(default: `applicant_data.json`)"
    )
    return parser.parse_args()


def main(args):
    validate_filepath(args.relative_filepath, must_exist=args.load)

    # if loading a results file
    if args.load:
        load_data(args.relative_filepath)
        return 0

    # missing Chrome binary for scraping
    if args.chrome_binary is None:
        raise ValueError("--chrome_binary is required unless --load is given.")
    # invalid filepath to Chrome binary
    if not args.chrome_binary.is_file():
        raise FileNotFoundError(f"'{args.chrome_binary}' is not a valid Chrome binary path.")

    admissions_url = "https://www.thegradcafe.com/survey"
    # check for permission with robots.txt
    if not check_robots_allowed(admissions_url):
        raise PermissionError(f"Scraping {admissions_url} is disallowed by robots.txt")

    # getting recent state or starting new
    current_url = None
    result_count = None
    state_path = args.relative_filepath.with_suffix(".state.json")
    state = load_state(state_path)
    if state:
        current_url = state["next_url"]
        result_count = state["result_count"]
        print(f"Resuming from saved state: {result_count} results already collected.")
    else:
        current_url = admissions_url
        result_count = 0

    # do not scrape if result already reached in file
    if result_count >= args.num_results:
        print(f"Already have {result_count} results (>= requested {args.num_results}); nothing to do.")
        return 0

    chrome_process = None
    profile_dir = create_profile_dir()
    try:
        # open Chrome browser
        driver, chrome_process = chrome_helper(
            admissions_url, "127.0.0.1:9222", args.chrome_binary, profile_dir
        )

        pages_completed = 0
        total_start = time.time()

        # continue scraping until CLI quota met
        while result_count < args.num_results:
            admissions_results, next_page_url = scrape_data(driver, current_url)
            parsed_results = clean_data(admissions_results, current_url)
            result_count += len(parsed_results)
            pages_completed += 1

            save_data(parsed_results, args.relative_filepath)

            if result_count >= args.num_results:
                print(f"Scraping finished with {result_count} results.")
                state_path.unlink(missing_ok=True)
                break

            # get next page, if exists
            if next_page_url is None:
                print(f"No additional pages available. Stopping at {result_count} results.")
                state_path.unlink(missing_ok=True)
                break

            save_state({"next_url": next_page_url, "result_count": result_count}, state_path)
            
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

        total_elapsed = round(time.time() - total_start, 0)
        print(f"Total scraping time: {format_duration(total_elapsed)}")
    finally:
        if chrome_process is not None:
            terminate_process(chrome_process)
        cleanup_profile(profile_dir)

    return 0


if __name__ == "__main__":
    """
    Execute with following on CLI:
    For scraping: python main.py --num_results {integer} --chrome_binary {abs_path_bin} [relative_filepath="applicant_data.json"]
    For loading: python main.py --load [relative_filepath="applicant_data.json"]
    """
    # my Chrome bin: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    main(parse_args())
