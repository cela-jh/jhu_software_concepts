"""
`test_db_helpers.py`
Covers db_helpers.py behavior not already exercised elsewhere: a real
(but deterministic, local-only) failed connection, and the standalone
pretty_print_query() formatter.
"""
import pytest

from database.db_helpers import connect_db, pretty_print_query


@pytest.mark.db
def test_connect_db_returns_none_on_failure():
    """A connection attempt against a database that doesn't exist should
    fail cleanly and return None rather than raising - this hits a real
    Postgres error locally, no network dependency."""
    bad_url = "postgresql://localhost:5432/definitely_not_a_real_database"

    conn = connect_db(bad_url)

    assert conn is None


@pytest.mark.db
def test_pretty_print_query_uppercases_and_splits_clauses():
    """Each SQL clause keyword should start its own line, in uppercase,
    regardless of the input's original casing."""
    query = "select * from applicants where status ilike 'accepted%' and term = 'Fall 2026'"

    formatted = pretty_print_query(query)
    lines = formatted.splitlines()

    assert lines[0].startswith("SELECT")
    assert any(line.startswith("FROM") for line in lines)
    assert any(line.startswith("WHERE") for line in lines)
    assert any(line.startswith("AND") for line in lines)
