"""
`scrape.py`
Scrapes admissions results from GradCafe into a JSON file. Run directly
(`python scrape.py [options] [output.json]`) to scrape; `scrape_data` and
the other functions here can also be imported on their own.
"""
import argparse
import functools
import sys
import time
import random
import tempfile
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from bs4 import BeautifulSoup

from clean import clean_data
from data import save_data, validate_filepath, save_state, load_state, load_existing_urls

# Force every print() in this process to flush immediately for logging purposes.
# Helps prevent making a script that is working look hung.
print = functools.partial(print, flush=True)

RESTART_EVERY_N_PAGES = 500


def create_profile_dir():
    """
    Creates a new temporary Chrome profile directory.
    Returns the path.
    """
    return tempfile.mkdtemp()


def _open_chrome(chrome_bin, profile_dir):
    """
    Opens Chrome in remote debugging mode using given Chrome binary path
    and a persistent profile directory.
    Returns the Chrome process.
    """
    chrome_process = subprocess.Popen(
        [
            chrome_bin,
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return chrome_process



def _try_debug_endpoint(host_port, retries=10):
    """
    Tries opening the debugging endpoint until open or reaching number of retries.
    """
    for _ in range(retries):
        try:
            urlopen(urljoin(host_port, "json"), timeout=10)
            break
        except URLError:
            time.sleep(1)


def _init_webdriver(host_port):
    """
    Create Chrome webdriver with remote debug options.
    Returns Chrome driver.
    """
    options = webdriver.ChromeOptions()
    options.debugger_address = host_port
    options.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2
    })
    driver = webdriver.Chrome(options=options)

    return driver


def terminate_process(process, timeout=10):
    """
    Terminates the given Chrome process, force-killing it if it doesn't
    respond to termination within the timeout. Does not remove the profile
    directory, since it may be reused across restarts.
    Returns none.
    """
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def cleanup_profile(profile_dir):
    """
    Removes the given Chrome profile directory. Call only once the profile
    is done being reused (i.e. scraping has fully finished).
    Returns none.
    """
    shutil.rmtree(profile_dir)


def chrome_helper(url, host_port, chrome_bin, profile_dir, retries=5, base_retry_delay=15):
    """
    Helper to work around Cloudflare verification at url (GradCafe), using a
    persistent Chrome profile so a cleared session survives restarts.
    Retries the initial navigation on transient errors, then only pauses for
    manual input if a Cloudflare challenge is actually shown. Cleans up its
    own spawned process if initialization fails partway through.
    Returns resulting driver and Chrome process.
    """
    chrome_process = _open_chrome(chrome_bin, profile_dir)
    try:
        http_host = "http://" + host_port
        _try_debug_endpoint(http_host)
        driver = _init_webdriver(host_port)

        for attempt in range(1, retries + 1):
            try:
                driver.get(url)
                break
            except Exception as e:
                print(f"Initial page load failed (attempt {attempt}/{retries}): {e}")
                if attempt == retries:
                    raise
                retry_delay = base_retry_delay * (2 ** (attempt - 1))
                print(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)

        if "Just a moment" in driver.title:
            input("Complete Cloudflare check in browser. Then, press Enter: ")
    except Exception:
        terminate_process(chrome_process)
        raise

    return driver, chrome_process


