"""
`orm_queries.py`
Repeats a subset of the Part 2 SQL analysis using the SQLAlchemy ORM
instead of handwritten SQL.
"""
from sqlalchemy import Numeric, and_, case, cast, func, or_, select
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
    return (f"PhD Computer Science at listed schools (LLM): {llm_count}, "
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


ORM_QUESTIONS = [orm_q1, orm_q4, orm_q5, orm_q8, orm_q9, orm_a1]


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
