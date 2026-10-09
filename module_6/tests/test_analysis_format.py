"""
`test_analysis_format.py`
Verifies that the analysis page labels every result with "Answer:" and
that every percentage value it displays is formatted with exactly two
decimal places, both in orm_queries.py's own answer functions and in
the rendered page.
"""
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from database.orm_queries import (
    _format_percentage, _or_na, orm_a1, orm_a2, orm_q2, orm_q3, orm_q5,
)
from helpers import assert_all_two_decimal_percentages as _assert_all_two_decimal_percentages


class _FakeResult:
    """Stands in for a SQLAlchemy Result: scalar_one()/all() return
    whatever this particular fake query result was scripted with."""

    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows

    def scalar_one(self):
        return self._scalar

    def all(self):
        return self._rows


class _FakeSession:
    """A session stand-in whose execute() hands back a scripted sequence
    of results in call order, ignoring the actual query passed in - lets
    orm_queries functions run for real against controlled fake data."""

    def __init__(self, results):
        self._results = iter(results)

    def execute(self, _query):
        return next(self._results)

    def close(self):
        pass


@pytest.mark.analysis
@pytest.mark.parametrize("raw_value", [50, 90, 45, 100, 0, Decimal("33.333333")])
def test_format_percentage_always_two_decimals(raw_value):
    """_format_percentage must never drop trailing zeros, regardless of
    whether the value is a whole number, a Decimal from SQL-side
    rounding, or a repeating decimal."""
    formatted = _format_percentage(raw_value)
    assert re.fullmatch(r"\d+\.\d{2}%", formatted)


@pytest.mark.analysis
def test_orm_q2_percentage_uses_two_decimals():
    """orm_q2 formats a single SQL-rounded percentage; a whole-number
    result must still render with two decimals, not "50%"."""
    session = _FakeSession([_FakeResult(scalar=Decimal("50"))])

    result = orm_q2(session)

    assert result == "International percentage: 50.00%"
    _assert_all_two_decimal_percentages(result)


@pytest.mark.analysis
def test_orm_q5_percentage_uses_two_decimals():
    """orm_q5's percentage must round to two decimals, not truncate or
    drop trailing digits."""
    session = _FakeSession([_FakeResult(scalar=Decimal("33.333333"))])

    result = orm_q5(session)

    assert result == "Percentage accepted: 33.33%"
    _assert_all_two_decimal_percentages(result)


@pytest.mark.analysis
@pytest.mark.parametrize("value,expected", [(None, "N/A"), (3.5, 3.5), (0, 0)])
def test_or_na_reports_na_only_for_none(value, expected):
    """_or_na must distinguish "no data" (None) from a real value of
    zero or otherwise falsy - only None should become "N/A"."""
    assert _or_na(value) == expected


@pytest.mark.analysis
def test_format_percentage_returns_na_for_no_data():
    """A percentage computed over zero matching rows arrives as SQL
    NULL / Python None; formatting it must report "N/A", not crash on
    float(None)."""
    assert _format_percentage(None) == "N/A"


@pytest.mark.analysis
def test_orm_q5_reports_na_when_no_matching_rows():
    """No Fall 2025 entries at all means SUM()/COUNT() over zero rows,
    which SQL returns as NULL - orm_q5 must report "N/A" instead of
    raising when it tries to format that percentage."""
    session = _FakeSession([_FakeResult(scalar=None)])

    result = orm_q5(session)

    assert result == "Percentage accepted: N/A"


@pytest.mark.analysis
def test_orm_q3_reports_na_when_no_matching_rows():
    """AVG() over zero matching rows is NULL for each of GPA/GRE/GRE
    V/GRE AW independently; orm_q3 must report "N/A" for each rather
    than the literal text "None"."""
    session = _FakeSession([
        _FakeResult(scalar=None), _FakeResult(scalar=None),
        _FakeResult(scalar=None), _FakeResult(scalar=None),
    ])

    result = orm_q3(session)

    assert result == ("Average GPA: N/A, Average GRE: N/A, "
                       "Average GRE V: N/A, Average GRE AW: N/A")


