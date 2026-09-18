"""
`scrape.py`
This module contains a function for scraping admissions results from GradCafe. 
The `scrape_data` function is run in `main.py`.
"""
import sys
import time
import random
import tempfile
import shutil
import subprocess
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from bs4 import BeautifulSoup


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
    