"""
`query_data.py`
SQL query definitions for the worker's analytics recompute handler.
Every statement is composed with psycopg's sql module: the table is
inserted with sql.Identifier, and all values are bound parameters.

This module intentionally omits connection management; the consumer
passes an open psycopg connection into each handler.
"""
from typing import NamedTuple

from psycopg import sql
from psycopg.rows import dict_row

# Constants inlined from db_helpers to keep the worker self-contained.
APPLICANTS_TABLE_NAME = "applicants"
APPLICANTS = sql.Identifier(APPLICANTS_TABLE_NAME)
LIKE_ESCAPE = "\\"

MIN_LIMIT = 1
MAX_LIMIT = 100
QUERY_LIMIT = 50

# Filter values shared by the SQL here.
ACCEPTED_PATTERN = "Accepted%"
LISTED_UNIVERSITIES = [
    "Georgetown University",
    "Massachusetts Institute of Technology",
    "MIT",
    "Stanford University",
    "Carnegie Mellon University",
]
USC_NAMES = ["University of Southern California", "USC"]

DEFAULT_SCHOOL = "University of Southern California"
ACCEPTED_SINCE_YEAR = 2024
MAX_SCHOOL_LENGTH = 100
SCHOOL_PREFIX_PATTERN = "^.*, "
TERM_YEAR_PATTERN = r"(\d{4})$"
SPRING_PATTERN = "Spring%"
VALID_TERM_PATTERN = r"^(Spring|Summer|Fall|Winter) \d{4}$"
NO_ACCEPTED_RESULTS = "No accepted results found."


class Query(NamedTuple):
    """A composed SQL statement and the parameters bound to it when run."""
    statement: sql.Composed
    params: dict


def clamp_limit(limit):
    """
    Keep a row limit inside [MIN_LIMIT, MAX_LIMIT].

    :param limit: The requested maximum number of rows.
    :type limit: int
    :returns: The clamped limit.
    :rtype: int
    """
    return max(MIN_LIMIT, min(MAX_LIMIT, int(limit)))


def query_limit():
    """
    The enforced row limit every SELECT in this module runs with.

    :returns: QUERY_LIMIT, clamped to the allowed range.
    :rtype: int
    """
    return clamp_limit(QUERY_LIMIT)


def escape_like(text):
    """
    Escape LIKE/ILIKE wildcards so text only ever matches literally.

    :param text: Raw text to embed in a LIKE pattern.
    :type text: str
    :returns: text with the escape character, "%", and "_" escaped.
    :rtype: str
    """
    for special in (LIKE_ESCAPE, "%", "_"):
        text = text.replace(special, LIKE_ESCAPE + special)
    return text


def _limited_query(select_text, **params):
    """
    Compose a SELECT whose text refers to the table as {table}, and
    append the enforced LIMIT as a bound parameter.

    :param select_text: The SELECT statement text, without a LIMIT.
    :type select_text: str
    :param params: Values for the statement's named placeholders.
    :returns: The composed statement and its parameters, including the limit.
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
    ),
]


def run_analytics(conn):
    """
    Execute every analytics query against the open connection and return
    a list of formatted answer strings.

    :param conn: An open psycopg connection. The caller owns commit/rollback.
    :type conn: psycopg.Connection
    :returns: One formatted answer string per question.
    :rtype: list[str]
    """
    answers = []
    with conn.cursor(row_factory=dict_row) as cursor:
        for _, query, format_result in QUESTION_QUERY:
            cursor.execute(query.statement, query.params)
            answers.append(format_result(cursor.fetchall()))
    return answers
