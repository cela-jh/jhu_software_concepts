"""
`test_incremental_scraper.py`
Unit tests for incremental_scraper.py. Pure-function tests run without a
database. Watermark and load tests use a real cam_db_test connection so
the SQL is exercised against an actual schema.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from etl.incremental_scraper import (
    SEED_SOURCE,
    _build_row,
    _parse_date,
    _parse_p_id,
    get_watermark,
    load_incremental,
    set_watermark,
)


# ---- pure function tests ----

@pytest.mark.db
def test_parse_p_id_extracts_integer_from_valid_url():
    """_parse_p_id must return the integer in /result/<n>."""
    assert _parse_p_id("https://www.thegradcafe.com/survey/result/12345") == 12345


@pytest.mark.db
def test_parse_p_id_returns_none_for_missing_url():
    """_parse_p_id must return None when the URL is None or has no /result/."""
    assert _parse_p_id(None) is None
    assert _parse_p_id("https://example.com/no-result") is None


@pytest.mark.db
def test_parse_date_converts_gradcafe_format_to_iso():
    """_parse_date must convert 'Added on Sep 12, 2026' to '2026-09-12'."""
    assert _parse_date("Added on Sep 12, 2026") == "2026-09-12"


@pytest.mark.db
def test_parse_date_returns_none_for_unrecognized_format():
    """_parse_date must return None when the string does not match."""
    assert _parse_date("2026-09-12") is None
    assert _parse_date(None) is None


@pytest.mark.db
def test_parse_date_returns_none_for_invalid_month_abbreviation():
    """_parse_date must return None when the month token is not in _MONTHS."""
    assert _parse_date("Added on Xyz 12, 2026") is None


@pytest.mark.db
def test_build_row_returns_none_when_url_unparseable():
    """_build_row must return None for a record whose URL has no /result/ path."""
    raw = {
        "url": "https://example.com/no-result",
        "date added": "Added on Jan 1, 2026",
        "program": "CS", "status": "Accepted", "term": "F26",
        "US/International": "US", "degree": "PhD",
    }
    assert _build_row(raw) is None


@pytest.mark.db
def test_build_row_returns_none_when_date_unparseable():
    """_build_row must return None for a record with an unrecognized date."""
    raw = {
        "url": "https://www.thegradcafe.com/survey/result/1",
        "date added": "not-a-date",
        "program": "CS", "status": "Accepted", "term": "F26",
        "US/International": "US", "degree": "PhD",
    }
    assert _build_row(raw) is None


@pytest.mark.db
def test_build_row_returns_none_when_required_field_missing():
    """_build_row must return None when a required column (e.g. status) is absent."""
    raw = {
        "url": "https://www.thegradcafe.com/survey/result/1",
        "date added": "Added on Jan 1, 2026",
        "program": "CS",
        # status missing
        "term": "F26", "US/International": "US", "degree": "PhD",
    }
    assert _build_row(raw) is None


@pytest.mark.db
def test_build_row_maps_fields_correctly():
    """_build_row must map JSON keys to their column-name equivalents."""
    raw = {
        "url": "https://www.thegradcafe.com/survey/result/99",
        "date added": "Added on Mar 3, 2025",
        "program": "CS", "status": "Accepted", "term": "F25",
        "US/International": "Intl", "degree": "MS", "comments": "great",
    }
    row = _build_row(raw)
    assert row is not None
    assert row["p_id"] == 99
    assert row["date_added"] == "2025-03-03"
    assert row["us_or_international"] == "Intl"
    assert row["comments"] == "great"


# ---- database-backed tests ----

@pytest.fixture
def worker_db(db_connection):
    """
    Extends db_connection to also truncate ingestion_watermarks so
    watermark tests always start from a clean state. Creates the table
    when the local test DB was initialized without the migration.
    """
    db_connection.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_watermarks (
            source     TEXT        PRIMARY KEY,
            last_seen  TEXT,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    db_connection.execute("TRUNCATE ingestion_watermarks")
    db_connection.commit()
    yield db_connection
    db_connection.execute("TRUNCATE ingestion_watermarks")
    db_connection.commit()


@pytest.mark.db
def test_get_watermark_returns_none_when_no_row_exists(worker_db):
    """get_watermark must return None before any watermark has been written."""
    with worker_db.cursor() as cursor:
        result = get_watermark(cursor, SEED_SOURCE)
    assert result is None


@pytest.mark.db
def test_set_and_get_watermark_roundtrip(worker_db):
    """A watermark written by set_watermark must be readable by get_watermark."""
    with worker_db.cursor() as cursor:
        set_watermark(cursor, SEED_SOURCE, "42")
        worker_db.commit()
        result = get_watermark(cursor, SEED_SOURCE)
    assert result == "42"


@pytest.mark.db
def test_set_watermark_upserts_on_conflict(worker_db):
    """set_watermark must update last_seen when the source already exists."""
    with worker_db.cursor() as cursor:
        set_watermark(cursor, SEED_SOURCE, "10")
        worker_db.commit()
        set_watermark(cursor, SEED_SOURCE, "99")
        worker_db.commit()
        result = get_watermark(cursor, SEED_SOURCE)
    assert result == "99"


@pytest.mark.db
def test_load_incremental_inserts_new_records(tmp_path, worker_db):
    """load_incremental must insert records whose p_id exceeds the watermark."""
    seed = [
        {
            "url": "https://www.thegradcafe.com/survey/result/10",
            "date added": "Added on Jan 1, 2026",
            "program": "CS", "status": "Accepted", "term": "F26",
            "US/International": "US", "degree": "PhD", "comments": None,
        }
    ]
    seed_path = tmp_path / "data.json"
    seed_path.write_text(json.dumps(seed))

    inserted = load_incremental(worker_db, seed_path)
    worker_db.commit()

    assert inserted == 1
    with worker_db.cursor() as cur:
        cur.execute("SELECT p_id FROM applicants WHERE p_id = 10")
        assert cur.fetchone() is not None


@pytest.mark.db
def test_load_incremental_skips_records_at_or_below_watermark(tmp_path, worker_db):
    """Records with p_id <= the since threshold must not be inserted."""
    seed = [
        {
            "url": "https://www.thegradcafe.com/survey/result/5",
            "date added": "Added on Jan 1, 2026",
            "program": "CS", "status": "Accepted", "term": "F26",
            "US/International": "US", "degree": "PhD", "comments": None,
        }
    ]
    seed_path = tmp_path / "data.json"
    seed_path.write_text(json.dumps(seed))

    inserted = load_incremental(worker_db, seed_path, since="5")
    worker_db.commit()

    assert inserted == 0


@pytest.mark.db
def test_load_incremental_advances_watermark(tmp_path, worker_db):
    """After loading, get_watermark must return the max p_id from the batch."""
    seed = [
        {
            "url": f"https://www.thegradcafe.com/survey/result/{p}",
            "date added": "Added on Jan 1, 2026",
            "program": "CS", "status": "Accepted", "term": "F26",
            "US/International": "US", "degree": "PhD", "comments": None,
        }
        for p in (20, 30, 25)
    ]
    seed_path = tmp_path / "data.json"
    seed_path.write_text(json.dumps(seed))

    load_incremental(worker_db, seed_path)
    worker_db.commit()

    with worker_db.cursor() as cursor:
        mark = get_watermark(cursor, SEED_SOURCE)
    assert mark == "30"


@pytest.mark.db
def test_load_incremental_is_idempotent(tmp_path, worker_db):
    """Running load_incremental twice on the same seed must not duplicate rows."""
    seed = [
        {
            "url": "https://www.thegradcafe.com/survey/result/50",
            "date added": "Added on Feb 5, 2026",
            "program": "EE", "status": "Rejected", "term": "F26",
            "US/International": "Intl", "degree": "MS", "comments": None,
        }
    ]
    seed_path = tmp_path / "data.json"
    seed_path.write_text(json.dumps(seed))

    load_incremental(worker_db, seed_path)
    worker_db.commit()
    load_incremental(worker_db, seed_path)
    worker_db.commit()

    with worker_db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM applicants WHERE p_id = 50")
        assert cur.fetchone()[0] == 1
