"""
`test_sql_safety.py`
Covers the SQL injection defenses and query limits: the limit clamp and
LIKE escaping helpers, school-name validation, that every composed
statement carries its values as bound parameters and a LIMIT, and the
A3 school search endpoint's handling of malicious input against the real
cam_db_test database.
"""
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import event
from sqlalchemy.engine import Engine

import database.load_data as load_data
from database import db_helpers
from database import query_data
from database.models import get_session
from database.orm_queries import ALL_ORM_ANSWERS, orm_a1, orm_a3
from helpers import fake_applicant_row

ENDPOINT = "/analysis/accepted-since-2024"
USC = "Computer Science, University of Southern California"


def _seed(conn, rows):
    """Insert raw scraped-style rows through load_data's own upsert."""
    with conn.cursor() as cursor:
        load_data._insert_batch(cursor, [load_data._build_row(row) for row in rows])
    conn.commit()


def _row_count(conn):
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM applicants")
        return cursor.fetchone()[0]


@pytest.fixture
def seeded(db_connection):
    """
    One row that A3 should match for the default school, plus one near
    miss for each filter it applies, and a school whose name contains a
    literal "%" to prove wildcards in input are matched literally.
    """
    _seed(db_connection, [
        fake_applicant_row(1, program=USC, term="Fall 2025"),
        fake_applicant_row(2, program=USC, term="Fall 2023"),
        fake_applicant_row(3, program=USC, status="Rejected", term="Fall 2026"),
        fake_applicant_row(4, program="Physics, Stanford University"),
        fake_applicant_row(5, program="Art, 100% Online University"),
        fake_applicant_row(6, program=USC, term="Fall"),  # no year: excluded, never an error
    ])
    return db_connection


# ---------------------------------------------------------------------------
# Limit and escaping helpers
# ---------------------------------------------------------------------------

@pytest.mark.db
@pytest.mark.parametrize("requested,expected", [
    (-5, 1), (0, 1), (1, 1), (50, 50), (100, 100), (101, 100), (10_000, 100),
])
def test_clamp_limit_keeps_limit_in_range(requested, expected):
    assert db_helpers.clamp_limit(requested) == expected


@pytest.mark.db
def test_query_limit_is_the_fixed_inherent_limit():
    assert db_helpers.query_limit() == 50
    assert db_helpers.MIN_LIMIT <= db_helpers.query_limit() <= db_helpers.MAX_LIMIT


@pytest.mark.db
@pytest.mark.parametrize("text,expected", [
    ("USC", "USC"),
    ("100%", "100\\%"),
    ("a_b", "a\\_b"),
    ("ends\\", "ends\\\\"),
])
def test_escape_like_neutralizes_wildcards(text, expected):
    assert db_helpers.escape_like(text) == expected


# ---------------------------------------------------------------------------
# School input validation
# ---------------------------------------------------------------------------

@pytest.mark.db
@pytest.mark.parametrize("raw,expected", [
    (None, query_data.DEFAULT_SCHOOL),
    ("   ", query_data.DEFAULT_SCHOOL),
    ("  Johns   Hopkins\tUniversity ", "Johns Hopkins University"),
])
def test_normalize_school_cleans_or_defaults(raw, expected):
    assert query_data.normalize_school(raw) == expected


@pytest.mark.db
@pytest.mark.parametrize("raw", [
    "x" * (query_data.MAX_SCHOOL_LENGTH + 1),
    "USC\x00",
    "USC\x07",
])
def test_normalize_school_rejects_oversized_or_control_characters(raw):
    with pytest.raises(query_data.InvalidSchoolInput):
        query_data.normalize_school(raw)


# ---------------------------------------------------------------------------
# Statement composition: values are parameters, every SELECT is limited
# ---------------------------------------------------------------------------

@pytest.mark.db
def test_every_analysis_statement_has_bound_limit(db_connection):
    for question, query, _ in query_data.CLI_QUESTION_QUERY:
        text = query.statement.as_string(db_connection)
        assert "LIMIT %(limit)s" in text, question
        assert '"applicants"' in text, question  # table quoted via Identifier
        assert query.params["limit"] == db_helpers.query_limit()


