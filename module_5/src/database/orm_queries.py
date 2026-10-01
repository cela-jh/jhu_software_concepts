"""
`orm_queries.py`
Repeats a subset of the Part 2 SQL analysis using the SQLAlchemy ORM
instead of handwritten SQL. Run from src/ as a module
(`python -m database.orm_queries`, with DATABASE_URL set) to print every
answer.
"""
# SQLAlchemy builds func.<name> SQL functions dynamically at runtime, so
# static analysis cannot see that func.count is callable.
# pylint: disable=not-callable
import os
import sys

from sqlalchemy import Integer, Numeric, and_, case, cast, func, or_, select

from database.db_helpers import LIKE_ESCAPE, escape_like, query_limit
from database.models import Applicant, get_session
from database.query_data import (
    ACCEPTED_PATTERN, ACCEPTED_SINCE_YEAR, LISTED_UNIVERSITIES,
    SCHOOL_PREFIX_PATTERN, SPRING_PATTERN, TERM_YEAR_PATTERN, USC_NAMES,
    VALID_TERM_PATTERN, format_accepted_row,
)


def _limited(statement):
    """
    Apply the enforced row limit to a SELECT. SQLAlchemy sends the
    limit value as a bound parameter.

    :param statement: The SELECT to limit.
    :type statement: sqlalchemy.sql.Select
    :returns: The same SELECT with LIMIT query_limit().
    :rtype: sqlalchemy.sql.Select
    """
    return statement.limit(query_limit())


def _scalar(session, statement):
    """
    Run a single-value SELECT with the enforced row limit applied.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :param statement: A SELECT returning exactly one row and column.
    :type statement: sqlalchemy.sql.Select
    :returns: The single value.
    :rtype: object
    """
    return session.execute(_limited(statement)).scalar_one()


def _term_year():
    """
    The four-digit year at the end of a term such as "Fall 2025", as an
    integer, or NULL for a term without one, so malformed scraped terms
    never raise a cast error.

    :returns: The year expression.
    :rtype: sqlalchemy.sql.expression.ColumnElement
    """
    return cast(func.substring(Applicant.term, TERM_YEAR_PATTERN), Integer)


def _round2(expr):
    """
    Round a SQL expression to 2 decimal places via a numeric cast.

    :param expr: The SQL expression to round.
    :type expr: sqlalchemy.sql.expression.ColumnElement
    :returns: The rounded expression.
    :rtype: sqlalchemy.sql.expression.ColumnElement
    """
    return func.round(cast(expr, Numeric), 2)


def _or_na(value):
    """
    Render a possibly-missing value (e.g. an AVG() over zero matching
    rows, which SQL returns as NULL) as "N/A" instead of the literal
    text "None".

    :param value: The value to render.
    :type value: object or None
    :returns: value, or "N/A" if value is None.
    :rtype: object or str
    """
    return value if value is not None else "N/A"


def _format_percentage(value):
    """
    Format a percentage value with exactly two decimal places (e.g. 50
    becomes "50.00%", not "50.0%" or "50%"), regardless of whether it
    arrived as a Decimal from SQL-side rounding or a plain Python float.

    :param value: The percentage value, or None if there were no
        matching rows to compute a percentage from (SQL SUM()/AVG()
        over zero rows is NULL).
    :type value: decimal.Decimal or float or None
    :returns: The formatted percentage, or "N/A" if value is None.
    :rtype: str
    """
    if value is None:
        return "N/A"
    return f"{float(value):.2f}%"


def orm_q1(session):
    """
    How many entries are from applicants who applied for Fall 2026?

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    count = _scalar(session, select(func.count())
                    .select_from(Applicant)
                    .where(Applicant.term.ilike("Fall 2026")))
    return f"Applicant count: {count}"


def orm_q2(session):
    """
    Percentage of entries with a usable nationality classification that
    are international.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    usable = and_(
        Applicant.us_or_international.is_not(None),
        Applicant.us_or_international != "",
    )
    international = case((Applicant.us_or_international.ilike("International"), 1), else_=0)
    pct = _scalar(session, select(_round2(func.sum(international) * 100.0 / func.count()))
                  .where(usable))
    return f"International percentage: {_format_percentage(pct)}"


def _average(session, column):
    """
    Average of a score column over rows that have a value, rounded to 2
    decimal places.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :param column: The mapped score column.
    :type column: sqlalchemy.orm.InstrumentedAttribute
    :returns: The rounded average, or None if no row has a value.
    :rtype: decimal.Decimal or None
    """
    return _scalar(session, select(_round2(func.avg(column))).where(column.is_not(None)))


