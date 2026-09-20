"""
`query_data.py`
Prints answers for Part 2: SQL Query Analysis. Run directly
(`python query_data.py --db_user <user> --db_password <password>`) to
print every answer; `analyze` can also be imported and called on its own.
"""
import argparse
from typing import Callable
import psycopg
from psycopg.rows import dict_row
from db_helpers import connect_db, disconnect_db, CONN_PARAMS


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
    return (f"PhD Computer Science at listed schools (LLM): {r['cnt_fall26_cs_phd_llm']}, "
            f"Difference: {r['llm_less_original']:+d}")


def _format_a1(rows):
    return ", ".join(f"{row['term']} acceptance: {row['pct_of_acceptances']}" for row in rows)


def _format_a2(rows):
    r = rows[0]
    return (f"USC average GPA accepted: {r['avg_gpa_accepted_usc']}, "
            f"USC average GPA not accepted: {r['avg_gpa_not_accepted_usc']}, "
            f"Difference: {r['gpa_diff']}")


QUESTION_QUERY = [
    (
        "Q1: How many entries in your database are from applicants who applied for Fall 2026?",
        """
        SELECT COUNT(*) AS cnt_fall26
        FROM applicants
        WHERE term = 'Fall 2026'
        """,
        _format_q1
    ),
    (
        "Q2: Among entries that provide a nationality classification, what "
        "percentage are international students?",
        """
        SELECT
            ROUND(
                SUM(
                    CASE WHEN us_or_international = 'International' THEN 1
                    ELSE 0
                    END
                ) * 100.0 / COUNT(us_or_international),
            2) || '%' AS pct_intl
        FROM applicants
        WHERE us_or_international IS NOT NULL
        """,
        _format_q2
    ),
    (
        "Q3: What are the average GPA, GRE Quantitative, GRE Verbal, and GRE "
        "Analytical Writing scores of applicants who provide each metric?",
        """
        WITH avg_gpa AS (
            SELECT ROUND(AVG(gpa)::numeric, 2) as avg_gpa
            FROM applicants
            WHERE gpa IS NOT NULL
        ),
        avg_gre AS (
            SELECT ROUND(AVG(gre)::numeric, 2) as avg_gre
            FROM applicants
            WHERE gre IS NOT NULL
        ),
        avg_gre_v AS (
            SELECT ROUND(AVG(gre_v)::numeric, 2) as avg_gre_v
            FROM applicants
            WHERE gre_v IS NOT NULL
        ),
        avg_gre_aw AS (
            SELECT ROUND(AVG(gre_aw)::numeric, 2) as avg_gre_aw
            FROM applicants
            WHERE gre_aw IS NOT NULL
        )
        SELECT *
        FROM avg_gpa, avg_gre, avg_gre_v, avg_gre_aw
        """,
        _format_q3
    ),
    (
        "Q4: What is the average GPA of American applicants who applied for Fall 2026?",
        """
        SELECT ROUND(AVG(gpa)::numeric, 2) as avg_gpa_us_fall26
        FROM applicants
        WHERE gpa IS NOT NULL
            AND us_or_international = 'American'
            AND term = 'Fall 2026'
        """,
        _format_q4
    ),
    (
        "Q5: What percentage of Fall 2025 entries are acceptances?",
        """
        SELECT
            ROUND(
                SUM(
                    CASE WHEN status ILIKE 'Accepted%' THEN 1
                    ELSE 0
                    END
                ) * 100.0 / COUNT(status),
            2) || '%' AS pct_accepted_fall25
        FROM applicants
        WHERE term = 'Fall 2025'
        """,
        _format_q5
    ),
    (
        "Q6: What is the average GPA of accepted applicants who applied for Fall 2026?",
        """
        SELECT
            ROUND(AVG(gpa)::numeric, 2) avg_gpa_accepted_fall26
        FROM applicants
        WHERE term = 'Fall 2026'
            AND gpa IS NOT NULL
            AND status ILIKE 'Accepted%'
        """,
        _format_q6
    ),
    (
        "Q7: How many entries are from applicants who applied to Johns Hopkins "
        "University for a master's degree in Computer Science?",
        """
        SELECT COUNT(*) AS cnt_jhu_ms_cs
        FROM applicants
        WHERE degree ILIKE 'Masters'
            AND program ILIKE 'Computer Science, %'
            AND (program ILIKE '%, Johns Hopkins University%'
                OR program ILIKE '%, JHU%')
        """,
        _format_q7
    ),
    (
        "Q8: How many Fall 2026 entries are acceptances from applicants applying "
        "for a PhD in Computer Science at one of the following universities? "
        "Georgetown University, Massachusetts Institute of Technology / MIT, "
        "Stanford University, Carnegie Mellon University",
        """
        SELECT COUNT(*) AS cnt_fall26_cs_phd
        FROM applicants
        WHERE term = 'Fall 2026'
            AND degree ILIKE 'PhD'
            AND status ILIKE 'Accepted%'
            AND program ILIKE 'Computer Science, %'
            AND (program ILIKE '%, Georgetown University'
                OR program ILIKE '%, Massachusetts Institute of Technology'
                OR program ILIKE '%, MIT'
                OR program ILIKE '%, Stanford University'
                OR program ILIKE '%, Carnegie Mellon University')
        """,
        _format_q8
    ),
    (
        "Q9: Repeat Question 8, but identify the university and program using "
        "llm_generated_program and llm_generated_university",
        """
        WITH q8 AS (
        SELECT COUNT(*) AS cnt
        FROM applicants
        WHERE term = 'Fall 2026'
            AND degree ILIKE 'PhD'
            AND status ILIKE 'Accepted%'
            AND program ILIKE 'Computer Science, %'
            AND (program ILIKE '%, Georgetown University'
                OR program ILIKE '%, Massachusetts Institute of Technology'
                OR program ILIKE '%, MIT'
                OR program ILIKE '%, Stanford University'
                OR program ILIKE '%, Carnegie Mellon University')
        ),
        q9 AS (
        SELECT COUNT(*) AS cnt
        FROM applicants
        WHERE term = 'Fall 2026'
            AND degree ILIKE 'PhD'
            AND status ILIKE 'Accepted%'
            AND llm_generated_program ILIKE 'Computer Science'
            AND (llm_generated_university ILIKE 'Georgetown University'
                OR llm_generated_university ILIKE 'Massachusetts Institute of Technology'
                OR llm_generated_university ILIKE 'MIT'
                OR llm_generated_university ILIKE 'Stanford University'
                OR llm_generated_university ILIKE 'Carnegie Mellon University')
        )
        SELECT q8.cnt AS cnt_fall26_cs_phd_original,
                q9.cnt AS cnt_fall26_cs_phd_llm,
                (q9.cnt - q8.cnt) AS llm_less_original
        FROM q8, q9
        """,
        _format_q9
    ),
    (
        "A1: What percentage of total acceptances come from each term found in the data?",
        """
        WITH accepted AS (
            SELECT term, COUNT(*) AS cnt
            FROM applicants
            WHERE status ILIKE 'Accepted%'
            GROUP BY term
        ),
        total_accepted AS (
            SELECT COUNT(*) AS cnt
            FROM applicants
            WHERE status ILIKE 'Accepted%'
        )
        SELECT accepted.term,
                ROUND(accepted.cnt * 100.0 / total_accepted.cnt, 2) || '%' AS pct_of_acceptances
        FROM accepted, total_accepted
        ORDER BY split_part(accepted.term, ' ', 2)::int,
                CASE WHEN accepted.term LIKE 'Spring%' THEN 0 ELSE 1 END
        """,
        _format_a1
    ),
    (
        "A2: What is the average GPA for students accepted to University of "
        "Southern California / USC, the average GPA for students not accepted "
        "there, and the difference in GPA?",
        """
        WITH usc AS (
            SELECT gpa, status
            FROM applicants
            WHERE gpa IS NOT NULL
                AND (program ILIKE '%, University of Southern California'
                    OR program ILIKE '%, USC')
        ),
        accepted_avg AS (
            SELECT ROUND(AVG(gpa)::numeric, 2) AS avg_gpa
            FROM usc
            WHERE status ILIKE 'Accepted%'
        ),
        not_accepted_avg AS (
            SELECT ROUND(AVG(gpa)::numeric, 2) AS avg_gpa
            FROM usc
            WHERE status NOT ILIKE 'Accepted%'
        )
        SELECT accepted_avg.avg_gpa AS avg_gpa_accepted_usc,
                not_accepted_avg.avg_gpa AS avg_gpa_not_accepted_usc,
                (accepted_avg.avg_gpa - not_accepted_avg.avg_gpa) AS gpa_diff
        FROM accepted_avg, not_accepted_avg
        """,
        _format_a2
    )
]


def analyze(question_query: list[tuple[str, str, Callable[[list[dict]], str]]], credentials: tuple[str, str]):
    """
    Takes a list of (question, query, format_result) tuples and a (user,
    password) credentials tuple, runs each query, and prints its answer
    using format_result. If a query fails, its error is printed in place
    of an answer and the remaining questions are still attempted instead
    of stopping the whole analysis.
    Returns none.
    """
    if len(question_query) == 0:
        print("No questions or queries submitted")
        return
    conn = connect_db(CONN_PARAMS, credentials)
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                for question, query, format_result in question_query:
                    try:
                        with conn.transaction():
                            cursor.execute(query)
                            print(format_result(cursor.fetchall()))
                    except psycopg.DatabaseError as error:
                        print(f"Could not run '{question}': {error}")
    finally:
        disconnect_db(conn)


def parse_args():
    """
    Parses CLI arguments for running the Part 2 SQL analysis directly.
    """
    parser = argparse.ArgumentParser(
        description="Run the Part 2 SQL analysis queries and print each answer."
    )
    parser.add_argument("--db_user", required=True, help="Database username.")
    parser.add_argument("--db_password", required=True, help="Database password.")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    analyze(QUESTION_QUERY, (cli_args.db_user, cli_args.db_password))
