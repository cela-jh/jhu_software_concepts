"""
`test_worker_query_data.py`
Unit tests for the worker's etl/query_data module. Format helpers and
run_analytics are covered here; all DB interactions use a mock connection.
"""
import pytest
from unittest.mock import MagicMock

from etl.query_data import (
    QUESTION_QUERY,
    _format_a1,
    _format_a2,
    _format_q1,
    _format_q2,
    _format_q3,
    _format_q4,
    _format_q5,
    _format_q6,
    _format_q7,
    _format_q8,
    _format_q9,
    escape_like,
    run_analytics,
)


# ---- escape_like ----

@pytest.mark.integration
def test_escape_like_escapes_percent_and_underscore():
    """escape_like must prefix '%' and '_' with the escape character."""
    result = escape_like("50% complete_now")
    assert "\\%" in result
    assert "\\_" in result


@pytest.mark.integration
def test_escape_like_escapes_the_escape_character_itself():
    """escape_like must escape the backslash before escaping other chars."""
    result = escape_like("path\\to\\file")
    assert result.count("\\\\") >= 2


@pytest.mark.integration
def test_escape_like_returns_plain_string_unchanged():
    """escape_like must not alter text that has no special characters."""
    assert escape_like("simple") == "simple"


# ---- individual format helpers ----

@pytest.mark.integration
def test_format_q1_renders_count():
    assert _format_q1([{"cnt_fall26": 7}]) == "Applicant count: 7"


@pytest.mark.integration
def test_format_q2_renders_percentage():
    assert _format_q2([{"pct_intl": "42.00%"}]) == "International percentage: 42.00%"


@pytest.mark.integration
def test_format_q3_renders_averages():
    row = {"avg_gpa": "3.5", "avg_gre": "320", "avg_gre_v": "160", "avg_gre_aw": "4.0"}
    result = _format_q3([row])
    assert "3.5" in result
    assert "320" in result


@pytest.mark.integration
def test_format_q4_renders_us_gpa():
    assert "3.6" in _format_q4([{"avg_gpa_us_fall26": "3.6"}])


@pytest.mark.integration
def test_format_q5_renders_acceptance_pct():
    assert "30.00%" in _format_q5([{"pct_accepted_fall25": "30.00%"}])


@pytest.mark.integration
def test_format_q6_renders_accepted_gpa():
    assert "3.7" in _format_q6([{"avg_gpa_accepted_fall26": "3.7"}])


@pytest.mark.integration
def test_format_q7_renders_jhu_ms_cs_count():
    assert "3" in _format_q7([{"cnt_jhu_ms_cs": 3}])


@pytest.mark.integration
def test_format_q8_renders_cs_phd_count():
    assert "10" in _format_q8([{"cnt_fall26_cs_phd": 10}])


@pytest.mark.integration
def test_format_q9_renders_original_llm_and_diff():
    row = {"cnt_fall26_cs_phd_original": 8, "cnt_fall26_cs_phd_llm": 10, "llm_less_original": 2}
    result = _format_q9([row])
    assert "8" in result
    assert "10" in result
    assert "+2" in result


@pytest.mark.integration
def test_format_a1_joins_term_acceptance_rows():
    rows = [{"term": "Fall 2026", "pct_of_acceptances": "50%"}]
    result = _format_a1(rows)
    assert "Fall 2026 acceptance: 50%" in result


@pytest.mark.integration
def test_format_a2_renders_usc_gpa_comparison():
    row = {"avg_gpa_accepted_usc": "3.8", "avg_gpa_not_accepted_usc": "3.5", "gpa_diff": 0.3}
    result = _format_a2([row])
    assert "3.8" in result
    assert "3.5" in result


# ---- run_analytics ----

def _mock_conn_with_rows(rows_per_query):
    """
    Build a mock psycopg connection whose cursor returns rows_per_query in
    sequence, one list of rows per execute() call.
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = list(rows_per_query)
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cm.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = mock_cm
    return conn


@pytest.mark.integration
def test_run_analytics_returns_one_string_per_question():
    """run_analytics must return exactly as many answers as QUESTION_QUERY has rows."""
    mock_rows = [
        [{"cnt_fall26": 1}],
        [{"pct_intl": "0.00%"}],
        [{"avg_gpa": "0", "avg_gre": "0", "avg_gre_v": "0", "avg_gre_aw": "0"}],
        [{"avg_gpa_us_fall26": "0"}],
        [{"pct_accepted_fall25": "0.00%"}],
        [{"avg_gpa_accepted_fall26": "0"}],
        [{"cnt_jhu_ms_cs": 0}],
        [{"cnt_fall26_cs_phd": 0}],
        [{"cnt_fall26_cs_phd_original": 0, "cnt_fall26_cs_phd_llm": 0, "llm_less_original": 0}],
        [{"term": "Fall 2026", "pct_of_acceptances": "100%"}],
        [{"avg_gpa_accepted_usc": "0", "avg_gpa_not_accepted_usc": "0", "gpa_diff": 0}],
    ]
    conn = _mock_conn_with_rows(mock_rows)
    results = run_analytics(conn)
    assert len(results) == len(QUESTION_QUERY)
    assert all(isinstance(r, str) for r in results)
