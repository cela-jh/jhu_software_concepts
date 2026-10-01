"""
`load_data.py`
Takes cleaned applicant data and loads it into a PostgreSQL database. Run
from src/ as a module (`python -m database.load_data [file.json]`) to load
a file; `load_data` can also be imported and called on its own.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import psycopg
from psycopg import sql

from database.db_helpers import APPLICANTS, connect_db, disconnect_db
from paths import DEFAULT_DATA_FILE
from scraping.storage import validate_filepath


REQUIRED_FIELDS = {
    "program": "program",
    "date added": "date_added",
    "url": "url",
    "status": "status",
    "term": "term",
    "US/International": "us_or_international",
    "degree": "degree",
}

COLUMNS = [
    "p_id", "program", "comments", "date_added", "url", "status", "term",
    "us_or_international", "gpa", "gre", "gre_v", "gre_aw", "degree",
    "llm_generated_program", "llm_generated_university",
]

BATCH_SIZE = 1000
SMALL_BATCH_SIZE = 10

GPA_VALID_RANGE = (0, 4.0)
GRE_VALID_RANGES = [(130, 170)]
GRE_V_VALID_RANGE = (130, 170)
GRE_AW_VALID_RANGE = (0, 6)

# Every score column and the (low, high) ranges its values must fall in.
SCORE_VALID_RANGES = {
    "gpa": [GPA_VALID_RANGE],
    "gre": GRE_VALID_RANGES,
    "gre_v": [GRE_V_VALID_RANGE],
    "gre_aw": [GRE_AW_VALID_RANGE],
}

NATIONALITY_VALUES = {"american": "American", "international": "International"}
OTHER_NATIONALITY = "Other"


class InvalidResult(Exception):
    """Raised when a result is missing required fields or has an invalid structure."""


def _extract_number(text, valid_ranges=None):
    """
    Pull the first number out of a badge string such as "GPA 3.40".

    :param text: The badge string to extract a number from.
    :type text: str or None
    :param valid_ranges: A list of (low, high) inclusive bounds; a number
        outside every range is discarded as an implausible or
        mis-scaled value rather than being stored as-is.
    :type valid_ranges: list[tuple(float, float)] or None
    :returns: The extracted number, or None if text is missing, has no
        number, or the number falls outside every given valid range.
    :rtype: float or None
    """
    if not text:
        return None
    match = re.search(r"[\d.]+", text)
    if not match:
        return None
    value = float(match.group())
    if valid_ranges is not None and not any(low <= value <= high for low, high in valid_ranges):
        return None
    return value


def _normalize_nationality(value):
    """
    Map a scraped US/International value to 'American' or
    'International' case-insensitively, or 'Other' for anything else
    (including values that were scraped from the wrong tag and aren't a
    nationality at all).

    :param value: The scraped US/International value.
    :type value: str
    :returns: 'American', 'International', or 'Other'.
    :rtype: str
    """
    return NATIONALITY_VALUES.get(value.strip().lower(), OTHER_NATIONALITY)


def _parse_date_added(text):
    """
    Parse a "date added" string such as "Added on Sep 12, 2026" into a date.

    :param text: The "date added" string to parse.
    :type text: str
    :raises ValueError: If text doesn't match the expected format.
    :returns: The parsed date.
    :rtype: datetime.date
    """
    cleaned = text.removeprefix("Added on ").strip()
    return datetime.strptime(cleaned, "%b %d, %Y").date()


def _extract_result_id(url):
    """
    Pull the numeric Grad Cafe result ID out of a result URL, for use as
    the table's p_id.

    :param url: The result URL to extract an ID from.
    :type url: str or None
    :returns: The extracted ID, or None if none could be found in the URL.
    :rtype: int or None
    """
    match = re.search(r"/result/(\d+)", url or "")
    return int(match.group(1)) if match else None


def _build_row(result):
    """
    Validate and transform a single scraped result into a row ready for
    insertion into the applicants table.

    :param result: The raw scraped result.
    :type result: dict
    :raises InvalidResult: If any required field is missing or invalid.
    :returns: A dictionary of column values.
    :rtype: dict
    """
    missing = [column for key, column in REQUIRED_FIELDS.items() if not result.get(key)]

    date_added = None
    if result.get("date added"):
        try:
            date_added = _parse_date_added(result["date added"])
        except ValueError:
            missing.append("date_added")

    p_id = _extract_result_id(result.get("url"))
    if result.get("url") and p_id is None:
        missing.append("p_id")

    if missing:
        raise InvalidResult(f"missing or invalid fields: {', '.join(missing)}")

    return {
        "p_id": p_id,
        "program": result["program"],
        "comments": result.get("comments"),
        "date_added": date_added,
        "url": result["url"],
        "status": result["status"],
        "term": result["term"],
        "us_or_international": _normalize_nationality(result["US/International"]),
        "gpa": _extract_number(result.get("GPA"), [GPA_VALID_RANGE]),
        "gre": _extract_number(result.get("GRE score"), GRE_VALID_RANGES),
        "gre_v": _extract_number(result.get("GRE V score"), [GRE_V_VALID_RANGE]),
        "gre_aw": _extract_number(result.get("GRE AW"), [GRE_AW_VALID_RANGE]),
        "degree": result["degree"],
        "llm_generated_program": result.get("llm-generated-program"),
        "llm_generated_university": result.get("llm-generated-university"),
    }


def _chunked(items, size):
    """
    Split items into consecutive lists of at most size items each.

    :param items: The items to split.
    :type items: list
    :param size: The maximum size of each chunk.
    :type size: int
    :returns: A generator of lists.
    :rtype: Iterator[list]
    """
    for i in range(0, len(items), size):
        yield items[i:i + size]


UPDATE_COLUMNS = [column for column in COLUMNS if column not in ("p_id", "url")]


def _build_upsert(row_count):
    """
    Compose the multi-row upsert for row_count rows. Table and column
    names are quoted with sql.Identifier and every value is a
    placeholder, so no data is ever written into the statement text.
    INSERT has no LIMIT clause in PostgreSQL; BATCH_SIZE caps how many
    rows one statement can carry instead.

    :param row_count: How many rows the statement inserts.
    :type row_count: int
    :returns: The composed INSERT ... ON CONFLICT statement.
    :rtype: psycopg.sql.Composed
    """
    column_list = sql.SQL(", ").join(sql.Identifier(column) for column in COLUMNS)
    row_placeholders = sql.SQL("({})").format(
        sql.SQL(", ").join(sql.Placeholder() for _ in COLUMNS)
    )
    # keep the existing value for any column the new data leaves NULL
    set_clause = sql.SQL(", ").join(
        sql.SQL("{column} = COALESCE(EXCLUDED.{column}, {table}.{column})").format(
            column=sql.Identifier(column), table=APPLICANTS,
        )
        for column in UPDATE_COLUMNS
    )
    return sql.SQL(
        "INSERT INTO {table} ({columns}) VALUES {values} "
        "ON CONFLICT ({url}) DO UPDATE SET {set_clause} "
        "RETURNING {url}, (xmax = 0) AS inserted"
    ).format(
        table=APPLICANTS,
        columns=column_list,
        values=sql.SQL(", ").join([row_placeholders] * row_count),
        url=sql.Identifier("url"),
        set_clause=set_clause,
    )


def _insert_batch(cursor, batch):
    """
    Insert or upsert a batch of rows into the applicants table in a
    single statement. When a row's url already exists, its columns are
    updated with the new values, keeping the existing value for any
    column the new data doesn't provide (COALESCE), so loading a file
    that adds optional fields (such as llm_generated_program) fills them
    in on already-loaded results instead of being skipped.

    :param cursor: An open database cursor.
    :type cursor: psycopg.Cursor
    :param batch: The rows to insert or upsert.
    :type batch: list[dict]
    :returns: A tuple of (set of newly inserted urls, set of updated urls).
    :rtype: tuple(set, set)
    """
    stmt = _build_upsert(len(batch))
    params = [row[column] for row in batch for column in COLUMNS]

    cursor.execute(stmt, params)
    inserted_urls = set()
    updated_urls = set()
    for url, was_inserted in cursor.fetchall():
        if was_inserted:
            inserted_urls.add(url)
        else:
            updated_urls.add(url)
    return inserted_urls, updated_urls


def _insert_with_fallback(conn, cursor, batch):
    """
    Upsert a batch of rows, using a savepoint so a failure only rolls
    back this attempt rather than the whole load. If the batch fails, it
    is split in half and each half is retried the same way, continuing
    until batches are at most SMALL_BATCH_SIZE rows, at which point rows
    are upserted one at a time so a bad row can be reported individually
    instead of losing every row around it.

    :param conn: An open database connection.
    :type conn: psycopg.Connection
    :param cursor: An open database cursor on conn.
    :type cursor: psycopg.Cursor
    :param batch: The rows to insert or upsert.
    :type batch: list[dict]
    :returns: A tuple of (set of newly inserted urls, set of updated urls).
    :rtype: tuple(set, set)
    """
    if len(batch) <= SMALL_BATCH_SIZE:
        inserted = set()
        updated = set()
        for row in batch:
            try:
                with conn.transaction():
                    row_inserted, row_updated = _insert_batch(cursor, [row])
                    inserted |= row_inserted
                    updated |= row_updated
            except psycopg.DatabaseError as error:
                print(f"Could not insert result with url '{row['url']}': {error}")
        return inserted, updated

    try:
        with conn.transaction():
            return _insert_batch(cursor, batch)
    except psycopg.DatabaseError:
        mid = len(batch) // 2
        first_inserted, first_updated = _insert_with_fallback(conn, cursor, batch[:mid])
        second_inserted, second_updated = _insert_with_fallback(conn, cursor, batch[mid:])
        return first_inserted | second_inserted, first_updated | second_updated


def _clear_invalid_scores(cursor):
    """
    Null out gpa, gre, gre_v, and gre_aw values already in the table
    that fall outside their valid score ranges, so implausible or
    mis-scaled values loaded before this validation existed don't skew
    analysis. Prints how many values were cleared for each column.

    :param cursor: An open database cursor.
    :type cursor: psycopg.Cursor
    :returns: None.
    :rtype: None
    """
    cleared = {}
    for column, valid_ranges in SCORE_VALID_RANGES.items():
        stmt = _build_clear_invalid(column, len(valid_ranges))
        cursor.execute(stmt, [value for bounds in valid_ranges for value in bounds])
        cleared[column] = cursor.rowcount

    total = sum(cleared.values())
    if total:
        counts = ", ".join(f"{column}: {count}" for column, count in cleared.items())
        print(f"Cleared {total} implausible score values already in the table ({counts}).")


def _build_clear_invalid(column, range_count):
    """
    Compose the UPDATE that nulls one score column's values outside all
    of its valid ranges. The column is quoted with sql.Identifier and
    each range bound is a placeholder. UPDATE has no LIMIT clause in
    PostgreSQL; this cleanup intentionally covers the whole table.

    :param column: The score column to clean.
    :type column: str
    :param range_count: How many (low, high) ranges the column accepts.
    :type range_count: int
    :returns: The composed UPDATE statement.
    :rtype: psycopg.sql.Composed
    """
    column_id = sql.Identifier(column)
    in_any_range = sql.SQL(" OR ").join(
        sql.SQL("{column} BETWEEN %s AND %s").format(column=column_id)
        for _ in range(range_count)
    )
    return sql.SQL(
        "UPDATE {table} SET {column} = NULL "
        "WHERE {column} IS NOT NULL AND NOT ({in_any_range})"
    ).format(table=APPLICANTS, column=column_id, in_any_range=in_any_range)


def _normalize_existing_nationality(cursor):
    """
    Set us_or_international to 'Other' for rows already in the table
    whose value isn't 'American' or 'International', so a value scraped
    from the wrong tag (such as a stray "0") doesn't get counted as a
    usable nationality classification it isn't. Prints how many rows were
    changed.

    :param cursor: An open database cursor.
    :type cursor: psycopg.Cursor
    :returns: None.
    :rtype: None
    """
    stmt = sql.SQL(
        "UPDATE {table} SET {column} = %s WHERE {column} <> ALL(%s)"
    ).format(table=APPLICANTS, column=sql.Identifier("us_or_international"))
    cursor.execute(stmt, (OTHER_NATIONALITY, list(NATIONALITY_VALUES.values())))
    changed = cursor.rowcount
    if changed:
        print(f"Set us_or_international to 'Other' for {changed} rows "
              f"that weren't 'American' or 'International'.")


def load_data(filepath, database_url: str):
    """
    Load applicant results from a JSON file into the applicants table.
    Results missing required fields are skipped and reported. A result
    whose url already exists in the table is upserted rather than
    skipped, so a file that adds optional fields not present in an
    earlier load (such as the llm_generated fields) fills them in on the
    existing row instead of being ignored. Implausible gpa/gre/gre_v/
    gre_aw values, whether from this file or already in the table from an
    earlier load, are cleared to NULL rather than left to skew analysis,
    and any us_or_international value that isn't 'American' or
    'International' is normalized to 'Other', in this file and in the
    table already.

    :param filepath: Path to the JSON results file to load.
    :type filepath: str or pathlib.Path
    :param database_url: A "postgresql://user:password@host:port/dbname"
        connection string.
    :type database_url: str
    :returns: True if the file was read and the database reached (even
        if some individual results were skipped as invalid), or False
        if the file couldn't be read or the database couldn't be
        reached at all - callers (the CLI entry point, the Pull Data
        upload step) use this to tell an unsuccessful load apart from a
        completed one.
    :rtype: bool
    """
    results = _read_results(filepath)
    if results is None:
        return False
    conn = connect_db(database_url)
    if conn is None:
        return False

    valid_rows, failed_ids = _build_rows(results)
    try:
        inserted_urls, updated_urls = _upsert_and_clean(conn, valid_rows)
    finally:
        disconnect_db(conn)

    _print_load_summary(len(inserted_urls), len(updated_urls), failed_ids)
    return True


def _read_results(filepath):
    """
    Read the JSON results file, printing a readable message instead of
    raising if it is missing or malformed.

    :param filepath: Path to the JSON results file to read.
    :type filepath: str or pathlib.Path
    :returns: The parsed results, or None if the file could not be read.
    :rtype: list[dict] or None
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Could not find the file '{filepath}'. Check the path and try again.")
    except json.JSONDecodeError as error:
        print(f"'{filepath}' is not valid JSON: {error}")
    return None


