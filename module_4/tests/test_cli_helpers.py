"""
`test_cli_helpers.py`
Covers the CLI-support functions in orm_queries.py and query_data.py that
only run when each module's script is executed directly: their own
_pg_credentials() readers, and the functions that print every answer
(run_orm_queries(), analyze()) against the real cam_db_test database.
"""
import pytest

import database.orm_queries as orm_queries
import database.query_data as query_data


@pytest.mark.db
def test_orm_queries_pg_credentials_reads_env_vars(monkeypatch):
    monkeypatch.setenv("PGUSER", "cameronela")
    monkeypatch.setenv("PGPASSWORD", "test_password")

    assert orm_queries._pg_credentials() == ("cameronela", "test_password")


@pytest.mark.db
def test_orm_queries_pg_credentials_raises_when_unset(monkeypatch):
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)

    with pytest.raises(EnvironmentError):
        orm_queries._pg_credentials()


@pytest.mark.db
def test_run_orm_queries_prints_every_answer(db_connection, db_credentials, capsys):
    """Against an empty (but real) applicants table, every ORM_QUESTIONS
    function must run and print without raising."""
    orm_queries.run_orm_queries(db_credentials)

    printed = capsys.readouterr().out
    assert "Applicant count:" in printed
    assert "No accepted applicants found" in printed


@pytest.mark.db
def test_query_data_pg_credentials_reads_env_vars(monkeypatch):
    monkeypatch.setenv("PGUSER", "cameronela")
    monkeypatch.setenv("PGPASSWORD", "test_password")

    assert query_data._pg_credentials() == ("cameronela", "test_password")


@pytest.mark.db
def test_query_data_pg_credentials_raises_when_unset(monkeypatch):
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)

    with pytest.raises(EnvironmentError):
        query_data._pg_credentials()


@pytest.mark.db
def test_analyze_prints_every_answer(db_connection, db_credentials, capsys):
    """Against an empty (but real) applicants table, every Part 2
    question must run and print a formatted answer without raising."""
    query_data.analyze(query_data.QUESTION_QUERY, db_credentials)

    printed = capsys.readouterr().out
    assert "Applicant count:" in printed


@pytest.mark.db
def test_analyze_with_no_questions_prints_message(db_credentials, capsys):
    query_data.analyze([], db_credentials)

    assert "No questions or queries submitted" in capsys.readouterr().out


@pytest.mark.db
def test_analyze_returns_quietly_when_connection_fails(monkeypatch, capsys):
    """If connect_db can't open a connection, analyze() should just
    return rather than trying to run any queries."""
    monkeypatch.setattr("database.query_data.connect_db", lambda conn_params, credentials: None)

    query_data.analyze(query_data.QUESTION_QUERY, ("cameronela", "test_password"))

    assert capsys.readouterr().out == ""


@pytest.mark.db
def test_analyze_prints_error_for_failing_query(db_connection, db_credentials, capsys):
    """A query against a table that doesn't exist should have its error
    printed in place, without stopping the rest of the run - here there's
    only one question, so it should just print the error and finish."""
    bad_question = [("A question about a missing table", "SELECT * FROM nonexistent_table_xyz", str)]

    query_data.analyze(bad_question, db_credentials)

    printed = capsys.readouterr().out
    assert "Could not run 'A question about a missing table'" in printed
