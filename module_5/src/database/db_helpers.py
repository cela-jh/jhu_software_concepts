"""
`db_helpers.py`
Reusable functions for connecting to and disconnecting from PostgreSQL,
plus the shared safety settings every query is built with: the table
identifier, the enforced row limit, and LIKE pattern escaping.
"""
import re
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

APPLICANTS_TABLE_NAME = "applicants"
# Quoted by psycopg wherever it is composed into SQL, never pasted as text.
APPLICANTS = sql.Identifier(APPLICANTS_TABLE_NAME)

# Every SELECT runs with LIMIT QUERY_LIMIT. The value is fixed in code
# rather than taken from a request, and clamp_limit() still keeps it
# inside [MIN_LIMIT, MAX_LIMIT] in case it is ever changed.
MIN_LIMIT = 1
MAX_LIMIT = 100
QUERY_LIMIT = 50

# Escape character for LIKE/ILIKE patterns built from user text.
LIKE_ESCAPE = "\\"


class DatabaseUnavailableError(Exception):
    """Raised when a connection to PostgreSQL cannot be opened."""


def clamp_limit(limit):
    """
    Keep a row limit inside [MIN_LIMIT, MAX_LIMIT].

    :param limit: The requested maximum number of rows.
    :type limit: int
    :returns: limit, raised to MIN_LIMIT or lowered to MAX_LIMIT if
        it falls outside that range.
    :rtype: int
    """
    return max(MIN_LIMIT, min(MAX_LIMIT, int(limit)))


def query_limit():
    """
    The enforced row limit every SELECT in this project runs with.

    :returns: QUERY_LIMIT, clamped to the allowed range.
    :rtype: int
    """
    return clamp_limit(QUERY_LIMIT)


def escape_like(text):
    """
    Escape LIKE/ILIKE wildcards so text only ever matches literally.
    The escape character itself is escaped first so an input ending in
    it cannot swallow the pattern's own trailing wildcard.

    :param text: Raw text to embed in a LIKE pattern.
    :type text: str
    :returns: text with the escape character, "%", and "_" escaped.
    :rtype: str
    """
    for special in (LIKE_ESCAPE, "%", "_"):
        text = text.replace(special, LIKE_ESCAPE + special)
    return text


SQL_CLAUSE_KEYWORDS = [
    "SELECT DISTINCT",
    "SELECT",
    "INSERT INTO",
    "DELETE FROM",
    "UPDATE",
    "VALUES",
    "SET",
    "FROM",
    "LEFT JOIN",
    "RIGHT JOIN",
    "INNER JOIN",
    "FULL JOIN",
    "JOIN",
    "ON",
    "WHERE",
    "GROUP BY",
    "ORDER BY",
    "HAVING",
    "LIMIT",
    "OFFSET",
    "UNION ALL",
    "UNION",
    "AND",
    "OR",
]

_SQL_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(r"\s+".join(re.escape(word) for word in keyword.split())
                       for keyword in SQL_CLAUSE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def connect_db(database_url: str):
    """
    Connect to the PostgreSQL database described by database_url.

    :param database_url: A "postgresql://user:password@host:port/dbname"
        connection string.
    :type database_url: str
    :returns: The open connection, or None if the connection failed.
    :rtype: psycopg.Connection or None
    """
    try:
        return psycopg.connect(database_url)
    except psycopg.DatabaseError as error:
        print(f"Could not connect to the database. Check DATABASE_URL "
              f"(database name, host, port, username, and password) and "
              f"try again. Details: {error}")
        return None


def disconnect_db(conn):
    """
    Close a database connection opened by connect_db.

    :param conn: The connection to close, or None.
    :type conn: psycopg.Connection or None
    :returns: None.
    :rtype: None
    """
    if conn is not None:
        conn.close()


def get_applicant(conn, p_id):
    """
    Query a single row from the applicants table by its primary key.

    :param conn: An open database connection.
    :type conn: psycopg.Connection
    :param p_id: The applicant's primary key.
    :type p_id: int
    :returns: A dict keyed by column name, or None if no row has that p_id.
    :rtype: dict or None
    """
    # p_id is the primary key, so at most one row can match
    stmt = sql.SQL("SELECT * FROM {table} WHERE {p_id} = %s LIMIT 1").format(
        table=APPLICANTS, p_id=sql.Identifier("p_id"),
    )
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(stmt, (p_id,))
        return cursor.fetchone()


def pretty_print_query(query):
    """
    Format a SQL query so each clause or special keyword (SELECT, FROM,
    WHERE, GROUP BY, AND, etc.) starts its own line and is written in
    uppercase.

    :param query: The SQL query to format.
    :type query: str
    :returns: The formatted query string.
    :rtype: str
    """
    formatted = _SQL_KEYWORD_PATTERN.sub(lambda m: "\n" + m.group(0).upper(), query)
    lines = [line.strip() for line in formatted.splitlines() if line.strip()]
    return "\n".join(lines)