def orm_q3(session):
    """
    Average GPA, GRE Quantitative, GRE Verbal, and GRE Analytical
    Writing scores.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    avg_gpa = _average(session, Applicant.gpa)
    avg_gre = _average(session, Applicant.gre)
    avg_gre_v = _average(session, Applicant.gre_v)
    avg_gre_aw = _average(session, Applicant.gre_aw)
    return (f"Average GPA: {_or_na(avg_gpa)}, Average GRE: {_or_na(avg_gre)}, "
            f"Average GRE V: {_or_na(avg_gre_v)}, Average GRE AW: {_or_na(avg_gre_aw)}")


def orm_q4(session):
    """
    Average GPA of American applicants who applied for Fall 2026.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    avg_gpa = _scalar(session, select(_round2(func.avg(Applicant.gpa))).where(
        and_(
            Applicant.gpa.is_not(None),
            Applicant.us_or_international.ilike("American"),
            Applicant.term.ilike("Fall 2026"),
        )
    ))
    return f"Average GPA American: {_or_na(avg_gpa)}"


def orm_q5(session):
    """
    Percentage of Fall 2025 entries that are acceptances.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    accepted = case((Applicant.status.ilike(ACCEPTED_PATTERN), 1), else_=0)
    # The denominator counts every Fall 2025 row via count(), not
    # count(status), so a NULL-status row is still counted (it just
    # never contributes to the numerator via the CASE above).
    pct = _scalar(session, select(_round2(func.sum(accepted) * 100.0 / func.count()))
                  .where(Applicant.term.ilike("Fall 2025")))
    return f"Percentage accepted: {_format_percentage(pct)}"


def orm_q6(session):
    """
    Average GPA of accepted applicants who applied for Fall 2026.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    avg_gpa = _scalar(session, select(_round2(func.avg(Applicant.gpa))).where(
        and_(
            Applicant.term.ilike("Fall 2026"),
            Applicant.gpa.is_not(None),
            Applicant.status.ilike(ACCEPTED_PATTERN),
        )
    ))
    return f"Average GPA accepted: {_or_na(avg_gpa)}"


def orm_q7(session):
    """
    Count of Johns Hopkins University master's Computer Science entries.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    count = _scalar(session, select(func.count()).select_from(Applicant).where(
        and_(
            Applicant.degree.ilike("Masters"),
            Applicant.program.ilike("Computer Science, %"),
            or_(
                Applicant.program.ilike("%, Johns Hopkins University%"),
                Applicant.program.ilike("%, JHU%"),
            ),
        )
    ))
    return f"JHU Masters Computer Science count: {count}"


def _q8_count(session):
    """
    Fall 2026 PhD Computer Science acceptances at the listed
    universities, by raw program text.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The matching row count.
    :rtype: int
    """
    university_match = or_(*(Applicant.program.ilike(f"%, {u}") for u in LISTED_UNIVERSITIES))
    return _scalar(session, select(func.count()).select_from(Applicant).where(
        and_(
            Applicant.term.ilike("Fall 2026"),
            Applicant.degree.ilike("PhD"),
            Applicant.status.ilike(ACCEPTED_PATTERN),
            Applicant.program.ilike("Computer Science, %"),
            university_match,
        )
    ))


def orm_q8(session):
    """
    How many Fall 2026 entries are PhD Computer Science acceptances at
    the listed universities?

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    return f"PhD Computer Science at listed schools: {_q8_count(session)}"


