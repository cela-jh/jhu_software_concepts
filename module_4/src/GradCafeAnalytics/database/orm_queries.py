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
    """Rounds a SQL expression to 2 decimal places via a numeric cast."""
    return func.round(cast(expr, Numeric), 2)


def orm_q1(session):
    """How many entries are from applicants who applied for Fall 2026?"""
    count = session.execute(
        select(func.count())
        .select_from(Applicant)
        .where(Applicant.term == "Fall 2026")
    ).scalar_one()
    return f"Applicant count: {count}"


def orm_q2(session):
    """Percentage of entries with a usable nationality classification that are international."""
    international = case((Applicant.us_or_international == "International", 1), else_=0)
    pct = session.execute(
        select(_round2(func.sum(international) * 100.0 / func.count(Applicant.us_or_international)))
        .where(Applicant.us_or_international.is_not(None))
    ).scalar_one()
    return f"International percentage: {pct}%"


def orm_q3(session):
    """Average GPA, GRE Quantitative, GRE Verbal, and GRE Analytical Writing scores."""
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
    return (f"Average GPA: {avg_gpa}, Average GRE: {avg_gre}, "
            f"Average GRE V: {avg_gre_v}, Average GRE AW: {avg_gre_aw}")


def orm_q4(session):
    """Average GPA of American applicants who applied for Fall 2026."""
    avg_gpa = session.execute(
        select(_round2(func.avg(Applicant.gpa)))
        .where(
            and_(
                Applicant.gpa.is_not(None),
                Applicant.us_or_international == "American",
                Applicant.term == "Fall 2026",
            )
        )
    ).scalar_one()
    return f"Average GPA American: {avg_gpa}"


def orm_q5(session):
    """Percentage of Fall 2025 entries that are acceptances."""
    accepted = case((Applicant.status.ilike("Accepted%"), 1), else_=0)
    pct = session.execute(
        select(_round2(func.sum(accepted) * 100.0 / func.count(Applicant.status)))
        .where(Applicant.term == "Fall 2025")
    ).scalar_one()
    return f"Percentage accepted: {pct}%"


def orm_q6(session):
    """Average GPA of accepted applicants who applied for Fall 2026."""
    avg_gpa = session.execute(
        select(_round2(func.avg(Applicant.gpa)))
        .where(
            and_(
                Applicant.term == "Fall 2026",
                Applicant.gpa.is_not(None),
                Applicant.status.ilike("Accepted%"),
            )
        )
    ).scalar_one()
    return f"Average GPA accepted: {avg_gpa}"


def orm_q7(session):
    """Count of Johns Hopkins University master's Computer Science entries."""
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
    """Fall 2026 PhD Computer Science acceptances at the listed universities, by raw program text."""
    university_match = or_(*(Applicant.program.ilike(f"%, {u}") for u in UNIVERSITIES))
    return session.execute(
        select(func.count())
        .select_from(Applicant)
        .where(
            and_(
                Applicant.term == "Fall 2026",
                Applicant.degree.ilike("PhD"),
                Applicant.status.ilike("Accepted%"),
                Applicant.program.ilike("Computer Science, %"),
                university_match,
            )
        )
    ).scalar_one()


def orm_q8(session):
    """How many Fall 2026 entries are PhD Computer Science acceptances at the listed universities?"""
    return f"PhD Computer Science at listed schools: {_q8_count(session)}"


def orm_q9(session):
    """Repeats Q8 using the LLM-generated program/university fields, and reports the difference."""
    original_count = _q8_count(session)
    university_match = or_(*(Applicant.llm_generated_university.ilike(u) for u in UNIVERSITIES))
    llm_count = session.execute(
        select(func.count())
        .select_from(Applicant)
        .where(
            and_(
                Applicant.term == "Fall 2026",
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
    """What percentage of total acceptances come from each term found in the data?"""
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
        f"{row.term} acceptance: {round(row.cnt * 100.0 / total_accepted, 2)}%"
        for row in ordered
    ]
    return ", ".join(parts)


def orm_a2(session):
    """Average GPA for USC applicants who were accepted versus not, and the difference."""
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
    difference = accepted_avg - not_accepted_avg
    return (f"USC average GPA accepted: {accepted_avg}, "
            f"USC average GPA not accepted: {not_accepted_avg}, "
            f"Difference: {difference}")


ORM_QUESTIONS = [orm_q1, orm_q4, orm_q5, orm_q8, orm_q9, orm_a1]

ALL_ORM_ANSWERS = [
    orm_q1, orm_q2, orm_q3, orm_q4, orm_q5,
    orm_q6, orm_q7, orm_q8, orm_q9, orm_a1, orm_a2,
]


def run_orm_queries(credentials: tuple[str, str]):
    """
    Opens a SQLAlchemy session against the applicants table and prints the
    answer to each question in ORM_QUESTIONS.
    Returns none.
    """
    session = get_session(credentials)
    try:
        for question in ORM_QUESTIONS:
            print(question(session))
    finally:
        session.close()


def _pg_credentials():
    """
    Reads database credentials from the PGUSER/PGPASSWORD environment
    variables.
    Returns a (user, password) tuple.
    Raises EnvironmentError if either variable isn't set.
    """
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    if not user or not password:
        raise EnvironmentError(
            "Set the PGUSER and PGPASSWORD environment variables before running this script."
        )
    return user, password


if __name__ == "__main__":
    run_orm_queries(_pg_credentials())
