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

from database.orm_queries import _format_percentage, orm_a1, orm_q2, orm_q5

PERCENTAGE_PATTERN = re.compile(r"\d+(?:\.\d+)?%")


def _assert_all_two_decimal_percentages(text):
    """Every percentage-looking token in text must be digits, a
    decimal point with exactly two digits, then '%'."""
    matches = PERCENTAGE_PATTERN.findall(text)
    assert matches, f"expected at least one percentage in {text!r}"
    for token in matches:
        assert re.fullmatch(r"\d+\.\d{2}%", token), f"badly formatted percentage: {token!r}"


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
def test_orm_a1_percentages_use_two_decimals():
    """orm_a1 formats one percentage per term found in the data; every
    one of them must carry exactly two decimals, not just whichever one
    happens to need rounding."""
    session = _FakeSession([
        _FakeResult(scalar=10),
        _FakeResult(rows=[
            SimpleNamespace(term="Fall 2026", cnt=3),
            SimpleNamespace(term="Spring 2026", cnt=7),
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
    monkeypatch.setenv("PGUSER", "test_user")
    monkeypatch.setenv("PGPASSWORD", "test_password")
    monkeypatch.setattr("app.routes.get_session", lambda credentials: _FakeSession([]))
    monkeypatch.setattr("app.routes.QUESTION_QUERY", fake_questions)
    monkeypatch.setattr("app.routes.ALL_ORM_ANSWERS", fake_answers)

    response = client.get("/")

    page = response.get_data(as_text=True)
    assert page.count("Answer:") == len(fake_questions)


@pytest.mark.analysis
@pytest.mark.web
def test_analysis_page_percentages_use_two_decimals(client, monkeypatch):
    """Any percentage rendered on the analysis page must have exactly
    two decimal places, end to end through the real template."""
    fake_questions = [("Percentage question?", None, None)]
    fake_answers = [lambda session: "International percentage: 50.00%"]
    monkeypatch.setenv("PGUSER", "test_user")
    monkeypatch.setenv("PGPASSWORD", "test_password")
    monkeypatch.setattr("app.routes.get_session", lambda credentials: _FakeSession([]))
    monkeypatch.setattr("app.routes.QUESTION_QUERY", fake_questions)
    monkeypatch.setattr("app.routes.ALL_ORM_ANSWERS", fake_answers)

    response = client.get("/")

    _assert_all_two_decimal_percentages(response.get_data(as_text=True))
