"""
`main.py`
Runs the scraping and cleaning process for admissions results from GradCafe.
Uses a helper script to handle Cloudflare's anti-bot protection.
"""
from scrape import scrape_data, chrome_helper, terminate_process


def main():
    # Chrome bin: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
    admissions_url = "https://www.thegradcafe.com/survey"
    driver, chrome_process, profile_dir = chrome_helper(admissions_url, "127.0.0.1:9222")
    try:
        admissions_results = scrape_data(driver, admissions_url)
        print(admissions_results)
    finally:
        terminate_process(chrome_process, profile_dir)

    return 0


if __name__ == "__main__":
    main()