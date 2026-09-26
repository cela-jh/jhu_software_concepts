"""
`models.py`
SQLAlchemy model for the applicants table, plus the engine and session
used to connect to the same PostgreSQL database as load_data.py.
"""
from datetime import date

from sqlalchemy import Date, Float, Text, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    """Declarative base class for every ORM model in this project."""


class Applicant(Base):
    """ORM model for a single row of the `applicants` table."""

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


def get_engine(database_url: str):
    """
    Build a SQLAlchemy engine for the same PostgreSQL database used by
    load_data.py. The psycopg driver is selected explicitly, since plain
    "postgresql://" would otherwise resolve to SQLAlchemy's default
    driver rather than the one this project installs.

    :param database_url: A "postgresql://user:password@host:port/dbname"
        connection string.
    :type database_url: str
    :returns: The engine.
    :rtype: sqlalchemy.engine.Engine
    """
    url = make_url(database_url).set(drivername="postgresql+psycopg")
    return create_engine(url)


def get_session(database_url: str) -> Session:
    """
    Open a new SQLAlchemy Session bound to an engine for the same
    PostgreSQL database used by load_data.py.

    :param database_url: A "postgresql://user:password@host:port/dbname"
        connection string.
    :type database_url: str
    :returns: The session. The caller is responsible for closing it.
    :rtype: sqlalchemy.orm.Session
    """
    return Session(get_engine(database_url))
