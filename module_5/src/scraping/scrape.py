"""
`scrape.py`
Scrapes admissions results from GradCafe into a JSON file. Run from src/
as a module (`python -m scraping.scrape [options] [output.json]`) to
scrape; `scrape_data` and the other functions here can also be imported
on their own.
"""
import argparse
import signal
import sys
import time
import random
import tempfile
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from bs4 import BeautifulSoup

from paths import DEFAULT_DATA_FILE, state_path_for
from scraping.clean import clean_data
from scraping.storage import (
    save_data, validate_filepath, save_state, load_state, load_existing_urls,
)

RESTART_EVERY_N_PAGES = 500
PULL_SEEN_LIMIT = 1000
RESULTS_PER_PAGE = 20

ADMISSIONS_URL = "https://www.thegradcafe.com/survey"
CHROME_DEBUG_PORT = 9222
CHROME_DEBUG_HOST_PORT = f"127.0.0.1:{CHROME_DEBUG_PORT}"
NEXT_LINK_XPATH = (
    '//nav[@aria-label="Results pagination"]'
    '//a[normalize-space(text())="Next"]'
)


class StopRequested(BaseException):
    """
    Raised when a SIGTERM asks a running scrape to stop cleanly. A
    BaseException rather than an Exception, like KeyboardInterrupt, so no
    retry loop in this file ever mistakes it for a recoverable page error.
    """


class ResultsTableMissing(RuntimeError):
    """Raised when a loaded page has no results table to scrape."""


# Errors a page load or click can recover from on a later attempt:
# Selenium command failures, a page without its results table yet, and
# socket level problems reaching the browser.
RETRYABLE_ERRORS = (WebDriverException, ResultsTableMissing, OSError)


@dataclass(frozen=True)
class RetryPolicy:
    """
    How many times to attempt an action and how long to wait between
    attempts. The wait starts at base_delay seconds and doubles after
    each failed attempt.
    """
    attempts: int
    base_delay: float

    def delay(self, attempt):
        """
        Seconds to wait after the given failed attempt.

        :param attempt: The 1-based number of the attempt that failed.
        :type attempt: int
        :returns: The backoff delay in seconds.
        :rtype: float
        """
        return self.base_delay * (2 ** (attempt - 1))


DEFAULT_RETRY = RetryPolicy(attempts=5, base_delay=15)
MISSING_LINK_RETRY = RetryPolicy(attempts=3, base_delay=5)


def _handle_sigterm(signum, frame):
    """
    SIGTERM handler that turns the signal into a StopRequested exception.

    :param signum: The received signal number (unused).
    :param frame: The interrupted stack frame (unused).
    :raises StopRequested: Always.
    """
    raise StopRequested()


def _with_retries(action, retry, label, on_retry=None):
    """
    Call action until it succeeds, retrying RETRYABLE_ERRORS with an
    exponential backoff and re-raising the last error once every attempt
    is used up.

    :param action: Zero-argument callable to attempt.
    :type action: Callable
    :param retry: How many attempts to make and how long to wait.
    :type retry: RetryPolicy
    :param label: Name of the action for the printed failure message.
    :type label: str
    :param on_retry: Optional zero-argument callable run after each
        backoff wait and before the next attempt.
    :type on_retry: Callable or None
    :returns: Whatever action returns.
    :rtype: object
    """
    attempt = 1
    while True:
        try:
            return action()
        except RETRYABLE_ERRORS as error:
            print(f"{label} failed (attempt {attempt}/{retry.attempts}): {error}")
            if attempt == retry.attempts:
                raise
            delay = retry.delay(attempt)
            print(f"Retrying in {delay}s...")
            time.sleep(delay)
            if on_retry is not None:
                on_retry()
            attempt += 1


def create_profile_dir():
    """
    Create a new temporary Chrome profile directory.

    :returns: The profile directory's path.
    :rtype: str
    """
    return tempfile.mkdtemp()


