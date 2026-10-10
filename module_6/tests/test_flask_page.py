"""
`test_flask_page.py`
Verifies the Flask app factory exposes the routes the analysis page and
its buttons depend on, and that the analysis page itself renders the
required structure.
"""
import pytest
from bs4 import BeautifulSoup
from sqlalchemy.exc import OperationalError


class _FakeSession:
    """Stands in for a SQLAlchemy session so analysis() never touches
    a real database in these page-rendering tests."""

    def close(self):
        pass


FAKE_QUESTION_QUERY = [
    ("What percentage of applicants were accepted?", "SELECT 1", str),
]
FAKE_ANSWERS = [lambda session: "42.00%"]


def _rule_methods(app, path):
    for rule in app.url_map.iter_rules():
        if rule.rule == path:
            return rule.methods
    raise AssertionError(f"no route registered for '{path}'")


@pytest.mark.web
def test_app_factory_creates_required_routes(app):
    """create_app() should register the analysis page and the two button
    endpoints. /pull/cancel and /pull/status no longer exist because the
    web service delegates all data operations to the worker via RabbitMQ."""
    rule_paths = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/analysis" in rule_paths
    assert "/pull-data" in rule_paths
    assert "/update-analysis" in rule_paths
    assert "/analysis/accepted-since-2024" in rule_paths
    assert "/pull/cancel" not in rule_paths
    assert "/pull/status" not in rule_paths

    assert "GET" in _rule_methods(app, "/analysis")
    assert "POST" in _rule_methods(app, "/pull-data")
    assert "POST" in _rule_methods(app, "/update-analysis")
    assert "GET" in _rule_methods(app, "/analysis/accepted-since-2024")


@pytest.mark.web
def test_analysis(client, monkeypatch):
    """GET /analysis should render 200 with both buttons and at least one
    labeled answer, without needing a real PostgreSQL connection."""
    monkeypatch.setattr("app.routes.get_session", lambda database_url: _FakeSession())
    monkeypatch.setattr("app.routes.ALL_ORM_ANSWERS", FAKE_ANSWERS)
    monkeypatch.setattr("app.routes.QUESTION_QUERY", FAKE_QUESTION_QUERY)
    monkeypatch.setattr("app.routes.fetch_accepted_since", lambda url, school: ["A3 row"])

    response = client.get("/analysis")

    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert soup.find(attrs={"data-testid": "pull-data-btn"}) is not None
    assert soup.find(attrs={"data-testid": "update-analysis-btn"}) is not None
    assert "Analysis" in soup.find("h1").get_text()
    assert soup.select_one(".answer") is not None
    assert soup.select_one(".answer").get_text().startswith("Answer:")


@pytest.mark.web
def test_analysis_page_returns_500_when_credentials_missing(client, monkeypatch):
    """GET /analysis should fail clearly, not crash, when a DB_*
    variable isn't set - it must never reach get_session() at all."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)

    response = client.get("/analysis")

    assert response.status_code == 500
    assert "DB_NAME" in response.get_data(as_text=True)


@pytest.mark.web
def test_analysis_page_returns_503_when_database_unavailable(client, monkeypatch):
    """GET /analysis should fail with a clear, readable message - not an
    unhandled 500 traceback - when PostgreSQL itself can't be reached."""
    def _raise_operational_error(session):
        raise OperationalError("statement", {}, Exception("connection refused"))

    monkeypatch.setattr("app.routes.get_session", lambda database_url: _FakeSession())
    monkeypatch.setattr("app.routes.ALL_ORM_ANSWERS", [_raise_operational_error])
    monkeypatch.setattr("app.routes.QUESTION_QUERY", FAKE_QUESTION_QUERY)

    response = client.get("/analysis")

    assert response.status_code == 503
    assert "database is currently unavailable" in response.get_data(as_text=True)
