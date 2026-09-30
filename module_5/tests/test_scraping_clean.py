"""
`test_scraping_clean.py`
Covers scraping/clean.py's HTML parsing against locally-constructed
BeautifulSoup fixtures (no network, no live GradCafe page) shaped like
the real results table: a main row per result, followed by a tags row
and an optional comments row, both marked class="tw-border-none".
"""
import pytest
from bs4 import BeautifulSoup

from scraping.clean import _get_tag, _order_keys, clean_data

BASE_URL = "https://www.thegradcafe.com/survey/"


def _rows_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.find_all("tr")


@pytest.mark.web
@pytest.mark.parametrize("tag,text,expected", [
    ("status", "Accepted on 10 Sep", "Accepted"),
    ("status", "no status here", None),
    ("decision date", "Accepted on 10 Sep", "10 Sep"),
    ("decision date", "no date here", None),
    ("degree", "PhD", "PhD"),
    ("degree", "MS", None),
    ("GRE score", "GRE 165", "GRE 165"),
    ("GRE score", "GRE V 160", None),
    ("GRE V score", "GRE V 160", "GRE V 160"),
    ("GPA", "GPA 3.75", "GPA 3.75"),
    ("GRE AW", "GRE AW 4.5", "GRE AW 4.5"),
])
def test_get_tag(tag, text, expected):
    assert _get_tag(tag, text) == expected


_FULL_ROW = {
    "program": "CS, Test U", "date added": "Added on Sep 12, 2026",
    "url": "https://example.com/result/1", "status": "Accepted",
    "term": "Fall 2026", "US/International": "American", "degree": "PhD",
}


@pytest.mark.web
def test_order_keys_without_comments():
    ordered = _order_keys({**_FULL_ROW, "extra": "x"})
    assert list(ordered.keys())[0] == "program"
    assert "extra" in ordered
    assert "comments" not in ordered


@pytest.mark.web
def test_order_keys_with_comments():
    ordered = _order_keys({**_FULL_ROW, "comments": "great school"})
    keys = list(ordered.keys())
    assert keys.index("comments") == 1


@pytest.mark.web
def test_clean_data_parses_full_page():
    html = f"""
    <table>
      <tr class="header-row"><td>stray header row, no main row before it</td></tr>

      <tr>
        <td>Test University</td>
        <td><span>Computer Science</span><span>PhD</span></td>
        <td>Sep 12, 2026</td>
        <td>Accepted on Sep 10</td>
        <td><a href="/result/1000001">See More</a></td>
      </tr>
      <tr class="tw-border-none">
        <td><div>
          <div>Accepted</div>
          <div>Fall 2026</div>
          <div>American</div>
          <div>GPA 3.75</div>
          <div>GRE AW 4.5</div>
        </div></td>
      </tr>
      <tr class="tw-border-none"><td>Loved the program.</td></tr>

      <tr>
        <td>Other University</td>
        <td><span>Biology</span><span>MS</span></td>
        <td>Sep 13, 2026</td>
        <td>Rejected on Sep 11</td>
        <td><a href="/result/1000002">See More</a></td>
      </tr>
      <tr class="tw-border-none">
        <td><div>
          <div>Spring 2026</div>
          <div>International</div>
        </div></td>
      </tr>

      <tr>
        <td>Third University</td>
        <td><span>Physics</span><span>Other</span></td>
        <td>Sep 14, 2026</td>
        <td>Interview</td>
        <td><a href="/result/1000003">See More</a></td>
      </tr>
      <tr class="tw-border-none">
        <td><div>
          <div>Fall 2025</div>
          <div>American</div>
          <div>GRE 165</div>
          <div>GRE V 160</div>
        </div></td>
      </tr>
    </table>
    """
    rows = _rows_from_html(html)

    results = clean_data(rows, BASE_URL)

    assert len(results) == 3

    first = results[0]
    assert first["program"] == "Computer Science, Test University"
    assert first["degree"] == "PhD"
    assert first["date added"] == "Added on Sep 12, 2026"
    assert first["status"] == "Accepted on Sep 10"
    assert first["url"] == "https://www.thegradcafe.com/result/1000001"
    assert first["term"] == "Fall 2026"
    assert first["US/International"] == "American"
    assert first["GPA"] == "GPA 3.75"
    assert first["GRE AW"] == "GRE AW 4.5"
    assert first["comments"] == "Loved the program."
    # comments should sort right after program per _order_keys
    assert list(first.keys())[1] == "comments"

    second = results[1]
    assert second["degree"] == "Masters"
    assert second["status"] == "Rejected on Sep 11"
    assert second["term"] == "Spring 2026"
    assert second["US/International"] == "International"
    assert "comments" not in second

    third = results[2]
    assert third["degree"] == "Other"
    assert third["status"] == "Interview"
    assert third["GRE score"] == "GRE 165"
    assert third["GRE V score"] == "GRE V 160"
