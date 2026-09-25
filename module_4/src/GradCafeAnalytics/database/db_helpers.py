"""
`db_helpers.py`
Reusable functions for connecting to and disconnecting from PostgreSQL.
"""
import os
import re
import psycopg
from psycopg.rows import dict_row


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
    Connects to the PostgreSQL database described by database_url (a
    "postgresql://user:password@host:port/dbname" connection string).
    Returns the open connection, or None if the connection failed.
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
    Closes a database connection opened by connect_db.
    Returns none.
    """
    if conn is not None:
        conn.close()


def get_applicant(conn, p_id):
    """
    Queries a single row from the applicants table by its primary key.
    Returns a dict keyed by column name, or None if no row has that p_id.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT * FROM applicants WHERE p_id = %s", (p_id,))
        return cursor.fetchone()


def pretty_print_query(query):
    """
    Formats a SQL query so each clause or special keyword (SELECT, FROM,
    WHERE, GROUP BY, AND, etc.) starts its own line and is written in
    uppercase.
    Returns the formatted query string.
    """
    formatted = _SQL_KEYWORD_PATTERN.sub(lambda m: "\n" + m.group(0).upper(), query)
    lines = [line.strip() for line in formatted.splitlines() if line.strip()]
    return "\n".join(lines)