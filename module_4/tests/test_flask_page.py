"""
`test_flask_page.py`
Verifies the Flask app factory exposes the routes the analysis page and
its buttons depend on, and that the analysis page itself renders the
required structure.
"""
import pytest


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
    """create_app() should register the analysis page (index) and every route
    the Pull Data / Update Analysis buttons call."""
    rule_paths = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/" in rule_paths
    assert "/pull/start" in rule_paths
    assert "/pull/cancel" in rule_paths
    assert "/pull/status" in rule_paths
    assert "/update-analysis" in rule_paths

    assert "GET" in _rule_methods(app, "/")
    assert "GET" in _rule_methods(app, "/pull/status")
    assert "POST" in _rule_methods(app, "/pull/start")
    assert "POST" in _rule_methods(app, "/pull/cancel")
    assert "POST" in _rule_methods(app, "/update-analysis")


@pytest.mark.web
def test_analysis(client, monkeypatch):
    """GET / should render 200 with both buttons and at least one
    labeled answer, without needing a real PostgreSQL connection."""
    monkeypatch.setenv("PGUSER", "test_user")
    monkeypatch.setenv("PGPASSWORD", "test_password")
    monkeypatch.setattr("app.routes.get_session", lambda credentials: _FakeSession())
    monkeypatch.setattr("app.routes.ALL_ORM_ANSWERS", FAKE_ANSWERS)
    monkeypatch.setattr("app.routes.QUESTION_QUERY", FAKE_QUESTION_QUERY)

    response = client.get("/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Pull Data" in page
    assert "Update Analysis" in page
    assert "Analysis" in page
    assert "Answer:" in page


@pytest.mark.web
def test_analysis_page_returns_500_when_credentials_missing(client, monkeypatch):
    """GET / should fail clearly, not crash, when PGUSER/PGPASSWORD
    aren't set - it must never reach get_session() at all."""
    monkeypatch.delenv("PGUSER", raising=False)
    monkeypatch.delenv("PGPASSWORD", raising=False)

    response = client.get("/")

    assert response.status_code == 500
    assert "PGUSER" in response.get_data(as_text=True)
