"""
`test_load_data.py`
Covers load_data.py branches not already exercised by test_db_insert.py
and test_integration_end_to_end.py: numeric/date parsing edge cases, the
batch-insert failure/retry-split path against a real constraint
violation, the score-cleanup and nationality-normalization print
branches, file-level error handling, and the CLI's parse_args().
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import database.load_data as load_data
from helpers import fake_applicant_row

# load_data runs as a package module, so the CLI is started from src/.
SRC_DIR = Path(load_data.__file__).resolve().parent.parent


@pytest.mark.db
@pytest.mark.parametrize("text,valid_ranges,expected", [
    (None, None, None),
    ("", None, None),
    ("no digits here", None, None),
    ("GPA 3.50", [(0, 4.0)], 3.50),
    ("GRE 99", [(130, 170)], None),  # out of range, discarded
])
def test_extract_number_edge_cases(text, valid_ranges, expected):
    assert load_data._extract_number(text, valid_ranges) == expected


@pytest.mark.db
def test_build_row_raises_on_bad_date(monkeypatch):
    result = fake_applicant_row(1, **{"date added": "not a real date"})
    with pytest.raises(load_data.InvalidResult, match="date_added"):
        load_data._build_row(result)


@pytest.mark.db
def test_build_row_raises_on_unparseable_url():
    result = fake_applicant_row(1, url="https://www.thegradcafe.com/no-id-here")
    with pytest.raises(load_data.InvalidResult, match="p_id"):
        load_data._build_row(result)


@pytest.mark.db
def test_build_row_raises_on_missing_required_field():
    result = fake_applicant_row(1)
    del result["program"]
    with pytest.raises(load_data.InvalidResult, match="program"):
        load_data._build_row(result)


@pytest.mark.db
def test_load_data_reports_and_skips_invalid_results(tmp_path, db_connection, database_url, capsys):
    """A file mixing one valid and one invalid result should load the
    valid one and report the invalid one as skipped, not crash - and
    still report success overall, since the file was read and the
    database was reached."""
    data_file = tmp_path / "applicant_data.json"
    invalid_row = fake_applicant_row(9000002)
    del invalid_row["program"]
    data_file.write_text(json.dumps([fake_applicant_row(9000001), invalid_row]))

    result = load_data.load_data(data_file, database_url)

    assert result is True
    printed = capsys.readouterr().out
    assert "Skipped 1 results with missing or invalid fields" in printed
    assert "Loaded 1 new results" in printed


@pytest.mark.db
def test_load_data_reports_missing_file(tmp_path, database_url, capsys):
    missing_file = tmp_path / "does_not_exist.json"

    result = load_data.load_data(missing_file, database_url)

    assert result is False
    assert "Could not find the file" in capsys.readouterr().out


@pytest.mark.db
def test_load_data_reports_invalid_json(tmp_path, database_url, capsys):
    bad_file = tmp_path / "not_json.json"
    bad_file.write_text("{not valid json")

    result = load_data.load_data(bad_file, database_url)

    assert result is False
    assert "is not valid JSON" in capsys.readouterr().out


@pytest.mark.db
def test_load_data_returns_quietly_when_connection_fails(tmp_path, monkeypatch, capsys):
    data_file = tmp_path / "applicant_data.json"
    data_file.write_text(json.dumps([fake_applicant_row(9000003)]))
    monkeypatch.setattr(load_data, "connect_db", lambda url: None)

    result = load_data.load_data(data_file, "postgresql://nowhere/nothing")

    assert result is False
    assert capsys.readouterr().out == ""


@pytest.mark.db
def test_insert_with_fallback_reports_single_row_failure(db_connection):
    """Within a small batch, one row violating the p_id primary key
    (a different url, but a p_id already in the table) should be
    reported individually while the rest still succeed."""
    with db_connection.cursor() as cursor:
        good_row = load_data._build_row(fake_applicant_row(9100001))
        load_data._insert_batch(cursor, [good_row])
    db_connection.commit()

    conflicting_row = load_data._build_row(
        fake_applicant_row(9100002, url="https://www.thegradcafe.com/result/9100002")
    )
    conflicting_row["p_id"] = 9100001  # same p_id as the row already committed above

    with db_connection.cursor() as cursor:
        import io
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            inserted, updated = load_data._insert_with_fallback(db_connection, cursor, [conflicting_row])

    assert inserted == set()
    assert updated == set()
    assert "Could not insert result with url" in buffer.getvalue()


@pytest.mark.db
def test_insert_with_fallback_splits_failing_large_batch(db_connection):
    """A batch bigger than SMALL_BATCH_SIZE where two rows collide on
    p_id should fail as one bulk insert, get split in half, and
    eventually succeed for every row except the colliding one."""
    rows = [load_data._build_row(fake_applicant_row(9200000 + i)) for i in range(12)]
    # Force a p_id collision between two different urls, so the single
    # bulk INSERT for the whole batch fails outright.
    rows[11]["p_id"] = rows[0]["p_id"]

    with db_connection.cursor() as cursor:
        inserted, updated = load_data._insert_with_fallback(db_connection, cursor, rows)

    # 11 distinct p_ids succeed (index 0 and 11 share one, so 12 rows -> 11 unique).
    assert len(inserted) == 11
    assert updated == set()


@pytest.mark.db
def test_clear_invalid_scores_reports_and_nulls_bad_values(db_connection):
    with db_connection.cursor() as cursor:
        row = load_data._build_row(fake_applicant_row(9300001))
        load_data._insert_batch(cursor, [row])
        cursor.execute("UPDATE applicants SET gpa = 9.9 WHERE p_id = 9300001")
    db_connection.commit()

    with db_connection.cursor() as cursor:
        import io
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            load_data._clear_invalid_scores(cursor)
        cursor.execute("SELECT gpa FROM applicants WHERE p_id = 9300001")
        assert cursor.fetchone()[0] is None
    db_connection.commit()

    assert "Cleared 1 implausible score values" in buffer.getvalue()


@pytest.mark.db
def test_normalize_existing_nationality_reports_and_updates(db_connection):
    with db_connection.cursor() as cursor:
        row = load_data._build_row(fake_applicant_row(9400001))
        load_data._insert_batch(cursor, [row])
        cursor.execute("UPDATE applicants SET us_or_international = 'Martian' WHERE p_id = 9400001")
    db_connection.commit()

    with db_connection.cursor() as cursor:
        import io
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            load_data._normalize_existing_nationality(cursor)
        cursor.execute("SELECT us_or_international FROM applicants WHERE p_id = 9400001")
        assert cursor.fetchone()[0] == "Other"
    db_connection.commit()

    assert "Set us_or_international to 'Other' for 1 rows" in buffer.getvalue()


@pytest.mark.db
def test_parse_args_uses_default_data_file(monkeypatch):
    monkeypatch.setattr("sys.argv", ["load_data.py"])

    args = load_data.parse_args()

    assert args.relative_filepath == load_data.DEFAULT_DATA_FILE


@pytest.mark.db
def test_parse_args_accepts_explicit_filepath(monkeypatch):
    monkeypatch.setattr("sys.argv", ["load_data.py", "custom_file.json"])

    args = load_data.parse_args()

    assert str(args.relative_filepath) == "custom_file.json"


@pytest.mark.db
def test_cli_exits_nonzero_when_database_unreachable(tmp_path):
    """Running load_data.py as a real script against a database that
    can't be reached should exit non-zero, not silently exit 0, so a
    caller (a shell script, CI step, cron job) can tell an unsuccessful
    load apart from a completed one."""
    data_file = tmp_path / "applicant_data.json"
    data_file.write_text(json.dumps([fake_applicant_row(9999999)]))

    result = subprocess.run(
        [sys.executable, "-m", "database.load_data", str(data_file)],
        env={
            **os.environ,
            "DATABASE_URL": "postgresql://localhost:5432/definitely_not_a_real_database",
        },
        cwd=SRC_DIR, capture_output=True, text=True, check=False,
    )

    assert result.returncode != 0
    # the failure must come from the database, not from the module
    # failing to import
    assert "Could not connect to the database" in result.stdout


@pytest.fixture
def cli_data_file(tmp_path, monkeypatch):
    """A real results file passed to main() through sys.argv."""
    data_file = tmp_path / "applicant_data.json"
    data_file.write_text(json.dumps([fake_applicant_row(9999998)]))
    monkeypatch.setattr("sys.argv", ["load_data.py", str(data_file)])
    return data_file


@pytest.mark.db
def test_main_exits_nonzero_when_database_url_unset(cli_data_file, monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        load_data.main()

    assert exit_info.value.code == 1
    assert "DATABASE_URL" in capsys.readouterr().out


@pytest.mark.db
def test_main_exits_nonzero_when_load_fails(cli_data_file, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(load_data, "load_data", lambda filepath, url: False)

    with pytest.raises(SystemExit) as exit_info:
        load_data.main()

    assert exit_info.value.code == 1


@pytest.mark.db
def test_main_returns_normally_when_load_succeeds(cli_data_file, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    load_calls = []
    monkeypatch.setattr(load_data, "load_data",
                        lambda filepath, url: load_calls.append((filepath, url)) or True)

    load_data.main()

    assert load_calls == [(cli_data_file, "postgresql://unused")]
