"""
`load_data.py`
Takes cleaned applicant data and loads it into a PostgreSQL database.
Reads the DATABASE_URL environment variable for the connection string.
Run directly (`python load_data.py [file.json]`) or import and call
`load_data(filepath, database_url)`.
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


APPLICANTS_TABLE_NAME = "applicants"
APPLICANTS = sql.Identifier(APPLICANTS_TABLE_NAME)

DEFAULT_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "applicant_data.json"

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


def _connect(database_url):
    """
    Open a psycopg connection to database_url, printing a readable error
    instead of raising on failure.

    :param database_url: PostgreSQL connection string.
    :type database_url: str
    :returns: The open connection, or None if the connection failed.
    :rtype: psycopg.Connection or None
    """
    try:
        return psycopg.connect(database_url)
    except psycopg.DatabaseError as error:
        print(f"Could not connect to the database: {error}")
        return None


def _extract_number(text, valid_ranges=None):
    """
    Pull the first number out of a badge string such as "GPA 3.40".

    :param text: The badge string to extract a number from.
    :type text: str or None
    :param valid_ranges: A list of (low, high) inclusive bounds; a number
        outside every range is discarded.
    :type valid_ranges: list[tuple(float, float)] or None
    :returns: The extracted number, or None.
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
    Map a scraped US/International value to 'American', 'International',
    or 'Other'.

    :param value: The scraped US/International value.
    :type value: str
    :returns: 'American', 'International', or 'Other'.
    :rtype: str
    """
    return NATIONALITY_VALUES.get(value.strip().lower(), OTHER_NATIONALITY)


def _parse_date_added(text):
    """
    Parse "Added on Sep 12, 2026" into a date.

    :param text: The date string to parse.
    :type text: str
    :raises ValueError: If text doesn't match the expected format.
    :returns: The parsed date.
    :rtype: datetime.date
    """
    cleaned = text.removeprefix("Added on ").strip()
    return datetime.strptime(cleaned, "%b %d, %Y").date()


def _extract_result_id(url):
    """
    Pull the numeric Grad Cafe result ID from a result URL.

    :param url: The result URL.
    :type url: str or None
    :returns: The extracted ID, or None.
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
    Compose the multi-row upsert for row_count rows. All column and
    table names are quoted with sql.Identifier; all values are
    placeholders.

    :param row_count: How many rows the statement inserts.
    :type row_count: int
    :returns: The composed INSERT ... ON CONFLICT statement.
    :rtype: psycopg.sql.Composed
    """
    column_list = sql.SQL(", ").join(sql.Identifier(column) for column in COLUMNS)
    row_placeholders = sql.SQL("({})").format(
        sql.SQL(", ").join(sql.Placeholder() for _ in COLUMNS)
    )
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
    Insert or upsert a batch of rows into the applicants table.

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
    Upsert a batch of rows using a savepoint so a failure only rolls
    back this attempt. If the batch fails it is split in half and each
    half is retried, down to individual rows at SMALL_BATCH_SIZE.

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


def _build_clear_invalid(column, range_count):
    """
    Compose the UPDATE that nulls one score column's values outside all
    of its valid ranges.

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


def _clear_invalid_scores(cursor):
    """
    Null out score values already in the table that fall outside their
    valid ranges.

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


def _normalize_existing_nationality(cursor):
    """
    Set us_or_international to 'Other' for rows whose value is not
    'American' or 'International'.

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


def _read_results(filepath):
    """
    Read the JSON results file, printing a readable error instead of
    raising on failure.

    :param filepath: Path to the JSON results file.
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
            failed_ids.append(
                _extract_result_id(result.get("url")) or result.get("url", "unknown url")
            )
    return valid_rows, failed_ids


def _upsert_and_clean(conn, valid_rows):
    """
    Upsert every valid row in BATCH_SIZE batches, then clean score and
    nationality values across the whole table.

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


def load_data(filepath, database_url: str):
    """
    Load applicant results from a JSON file into the applicants table.
    Results missing required fields are skipped. Existing rows are
    upserted so optional fields added later fill in without duplication.
    Implausible score values and non-standard nationality values are
    cleaned on every load.

    :param filepath: Path to the JSON results file to load.
    :type filepath: str or pathlib.Path
    :param database_url: PostgreSQL connection string.
    :type database_url: str
    :returns: True if the file was read and the database reached, False
        if either step failed entirely.
    :rtype: bool
    """
    results = _read_results(filepath)
    if results is None:
        return False
    conn = _connect(database_url)
    if conn is None:
        return False

    valid_rows, failed_ids = _build_rows(results)
    try:
        inserted_urls, updated_urls = _upsert_and_clean(conn, valid_rows)
    finally:
        conn.close()

    _print_load_summary(len(inserted_urls), len(updated_urls), failed_ids)
    return True


def main():
    """
    CLI entry point: load the given (or default) results file into
    PostgreSQL using the DATABASE_URL environment variable.

    :raises SystemExit: With code 1 on any unsuccessful load.
    :returns: None.
    :rtype: None
    """
    parser = argparse.ArgumentParser(
        description="Load a results file into the PostgreSQL applicants table."
    )
    parser.add_argument(
        "filepath", type=Path, nargs="?", default=DEFAULT_DATA_FILE,
        help=f"File to load (default: {DEFAULT_DATA_FILE})"
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Set DATABASE_URL before running.")
        sys.exit(1)

    if not load_data(args.filepath, database_url):
        sys.exit(1)


if __name__ == "__main__":
    main()