def _build_rows(results):
    """
    Validate every scraped result, separating rows ready for insertion
    from the identifiers of results that failed validation.

    :param results: The raw scraped results.
    :type results: list[dict]
    :returns: A tuple of (valid rows, failed result ids or urls).
    :rtype: tuple(list[dict], list)
    """
    valid_rows = []
    failed_ids = []
    for result in results:
        try:
            valid_rows.append(_build_row(result))
        except InvalidResult:
            # fall back to the raw url, then a placeholder, so every
            # skipped result is still identifiable in the report
            failed_ids.append(
                _extract_result_id(result.get("url")) or result.get("url", "unknown url")
            )
    return valid_rows, failed_ids


def _upsert_and_clean(conn, valid_rows):
    """
    Upsert every valid row in BATCH_SIZE batches, then clean score and
    nationality values across the whole table, all in one transaction.

    :param conn: An open database connection.
    :type conn: psycopg.Connection
    :param valid_rows: The validated rows to upsert.
    :type valid_rows: list[dict]
    :returns: A tuple of (set of newly inserted urls, set of updated urls).
    :rtype: tuple(set, set)
    """
    inserted_urls = set()
    updated_urls = set()
    with conn:
        with conn.cursor() as cursor:
            for batch in _chunked(valid_rows, BATCH_SIZE):
                batch_inserted, batch_updated = _insert_with_fallback(conn, cursor, batch)
                inserted_urls |= batch_inserted
                updated_urls |= batch_updated
            _clear_invalid_scores(cursor)
            _normalize_existing_nationality(cursor)
    return inserted_urls, updated_urls


