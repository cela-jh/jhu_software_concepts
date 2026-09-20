"""
`models.py`
SQLAlchemy model for the applicants table, plus the engine and session
used to connect to the same PostgreSQL database as load_data.py.
"""
from datetime import date

from sqlalchemy import URL, Date, Float, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from db_helpers import CONN_PARAMS


class Base(DeclarativeBase):
    pass


class Applicant(Base):
    __tablename__ = "applicants"

    p_id: Mapped[int] = mapped_column(primary_key=True)
    program: Mapped[str] = mapped_column(Text)
    comments: Mapped[str | None] = mapped_column(Text)
    date_added: Mapped[date] = mapped_column(Date)
    url: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text)
    term: Mapped[str] = mapped_column(Text)
    us_or_international: Mapped[str] = mapped_column(Text)
    gpa: Mapped[float | None] = mapped_column(Float)
    gre: Mapped[float | None] = mapped_column(Float)
    gre_v: Mapped[float | None] = mapped_column(Float)
    gre_aw: Mapped[float | None] = mapped_column(Float)
    degree: Mapped[str] = mapped_column(Text)
    llm_generated_program: Mapped[str | None] = mapped_column(Text)
    llm_generated_university: Mapped[str | None] = mapped_column(Text)


def get_engine(credentials: tuple[str, str]):
    """
    Builds a SQLAlchemy engine for the same PostgreSQL database used by
    load_data.py, from a (user, password) credentials tuple and the
    connection details in db_helpers.CONN_PARAMS.
    Returns the engine.
    """
    user, password = credentials
    url = URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=CONN_PARAMS["host"],
        port=CONN_PARAMS["port"],
        database=CONN_PARAMS["dbname"],
    )
    return create_engine(url)


def get_session(credentials: tuple[str, str]) -> Session:
    """
    Opens a new SQLAlchemy Session bound to an engine for the same
    PostgreSQL database used by load_data.py.
    Returns the session. The caller is responsible for closing it.
    """
    return Session(get_engine(credentials))
