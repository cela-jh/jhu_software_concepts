"""
`test_db_insert.py`
Verifies real PostgreSQL behavior (against the disposable cam_db_test
database, never cam_db): that a pull inserts rows with every required
field populated, that re-pulling the same data doesn't create
duplicates, and that a simple query function returns the expected keys.
"""
import json

import pytest

from app import pull_control
from database.db_helpers import get_applicant


class _FakeProcess:
    """Stands in for the subprocess.Popen scrape.py process. The faked
    scraper has already written its results to DATA_FILE before this
    "process" is created, so stdout just needs to end cleanly."""

    def __init__(self, lines=()):
        self.stdout = iter(lines)

    def wait(self):
        return 0


def _write_fake_scraped_data(path, rows):
    path.write_text(json.dumps(rows, indent=2))


def _fake_row(result_id, **overrides):
    """A minimally valid scraped result; _extract_result_id() pulls
    result_id back out of the url as the row's p_id."""
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


@pytest.mark.db
def test_pull_inserts_rows_with_required_fields(client, monkeypatch, tmp_path, db_connection):
    """Before a pull, the table is empty (guaranteed by db_connection).
    After POST /pull/start, the faked scraper's rows should be loaded
    into PostgreSQL with every required field populated."""
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM applicants")
        assert cursor.fetchone()[0] == 0

    data_file = tmp_path / "applicant_data.json"
    _write_fake_scraped_data(data_file, [_fake_row(1000001), _fake_row(1000002)])

    monkeypatch.setattr(pull_control, "DATA_FILE", data_file)
    monkeypatch.setattr("app.pull_control.subprocess.Popen", lambda *a, **kw: _FakeProcess())
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.setenv("PGUSER", "cameronela")
    monkeypatch.setenv("PGPASSWORD", "test_password")

    response = client.post("/pull/start")
    assert response.status_code == 200
    pull_control._thread.join(timeout=5)

    with db_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM applicants")
        assert cursor.fetchone()[0] == 2

    required_columns = ["program", "date_added", "url", "status", "term",
                         "us_or_international", "degree"]
    for p_id in (1000001, 1000002):
        row = get_applicant(db_connection, p_id)
        assert row is not None
        for column in required_columns:
            assert row[column] is not None, f"{column} was NULL for p_id {p_id}"


@pytest.mark.db
def test_repeated_pull_does_not_duplicate_rows(client, monkeypatch, tmp_path, db_connection):
    """Pulling the same result twice (e.g. an overlapping re-scrape)
    must upsert, not duplicate, since url is UNIQUE."""
    data_file = tmp_path / "applicant_data.json"
    _write_fake_scraped_data(data_file, [_fake_row(2000001)])

    monkeypatch.setattr(pull_control, "DATA_FILE", data_file)
    monkeypatch.setattr("app.pull_control.subprocess.Popen", lambda *a, **kw: _FakeProcess())
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")
    monkeypatch.setenv("PGUSER", "cameronela")
    monkeypatch.setenv("PGPASSWORD", "test_password")

    first_response = client.post("/pull/start")
    assert first_response.status_code == 200
    pull_control._thread.join(timeout=5)

    with db_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM applicants")
        assert cursor.fetchone()[0] == 1

    # A second pull over the exact same (unchanged) data file, simulating
    # a re-scrape that finds nothing new.
    second_response = client.post("/pull/start")
    assert second_response.status_code == 200
    pull_control._thread.join(timeout=5)

    with db_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM applicants")
        assert cursor.fetchone()[0] == 1


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
