"""
`main.py`
Runs the scraping and cleaning process for admissions results from GradCafe.
Uses a helper script to handle Cloudflare's anti-bot protection.
"""
import argparse
import json
import time
from pathlib import Path
from scrape import scrape_data, chrome_helper, terminate_process, check_robots_allowed
from clean import clean_data
from data import save_data, load_data, validate_filepath


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
    
    return f"{hours}h {minutes}m {secs}s"


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
    # my Chrome bin: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
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
    """
    Execute with following on CLI:
    For scraping: python main.py --num_results {integer} [relative_filepath="applicant_data.json"]
    For loading: python main.py --load [relative_filepath="applicant_data.json"]
    """
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
    try:
        driver, chrome_process, profile_dir = chrome_helper(
            admissions_url, "127.0.0.1:9222", args.chrome_binary
        )
        result_count = 0
        current_url = admissions_url
        total_start = time.time()

        # continue scraping until CLI quota met
        while result_count < args.num_results:
            loop_start = time.time()
            admissions_results, next_page_url = scrape_data(driver, current_url)
            parsed_results = clean_data(admissions_results, current_url)
            result_count += len(parsed_results)

            # log results to console
            for result in parsed_results:
                print(json.dumps(result, indent=2))

            save_data(parsed_results, args.relative_filepath)

            if result_count >= args.num_results:
                print(f"Scraping finished with {result_count} results.")
                break

            # get next page, if exists
            if next_page_url is None:
                print(f"No additional pages available. Stopping at {result_count} results.")
                break

            loop_elapsed = round(time.time() - loop_start, 1)
            print(f"{format_duration(loop_elapsed)}     Proceeding to next page:\n")

            current_url = next_page_url

        total_elapsed = round(time.time() - total_start, 0)
        print(f"Total scraping time: {format_duration(total_elapsed)}")
    finally:
        terminate_process(chrome_process, profile_dir)

    return 0


if __name__ == "__main__":
    main(parse_args())