@pytest.mark.db
def test_malicious_school_never_reaches_statement_text(db_connection):
    payload = "USC'; DROP TABLE applicants; --"

    query = query_data.build_accepted_since_query(payload)

    assert "DROP" not in query.statement.as_string(db_connection)
    assert query.params["school"] == f"%{payload}%"


@pytest.mark.db
def test_upsert_statement_quotes_identifiers_and_holds_no_values(db_connection):
    text = load_data._build_upsert(2).as_string(db_connection)

    assert 'INSERT INTO "applicants"' in text
    assert '"llm_generated_university"' in text
    assert text.count("%s") == 2 * len(load_data.COLUMNS)


@pytest.mark.db
def test_every_orm_select_carries_a_limit(seeded, database_url):
    """Captures the SQL SQLAlchemy actually sends while every ORM answer
    runs, and requires a LIMIT on each SELECT."""
    statements = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _capture)
    session = get_session(database_url)
    try:
        for answer in ALL_ORM_ANSWERS:
            answer(session)
        orm_a3(session, query_data.DEFAULT_SCHOOL)
    finally:
        session.close()
        event.remove(Engine, "before_cursor_execute", _capture)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert selects
    assert all("LIMIT" in s for s in selects)


# ---------------------------------------------------------------------------
# A3 query results
# ---------------------------------------------------------------------------

@pytest.mark.db
def test_accepted_since_applies_every_filter(seeded, database_url):
    rows = query_data.fetch_accepted_since(database_url, query_data.DEFAULT_SCHOOL)

    assert rows == [f"{USC} | Masters | Fall 2025 | Accepted | GPA: N/A"]


@pytest.mark.db
def test_accepted_since_returns_at_most_the_limit(db_connection, database_url):
    _seed(db_connection, [fake_applicant_row(1000 + i, program=USC) for i in range(60)])

    rows = query_data.fetch_accepted_since(database_url, query_data.DEFAULT_SCHOOL)

    assert len(rows) == db_helpers.query_limit()


@pytest.mark.db
@pytest.mark.parametrize("school", [
    query_data.DEFAULT_SCHOOL, "southern calif", "%", "' OR '1'='1",
])
def test_orm_a3_matches_psycopg_a3(seeded, database_url, school):
    session = get_session(database_url)
    try:
        orm_rows = orm_a3(session, school)
    finally:
        session.close()

    assert orm_rows == query_data.fetch_accepted_since(database_url, school)


@pytest.mark.db
def test_a1_excludes_terms_missing_season_or_year(db_connection, database_url, capsys):
    """Only terms with both a season and a year count toward A1, in the
    listed terms and in the total alike, in both implementations."""
    _seed(db_connection, [
        fake_applicant_row(1, term="Spring 2026"),
        fake_applicant_row(2, term="Fall 2026"),
        fake_applicant_row(3, term="fall 2026"),  # valid, matched case-insensitively
        fake_applicant_row(4, term="Fall"),
        fake_applicant_row(5, term="2026"),
        fake_applicant_row(6, term="Fall2026"),
        fake_applicant_row(7, term="Autumn 2026"),
    ])

    session = get_session(database_url)
    try:
        orm_answer = orm_a1(session)
    finally:
        session.close()
    a1 = [entry for entry in query_data.QUESTION_QUERY if entry[0].startswith("A1:")]
    query_data.analyze(a1, database_url)
    sql_answer = capsys.readouterr().out.strip()

    # 3 valid acceptances, so the 4 malformed rows don't dilute the total
    assert orm_answer == sql_answer
    assert orm_answer.startswith("Spring 2026 acceptance: 33.33%")
    assert "Fall 2026 acceptance: 33.33%" in orm_answer
    assert "fall 2026 acceptance: 33.33%" in orm_answer
    for malformed in ("Fall acceptance", "2026 acceptance:", "Fall2026", "Autumn"):
        assert not orm_answer.startswith(malformed)
        assert f", {malformed}" not in orm_answer


@pytest.mark.db
def test_fetch_accepted_since_raises_when_database_unreachable(monkeypatch):
    monkeypatch.setattr("database.query_data.connect_db", lambda url: None)

    with pytest.raises(db_helpers.DatabaseUnavailableError):
        query_data.fetch_accepted_since("postgresql://nowhere/nothing", "USC")