def _print_load_summary(loaded, updated, failed_ids):
    """
    Print how many results were inserted, updated, and skipped.

    :param loaded: Count of newly inserted results.
    :type loaded: int
    :param updated: Count of existing results that were updated.
    :type updated: int
    :param failed_ids: Identifiers of results skipped as invalid.
    :type failed_ids: list
    :returns: None.
    :rtype: None
    """
    skipped_invalid = len(failed_ids)
    if failed_ids:
        print(f"Skipped {skipped_invalid} results with missing or invalid fields, "
              f"ids: {failed_ids}")

    print(f"Loaded {loaded} new results. Updated {updated} existing results with "
          f"new field values. Skipped {skipped_invalid} with missing or invalid fields.")


def parse_args():
    """
    Parse CLI arguments for loading a results file into PostgreSQL
    directly.

    :returns: Parsed arguments with a `relative_filepath` attribute.
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(
        description="Load a results file into the PostgreSQL applicants table."
    )
    parser.add_argument(
        "relative_filepath", type=Path, nargs="?", default=DEFAULT_DATA_FILE,
        help=f"File to load into PostgreSQL (default: `{DEFAULT_DATA_FILE}`)"
    )
    return parser.parse_args()


def main():
    """
    CLI entry point: load the given (or default) results file into
    PostgreSQL, exiting non-zero if DATABASE_URL is unset or the load
    could not complete, so shell scripts and CI can detect the failure.

    :raises SystemExit: With code 1 on any unsuccessful load.
    :returns: None.
    :rtype: None
    """
    cli_args = parse_args()
    validate_filepath(cli_args.relative_filepath, must_exist=True)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Set the DATABASE_URL environment variable before running load_data.")
        sys.exit(1)

    if not load_data(cli_args.relative_filepath, database_url):
        sys.exit(1)


if __name__ == "__main__":
    main()