def orm_q9(session):
    """
    Repeat Q8 using the LLM-generated program/university fields, and
    report the difference.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    original_count = _q8_count(session)
    university_match = or_(
        *(Applicant.llm_generated_university.ilike(u) for u in LISTED_UNIVERSITIES)
    )
    llm_count = _scalar(session, select(func.count()).select_from(Applicant).where(
        and_(
            Applicant.term.ilike("Fall 2026"),
            Applicant.degree.ilike("PhD"),
            Applicant.status.ilike(ACCEPTED_PATTERN),
            Applicant.llm_generated_program.ilike("Computer Science"),
            university_match,
        )
    ))
    difference = llm_count - original_count
    return (f"PhD Computer Science at listed schools: {original_count}, "
            f"PhD Computer Science at listed schools (LLM): {llm_count}, "
            f"Difference: {difference:+d}")


def orm_a1(session):
    """
    What percentage of total acceptances come from each term found in
    the data? Only terms with both a season and a year count, in the
    list and in the total alike.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    accepted_filter = and_(
        Applicant.status.ilike(ACCEPTED_PATTERN),
        Applicant.term.regexp_match(VALID_TERM_PATTERN, flags="i"),
    )
    total_accepted = _scalar(
        session, select(func.count()).select_from(Applicant).where(accepted_filter)
    )

    # chronological: by year, then Spring before Fall within a year
    rows = session.execute(_limited(
        select(Applicant.term, func.count().label("cnt"))
        .where(accepted_filter)
        .group_by(Applicant.term)
        .order_by(
            _term_year().asc(),
            case((Applicant.term.ilike(SPRING_PATTERN), 0), else_=1),
        )
    )).all()

    parts = [
        f"{row.term} acceptance: {_format_percentage(row.cnt * 100.0 / total_accepted)}"
        for row in rows
    ]
    return ", ".join(parts) if parts else "No accepted applicants found"


def orm_a2(session):
    """
    Average GPA for USC applicants who were accepted versus not, and
    the difference.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    usc_with_gpa = and_(
        Applicant.gpa.is_not(None),
        or_(*(Applicant.program.ilike(f"%, {name}") for name in USC_NAMES)),
    )
    accepted_avg = _scalar(session, select(_round2(func.avg(Applicant.gpa))).where(
        and_(usc_with_gpa, Applicant.status.ilike(ACCEPTED_PATTERN))
    ))
    not_accepted_avg = _scalar(session, select(_round2(func.avg(Applicant.gpa))).where(
        and_(usc_with_gpa, Applicant.status.not_ilike(ACCEPTED_PATTERN))
    ))
    difference = (
        accepted_avg - not_accepted_avg
        if accepted_avg is not None and not_accepted_avg is not None
        else None
    )
    return (f"USC average GPA accepted: {_or_na(accepted_avg)}, "
            f"USC average GPA not accepted: {_or_na(not_accepted_avg)}, "
            f"Difference: {_or_na(difference)}")


def orm_a3(session, school):
    """
    ORM version of query_data's A3: accepted results from
    ACCEPTED_SINCE_YEAR terms onward at a school whose name contains
    school. SQLAlchemy binds every value, and LIKE wildcards in school
    are escaped so it only ever matches literally.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :param school: A school name already cleaned by
        query_data.normalize_school().
    :type school: str
    :returns: One formatted line per matching result, at most
        query_limit() lines.
    :rtype: list[str]
    """
    school_part = func.regexp_replace(Applicant.program, SCHOOL_PREFIX_PATTERN, "")
    term_year = _term_year()
    rows = session.execute(_limited(
        select(Applicant.program, Applicant.degree, Applicant.term,
               Applicant.status, Applicant.gpa)
        .where(
            and_(
                Applicant.status.ilike(ACCEPTED_PATTERN),
                term_year >= ACCEPTED_SINCE_YEAR,
                school_part.ilike(f"%{escape_like(school)}%", escape=LIKE_ESCAPE),
            )
        )
        .order_by(Applicant.date_added.desc(), Applicant.p_id.desc())
    )).mappings().all()
    return [format_accepted_row(row) for row in rows]


ORM_QUESTIONS = [orm_q1, orm_q4, orm_q5, orm_q8, orm_q9, orm_a1]

ALL_ORM_ANSWERS = [
    orm_q1, orm_q2, orm_q3, orm_q4, orm_q5,
    orm_q6, orm_q7, orm_q8, orm_q9, orm_a1, orm_a2,
]


def run_orm_queries(database_url: str):
    """
    Open a SQLAlchemy session against the applicants table and print
    the answer to each question in ORM_QUESTIONS.

    :param database_url: A "postgresql://user:password@host:port/dbname"
        connection string.
    :type database_url: str
    :returns: None.
    :rtype: None
    """
    session = get_session(database_url)
    try:
        for question in ORM_QUESTIONS:
            print(question(session))
    finally:
        session.close()


def _database_url():
    """
    Read the DATABASE_URL environment variable.

    :raises EnvironmentError: If it isn't set.
    :returns: The connection string.
    :rtype: str
    """
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise EnvironmentError(
            "Set the DATABASE_URL environment variable before running this script."
        )
    return database_url


if __name__ == "__main__":
    try:
        run_orm_queries(_database_url())
    except EnvironmentError as error:
        print(error)
        sys.exit(1)