@pytest.mark.db
def test_cli_prints_a3_placeholder_when_nothing_matches(db_connection, database_url, capsys):
    query_data.analyze(query_data.CLI_QUESTION_QUERY[-1:], database_url)

    assert query_data.NO_ACCEPTED_RESULTS in capsys.readouterr().out


# ---------------------------------------------------------------------------
# A3 endpoint: user input through the web app
# ---------------------------------------------------------------------------

@pytest.mark.web
@pytest.mark.db
@pytest.mark.parametrize("query_string", ["", "?school=", "?school=%20%20"])
def test_endpoint_defaults_to_usc(client, seeded, query_string):
    body = client.get(ENDPOINT + query_string).get_json()

    assert body["ok"] is True
    assert body["school"] == query_data.DEFAULT_SCHOOL
    assert len(body["rows"]) == 1


@pytest.mark.web
@pytest.mark.db
def test_endpoint_matches_school_substring_case_insensitively(client, seeded):
    body = client.get(ENDPOINT, query_string={"school": "southern CALIF"}).get_json()

    assert body["rows"] == [f"{USC} | Masters | Fall 2025 | Accepted | GPA: N/A"]


@pytest.mark.web
@pytest.mark.db
@pytest.mark.parametrize("payload", [
    "' OR '1'='1",
    "' OR 1=1 --",
    "USC'; DROP TABLE applicants; --",
    "') UNION SELECT program, degree, term, status, gpa FROM applicants --",
    "_",
    "\\",
])
def test_endpoint_treats_injection_attempts_as_plain_text(client, seeded, payload):
    """Classic injection strings and LIKE wildcards must match nothing
    (no school name contains them), return normally, and leave the
    table intact."""
    rows_before = _row_count(seeded)

    response = client.get(ENDPOINT, query_string={"school": payload})

    assert response.status_code == 200
    assert response.get_json()["rows"] == []
    assert _row_count(seeded) == rows_before


@pytest.mark.web
@pytest.mark.db
def test_endpoint_percent_matches_only_literal_percent(client, seeded):
    """A bare "%" must not act as a wildcard returning every school; it
    only matches a school whose name really contains a percent sign."""
    rows = client.get(ENDPOINT, query_string={"school": "%"}).get_json()["rows"]

    assert len(rows) == 1
    assert "100% Online University" in rows[0]


@pytest.mark.web
@pytest.mark.parametrize("payload", ["x" * 101, "USC\x00"])
def test_endpoint_rejects_invalid_school_with_400(client, payload):
    response = client.get(ENDPOINT, query_string={"school": payload})

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


@pytest.mark.web
def test_endpoint_reports_missing_database_config(client, monkeypatch):
    monkeypatch.delenv("DB_PORT", raising=False)

    response = client.get(ENDPOINT)

    assert response.status_code == 500


@pytest.mark.web
def test_endpoint_reports_unreachable_database(client, monkeypatch):
    monkeypatch.setattr("database.query_data.connect_db", lambda url: None)

    response = client.get(ENDPOINT)

    assert response.status_code == 503
    assert response.get_json()["ok"] is False


@pytest.mark.web
@pytest.mark.db
def test_analysis_page_escapes_markup_in_results(client, db_connection):
    """Result text is rendered as text, so a program name containing a
    script tag can never run in the page."""
    _seed(db_connection, [fake_applicant_row(
        8, program="<script>alert(1)</script>, University of Southern California",
    )])

    html = client.get("/analysis").get_data(as_text=True)

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    soup = BeautifulSoup(html, "html.parser")
    assert all("alert(1)" not in (tag.string or "") for tag in soup.find_all("script"))


@pytest.mark.web
def test_analysis_page_503_when_a3_database_unreachable(client, monkeypatch):
    class _FakeSession:
        def close(self):
            pass

    def _unreachable(url, school):
        raise db_helpers.DatabaseUnavailableError("down")

    monkeypatch.setattr("app.routes.get_session", lambda database_url: _FakeSession())
    monkeypatch.setattr("app.routes.ALL_ORM_ANSWERS", [])
    monkeypatch.setattr("app.routes.fetch_accepted_since", _unreachable)

    assert client.get("/analysis").status_code == 503
