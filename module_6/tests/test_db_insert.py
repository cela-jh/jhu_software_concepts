"""
`test_db_insert.py`
Verifies real PostgreSQL behavior against cam_db_test (never cam_db):
that a query helper returns a single applicant row as a dict keyed by
every required field. Data-ingestion integration tests are in
test_integration_end_to_end.py; pull_control stub tests are in
test_pull_control.py.
"""
import pytest

from database.db_helpers import get_applicant


@pytest.mark.db
def test_get_applicant_returns_dict_with_expected_keys(db_connection):
    """A simple query function should return a single applicant's data
    as a dict keyed by every required M3 field."""
    with db_connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO applicants
                (p_id, program, date_added, url, status, term,
                 us_or_international, degree)
            VALUES
                (3000001, 'Computer Science, Test University', '2026-09-12',
                 'https://www.thegradcafe.com/result/3000001', 'Accepted',
                 'Fall 2026', 'American', 'Masters')
            """
        )
    db_connection.commit()

    row = get_applicant(db_connection, 3000001)

    assert row is not None
    expected_keys = {
        "p_id", "program", "comments", "date_added", "url", "status", "term",
        "us_or_international", "gpa", "gre", "gre_v", "gre_aw", "degree",
        "llm_generated_program", "llm_generated_university",
    }
    assert expected_keys.issubset(row.keys())
    assert row["p_id"] == 3000001
    assert row["program"] == "Computer Science, Test University"
