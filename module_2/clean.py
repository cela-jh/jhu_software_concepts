"""
`clean.py`
This module contains a function for cleaning and parsing admissions results 
from GradCafe. The `parse_results` function is run in `main.py`.
"""
from urllib.request import urlopen
from bs4 import BeautifulSoup


def parse_results(results):
    """
    Parses the list of admissions results into clean, readable dictionaries.
    Returns a list of dictionaries, each containing relevant information 
    about a single result.
    """
    parsed_results = []
    for result in results:
        # Example parsing logic - replace with actual implementation
        parsed_result = {
            "name": result.find("td", class_="name").text,
            "status": result.find("td", class_="status").text,
            "date": result.find("td", class_="date").text
        }
        parsed_results.append(parsed_result)
    return parsed_results