def check_robots_allowed(url, user_agent="*"):
    """
    Checks the site's robots.txt to see if scraping is permitted on the domain.
    Fetches it with a browser-like User-Agent, since Cloudflare returns a 403
    for RobotFileParser's default "Python-urllib/x.y" UA - which robotparser's
    read() treats as "disallow everything" rather than as a fetch failure.
    Returns True if allowed, else False.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    request = Request(robots_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request) as response:
        lines = response.read().decode("utf-8").splitlines()

    robots_parser = RobotFileParser()
    robots_parser.set_url(robots_url)
    robots_parser.parse(lines)

    return robots_parser.can_fetch(user_agent, url)


def _get_page(driver, url=None, wait=2, retries=5, base_retry_delay=15):
    """
    Loads a page either by navigating to `url` directly, or, if url is None,
    by using whatever page is currently loaded (like after clicking "Next").
    Retries by re-navigating (or refreshing) on transient errors or
    unexpected page content, with an exponentially growing delay between
    attempts, and a randomized polling delay once successful.
    Returns a BeautifulSoup object.
    """
    soup = None
    for attempt in range(1, retries + 1):
        try:
            if url is not None:
                driver.get(url)
            candidate = BeautifulSoup(driver.page_source, "html.parser")
            if candidate.find("tbody") is None:
                raise RuntimeError(f"Results table not found (page title: '{driver.title}').")
            soup = candidate
            break
        except HTTPError as e:
            print("HTTP Error:", e.code)
            sys.exit(1)
        except Exception as e:
            print(f"Page load failed (attempt {attempt}/{retries}): {e}")
            if attempt == retries:
                raise
            retry_delay = base_retry_delay * (2 ** (attempt - 1))
            print(f"Retrying in {retry_delay}s...")
            time.sleep(retry_delay)
            if url is None:
                driver.refresh()

    time.sleep(random.uniform(wait * 0.7, wait * 1.3))    #  add polite, jittered polling time

    return soup


def _click_next_page(driver, retries=5, base_retry_delay=15,
                      missing_link_retries=3, missing_link_delay=5):
    """
    Finds and clicks the "Next" pagination link via JavaScript so navigation
    carries a natural Referer header and isn't blocked by overlapping page
    elements that would intercept a native mouse click. Retries
    on transient WebDriver command failures.

    Not finding the "Next" link is retried with a short wait and a page
    refresh up to {missing_link_retries} times in case the page has not loaded yet.

    Returns the resulting page's URL, or None if no next page exists after
    exhausting missing_link_retries.
    """
    for attempt in range(1, retries + 1):
        try:
            next_link = None
            for missing_attempt in range(1, missing_link_retries + 1):
                try:
                    next_link = driver.find_element(
                        By.XPATH, '//nav[@aria-label="Results pagination"]//a[normalize-space(text())="Next"]'
                    )
                    break
                except NoSuchElementException:
                    if missing_attempt == missing_link_retries:
                        return None
                    delay = missing_link_delay * (2 ** (missing_attempt - 1))
                    print(f"'Next' link not found (check {missing_attempt}/{missing_link_retries}); "
                          f"refreshing and re-checking in {delay}s before assuming no more pages...")
                    driver.refresh()
                    time.sleep(delay)

            driver.execute_script("arguments[0].click();", next_link)
            return driver.current_url
        except Exception as e:
            print(f"Click 'Next' failed (attempt {attempt}/{retries}): {e}")
            if attempt == retries:
                raise
            retry_delay = base_retry_delay * (2 ** (attempt - 1))
            print(f"Retrying in {retry_delay}s...")
            time.sleep(retry_delay)


def scrape_data(driver, url=None):
    """
    Scrapes admissions results from the page at `url`, or from whatever page
    is currently loaded if url is None. Clicks "Next" afterward so the
    following page's request carries a natural Referer.
    Returns list of Tag objects, each being a row with application details,
    and the next page's URL (for resumable state), or None if no next page
    exists.
    """
    soup = _get_page(driver, url)
    table = soup.find("tbody")
    results = table.find_all("tr")
    next_page_url = _click_next_page(driver)

    return results, next_page_url


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
    Parses CLI arguments for scraping GradCafe admissions results directly.
    """
    parser = argparse.ArgumentParser(
        description="Scrape GradCafe admissions results into a JSON file."
    )
    parser.add_argument(
        "--num_results", type=int, required=True,
        help="Number of results to collect."
    )
    parser.add_argument(
        "--chrome_binary", type=Path, required=True,
        help="Absolute path to the system Chrome binary."
    )
    parser.add_argument(
        "relative_filepath", type=Path, nargs="?", default=Path("applicant_data.json"),
        help="File to save results to (default: `applicant_data.json`)"
    )
    return parser.parse_args()


def run_scrape(args):
    """
    Scrapes GradCafe admissions results into a JSON file, resuming from
    saved pagination state and skipping already-seen results when the
    output file already exists.
    Returns none.
    """
    validate_filepath(args.relative_filepath, must_exist=False)

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


if __name__ == "__main__":
    run_scrape(parse_args())
