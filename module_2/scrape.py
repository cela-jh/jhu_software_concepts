"""
`scrape.py`
This module contains a function for scraping admissions results from GradCafe. 
The `scrape_data` function is run in `main.py`.
"""
import sys
import time
import tempfile
import shutil
import subprocess
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from selenium import webdriver
from bs4 import BeautifulSoup


def _open_chrome(chrome_bin):
    """
    Opens Chrome in remote debugging mode using given Chrome binary path.
    Returns the Chrome process and profile used.
    """
    # open Chrome in remote debugging mode and silence logs so input prompt can be seen
    profile_dir = tempfile.mkdtemp()
    chrome_process = subprocess.Popen(
        [chrome_bin, "--remote-debugging-port=9222", f"--user-data-dir={profile_dir}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return (chrome_process, profile_dir)


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
    driver = webdriver.Chrome(options=options)

    return driver


def terminate_process(process, profile, timeout=10):
    """
    Performs cleanup with open remote debug Chrome browser and removes
    temporary profile.
    Returns none.
    """
    process.terminate()
    process.wait(timeout=timeout)
    shutil.rmtree(profile)


def chrome_helper(url, host_port, chrome_bin):
    """
    Helper to work around Cloudflare verification at url (GradCafe).
    Returns resulting driver.
    """
    chrome_process, profile_dir = _open_chrome(chrome_bin)
    http_host = "http://" + host_port
    _try_debug_endpoint(http_host)
    driver = _init_webdriver(host_port)
    driver.get(url)
    input("Complete Cloudflare check in browser. Then, press Enter: ")

    return driver, chrome_process, profile_dir


def check_robots_allowed(url, user_agent="*"):
    """
    Checks the site's robots.txt to see if scraping is permitted on the domain.
    Returns True if allowed, else False.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    robots_parser = RobotFileParser()
    robots_parser.set_url(robots_url)
    robots_parser.read()

    return robots_parser.can_fetch(user_agent, url)


def _get_page(driver, url, wait=3):
    """
    Scrapes the admissions results table from the given URL (a GradCafe survey page).
    Returns a BeautifulSoup object.
    """
    # log error if HTTP error is raised
    try:
        driver.get(url)
    except HTTPError as e:
        print("HTTP Error:", e.code)
        sys.exit(1)

    # adapt Selenium driver to existing BeautifulSoup architecture
    soup = BeautifulSoup(driver.page_source, "html.parser")
    time.sleep(wait)    #  add polite polling time

    return soup


def _get_next_page_url(soup):
    """
    Gets the "Next" page button link's url.
    Returns the url, else None:
    """
    nav = soup.find("nav", attrs={"aria-label": "Results pagination"})
    for link in nav.find_all("a"):
        if link.get_text(strip=True) == "Next":
            return link["href"]
    
    return None    


def scrape_data(driver, url):
    """
    Scrapes admissions results from the given URL (a GradCafe result page).
    Returns list of Tag objects, each being a row with application details.
    """
    soup = _get_page(driver, url)
    table = soup.find("tbody")
    results = table.find_all("tr")
    next_page_url = _get_next_page_url(soup)

    return results, next_page_url
    