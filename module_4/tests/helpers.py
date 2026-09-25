"""
`helpers.py`
Shared, non-fixture test doubles and data builders used by more than one
test file: a fake subprocess.Popen scrape.py process, helpers for
writing/building valid fake scraped rows, and a percentage-formatting
assertion used anywhere rendered analysis output gets checked.
"""
import json
import re

PERCENTAGE_PATTERN = re.compile(r"\d+(?:\.\d+)?%")


def assert_all_two_decimal_percentages(text):
    """Every percentage-looking token in text must be digits, a literal
    decimal point with exactly two digits, then '%' - never "50%" or
    "50.0%"."""
    matches = PERCENTAGE_PATTERN.findall(text)
    assert matches, f"expected at least one percentage in {text!r}"
    for token in matches:
        assert re.fullmatch(r"\d+\.\d{2}%", token), f"badly formatted percentage: {token!r}"


class FakeProcess:
    """Stands in for the subprocess.Popen scrape.py process. The faked
    scraper has already written its results to DATA_FILE before this
    "process" is created, so stdout just needs to end cleanly."""

    def __init__(self, lines=()):
        self.stdout = iter(lines)

    def wait(self):
        return 0


def write_fake_scraped_data(path, rows):
    """Writes rows (a list of raw scraped-result dicts) to path as JSON,
    the same shape scrape.py's save_data() would produce."""
    path.write_text(json.dumps(rows, indent=2))


def fake_applicant_row(result_id, **overrides):
    """A minimally valid scraped result; load_data.py's
    _extract_result_id() pulls result_id back out of the url as the
    row's p_id."""
    row = {
        "program": "Computer Science, Test University",
        "date added": "Added on Sep 12, 2026",
        "url": f"https://www.thegradcafe.com/result/{result_id}",
        "status": "Accepted",
        "term": "Fall 2026",
        "US/International": "American",
        "degree": "Masters",
    }
    row.update(overrides)
    return row
