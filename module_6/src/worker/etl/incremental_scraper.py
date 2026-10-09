"""
`incremental_scraper.py`
Watermark-based loader: reads applicant records from the seed JSON file
and inserts only those whose p_id exceeds the last-seen watermark stored
in ingestion_watermarks. Idempotent via ON CONFLICT (p_id) DO NOTHING.
"""
import json
import re
from pathlib import Path

WATERMARKS_TABLE = "ingestion_watermarks"
SEED_SOURCE = "applicant_data_json"

# Extracts the numeric GradCafe result ID from a result URL.
_P_ID_RE = re.compile(r"/result/(\d+)")

# Parses "Added on Sep 12, 2026" into date components.
_DATE_RE = re.compile(r"Added on (\w{3})\s+(\d{1,2}),\s+(\d{4})")
_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_INSERT_SQL = """
    INSERT INTO applicants
        (p_id, program, comments, date_added, url, status, term,
         us_or_international, degree)
    VALUES
        (%(p_id)s, %(program)s, %(comments)s, %(date_added)s, %(url)s,
         %(status)s, %(term)s, %(us_or_international)s, %(degree)s)
    ON CONFLICT (p_id) DO NOTHING
"""

_UPSERT_WATERMARK_SQL = """
    INSERT INTO ingestion_watermarks (source, last_seen, updated_at)
    VALUES (%s, %s, now())
    ON CONFLICT (source) DO UPDATE
        SET last_seen = EXCLUDED.last_seen, updated_at = now()
"""

_SELECT_WATERMARK_SQL = "SELECT last_seen FROM ingestion_watermarks WHERE source = %s"


def _parse_p_id(url):
    """Extract the integer p_id from a GradCafe result URL."""
    match = _P_ID_RE.search(url or "")
    return int(match.group(1)) if match else None


def _parse_date(date_str):
    """Convert 'Added on Sep 12, 2026' to 'YYYY-MM-DD', or None on failure."""
    match = _DATE_RE.search(date_str or "")
    if not match:
        return None
    month = _MONTHS.get(match.group(1))
    if not month:
        return None
    return f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}"


def _build_row(raw):
    """
    Convert a raw JSON dict to a DB-ready parameter dict, or return None
    if the record is missing required fields or has an unparseable URL/date.

    :param raw: A single record dict from the seed JSON file.
    :type raw: dict
    :returns: A dict keyed by column name, or None for invalid records.
    :rtype: dict or None
    """
    url = raw.get("url", "")
    p_id = _parse_p_id(url)
    if p_id is None:
        return None
    date_added = _parse_date(raw.get("date added", ""))
    if not date_added:
        return None
    required = {
        "program": raw.get("program"),
        "status": raw.get("status"),
        "term": raw.get("term"),
        "us_or_international": raw.get("US/International"),
        "degree": raw.get("degree"),
    }
    if any(v is None for v in required.values()):
        return None
    return {
        "p_id": p_id,
        "date_added": date_added,
        "url": url,
        "comments": raw.get("comments"),
        **required,
    }


def get_watermark(cursor, source):
    """
    Read the last_seen value for source from ingestion_watermarks.

    :param cursor: An open database cursor.
    :type cursor: psycopg.Cursor
    :param source: The data source identifier.
    :type source: str
    :returns: The last-seen value, or None if no watermark exists yet.
    :rtype: str or None
    """
    cursor.execute(_SELECT_WATERMARK_SQL, (source,))
    row = cursor.fetchone()
    return row[0] if row else None


def set_watermark(cursor, source, last_seen):
    """
    Upsert the watermark for source to last_seen.

    :param cursor: An open database cursor.
    :type cursor: psycopg.Cursor
    :param source: The data source identifier.
    :type source: str
    :param last_seen: The new last-seen value to store.
    :type last_seen: str
    :returns: None.
    :rtype: None
    """
    cursor.execute(_UPSERT_WATERMARK_SQL, (source, last_seen))


def load_incremental(conn, seed_json_path, since=None):
    """
    Load records from seed_json_path whose p_id exceeds since (or the
    stored watermark when since is None). Inserts with ON CONFLICT
    (p_id) DO NOTHING for idempotence and advances the watermark after
    all inserts.

    :param conn: An open psycopg connection. The caller owns
        commit/rollback; this function does not commit.
    :type conn: psycopg.Connection
    :param seed_json_path: Path to the applicant data JSON file.
    :type seed_json_path: str or pathlib.Path
    :param since: Override the stored watermark with this value.
    :type since: str or None
    :returns: Number of newly inserted rows.
    :rtype: int
    """
    all_raw = json.loads(Path(seed_json_path).read_text(encoding="utf-8"))

    with conn.cursor() as cursor:
        if since is None:
            since = get_watermark(cursor, SEED_SOURCE)

        # Threshold of -1 means no watermark: load every valid record.
        threshold = int(since) if since is not None else -1

        new_rows = [
            row for raw in all_raw
            if (row := _build_row(raw)) is not None
            and row["p_id"] > threshold
        ]

        if not new_rows:
            return 0

        inserted = 0
        for row in new_rows:
            cursor.execute(_INSERT_SQL, row)
            inserted += cursor.rowcount

        max_p_id = str(max(r["p_id"] for r in new_rows))
        set_watermark(cursor, SEED_SOURCE, max_p_id)

    return inserted
