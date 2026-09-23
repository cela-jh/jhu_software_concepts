"""
`db_helpers.py`
Reusable functions for connecting to and disconnecting from PostgreSQL.
"""
import psycopg
import re

CONN_PARAMS = {
    "dbname": "cam_db",
    "host": "localhost",
    "port": 5432
}


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


def connect_db(conn_params: dict, credentials: tuple[str, str]):
    """
    Connects to the PostgreSQL database described by conn_params.
    Returns the open connection, or None if the connection failed.
    """
    user, password = credentials
    try:
        return psycopg.connect(
            dbname=conn_params["dbname"],
            user=user,
            password=password,
            host=conn_params["host"],
            port=conn_params["port"]
        )
    except psycopg.DatabaseError as error:
        print(f"Could not connect to the database. Check the database name, "
              f"host, port, username, and password and try again. Details: {error}")
        return None


def disconnect_db(conn):
    """
    Closes a database connection opened by connect_db.
    Returns none.
    """
    if conn is not None:
        conn.close()


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