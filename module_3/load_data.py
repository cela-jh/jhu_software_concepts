"""
`load_data.py`
Takes cleaned applicant data and loads it into a PostgreSQL database
"""
import json
import re
from datetime import datetime
import psycopg
from db_connection import connect_db, disconnect_db, CONN_PARAMS

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


class InvalidResult(Exception):
    """Raised when a result is missing required fields or has an invalid structure."""


def _extract_number(text):
    """
    Pulls the first number out of a badge string such as "GPA 3.40".
    Returns a float, or None if text is missing or has no number in it.
    """
    if not text:
        return None
    match = re.search(r"[\d.]+", text)
    return float(match.group()) if match else None


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
        "us_or_international": result["US/International"],
        "gpa": _extract_number(result.get("GPA")),
        "gre": _extract_number(result.get("GRE score")),
        "gre_v": _extract_number(result.get("GRE V score")),
        "gre_aw": _extract_number(result.get("GRE AW")),
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


def load_data(filepath, user, password):
    """
    Loads applicant results from a JSON file into the applicants table.
    Results missing required fields are skipped and reported. A result
    whose url already exists in the table is upserted rather than
    skipped, so a file that adds optional fields not present in an
    earlier load (such as the llm_generated fields) fills them in on the
    existing row instead of being ignored.
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

    conn = connect_db(CONN_PARAMS, user, password)
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
    finally:
        disconnect_db(conn)

    loaded = len(inserted_urls)
    updated = len(updated_urls)
    skipped_invalid = len(failed_ids)

    if failed_ids:
        print(f"Skipped {skipped_invalid} results with missing or invalid fields, ids: {failed_ids}")

    print(f"Loaded {loaded} new results. Updated {updated} existing results with "
          f"new field values. Skipped {skipped_invalid} with missing or invalid fields.")