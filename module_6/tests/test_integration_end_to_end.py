"""
`test_integration_end_to_end.py`
End-to-end coverage of the load -> update-analysis -> render pipeline
against cam_db_test. In module_6 data ingestion is handled by the
worker; these tests load rows directly via load_data() to verify the
Update Analysis endpoint and the rendered analysis page.
"""
import json

import pytest
from bs4 import BeautifulSoup

import database.load_data as load_data
from helpers import (
    assert_all_two_decimal_percentages as _assert_all_two_decimal_percentages,
    fake_applicant_row,
)


@pytest.mark.integration
def test_load_update_render_end_to_end(client, monkeypatch, tmp_path, db_connection,
                                       database_url):
    """Rows loaded via load_data() into cam_db_test must appear on the
    rendered analysis page after POST /update-analysis, with every
    percentage formatted to two decimal places."""
    data_file = tmp_path / "applicant_data.json"
    data_file.write_text(json.dumps([
        fake_applicant_row(4000001, status="Accepted", term="Fall 2026"),
        fake_applicant_row(4000002, status="Rejected", term="Fall 2026"),
        fake_applicant_row(4000003, status="Accepted", term="Spring 2026"),
    ]))
    load_data.load_data(data_file, database_url)

    monkeypatch.setattr("app.routes.publish_task", lambda kind, **kw: None)
    update_response = client.post("/update-analysis")
    assert update_response.status_code == 202
    assert update_response.get_json()["status"] == "queued"

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
    # Fall 2026, so the real (unmocked) ORM query should reflect that.
    assert "Applicant count: 2" in page_text
    # None of the faked rows are USC, so there is no data for either
    # side of its accepted/not-accepted comparison; it should report
    # "N/A" rather than crashing on None - None.
    assert "USC average GPA accepted: N/A" in page_text


@pytest.mark.integration
def test_overlapping_loads_do_not_duplicate_rows(client, monkeypatch, tmp_path, db_connection,
                                                 database_url):
    """Loading the same applicant data twice must not create duplicate
    rows; the second load is an upsert that updates existing records."""
    row_a = fake_applicant_row(5000001)
    row_b = fake_applicant_row(5000002)
    data_file = tmp_path / "applicant_data.json"
    data_file.write_text(json.dumps([row_a, row_b]))

    load_data.load_data(data_file, database_url)

    with db_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM applicants")
        assert cursor.fetchone()[0] == 2

    # Second load: same rows plus one new one.
    data_file.write_text(json.dumps([row_a, row_b, fake_applicant_row(5000003)]))
    load_data.load_data(data_file, database_url)

    with db_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM applicants")
        assert cursor.fetchone()[0] == 3
