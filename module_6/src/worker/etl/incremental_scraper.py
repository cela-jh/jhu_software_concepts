"""
`incremental_scraper.py`
Watermark-based loader: reads applicant records from the seed JSON file
and inserts only those newer than the last-seen watermark stored in the
ingestion_watermarks table. Implemented in Section 4.
"""

WATERMARKS_TABLE = "ingestion_watermarks"
SEED_SOURCE = "applicant_data_json"


def get_watermark(cursor, source):
    """
    Read the last_seen value for source from ingestion_watermarks.
    Returns None if no watermark exists yet.

    :param cursor: An open database cursor.
    :type cursor: psycopg.Cursor
    :param source: The data source identifier.
    :type source: str
    :returns: The last-seen value, or None.
    :rtype: str or None
    """
    raise NotImplementedError("get_watermark will be implemented in Section 4")


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
    raise NotImplementedError("set_watermark will be implemented in Section 4")


def load_incremental(conn, seed_json_path, since=None):
    """
    Load records from seed_json_path that are newer than since (or the
    stored watermark when since is None). Inserts with ON CONFLICT DO
    NOTHING for idempotence and advances the watermark after a
    successful commit.

    :param conn: An open psycopg connection. Caller owns the transaction.
    :type conn: psycopg.Connection
    :param seed_json_path: Path to the applicant data JSON file.
    :type seed_json_path: str or pathlib.Path
    :param since: Override the stored watermark with this value.
    :type since: str or None
    :returns: Number of newly inserted rows.
    :rtype: int
    """
    raise NotImplementedError("load_incremental will be implemented in Section 4")
