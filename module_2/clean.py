"""
`clean.py`
This module contains a function for cleaning and parsing admissions results 
from GradCafe. The `parse_results` function is run in `main.py`.
"""
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup


TAGS_REGEX_DICT = {
    "status": r"(Accepted|Rejected|Wait listed|Interview)",
    "decision date": r"on (.+)$",
    "degree": r"(PhD|Other)",
    "GRE score": r"^GRE (\d+)$",
    "GRE V score": r"^GRE V (\d+)$",
    "GPA": r"^GPA ([\d.]+)$",
    "GRE AW": r"^GRE AW ([\d.]+)$"
}


def group_rows(results):
    """
    Groups main data values with accompanying tags and comments. Rows with tags 
    or comments have class="tw-border-none".
    Returns list of grouped rows.
    """
    groups = []
    i = 0
    # traverse all rows on page
    while i < len(results):
        if results[i].get("class") is not None:     # skips empty rows
            i += 1
            continue
        main_row = results[i]       # main data that anchors tags and comments
        extra_rows = []
        i += 1
        # checks if row is for tags or comments
        while i < len(results) and "tw-border-none" in (results[i].get("class") or []):
            extra_rows.append(results[i])
            i += 1
        groups.append((main_row, extra_rows))

    return groups


def get_tag(tag, text):
    """
    Uses regex to find a tag.
    Returns tag if it exists, else None.
    """
    tag_regex = TAGS_REGEX_DICT[tag]
    match = re.search(tag_regex, text)
    if tag == "decision date":      # only return content in parentheses
        return match.group(1) if match else None

    return match.group(0) if match else None


def parse_main_row(main_row, url):
    """
    Parses the main row to get school, program, date added, status, 
    status date, and url.
    Returns a dictionary with these values.
    """
    cells = main_row.find_all("td")

    # get school from first cell
    school = cells[0].get_text(strip=True)

    # get program and degree from second cell
    program_spans = cells[1].find_all("span")
    program = program_spans[0].get_text(strip=True)
    degree_text = program_spans[1].get_text(strip=True)
    is_phd_other = True if get_tag("degree", degree_text) else False
    degree = get_tag("degree", degree_text) if is_phd_other else "Masters"

    # get date added from third cell
    date_added = "Added on " + cells[2].get_text(strip=True)

    # get status using regex on text from fourth cell
    status_text = cells[3].get_text(strip=True)
    status = get_tag("status", status_text)
    decision_date = get_tag("decision date", status_text)

    # get url from fifth cell
    result_url = urljoin(url, cells[4].find("a")["href"])  

    main_row_parsed = {
        "program": program + ", " + school,
        "degree": degree,
        "date added": date_added,
        "status": status,
        "url": result_url
    }
    # adds acceptance/rejection date
    if status == "Accepted":
        main_row_parsed["acceptance date"] = decision_date
    elif status == "Rejected":
        main_row_parsed["rejection date"] = decision_date

    return main_row_parsed


def parse_tags_row(tags_row):
    """
    Used for parsing the subsequent tags row's cells. Not for use with main row.
    Returns a dictionary of any tags found.
    """
    wrapper = tags_row.find("div")
    all_cells = wrapper.find_all("div", recursive=False)
    # drop redundant status object if it exists
    tags_cells = [cell for cell in all_cells if not get_tag("status", cell.get_text(strip=True))]

    # get tags that always appear
    tags_parsed = {
        "term": tags_cells[0].get_text(strip=True),
        "US/International": tags_cells[1].get_text(strip=True)
    }

    # if there is more than term and nationality
    if len(tags_cells) > 2:
        for tag in tags_cells[2:]:
            text = tag.get_text(strip=True)
            if get_tag("GRE AW", text):
                tags_parsed["GRE AW"] = get_tag("GRE AW", text)
            elif get_tag("GRE V score", text):
                tags_parsed["GRE V score"] = get_tag("GRE V score", text)
            elif get_tag("GRE score", text):
                tags_parsed["GRE score"] = get_tag("GRE score", text)
            elif get_tag("GPA", text):
                tags_parsed["GPA"] = get_tag("GPA", text)

    return tags_parsed


def parse_sub_rows(extra_rows):
    """
    Parses the tags and comments rows grouped with a main row.
    Returns a combined dictionary of tags and comment data.
    """
    sub_rows_parsed = dict()
    tags_row_parsed = parse_tags_row(extra_rows[0])
    sub_rows_parsed.update(tags_row_parsed)

    # get comments if exists
    if len(extra_rows) == 2:
        comment_text = extra_rows[1].get_text(strip=True)
        sub_rows_parsed["comments"] = comment_text

    return sub_rows_parsed


def order_keys(parsed_results):
    """
    Orders keys for preferred output.
    Returns dictionary with custom ordered keys.
    """
    keys = parsed_results.keys()
    order = [
        "program", "date added", "url", "status", "term",
        "US/International", "degree"
        ]
    if "comments" in keys:
        order = [
            "program", "comments", "date added", "url", "status", "term",
            "US/International", "degree"
                ]
    order.extend(item for item in keys if item not in order)
    parsed_results_ordered = {key: parsed_results[key] for key in order}

    return parsed_results_ordered


def parse_groups(grouped_results, url):
    """
    Parses the list of grouped admissions.
    Returns a list of readable dictionaries.
    """
    parsed_results = []
    for group in grouped_results:
        # parse main row
        main_row = group[0]
        main_row_parsed = parse_main_row(main_row, url)
        # parse subsequent rows (not implemented)
        sub_rows = group[1]
        sub_rows_parsed = parse_sub_rows(sub_rows)
        # concatenate dictionaries into a single result and append
        parsed_result = main_row_parsed
        parsed_result.update(sub_rows_parsed)
        # order keys and append to parsed results
        parsed_result_ordered = order_keys(parsed_result)
        parsed_results.append(parsed_result_ordered)

    return parsed_results


def clean_data(results: list, url):
    """
    Cleans raw html the list of admissions results into readable dictionaries.
    Returns a list of dictionaries, each containing relevant information about 
    a single result.
    """
    groups = group_rows(results)
    parsed_results = parse_groups(groups, url)

    return parsed_results