@pytest.mark.analysis
def test_orm_a2_reports_na_without_crashing_when_no_usc_data():
    """With zero USC applicants on either side of the accepted/not
    comparison, both averages are None; orm_a2 must report "N/A" for
    each and for the difference, not raise on None - None."""
    session = _FakeSession([_FakeResult(scalar=None), _FakeResult(scalar=None)])

    result = orm_a2(session)

    assert result == ("USC average GPA accepted: N/A, "
                       "USC average GPA not accepted: N/A, "
                       "Difference: N/A")


@pytest.mark.analysis
def test_orm_a1_reports_message_when_no_accepted_applicants():
    """With zero accepted applicants at all, there are no terms to list
    a percentage for; orm_a1 must say so rather than return an empty
    string."""
    session = _FakeSession([_FakeResult(scalar=0), _FakeResult(rows=[])])

    result = orm_a1(session)

    assert result == "No accepted applicants found"


@pytest.mark.analysis
def test_orm_a1_percentages_use_two_decimals():
    """orm_a1 formats one percentage per term found in the data; every
    one of them must carry exactly two decimals, not just whichever one
    happens to need rounding."""
    # rows arrive already in chronological order, as the ORDER BY in
    # orm_a1's own query returns them from PostgreSQL
    session = _FakeSession([
        _FakeResult(scalar=10),
        _FakeResult(rows=[
            SimpleNamespace(term="Spring 2026", cnt=7),
            SimpleNamespace(term="Fall 2026", cnt=3),
        ]),
    ])

    result = orm_a1(session)

    assert result == "Spring 2026 acceptance: 70.00%, Fall 2026 acceptance: 30.00%"
    _assert_all_two_decimal_percentages(result)


@pytest.mark.analysis
@pytest.mark.web
def test_analysis_page_labels_every_result_answer(client, monkeypatch):
    """Every result on the analysis page must carry its own "Answer:"
    label, not just the first one."""
    fake_questions = [
        ("Question one?", None, None),
        ("Question two?", None, None),
        ("Question three?", None, None),
    ]
    fake_answers = [
        lambda session: "Applicant count: 12",
        lambda session: "International percentage: 50.00%",
        lambda session: "Percentage accepted: 33.33%",
    ]
    monkeypatch.setattr("app.routes.get_session", lambda database_url: _FakeSession([]))
    monkeypatch.setattr("app.routes.QUESTION_QUERY", fake_questions)
    monkeypatch.setattr("app.routes.ALL_ORM_ANSWERS", fake_answers)
    monkeypatch.setattr("app.routes.fetch_accepted_since", lambda url, school: ["A3 row"])

    response = client.get("/analysis")

    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    answer_elements = soup.select(".answer")
    # one per Part 2 question, plus A3's own answer box
    assert len(answer_elements) == len(fake_questions) + 1
    for element in answer_elements:
        assert element.get_text(strip=True).startswith("Answer:")


@pytest.mark.analysis
@pytest.mark.web
def test_analysis_page_percentages_use_two_decimals(client, monkeypatch):
    """Any percentage rendered on the analysis page must have exactly
    two decimal places, end to end through the real template."""
    fake_questions = [("Percentage question?", None, None)]
    fake_answers = [lambda session: "International percentage: 50.00%"]
    monkeypatch.setattr("app.routes.get_session", lambda database_url: _FakeSession([]))
    monkeypatch.setattr("app.routes.QUESTION_QUERY", fake_questions)
    monkeypatch.setattr("app.routes.ALL_ORM_ANSWERS", fake_answers)
    monkeypatch.setattr("app.routes.fetch_accepted_since", lambda url, school: [])

    response = client.get("/analysis")

    _assert_all_two_decimal_percentages(response.get_data(as_text=True))
