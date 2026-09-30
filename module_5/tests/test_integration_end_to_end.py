"""
`test_integration_end_to_end.py`
End-to-end coverage of the full pull -> update -> render pipeline against
the real (disposable) cam_db_test database: a faked scraper's rows go in
via POST /pull/start, POST /update-analysis re-syncs them, and GET /
renders live, correctly formatted analysis computed from those same
rows - no mocked ALL_ORM_ANSWERS here, the real ORM queries run for real.
"""
import pytest
from bs4 import BeautifulSoup

from app import pull_control
from helpers import (
    FakeProcess,
    assert_all_two_decimal_percentages as _assert_all_two_decimal_percentages,
    fake_applicant_row,
    write_fake_scraped_data,
)


def _start_pull(client, monkeypatch, data_file):
    monkeypatch.setattr(pull_control, "DATA_FILE", data_file)
    # /update-analysis reads its own separately-imported DEFAULT_DATA_FILE
    # in routes.py, not pull_control.DATA_FILE; both must point at the
    # same fake file or Update Analysis would load the real project data
    # file into cam_db_test instead.
    monkeypatch.setattr("app.routes.DEFAULT_DATA_FILE", data_file)
    monkeypatch.setattr("app.pull_control.subprocess.Popen", lambda *a, **kw: FakeProcess())
    monkeypatch.setenv("CHROME_BINARY", "/fake/chrome")

    response = client.post("/pull-data")
    pull_control._state.thread.join(timeout=5)
    return response


@pytest.mark.integration
def test_pull_update_render_end_to_end(client, monkeypatch, tmp_path, db_connection):
    """A faked scraper's rows go in via Pull Data, Update Analysis
    confirms it's safe to reload, and the rendered page then shows real,
    correctly formatted analysis computed from those exact rows."""
    data_file = tmp_path / "applicant_data.json"
    write_fake_scraped_data(data_file, [
        fake_applicant_row(4000001, status="Accepted", term="Fall 2026"),
        fake_applicant_row(4000002, status="Rejected", term="Fall 2026"),
        fake_applicant_row(4000003, status="Accepted", term="Spring 2026"),
    ])

    pull_response = _start_pull(client, monkeypatch, data_file)
    assert pull_response.status_code == 200

    with db_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM applicants")
        assert cursor.fetchone()[0] == 3

    update_response = client.post("/update-analysis")
    assert update_response.status_code == 200
    assert update_response.get_json()["status"] == "ok"

    render_response = client.get("/analysis")
    assert render_response.status_code == 200
    soup = BeautifulSoup(render_response.get_data(as_text=True), "html.parser")

    assert soup.find(attrs={"data-testid": "pull-data-btn"}) is not None
    assert soup.find(attrs={"data-testid": "update-analysis-btn"}) is not None
    answer_elements = soup.select(".answer")
    assert len(answer_elements) > 0
    page_text = soup.get_text()
    _assert_all_two_decimal_percentages(page_text)
    # orm_q1 counts Fall 2026 entries; two of the three faked rows are
    # Fall 2026, so the real (unmocked) query should reflect that.
    assert "Applicant count: 2" in page_text
    # None of the faked rows are USC, so orm_a2 has no data on either side
    # of its accepted/not-accepted comparison; it should report "N/A"
    # rather than crashing the whole page on None - None.
    assert "USC average GPA accepted: N/A" in page_text


@pytest.mark.integration
def test_multiple_pulls_with_overlapping_data_stay_consistent(client, monkeypatch, tmp_path, db_connection):
    """Running Pull Data twice with overlapping records must not create duplicates, 
    end to end through the actual HTTP endpoint, background thread, and database."""
    data_file = tmp_path / "applicant_data.json"
    write_fake_scraped_data(data_file, [
        fake_applicant_row(5000001),
        fake_applicant_row(5000002),
    ])

    first_response = _start_pull(client, monkeypatch, data_file)
    assert first_response.status_code == 200

    with db_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM applicants")
        assert cursor.fetchone()[0] == 2

    # Simulate a second, overlapping pull: the same two known results
    # plus one genuinely new one.
    write_fake_scraped_data(data_file, [
        fake_applicant_row(5000001),
        fake_applicant_row(5000002),
        fake_applicant_row(5000003),
    ])

    second_response = _start_pull(client, monkeypatch, data_file)
    assert second_response.status_code == 200

    with db_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM applicants")
        assert cursor.fetchone()[0] == 3
