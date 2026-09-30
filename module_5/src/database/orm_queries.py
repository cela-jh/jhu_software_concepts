"""
`orm_queries.py`
Repeats a subset of the Part 2 SQL analysis using the SQLAlchemy ORM
instead of handwritten SQL. Run directly (`python orm_queries.py`, with
PGUSER/PGPASSWORD set) to print every answer.
"""
import os
import sys
from pathlib import Path

from sqlalchemy import Numeric, and_, case, cast, func, or_, select

# Ensures models resolves whether orm_queries.py is run directly or
# imported as database.orm_queries from elsewhere in the package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import Applicant, get_session

UNIVERSITIES = [
    "Georgetown University",
    "Massachusetts Institute of Technology",
    "MIT",
    "Stanford University",
    "Carnegie Mellon University",
]


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
    count = session.execute(
        select(func.count())
        .select_from(Applicant)
        .where(Applicant.term.ilike("Fall 2026"))
    ).scalar_one()
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
    pct = session.execute(
        select(_round2(func.sum(international) * 100.0 / func.count()))
        .where(usable)
    ).scalar_one()
    return f"International percentage: {_format_percentage(pct)}"


def orm_q3(session):
    """
    Average GPA, GRE Quantitative, GRE Verbal, and GRE Analytical
    Writing scores.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    avg_gpa = session.execute(
        select(_round2(func.avg(Applicant.gpa))).where(Applicant.gpa.is_not(None))
    ).scalar_one()
    avg_gre = session.execute(
        select(_round2(func.avg(Applicant.gre))).where(Applicant.gre.is_not(None))
    ).scalar_one()
    avg_gre_v = session.execute(
        select(_round2(func.avg(Applicant.gre_v))).where(Applicant.gre_v.is_not(None))
    ).scalar_one()
    avg_gre_aw = session.execute(
        select(_round2(func.avg(Applicant.gre_aw))).where(Applicant.gre_aw.is_not(None))
    ).scalar_one()
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
    avg_gpa = session.execute(
        select(_round2(func.avg(Applicant.gpa)))
        .where(
            and_(
                Applicant.gpa.is_not(None),
                Applicant.us_or_international.ilike("American"),
                Applicant.term.ilike("Fall 2026"),
            )
        )
    ).scalar_one()
    return f"Average GPA American: {_or_na(avg_gpa)}"


def orm_q5(session):
    """
    Percentage of Fall 2025 entries that are acceptances.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    accepted = case((Applicant.status.ilike("Accepted%"), 1), else_=0)
    pct = session.execute(
        # The denominator counts every Fall 2025 row via count(), not
        # count(status), so a NULL-status row is still counted (it just
        # never contributes to the numerator via the CASE above).
        select(_round2(func.sum(accepted) * 100.0 / func.count()))
        .where(Applicant.term.ilike("Fall 2025"))
    ).scalar_one()
    return f"Percentage accepted: {_format_percentage(pct)}"


def orm_q6(session):
    """
    Average GPA of accepted applicants who applied for Fall 2026.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    avg_gpa = session.execute(
        select(_round2(func.avg(Applicant.gpa)))
        .where(
            and_(
                Applicant.term.ilike("Fall 2026"),
                Applicant.gpa.is_not(None),
                Applicant.status.ilike("Accepted%"),
            )
        )
    ).scalar_one()
    return f"Average GPA accepted: {_or_na(avg_gpa)}"


def orm_q7(session):
    """
    Count of Johns Hopkins University master's Computer Science entries.

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    count = session.execute(
        select(func.count())
        .select_from(Applicant)
        .where(
            and_(
                Applicant.degree.ilike("Masters"),
                Applicant.program.ilike("Computer Science, %"),
                or_(
                    Applicant.program.ilike("%, Johns Hopkins University%"),
                    Applicant.program.ilike("%, JHU%"),
                ),
            )
        )
    ).scalar_one()
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
    university_match = or_(*(Applicant.program.ilike(f"%, {u}") for u in UNIVERSITIES))
    return session.execute(
        select(func.count())
        .select_from(Applicant)
        .where(
            and_(
                Applicant.term.ilike("Fall 2026"),
                Applicant.degree.ilike("PhD"),
                Applicant.status.ilike("Accepted%"),
                Applicant.program.ilike("Computer Science, %"),
                university_match,
            )
        )
    ).scalar_one()


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
    university_match = or_(*(Applicant.llm_generated_university.ilike(u) for u in UNIVERSITIES))
    llm_count = session.execute(
        select(func.count())
        .select_from(Applicant)
        .where(
            and_(
                Applicant.term.ilike("Fall 2026"),
                Applicant.degree.ilike("PhD"),
                Applicant.status.ilike("Accepted%"),
                Applicant.llm_generated_program.ilike("Computer Science"),
                university_match,
            )
        )
    ).scalar_one()
    difference = llm_count - original_count
    return (f"PhD Computer Science at listed schools: {original_count}, "
            f"PhD Computer Science at listed schools (LLM): {llm_count}, "
            f"Difference: {difference:+d}")


def orm_a1(session):
    """
    What percentage of total acceptances come from each term found in
    the data?

    :param session: Active SQLAlchemy session.
    :type session: sqlalchemy.orm.Session
    :returns: The formatted answer.
    :rtype: str
    """
    accepted_filter = Applicant.status.ilike("Accepted%")
    total_accepted = session.execute(
        select(func.count()).select_from(Applicant).where(accepted_filter)
    ).scalar_one()

    rows = session.execute(
        select(Applicant.term, func.count().label("cnt"))
        .where(accepted_filter)
        .group_by(Applicant.term)
    ).all()

    ordered = sorted(
        rows,
        key=lambda row: (int(row.term.split()[1]), 0 if row.term.startswith("Spring") else 1)
    )
    parts = [
        f"{row.term} acceptance: {_format_percentage(row.cnt * 100.0 / total_accepted)}"
        for row in ordered
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
    usc_match = or_(
        Applicant.program.ilike("%, University of Southern California"),
        Applicant.program.ilike("%, USC"),
    )
    accepted_avg = session.execute(
        select(_round2(func.avg(Applicant.gpa)))
        .where(and_(Applicant.gpa.is_not(None), usc_match, Applicant.status.ilike("Accepted%")))
    ).scalar_one()
    not_accepted_avg = session.execute(
        select(_round2(func.avg(Applicant.gpa)))
        .where(and_(Applicant.gpa.is_not(None), usc_match, Applicant.status.not_ilike("Accepted%")))
    ).scalar_one()
    difference = (
        accepted_avg - not_accepted_avg
        if accepted_avg is not None and not_accepted_avg is not None
        else None
    )
    return (f"USC average GPA accepted: {_or_na(accepted_avg)}, "
            f"USC average GPA not accepted: {_or_na(not_accepted_avg)}, "
            f"Difference: {_or_na(difference)}")


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