def _open_chrome(chrome_bin, profile_dir):
    """
    Open Chrome in remote debugging mode using given Chrome binary path
    and a persistent profile directory.

    :param chrome_bin: Path to the Chrome binary to launch.
    :type chrome_bin: str or pathlib.Path
    :param profile_dir: Path to the Chrome profile directory to use.
    :type profile_dir: str
    :returns: The Chrome process.
    :rtype: subprocess.Popen
    """
    # Chrome must outlive this function; the caller stops it later with
    # terminate_process(), so a with block cannot own it here.
    chrome_process = subprocess.Popen(  # pylint: disable=consider-using-with
        [
            chrome_bin,
            f"--remote-debugging-port={CHROME_DEBUG_PORT}",
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
    Try opening the debugging endpoint until open or reaching number of
    retries.

    :param host_port: The debugging endpoint's base URL.
    :type host_port: str
    :param retries: How many times to retry before giving up.
    :type retries: int
    :returns: None.
    :rtype: None
    """
    for _ in range(retries):
        try:
            with urlopen(urljoin(host_port, "json"), timeout=10):
                break
        except URLError:
            time.sleep(1)


def _init_webdriver(host_port):
    """
    Create Chrome webdriver with remote debug options.

    :param host_port: The debugging endpoint's host:port address.
    :type host_port: str
    :returns: The Chrome driver.
    :rtype: selenium.webdriver.Chrome
    """
    options = webdriver.ChromeOptions()
    options.debugger_address = host_port
    options.page_load_strategy = "eager"
    options.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2
    })
    # selenium exposes webdriver.Chrome through a lazy module attribute
    # that static analysis cannot resolve as a class.
    driver = webdriver.Chrome(options=options)  # pylint: disable=not-callable

    return driver


def terminate_process(process, timeout=10):
    """
    Terminate the given Chrome process, force-killing it if it doesn't
    respond to termination within the timeout. Does not remove the
    profile directory, since it may be reused across restarts.

    :param process: The Chrome process to terminate.
    :type process: subprocess.Popen
    :param timeout: Seconds to wait for a clean exit before killing it.
    :type timeout: int
    :returns: None.
    :rtype: None
    """
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def cleanup_profile(profile_dir):
    """
    Remove the given Chrome profile directory. Call only once the
    profile is done being reused (i.e. scraping has fully finished).

    :param profile_dir: Path to the Chrome profile directory to remove.
    :type profile_dir: str
    :returns: None.
    :rtype: None
    """
    shutil.rmtree(profile_dir)


CLOUDFLARE_WAIT_TIMEOUT = 300
CLOUDFLARE_POLL_INTERVAL = 3


def _wait_for_cloudflare(driver, timeout=CLOUDFLARE_WAIT_TIMEOUT,
                         poll_interval=CLOUDFLARE_POLL_INTERVAL):
    """
    Wait for a human to clear Cloudflare's challenge in the visible
    Chrome window, polling the page title instead of blocking on
    keyboard input, so this works whether scrape.py is run directly or
    as a subprocess with no interactive terminal to type into.

    :param driver: The active Selenium Chrome driver.
    :type driver: selenium.webdriver.Chrome
    :param timeout: Seconds to wait before giving up.
    :type timeout: int
    :param poll_interval: Seconds between checks of the page title.
    :type poll_interval: int
    :raises TimeoutError: If the challenge isn't cleared within timeout.
    :returns: None.
    :rtype: None
    """
    print(f"Cloudflare check shown; complete it in the browser window. "
          f"Waiting up to {timeout}s...")
    waited = 0
    while "Just a moment" in driver.title:
        time.sleep(poll_interval)
        waited += poll_interval
        if waited >= timeout:
            raise TimeoutError("Cloudflare check was not completed in time.")
    print("Cloudflare check cleared; continuing.")


AD_TRACKER_URL_PATTERNS = [
    "*doubleclick.net*",
    "*googlesyndication.com*",
    "*adthrive.com*",
    "*pubmatic.com*",
    "*rubiconproject.com*",
    "*casalemedia.com*",
    "*openx.net*",
    "*3lift.com*",
    "*onetag-sys.com*",
    "*presage.io*",
    "*tapad.com*",
    "*creativecdn.com*",
    "*deepintent.com*",
    "*bidr.io*",
    "*smartadserver.com*",
    "*2mdn.net*",
    "*adtrafficquality.google*",
    "*temu.com*",
    "*recaptcha*",
]


def _block_ad_trackers(driver):
    """
    Block known ad and real-time-bidding tracker requests via Chrome
    DevTools Protocol. GradCafe's page loads dozens of ad-auction and
    cookie-sync iframes on every visit; since a fresh, cookie-less Chrome
    profile is used for every scrape (needed for the Cloudflare
    workaround), this full ad auction re-runs from scratch every time,
    spawning enough renderer processes to stall the page for minutes.
    None of this is needed to read the results table.

    :param driver: The active Selenium Chrome driver.
    :type driver: selenium.webdriver.Chrome
    :returns: None.
    :rtype: None
    """
    driver.execute_cdp_cmd("Network.enable", {})
    driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": AD_TRACKER_URL_PATTERNS})


def chrome_helper(url, host_port, chrome_bin, profile_dir, retry=DEFAULT_RETRY):
    """
    Work around Cloudflare verification at url (GradCafe), using a
    persistent Chrome profile so a cleared session survives restarts.
    Retries the initial navigation on transient errors, then only waits
    for manual completion if a Cloudflare challenge is actually shown.
    Cleans up its own spawned process if initialization fails partway
    through.

    :param url: The URL to navigate to.
    :type url: str
    :param host_port: The debugging endpoint's host:port address.
    :type host_port: str
    :param chrome_bin: Path to the Chrome binary to launch.
    :type chrome_bin: str or pathlib.Path
    :param profile_dir: Path to the Chrome profile directory to use.
    :type profile_dir: str
    :param retry: Attempts and backoff for the initial navigation.
    :type retry: RetryPolicy
    :returns: The resulting driver and Chrome process.
    :rtype: tuple(selenium.webdriver.Chrome, subprocess.Popen)
    """
    chrome_process = _open_chrome(chrome_bin, profile_dir)
    try:
        _try_debug_endpoint("http://" + host_port)
        driver = _init_webdriver(host_port)
        _block_ad_trackers(driver)

        print("Loading GradCafe...")
        _with_retries(lambda: driver.get(url), retry, "Initial page load")

        if "Just a moment" in driver.title:
            _wait_for_cloudflare(driver)
    except Exception:
        # any failure leaves a half-started browser behind, so stop it
        # before passing the error up
        terminate_process(chrome_process)
        raise

    return driver, chrome_process


def check_robots_allowed(url, user_agent="*"):
    """
    Check the site's robots.txt to see if scraping is permitted on the
    domain. Fetches it with a browser-like User-Agent, since Cloudflare
    returns a 403 for RobotFileParser's default "Python-urllib/x.y" UA -
    which robotparser's read() treats as "disallow everything" rather
    than as a fetch failure.

    :param url: The URL to check permission for.
    :type url: str
    :param user_agent: The user agent to check permission for.
    :type user_agent: str
    :returns: True if allowed, else False.
    :rtype: bool
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


def _load_results_page(driver, url):
    """
    Navigate to url (or keep the current page when url is None) and
    parse it, requiring the results table to be present.

    :param driver: The active Selenium Chrome driver.
    :type driver: selenium.webdriver.Chrome
    :param url: The URL to navigate to, or None to use the current page.
    :type url: str or None
    :raises ResultsTableMissing: If the page has no results table.
    :returns: The parsed page.
    :rtype: bs4.BeautifulSoup
    """
    if url is not None:
        driver.get(url)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    if soup.find("tbody") is None:
        raise ResultsTableMissing(f"Results table not found (page title: '{driver.title}').")
    return soup


def _get_page(driver, url=None, wait=2, retry=DEFAULT_RETRY):
    """
    Load a page either by navigating to `url` directly, or, if url is
    None, by using whatever page is currently loaded (like after
    clicking "Next"). Retries by re-navigating (or refreshing) on
    transient errors or unexpected page content, with an exponentially
    growing delay between attempts, and a randomized polling delay once
    successful.

    :param driver: The active Selenium Chrome driver.
    :type driver: selenium.webdriver.Chrome
    :param url: The URL to navigate to, or None to use the current page.
    :type url: str or None
    :param wait: Base seconds to politely wait after a successful load.
    :type wait: float
    :param retry: Attempts and backoff for loading the page.
    :type retry: RetryPolicy
    :returns: The parsed page.
    :rtype: bs4.BeautifulSoup
    """
    # re-navigating to url repeats the load itself; with no url, the
    # current page is refreshed instead
    on_retry = driver.refresh if url is None else None
    try:
        soup = _with_retries(
            lambda: _load_results_page(driver, url), retry, "Page load", on_retry
        )
    except HTTPError as e:
        print("HTTP Error:", e.code)
        sys.exit(1)

    time.sleep(random.uniform(wait * 0.7, wait * 1.3))    #  add polite, jittered polling time

    return soup


def _find_next_link(driver, missing_link_retry):
    """
    Find the "Next" pagination link, refreshing and re-checking with a
    growing delay if it is not there yet in case the page is still
    loading.

    :param driver: The active Selenium Chrome driver.
    :type driver: selenium.webdriver.Chrome
    :param missing_link_retry: Checks and backoff for a missing link.
    :type missing_link_retry: RetryPolicy
    :returns: The link element, or None once every check came up empty.
    :rtype: selenium.webdriver.remote.webelement.WebElement or None
    """
    check = 1
    while True:
        try:
            return driver.find_element(By.XPATH, NEXT_LINK_XPATH)
        except NoSuchElementException:
            if check == missing_link_retry.attempts:
                return None
            delay = missing_link_retry.delay(check)
            print(f"'Next' link not found (check {check}/{missing_link_retry.attempts}); "
                  f"refreshing and re-checking in {delay}s before assuming no more pages...")
            driver.refresh()
            time.sleep(delay)
            check += 1


def _click_next_page(driver, retry=DEFAULT_RETRY, missing_link_retry=MISSING_LINK_RETRY):
    """
    Find and click the "Next" pagination link via JavaScript so
    navigation carries a natural Referer header and isn't blocked by
    overlapping page elements that would intercept a native mouse
    click. Retries on transient WebDriver command failures.

    Not finding the "Next" link is retried with a short wait and a page
    refresh in case the page has not loaded yet.

    :param driver: The active Selenium Chrome driver.
    :type driver: selenium.webdriver.Chrome
    :param retry: Attempts and backoff for WebDriver failures.
    :type retry: RetryPolicy
    :param missing_link_retry: Checks and backoff for a missing link.
    :type missing_link_retry: RetryPolicy
    :returns: The resulting page's URL, or None if no next page exists
        after every missing-link check.
    :rtype: str or None
    """
    def _find_and_click():
        next_link = _find_next_link(driver, missing_link_retry)
        if next_link is None:
            return None
        driver.execute_script("arguments[0].click();", next_link)
        return driver.current_url

    return _with_retries(_find_and_click, retry, "Click 'Next'")


def scrape_data(driver, url=None):
    """
    Scrape admissions results from the page at `url`, or from whatever
    page is currently loaded if url is None. Clicks "Next" afterward so
    the following page's request carries a natural Referer.

    :param driver: The active Selenium Chrome driver.
    :type driver: selenium.webdriver.Chrome
    :param url: The URL to navigate to, or None to use the current page.
    :type url: str or None
    :returns: A list of Tag objects, each being a row with application
        details, and the next page's URL (for resumable state), or None
        if no next page exists.
    :rtype: tuple(list[bs4.Tag], str or None)
    """
    soup = _get_page(driver, url)
    table = soup.find("tbody")
    results = table.find_all("tr")
    next_page_url = _click_next_page(driver)

    return results, next_page_url


def format_duration(seconds):
    """
    Convert seconds to hours, minutes, seconds for loop/script
    execution.

    :param seconds: The duration to format.
    :type seconds: float
    :returns: The formatted duration.
    :rtype: str
    """
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)

    if hours == 0 and minutes == 0:
        return f"{secs}s"
    if hours == 0:
        return f"{minutes}m {secs}s"

    return f"{hours}h {minutes}m {round(secs, 0)}s"


def parse_args():
    """
    Parse CLI arguments for scraping GradCafe admissions results
    directly.

    :returns: Parsed arguments.
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(
        description="Scrape GradCafe admissions results into a JSON file."
    )
    parser.add_argument(
        "--num_results", type=int, default=None,
        help="Number of results to collect. If omitted, scrapes from page "
        f"1 until {PULL_SEEN_LIMIT} consecutive already-seen results are "
        "found, or until stopped."
    )
    parser.add_argument(
        "--pull_seen_limit", type=int, default=PULL_SEEN_LIMIT,
        help=f"Consecutive already-seen results that end a --num_results-less "
        f"run (default: {PULL_SEEN_LIMIT}). Ignored with --num_results."
    )
    parser.add_argument(
        "--chrome_binary", type=Path, required=True,
        help="Absolute path to the system Chrome binary."
    )
    parser.add_argument(
        "relative_filepath", type=Path, nargs="?", default=DEFAULT_DATA_FILE,
        help=f"File to save results to (default: `{DEFAULT_DATA_FILE}`)"
    )
    return parser.parse_args()


@dataclass
class _ScrapeProgress:
    """
    Running totals for one scrape. seen_urls starts as every url already
    in the output file, which is the source of truth for what to skip.
    """
    seen_urls: set
    result_count: int = 0
    pages_completed: int = 0
    consecutive_seen: int = 0
    start_time: float = 0.0


@dataclass
class _ChromeSession:
    """
    The Chrome process and driver used for one scrape. The profile
    directory is shared across restarts so a cleared Cloudflare session
    survives them, and is removed only by close().
    """
    chrome_binary: Path
    profile_dir: str
    driver: object = None
    process: object = None

    def start(self):
        """
        Launch Chrome and load GradCafe through chrome_helper().

        :returns: None.
        :rtype: None
        """
        self.driver, self.process = chrome_helper(
            ADMISSIONS_URL, CHROME_DEBUG_HOST_PORT, self.chrome_binary, self.profile_dir
        )

    def restart(self):
        """
        Stop the current Chrome process and start a fresh one on the same
        profile, clearing accumulated browser session state.

        :returns: None.
        :rtype: None
        """
        print("Restarting Chrome to clear accumulated session state...")
        terminate_process(self.process)
        self.start()

    def close(self):
        """
        Stop Chrome if it was started, then remove the profile directory.

        :returns: None.
        :rtype: None
        """
        if self.process is not None:
            terminate_process(self.process)
        cleanup_profile(self.profile_dir)


def _check_can_scrape(args):
    """
    Confirm the output path, the Chrome binary, and robots.txt all allow
    a scrape before any browser is started.

    :param args: Parsed CLI arguments, as returned by parse_args().
    :type args: argparse.Namespace
    :raises FileNotFoundError: If the Chrome binary does not exist.
    :raises PermissionError: If robots.txt disallows the results page.
    :returns: None.
    :rtype: None
    """
    validate_filepath(args.relative_filepath, must_exist=False)

    if not args.chrome_binary.is_file():
        raise FileNotFoundError(f"'{args.chrome_binary}' is not a valid Chrome binary path.")

    if not check_robots_allowed(ADMISSIONS_URL):
        raise PermissionError(f"Scraping {ADMISSIONS_URL} is disallowed by robots.txt")


def _starting_url(args, result_count, state_path):
    """
    Choose the page to start on. Pull mode always starts at page 1;
    resume mode continues from saved pagination state when there is
    any.

    :param args: Parsed CLI arguments, as returned by parse_args().
    :type args: argparse.Namespace
    :param result_count: Unique results already in the output file.
    :type result_count: int
    :param state_path: Path to the sidecar pagination state file.
    :type state_path: pathlib.Path
    :returns: The URL to start from, or None if the requested number of
        results is already met.
    :rtype: str or None
    """
    if args.num_results is None:
        print(f"Pulling new results from page 1 until {args.pull_seen_limit} "
              "consecutive already-seen results are found.")
        return ADMISSIONS_URL

    start_url = ADMISSIONS_URL
    state = load_state(state_path)
    if state:
        start_url = state["next_url"]
        print(f"Resuming pagination from saved state "
              f"({result_count} unique results already in file).")

    if result_count >= args.num_results:
        print(f"Already have {result_count} results "
              f"(>= requested {args.num_results}); nothing to do.")
        return None
    return start_url


def _record_page(progress, parsed_results, filepath):
    """
    Save the page's results that are not already on disk and update the
    running totals, including the streak of consecutive already-seen
    results that ends a pull.

    :param progress: The scrape's running totals, updated in place.
    :type progress: _ScrapeProgress
    :param parsed_results: The page's cleaned results.
    :type parsed_results: list[dict]
    :param filepath: Path to the JSON output file.
    :type filepath: pathlib.Path
    :returns: None.
    :rtype: None
    """
    progress.pages_completed += 1
    new_results = []
    for result in parsed_results:
        if result.get("url") in progress.seen_urls:
            progress.consecutive_seen += 1
        else:
            progress.consecutive_seen = 0
            new_results.append(result)
    progress.seen_urls.update(r["url"] for r in new_results if r.get("url"))
    progress.result_count += len(new_results)

    if new_results:
        save_data(new_results, filepath)

    # printed for every page whether data was written or not, so read
    # pages are always visible even when they add nothing new
    print(
        f"Page {progress.pages_completed}: read {len(parsed_results)}, "
        f"{len(new_results)} new ({progress.result_count} total unique so far)"
    )


def _print_eta(num_results, progress):
    """
    Print the running total with an estimate of the time left to reach
    num_results, based on the average time per page so far.

    :param num_results: The requested total number of results.
    :type num_results: int
    :param progress: The scrape's running totals.
    :type progress: _ScrapeProgress
    :returns: None.
    :rtype: None
    """
    avg_loop_time = (time.time() - progress.start_time) / progress.pages_completed
    remaining_results = num_results - progress.result_count
    remaining_pages = -(-remaining_results // RESULTS_PER_PAGE)  # ceiling division
    eta_seconds = remaining_pages * avg_loop_time
    print(f"Running total: {progress.result_count} (ETA: {format_duration(eta_seconds)})")


def _should_stop(args, progress, next_page_url, state_path):
    """
    Decide whether the scrape is done after a page, printing why, and in
    resume mode save pagination state so a later run can continue here.

    :param args: Parsed CLI arguments, as returned by parse_args().
    :type args: argparse.Namespace
    :param progress: The scrape's running totals.
    :type progress: _ScrapeProgress
    :param next_page_url: The next page's URL, or None on the last page.
    :type next_page_url: str or None
    :param state_path: Path to the sidecar pagination state file.
    :type state_path: pathlib.Path
    :returns: True if the scrape should stop.
    :rtype: bool
    """
    pull_mode = args.num_results is None

    if pull_mode and progress.consecutive_seen >= args.pull_seen_limit:
        print(f"Reached {progress.consecutive_seen} consecutive already-seen results; stopping.")
        return True

    if next_page_url is None:
        print(f"No additional pages available. Stopping at {progress.result_count} results.")
        if not pull_mode:
            state_path.unlink(missing_ok=True)
        return True

    if pull_mode:
        print(f"Running total: {progress.result_count}, "
              f"{progress.consecutive_seen} consecutive already-seen")
        return False

    # save pagination state even after reaching quota so later runs
    # asking for more results resume near here instead of restarting
    # the crawl from page 1
    save_state({"next_url": next_page_url}, state_path)

    if progress.result_count >= args.num_results:
        print(f"Scraping finished with {progress.result_count} results.")
        return True

    _print_eta(args.num_results, progress)
    return False


def _scrape_pages(args, chrome, progress, current_url, state_path):
    """
    Scrape page after page until _should_stop() says the scrape is done,
    restarting Chrome every RESTART_EVERY_N_PAGES pages.

    :param args: Parsed CLI arguments, as returned by parse_args().
    :type args: argparse.Namespace
    :param chrome: The started Chrome session.
    :type chrome: _ChromeSession
    :param progress: The scrape's running totals, updated in place.
    :type progress: _ScrapeProgress
    :param current_url: The first page's URL.
    :type current_url: str
    :param state_path: Path to the sidecar pagination state file.
    :type state_path: pathlib.Path
    :returns: None.
    :rtype: None
    """
    # the first page (fresh or resumed) needs an explicit URL navigation;
    # later pages are reached by clicking "Next" inside scrape_data
    navigate_by_url = True
    while True:
        raw_results, next_page_url = scrape_data(
            chrome.driver, current_url if navigate_by_url else None
        )
        navigate_by_url = False
        _record_page(progress, clean_data(raw_results, current_url), args.relative_filepath)

        if _should_stop(args, progress, next_page_url, state_path):
            return
        current_url = next_page_url

        # periodic restart to clear accumulated browser session state
        if progress.pages_completed % RESTART_EVERY_N_PAGES == 0:
            chrome.restart()
            navigate_by_url = True


def run_scrape(args):
    """
    Scrape GradCafe admissions results into a JSON file.

    With --num_results, resumes from saved pagination state and stops at
    that many total results (or when there are no more pages).

    Without --num_results ("pull mode"), always starts at page 1 and
    ignores saved pagination state, since the goal is to catch newly
    submitted entries rather than continue an earlier crawl. It stops
    once --pull_seen_limit consecutive results already exist in the
    output file (a sign this run has caught up to previously scraped
    data), when there are no more pages, or when this process receives
    SIGTERM (as sent by Flask's Cancel button), whichever comes first.
    Whatever was already saved before stopping stays saved either way.

    :param args: Parsed CLI arguments, as returned by parse_args().
    :type args: argparse.Namespace
    :returns: None.
    :rtype: None
    """
    signal.signal(signal.SIGTERM, _handle_sigterm)
    _check_can_scrape(args)

    seen_urls = load_existing_urls(args.relative_filepath)
    progress = _ScrapeProgress(seen_urls=seen_urls, result_count=len(seen_urls))
    state_path = state_path_for(args.relative_filepath)

    start_url = _starting_url(args, progress.result_count, state_path)
    if start_url is None:
        return

    chrome = _ChromeSession(args.chrome_binary, create_profile_dir())
    try:
        chrome.start()
        progress.start_time = time.time()
        _scrape_pages(args, chrome, progress, start_url, state_path)
        total_elapsed = round(time.time() - progress.start_time, 0)
        print(f"Total scraping time: {format_duration(total_elapsed)}")
    except StopRequested:
        print("Stopping: cancellation requested. Results collected so far are already saved.")
    finally:
        chrome.close()


if __name__ == "__main__":
    # line-buffer stdout so each progress line reaches a piping parent
    # process (Pull Data) as soon as it is printed
    sys.stdout.reconfigure(line_buffering=True)
    run_scrape(parse_args())
