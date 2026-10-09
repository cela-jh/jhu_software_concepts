"""
`query_data.py`
Prints answers for Part 2: SQL Query Analysis. Run from src/ as a module
(`python -m database.query_data`, with the DB_* variables set) to print every
answer; `analyze` can also be imported and called on its own.

Every statement here is composed with psycopg's sql module: the table is
inserted with sql.Identifier, and every value (filter patterns, the
user's school name, the row limit) is passed separately as a bound
parameter at execution time, never written into the SQL text.
"""
import sys
from typing import Callable, NamedTuple
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from database.db_helpers import (
    APPLICANTS, LIKE_ESCAPE, DatabaseConfigError, DatabaseUnavailableError,
    connect_db, database_url_from_env, disconnect_db, escape_like, load_env_file,
    query_limit,
)

# Filter values shared by the SQL here and the ORM in orm_queries.py.
ACCEPTED_PATTERN = "Accepted%"
LISTED_UNIVERSITIES = [
    "Georgetown University",
    "Massachusetts Institute of Technology",
    "MIT",
    "Stanford University",
    "Carnegie Mellon University",
]
USC_NAMES = ["University of Southern California", "USC"]

# A3: accepted results from these term years onward, at a school whose
# name contains the user's text.
DEFAULT_SCHOOL = "University of Southern California"
ACCEPTED_SINCE_YEAR = 2024
MAX_SCHOOL_LENGTH = 100
# Program is stored as "Program, School"; stripping everything through
# the last ", " leaves the school.
SCHOOL_PREFIX_PATTERN = "^.*, "
# The four-digit year at the end of a term such as "Fall 2025". A term
# without one yields NULL instead of a cast error.
TERM_YEAR_PATTERN = r"(\d{4})$"
SPRING_PATTERN = "Spring%"
# A1 only counts terms with both a season and a year, such as "Fall 2026";
# matched case-insensitively.
VALID_TERM_PATTERN = r"^(Spring|Summer|Fall|Winter) \d{4}$"
NO_ACCEPTED_RESULTS = "No accepted results found."


class Query(NamedTuple):
    """A composed SQL statement and the parameters bound to it when run."""
    statement: sql.Composed
    params: dict


class InvalidSchoolInput(ValueError):
    """Raised when a user-supplied school name fails validation."""


def _limited_query(select_text, **params):
    """
    Compose a SELECT whose text refers to the table as {table}, and
    append the enforced LIMIT as a bound parameter.

    :param select_text: The SELECT statement text, without a LIMIT.
    :type select_text: str
    :param params: Values for the statement's named placeholders.
    :returns: The composed statement and its parameters, including the
        limit.
    :rtype: Query
    """
    statement = (
        sql.SQL(select_text).format(table=APPLICANTS)
        + sql.SQL(" LIMIT %(limit)s")
    )
    return Query(statement, {**params, "limit": query_limit()})


def _format_q1(rows):
    return f"Applicant count: {rows[0]['cnt_fall26']}"


def _format_q2(rows):
    return f"International percentage: {rows[0]['pct_intl']}"


def _format_q3(rows):
    r = rows[0]
    return (f"Average GPA: {r['avg_gpa']}, Average GRE: {r['avg_gre']}, "
            f"Average GRE V: {r['avg_gre_v']}, Average GRE AW: {r['avg_gre_aw']}")


def _format_q4(rows):
    return f"Average GPA American: {rows[0]['avg_gpa_us_fall26']}"


def _format_q5(rows):
    return f"Percentage accepted: {rows[0]['pct_accepted_fall25']}"


def _format_q6(rows):
    return f"Average GPA accepted: {rows[0]['avg_gpa_accepted_fall26']}"


def _format_q7(rows):
    return f"JHU Masters Computer Science count: {rows[0]['cnt_jhu_ms_cs']}"


def _format_q8(rows):
    return f"PhD Computer Science at listed schools: {rows[0]['cnt_fall26_cs_phd']}"


def _format_q9(rows):
    r = rows[0]
    return (f"PhD Computer Science at listed schools: {r['cnt_fall26_cs_phd_original']}, "
            f"PhD Computer Science at listed schools (LLM): {r['cnt_fall26_cs_phd_llm']}, "
            f"Difference: {r['llm_less_original']:+d}")


def _format_a1(rows):
    return ", ".join(f"{row['term']} acceptance: {row['pct_of_acceptances']}" for row in rows)


def _format_a2(rows):
    r = rows[0]
    return (f"USC average GPA accepted: {r['avg_gpa_accepted_usc']}, "
            f"USC average GPA not accepted: {r['avg_gpa_not_accepted_usc']}, "
            f"Difference: {r['gpa_diff']}")


