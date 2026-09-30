"""
`test_cli_helpers.py`
Covers the CLI-support functions in orm_queries.py and query_data.py that
only run when each module's script is executed directly: their own
_database_url() readers, and the functions that print every answer
(run_orm_queries(), analyze()) against the real cam_db_test database.
"""
import pytest

import database.orm_queries as orm_queries
import database.query_data as query_data


@pytest.mark.db
def test_orm_queries_database_url_reads_env_var(monkeypatch, database_url):
    monkeypatch.setenv("DATABASE_URL", database_url)

    assert orm_queries._database_url() == database_url


@pytest.mark.db
def test_orm_queries_database_url_raises_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(EnvironmentError):
        orm_queries._database_url()


@pytest.mark.db
def test_run_orm_queries_prints_every_answer(db_connection, database_url, capsys):
    """Against an empty (but real) applicants table, every ORM_QUESTIONS
    function must run and print without raising."""
    orm_queries.run_orm_queries(database_url)

    printed = capsys.readouterr().out
    assert "Applicant count:" in printed
    assert "No accepted applicants found" in printed


@pytest.mark.db
def test_query_data_database_url_reads_env_var(monkeypatch, database_url):
    monkeypatch.setenv("DATABASE_URL", database_url)

    assert query_data._database_url() == database_url


@pytest.mark.db
def test_query_data_database_url_raises_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(EnvironmentError):
        query_data._database_url()


@pytest.mark.db
def test_analyze_prints_every_answer(db_connection, database_url, capsys):
    """Against an empty (but real) applicants table, every Part 2
    question must run and print a formatted answer without raising."""
    query_data.analyze(query_data.QUESTION_QUERY, database_url)

    printed = capsys.readouterr().out
    assert "Applicant count:" in printed


@pytest.mark.db
def test_analyze_with_no_questions_prints_message(database_url, capsys):
    query_data.analyze([], database_url)

    assert "No questions or queries submitted" in capsys.readouterr().out


@pytest.mark.db
def test_analyze_returns_quietly_when_connection_fails(monkeypatch, capsys):
    """If connect_db can't open a connection, analyze() should just
    return rather than trying to run any queries."""
    monkeypatch.setattr("database.query_data.connect_db", lambda url: None)

    query_data.analyze(query_data.QUESTION_QUERY, "postgresql://nowhere/nothing")

    assert capsys.readouterr().out == ""


@pytest.mark.db
def test_analyze_prints_error_for_failing_query(db_connection, database_url, capsys):
    """A query against a table that doesn't exist should have its error
    printed in place, without stopping the rest of the run - here there's
    only one question, so it should just print the error and finish."""
    bad_question = [("A question about a missing table", "SELECT * FROM nonexistent_table_xyz", str)]

    query_data.analyze(bad_question, database_url)

    printed = capsys.readouterr().out
    assert "Could not run 'A question about a missing table'" in printed
