"""
`db_connection.py`
Reusable functions for connecting to and disconnecting from PostgreSQL.
"""
import psycopg

CONN_PARAMS = {
    "dbname": "cam_db",
    "host": "localhost",
    "port": 5432
}


def connect_db(conn_params: dict, user: str, password: str):
    """
    Connects to the PostgreSQL database described by conn_params.
    Returns the open connection, or None if the connection failed.
    """
    try:
        return psycopg.connect(
            dbname=conn_params["dbname"],
            user=user,
            password=password,
            host=conn_params["host"],
            port=conn_params["port"]
        )
    except psycopg.DatabaseError as error:
        print(f"Could not connect to the database. Check the host, username, "
              f"and password and try again. Details: {error}")
        return None


def disconnect_db(conn):
    """
    Closes a database connection opened by connect_db.
    Returns none.
    """
    if conn is not None:
        conn.close()


def test_connection_db(conn_params: dict, user: str, password: str):
    """
    Tests connectivity to the database described by conn_params.
    Returns a list of table names in the public schema, or an empty list
    if the connection failed.
    """
    conn = connect_db(conn_params, user, password)
    if conn is None:
        return []

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_user;")
            print(f"Connected as: {cursor.fetchone()[0]}")

            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public';"
            )
            return [row[0] for row in cursor.fetchall()]
    finally:
        disconnect_db(conn)