# "%, School" patterns matching the school part of the program field.
_LISTED_SCHOOL_PATTERNS = [f"%, {name}" for name in LISTED_UNIVERSITIES]
_USC_PATTERNS = [f"%, {name}" for name in USC_NAMES]

QUESTION_QUERY = [
    (
        "Q1: How many entries in your database are from applicants who applied for Fall 2026?",
        _limited_query(
            """
            SELECT COUNT(*) AS cnt_fall26
            FROM {table}
            WHERE term ILIKE %(term)s
            """,
            term="Fall 2026",
        ),
        _format_q1
    ),
    (
        "Q2: Among entries that provide a nationality classification, what "
        "percentage are international students?",
        _limited_query(
            """
            SELECT
                ROUND(
                    SUM(
                        CASE WHEN us_or_international ILIKE %(international)s THEN 1
                        ELSE 0
                        END
                    ) * 100.0 / COUNT(*),
                2) || '%%' AS pct_intl
            FROM {table}
            WHERE us_or_international IS NOT NULL
                AND us_or_international != ''
            """,
            international="International",
        ),
        _format_q2
    ),
    (
        "Q3: What are the average GPA, GRE Quantitative, GRE Verbal, and GRE "
        "Analytical Writing scores of applicants who provide each metric?",
        _limited_query(
            """
            WITH avg_gpa AS (
                SELECT ROUND(AVG(gpa)::numeric, 2) as avg_gpa
                FROM {table}
                WHERE gpa IS NOT NULL
            ),
            avg_gre AS (
                SELECT ROUND(AVG(gre)::numeric, 2) as avg_gre
                FROM {table}
                WHERE gre IS NOT NULL
            ),
            avg_gre_v AS (
                SELECT ROUND(AVG(gre_v)::numeric, 2) as avg_gre_v
                FROM {table}
                WHERE gre_v IS NOT NULL
            ),
            avg_gre_aw AS (
                SELECT ROUND(AVG(gre_aw)::numeric, 2) as avg_gre_aw
                FROM {table}
                WHERE gre_aw IS NOT NULL
            )
            SELECT *
            FROM avg_gpa, avg_gre, avg_gre_v, avg_gre_aw
            """,
        ),
        _format_q3
    ),
    (
        "Q4: What is the average GPA of American applicants who applied for Fall 2026?",
        _limited_query(
            """
            SELECT ROUND(AVG(gpa)::numeric, 2) as avg_gpa_us_fall26
            FROM {table}
            WHERE gpa IS NOT NULL
                AND us_or_international ILIKE %(american)s
                AND term ILIKE %(term)s
            """,
            american="American", term="Fall 2026",
        ),
        _format_q4
    ),
    (
        "Q5: What percentage of Fall 2025 entries are acceptances?",
        _limited_query(
            """
            SELECT
                ROUND(
                    SUM(
                        CASE WHEN status ILIKE %(accepted)s THEN 1
                        ELSE 0
                        END
                    ) * 100.0 / COUNT(*),
                2) || '%%' AS pct_accepted_fall25
            FROM {table}
            WHERE term ILIKE %(term)s
            """,
            accepted=ACCEPTED_PATTERN, term="Fall 2025",
        ),
        _format_q5
    ),
    (
        "Q6: What is the average GPA of accepted applicants who applied for Fall 2026?",
        _limited_query(
            """
            SELECT
                ROUND(AVG(gpa)::numeric, 2) avg_gpa_accepted_fall26
            FROM {table}
            WHERE term ILIKE %(term)s
                AND gpa IS NOT NULL
                AND status ILIKE %(accepted)s
            """,
            term="Fall 2026", accepted=ACCEPTED_PATTERN,
        ),
        _format_q6
    ),
    (
        "Q7: How many entries are from applicants who applied to Johns Hopkins "
        "University for a master's degree in Computer Science?",
        _limited_query(
            """
            SELECT COUNT(*) AS cnt_jhu_ms_cs
            FROM {table}
            WHERE degree ILIKE %(degree)s
                AND program ILIKE %(program)s
                AND program ILIKE ANY(%(schools)s)
            """,
            degree="Masters", program="Computer Science, %",
            schools=["%, Johns Hopkins University%", "%, JHU%"],
        ),
        _format_q7
    ),
    (
        "Q8: How many Fall 2026 entries are acceptances from applicants applying "
        "for a PhD in Computer Science at one of the following universities? "
        "Georgetown University, Massachusetts Institute of Technology / MIT, "
        "Stanford University, Carnegie Mellon University",
        _limited_query(
            """
            SELECT COUNT(*) AS cnt_fall26_cs_phd
            FROM {table}
            WHERE term ILIKE %(term)s
                AND degree ILIKE %(degree)s
                AND status ILIKE %(accepted)s
                AND program ILIKE %(program)s
                AND program ILIKE ANY(%(schools)s)
            """,
            term="Fall 2026", degree="PhD", accepted=ACCEPTED_PATTERN,
            program="Computer Science, %", schools=_LISTED_SCHOOL_PATTERNS,
        ),
        _format_q8
    ),
    (
        "Q9: Repeat Question 8, but identify the university and program using "
        "llm_generated_program and llm_generated_university",
        _limited_query(
            """
            WITH q8 AS (
            SELECT COUNT(*) AS cnt
            FROM {table}
            WHERE term ILIKE %(term)s
                AND degree ILIKE %(degree)s
                AND status ILIKE %(accepted)s
                AND program ILIKE %(program)s
                AND program ILIKE ANY(%(schools)s)
            ),
            q9 AS (
            SELECT COUNT(*) AS cnt
            FROM {table}
            WHERE term ILIKE %(term)s
                AND degree ILIKE %(degree)s
                AND status ILIKE %(accepted)s
                AND llm_generated_program ILIKE %(llm_program)s
                AND llm_generated_university ILIKE ANY(%(llm_schools)s)
            )
            SELECT q8.cnt AS cnt_fall26_cs_phd_original,
                    q9.cnt AS cnt_fall26_cs_phd_llm,
                    (q9.cnt - q8.cnt) AS llm_less_original
            FROM q8, q9
            """,
            term="Fall 2026", degree="PhD", accepted=ACCEPTED_PATTERN,
            program="Computer Science, %", schools=_LISTED_SCHOOL_PATTERNS,
            llm_program="Computer Science", llm_schools=LISTED_UNIVERSITIES,
        ),
        _format_q9
    ),
    (
        "A1: What percentage of total acceptances come from each term found in the data?",
        _limited_query(
            """
            WITH accepted AS (
                SELECT term, COUNT(*) AS cnt
                FROM {table}
                WHERE status ILIKE %(accepted)s
                    AND term ~* %(valid_term)s
                GROUP BY term
            ),
            total_accepted AS (
                SELECT COUNT(*) AS cnt
                FROM {table}
                WHERE status ILIKE %(accepted)s
                    AND term ~* %(valid_term)s
            )
            SELECT accepted.term,
                    ROUND(accepted.cnt * 100.0 / total_accepted.cnt, 2) || '%%'
                        AS pct_of_acceptances
            FROM accepted, total_accepted
            ORDER BY substring(accepted.term from %(year_pattern)s)::int,
                    CASE WHEN accepted.term ILIKE %(spring)s THEN 0 ELSE 1 END
            """,
            accepted=ACCEPTED_PATTERN, valid_term=VALID_TERM_PATTERN,
            year_pattern=TERM_YEAR_PATTERN, spring=SPRING_PATTERN,
        ),
        _format_a1
    ),
    (
        "A2: What is the average GPA for students accepted to University of "
        "Southern California / USC, the average GPA for students not accepted "
        "there, and the difference in GPA?",
        _limited_query(
            """
            WITH usc AS (
                SELECT gpa, status
                FROM {table}
                WHERE gpa IS NOT NULL
                    AND program ILIKE ANY(%(schools)s)
            ),
            accepted_avg AS (
                SELECT ROUND(AVG(gpa)::numeric, 2) AS avg_gpa
                FROM usc
                WHERE status ILIKE %(accepted)s
            ),
            not_accepted_avg AS (
                SELECT ROUND(AVG(gpa)::numeric, 2) AS avg_gpa
                FROM usc
                WHERE status NOT ILIKE %(accepted)s
            )
            SELECT accepted_avg.avg_gpa AS avg_gpa_accepted_usc,
                    not_accepted_avg.avg_gpa AS avg_gpa_not_accepted_usc,
                    (accepted_avg.avg_gpa - not_accepted_avg.avg_gpa) AS gpa_diff
            FROM accepted_avg, not_accepted_avg
            """,
            schools=_USC_PATTERNS, accepted=ACCEPTED_PATTERN,
        ),
        _format_a2
    )
]


