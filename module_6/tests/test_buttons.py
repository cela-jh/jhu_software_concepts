"""
`test_buttons.py`
Verifies the Pull Data and Update Analysis endpoints. Both return 202
when publish_task succeeds and 503 when the broker is unreachable.
"""
import pytest


@pytest.mark.buttons
def test_pull_start_returns_202_and_queued_status(client, monkeypatch):
    """POST /pull-data should return 202 with status=queued when the
    broker accepts the message."""
    monkeypatch.setattr("app.routes.publish_task", lambda kind, **kw: None)

    response = client.post("/pull-data")

    assert response.status_code == 202
    body = response.get_json()
    assert body["ok"] is True
    assert body["status"] == "queued"
    assert body["task"] == "scrape_new_data"


@pytest.mark.buttons
def test_pull_start_returns_503_when_broker_unreachable(client, monkeypatch):
    """POST /pull-data should return 503 when publish_task raises."""
    monkeypatch.setattr(
        "app.routes.publish_task",
        lambda kind, **kw: (_ for _ in ()).throw(Exception("connection refused")),
    )

    response = client.post("/pull-data")

    assert response.status_code == 503
    body = response.get_json()
    assert body["ok"] is False
    assert body["status"] == "error"


@pytest.mark.buttons
def test_update_analysis_returns_202_and_queued_status(client, monkeypatch):
    """POST /update-analysis should return 202 with status=queued when
    the broker accepts the message."""
    monkeypatch.setattr("app.routes.publish_task", lambda kind, **kw: None)

    response = client.post("/update-analysis")

    assert response.status_code == 202
    body = response.get_json()
    assert body["ok"] is True
    assert body["status"] == "queued"
    assert body["task"] == "recompute_analytics"


@pytest.mark.buttons
def test_update_analysis_returns_503_when_broker_unreachable(client, monkeypatch):
    """POST /update-analysis should return 503 when publish_task raises."""
    monkeypatch.setattr(
        "app.routes.publish_task",
        lambda kind, **kw: (_ for _ in ()).throw(Exception("timeout")),
    )

    response = client.post("/update-analysis")

    assert response.status_code == 503
    body = response.get_json()
    assert body["ok"] is False
    assert body["status"] == "error"


@pytest.mark.buttons
def test_pull_start_publishes_correct_task_kind(client, monkeypatch):
    """POST /pull-data must publish kind=scrape_new_data, not any other."""
    published = []
    monkeypatch.setattr("app.routes.publish_task", lambda kind, **kw: published.append(kind))

    client.post("/pull-data")

    assert published == ["scrape_new_data"]


@pytest.mark.buttons
def test_update_analysis_publishes_correct_task_kind(client, monkeypatch):
    """POST /update-analysis must publish kind=recompute_analytics."""
    published = []
    monkeypatch.setattr("app.routes.publish_task", lambda kind, **kw: published.append(kind))

    client.post("/update-analysis")

    assert published == ["recompute_analytics"]
