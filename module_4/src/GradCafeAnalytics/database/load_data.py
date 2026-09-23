"""
`load_data.py`
Takes cleaned applicant data and loads it into a PostgreSQL database. Run
directly (`python load_data.py [file.json]`) to load a file; `load_data`
can also be imported and called on its own.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import psycopg

# Ensures db_helpers resolves whether load_data.py is run directly or
# imported as database.load_data from elsewhere in the package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_helpers import connect_db, disconnect_db, CONN_PARAMS


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

NATIONALITY_VALUES = {"american": "American", "international": "International"}


class InvalidResult(Exception):
    """Raised when a result is missing required fields or has an invalid structure."""


def _extract_number(text, valid_ranges=None):
    """
    Pulls the first number out of a badge string such as "GPA 3.40". If
    valid_ranges is given (a list of (low, high) inclusive bounds), a
    number outside every range is discarded as an implausible or
    mis-scaled value rather than being stored as-is.
    Returns a float, or None if text is missing, has no number, or the
    number falls outside every given valid range.
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
    Maps a scraped US/International value to 'American' or 'International'
    case-insensitively, or 'Other' for anything else (including values that
    were scraped from the wrong tag and aren't a nationality at all).
    Returns a string.
    """
    return NATIONALITY_VALUES.get(value.strip().lower(), "Other")


def _parse_date_added(text):
    """
    Parses a "date added" string such as "Added on Sep 12, 2026" into a date.
    Raises ValueError if text doesn't match the expected format.
    Returns a date object.
    """
    cleaned = text.removeprefix("Added on ").strip()
    return datetime.strptime(cleaned, "%b %d, %Y").date()


def _extract_result_id(url):
    """
    Pulls the numeric Grad Cafe result ID out of a result URL, for use as
    the table's p_id.
    Returns an integer, or None if no ID could be found in the URL.
    """
    match = re.search(r"/result/(\d+)", url or "")
    return int(match.group(1)) if match else None


def _build_row(result):
    """
    Validates and transforms a single scraped result into a row ready for
    insertion into the applicants table.
    Raises InvalidResult if any required field is missing or invalid.
    Returns a dictionary of column values.
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
    Splits items into consecutive lists of at most size items each.
    Returns a generator of lists.
    """
    for i in range(0, len(items), size):
        yield items[i:i + size]


UPDATE_COLUMNS = [column for column in COLUMNS if column not in ("p_id", "url")]


def _insert_batch(cursor, batch):
    """
    Inserts or upserts a batch of rows into the applicants table in a
    single statement. When a row's url already exists, its columns are
    updated with the new values, keeping the existing value for any
    column the new data doesn't provide (COALESCE), so loading a file
    that adds optional fields (such as llm_generated_program) fills them
    in on already-loaded results instead of being skipped.
    Returns a tuple of (set of newly inserted urls, set of updated urls).
    """
    placeholder_group = "(" + ", ".join(["%s"] * len(COLUMNS)) + ")"
    values_clause = ", ".join([placeholder_group] * len(batch))
    set_clause = ", ".join(
        f"{column} = COALESCE(EXCLUDED.{column}, applicants.{column})"
        for column in UPDATE_COLUMNS
    )
    sql = (
        f"INSERT INTO applicants ({', '.join(COLUMNS)}) "
        f"VALUES {values_clause} "
        f"ON CONFLICT (url) DO UPDATE SET {set_clause} "
        f"RETURNING url, (xmax = 0) AS inserted;"
    )
    params = [row[column] for row in batch for column in COLUMNS]

    cursor.execute(sql, params)
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
    Upserts a batch of rows, using a savepoint so a failure only rolls
    back this attempt rather than the whole load. If the batch fails, it
    is split in half and each half is retried the same way, continuing
    until batches are at most SMALL_BATCH_SIZE rows, at which point rows
    are upserted one at a time so a bad row can be reported individually
    instead of losing every row around it.
    Returns a tuple of (set of newly inserted urls, set of updated urls).
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
    Nulls out gpa, gre, gre_v, and gre_aw values already in the table
    that fall outside their valid score ranges, so implausible or
    mis-scaled values loaded before this validation existed don't skew
    analysis. Prints how many values were cleared for each column.
    Returns none.
    """
    cursor.execute(
        "UPDATE applicants SET gpa = NULL "
        "WHERE gpa IS NOT NULL AND NOT (gpa BETWEEN %s AND %s);",
        GPA_VALID_RANGE,
    )
    cleared_gpa = cursor.rowcount
    gre_range_clause = " OR ".join(["gre BETWEEN %s AND %s"] * len(GRE_VALID_RANGES))
    cursor.execute(
        f"UPDATE applicants SET gre = NULL "
        f"WHERE gre IS NOT NULL AND NOT ({gre_range_clause});",
        [value for bounds in GRE_VALID_RANGES for value in bounds],
    )
    cleared_gre = cursor.rowcount
    cursor.execute(
        "UPDATE applicants SET gre_v = NULL "
        "WHERE gre_v IS NOT NULL AND NOT (gre_v BETWEEN %s AND %s);",
        GRE_V_VALID_RANGE,
    )
    cleared_gre_v = cursor.rowcount
    cursor.execute(
        "UPDATE applicants SET gre_aw = NULL "
        "WHERE gre_aw IS NOT NULL AND NOT (gre_aw BETWEEN %s AND %s);",
        GRE_AW_VALID_RANGE,
    )
    cleared_gre_aw = cursor.rowcount

    total = cleared_gpa + cleared_gre + cleared_gre_v + cleared_gre_aw
    if total:
        print(f"Cleared {total} implausible score values already in the table "
              f"(gpa: {cleared_gpa}, gre: {cleared_gre}, gre_v: {cleared_gre_v}, "
              f"gre_aw: {cleared_gre_aw}).")


def _normalize_existing_nationality(cursor):
    """
    Sets us_or_international to 'Other' for rows already in the table
    whose value isn't 'American' or 'International', so a value scraped
    from the wrong tag (such as a stray "0") doesn't get counted as a
    usable nationality classification it isn't. Prints how many rows were
    changed.
    Returns none.
    """
    cursor.execute(
        "UPDATE applicants SET us_or_international = 'Other' "
        "WHERE us_or_international NOT IN ('American', 'International');"
    )
    changed = cursor.rowcount
    if changed:
        print(f"Set us_or_international to 'Other' for {changed} rows "
              f"that weren't 'American' or 'International'.")


def load_data(filepath, credentials: tuple[str, str]):
    """
    Loads applicant results from a JSON file into the applicants table.
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
    Returns none.
    """
    try:
        with open(filepath, "r") as f:
            results = json.load(f)
    except FileNotFoundError:
        print(f"Could not find the file '{filepath}'. Check the path and try again.")
        return
    except json.JSONDecodeError as error:
        print(f"'{filepath}' is not valid JSON: {error}")
        return
    conn = connect_db(CONN_PARAMS, credentials)
    if conn is None:
        return

    valid_rows = []
    failed_ids = []

    for result in results:
        try:
            valid_rows.append(_build_row(result))
        except InvalidResult:
            failed_ids.append(_extract_result_id(result.get("url")) or result.get("url", "unknown url"))

    inserted_urls = set()
    updated_urls = set()
    try:
        with conn:
            with conn.cursor() as cursor:
                for batch in _chunked(valid_rows, BATCH_SIZE):
                    batch_inserted, batch_updated = _insert_with_fallback(conn, cursor, batch)
                    inserted_urls |= batch_inserted
                    updated_urls |= batch_updated
                _clear_invalid_scores(cursor)
                _normalize_existing_nationality(cursor)
    finally:
        disconnect_db(conn)

    loaded = len(inserted_urls)
    updated = len(updated_urls)
    skipped_invalid = len(failed_ids)

    if failed_ids:
        print(f"Skipped {skipped_invalid} results with missing or invalid fields, ids: {failed_ids}")

    print(f"Loaded {loaded} new results. Updated {updated} existing results with "
          f"new field values. Skipped {skipped_invalid} with missing or invalid fields.")


def parse_args():
    """
    Parses CLI arguments for loading a results file into PostgreSQL
    directly.
    """
    parser = argparse.ArgumentParser(
        description="Load a results file into the PostgreSQL applicants table."
    )
    parser.add_argument(
        "relative_filepath", type=Path, nargs="?", default=DEFAULT_DATA_FILE,
        help=f"File to load into PostgreSQL (default: `{DEFAULT_DATA_FILE}`)"
    )
    return parser.parse_args()


if __name__ == "__main__":
    # paths.py and the scraping package are siblings of database/, both
    # directly under GradCafeAnalytics/.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from paths import DEFAULT_DATA_FILE
    from scraping.storage import validate_filepath

    cli_args = parse_args()
    validate_filepath(cli_args.relative_filepath, must_exist=True)

    pg_user = os.getenv("PGUSER")
    pg_password = os.getenv("PGPASSWORD")
    if not pg_user or not pg_password:
        print("Set the PGUSER and PGPASSWORD environment variables before running load_data.py.")
        sys.exit(1)

    load_data(cli_args.relative_filepath, (pg_user, pg_password))