ACCEPTED_SINCE_QUESTION = (
    f"A3: Which accepted results from {ACCEPTED_SINCE_YEAR} terms onward are "
    f"at a school whose name contains the text below? (Defaults to "
    f"{DEFAULT_SCHOOL}; shows up to {query_limit()} results, newest first.)"
)


def normalize_school(raw_school):
    """
    Validate a user-supplied school name for A3. Whitespace runs are
    collapsed, and a blank value falls back to DEFAULT_SCHOOL.

    :param raw_school: The school name as typed, or None if absent.
    :type raw_school: str or None
    :raises InvalidSchoolInput: If the name is longer than
        MAX_SCHOOL_LENGTH or contains non-printable characters (such as
        a NUL byte, which PostgreSQL text cannot store).
    :returns: The cleaned school name.
    :rtype: str
    """
    school = " ".join((raw_school or "").split())
    if not school:
        return DEFAULT_SCHOOL
    if len(school) > MAX_SCHOOL_LENGTH:
        raise InvalidSchoolInput(
            f"School name must be at most {MAX_SCHOOL_LENGTH} characters."
        )
    if not school.isprintable():
        raise InvalidSchoolInput("School name contains characters that are not allowed.")
    return school


def build_accepted_since_query(school):
    """
    Compose A3's statement for one school. The school is matched as a
    literal substring of the school part of `program`: it is bound as a
    parameter, and any LIKE wildcards in it are escaped first.

    :param school: A school name already cleaned by normalize_school().
    :type school: str
    :returns: The composed statement and its parameters.
    :rtype: Query
    """
    columns = ("program", "degree", "term", "status", "gpa", "date_added", "p_id")
    statement = sql.SQL(
        """
        SELECT {program}, {degree}, {term}, {status}, {gpa}
        FROM {table}
        WHERE {status} ILIKE %(accepted)s
            AND substring({term} from %(year_pattern)s)::int >= %(since_year)s
            AND regexp_replace({program}, %(school_prefix)s, '')
                ILIKE %(school)s ESCAPE %(escape)s
        ORDER BY {date_added} DESC, {p_id} DESC
        LIMIT %(limit)s
        """
    ).format(table=APPLICANTS, **{name: sql.Identifier(name) for name in columns})
    params = {
        "accepted": ACCEPTED_PATTERN,
        "year_pattern": TERM_YEAR_PATTERN,
        "since_year": ACCEPTED_SINCE_YEAR,
        "school_prefix": SCHOOL_PREFIX_PATTERN,
        "school": f"%{escape_like(school)}%",
        "escape": LIKE_ESCAPE,
        "limit": query_limit(),
    }
    return Query(statement, params)


