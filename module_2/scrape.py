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
from urllib.parse import urljoin
from pathlib import Path
from selenium import webdriver
from bs4 import BeautifulSoup


def open_chrome():
    """
    Opens Chrome in remote debugging mode using input path to Chrome binary.
    Returns the Chrome process and profile used.
    """
    # validate Chrome binary path
    chrome_bin = None
    while chrome_bin is None:
        chrome_bin = input("Use Chrome to scrape. Paste the absolute path to your Chrome binary: ")
        candidate = Path(chrome_bin)
        if candidate.exists():
            chrome_path = candidate
        else:
            print(f"'{chrome_bin}' is not a valid path. Try again.")
    # open Chrome in remote debugging mode and silence logs so input prompt can be seen
    profile_dir = tempfile.mkdtemp()
    chrome_process = subprocess.Popen(
        [chrome_path, "--remote-debugging-port=9222", f"--user-data-dir={profile_dir}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return (chrome_process, profile_dir)


def try_debug_endpoint(host_port, retries=10):
    """
    Tries opening the debugging endpoint until open or reaching number of retries.
    """
    for _ in range(retries):
        try:
            urlopen(urljoin(host_port, "json"), timeout=10)
            break
        except URLError:
            time.sleep(1)


def init_webdriver(host_port):
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


def chrome_helper(url, host_port):
    """
    Helper to work around Cloudflare verification at url (GradCafe).
    Returns resulting driver.
    """
    chrome_process, profile_dir = open_chrome()
    http_host = "http://" + host_port
    try_debug_endpoint(http_host)
    driver = init_webdriver(host_port)
    driver.get(url)
    input("Complete Cloudflare check in browser. Then, press Enter: ")

    return driver, chrome_process, profile_dir


def get_page(driver, url, wait=3):
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


def scrape_data(driver, url):
    """
    Scrapes admissions results from the given URL (a GradCafe result page).
    Returns raw HTML of the application details.
    """
    soup = get_page(driver, url)
    table = soup.find("tbody")
    results = table.find_all("tr")

    return results
    