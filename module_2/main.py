"""
`main.py`
Runs the scraping and cleaning process for admissions results from GradCafe.
Uses a helper script to handle Cloudflare's anti-bot protection.
"""
from scrape import scrape_data, chrome_helper


def main():
    # Chrome bin: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
    admissions_url = "https://www.thegradcafe.com/survey"
    print(chrome_helper(admissions_url, "127.0.0.1:9222"))
    # admissions_results = scrape_data(admissions_url)
    # print(admissions_results)


if __name__ == "__main__":
    main()