def format_accepted_row(row):
    """
    Render one A3 result row as a single line of text.

    :param row: A result with program, degree, term, status, and gpa.
    :type row: Mapping
    :returns: The formatted line.
    :rtype: str
    """
    gpa = row["gpa"] if row["gpa"] is not None else "N/A"
    return f"{row['program']} | {row['degree']} | {row['term']} | {row['status']} | GPA: {gpa}"


def fetch_accepted_since(database_url, school):
    """
    Run A3 for one school and return its formatted result lines.

    :param database_url: A "postgresql://user:password@host:port/dbname"
        connection string.
    :type database_url: str
    :param school: A school name already cleaned by normalize_school().
    :type school: str
    :raises DatabaseUnavailableError: If PostgreSQL can't be reached.
    :returns: One formatted line per matching result, at most
        query_limit() lines.
    :rtype: list[str]
    """
    query = build_accepted_since_query(school)
    conn = connect_db(database_url)
    if conn is None:
        raise DatabaseUnavailableError("Could not connect to the database.")
    try:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query.statement, query.params)
            return [format_accepted_row(row) for row in cursor.fetchall()]
    finally:
        disconnect_db(conn)


def _format_a3(rows):
    return "\n".join(format_accepted_row(row) for row in rows) or NO_ACCEPTED_RESULTS


# The CLI prints every Part 2 answer, then A3 for the default school.
CLI_QUESTION_QUERY = QUESTION_QUERY + [
    (ACCEPTED_SINCE_QUESTION, build_accepted_since_query(DEFAULT_SCHOOL), _format_a3),
]


def analyze(question_query: list[tuple[str, Query, Callable[[list[dict]], str]]],
            database_url: str):
    """
    Run each (question, query, format_result) tuple's query and print
    its answer using format_result. If a query fails, its error is
    printed in place of an answer and the remaining questions are still
    attempted instead of stopping the whole analysis.

    :param question_query: A list of (question, composed query, result
        formatter) tuples.
    :type question_query: list[tuple(str, Query, Callable[[list[dict]], str])]
    :param database_url: A "postgresql://user:password@host:port/dbname"
        connection string.
    :type database_url: str
    :returns: None.
    :rtype: None
    """
    if len(question_query) == 0:
        print("No questions or queries submitted")
        return
    conn = connect_db(database_url)
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                for question, query, format_result in question_query:
                    try:
                        # statement and values travel separately; psycopg
                        # binds params server side, never into the text
                        with conn.transaction():
                            cursor.execute(query.statement, query.params)
                            print(format_result(cursor.fetchall()))
                    except psycopg.DatabaseError as error:
                        print(f"Could not run '{question}': {error}")
    finally:
        disconnect_db(conn)


if __name__ == "__main__":
    load_env_file()
    try:
        analyze(CLI_QUESTION_QUERY, database_url_from_env())
    except DatabaseConfigError as error:
        print(error)
        sys.exit(1)
