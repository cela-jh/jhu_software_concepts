"""
`test_scraping_storage.py`
Covers scraping/storage.py's JSON persistence and validation helpers:
pure file I/O, tested against tmp_path rather than any real scrape.
"""
import json

import pytest

from scraping.storage import (
    load_existing_urls, load_state, save_data, save_state, validate_filepath,
)


@pytest.mark.db
def test_save_data_creates_new_file(tmp_path):
    filepath = tmp_path / "applicant_data.json"

    save_data([{"url": "https://example.com/result/1"}], filepath)

    assert json.loads(filepath.read_text()) == [{"url": "https://example.com/result/1"}]


@pytest.mark.db
def test_save_data_appends_to_existing_file(tmp_path):
    filepath = tmp_path / "applicant_data.json"
    save_data([{"url": "https://example.com/result/1"}], filepath)

    save_data([{"url": "https://example.com/result/2"}], filepath)

    contents = json.loads(filepath.read_text())
    assert contents == [
        {"url": "https://example.com/result/1"},
        {"url": "https://example.com/result/2"},
    ]


@pytest.mark.db
def test_load_existing_urls_returns_empty_set_when_file_missing(tmp_path):
    assert load_existing_urls(tmp_path / "does_not_exist.json") == set()


@pytest.mark.db
def test_load_existing_urls_returns_empty_set_when_file_is_empty(tmp_path):
    filepath = tmp_path / "empty.json"
    filepath.write_text("")

    assert load_existing_urls(filepath) == set()


@pytest.mark.db
def test_load_existing_urls_reads_urls_and_skips_rows_without_one(tmp_path):
    filepath = tmp_path / "applicant_data.json"
    filepath.write_text(json.dumps([
        {"url": "https://example.com/result/1"},
        {"comments": "no url on this one"},
    ]))

    assert load_existing_urls(filepath) == {"https://example.com/result/1"}


@pytest.mark.db
def test_validate_filepath_accepts_json_path_that_neednt_exist(tmp_path):
    validate_filepath(tmp_path / "new_file.json", must_exist=False)  # must not raise


@pytest.mark.db
def test_validate_filepath_rejects_non_path_argument():
    with pytest.raises(TypeError):
        validate_filepath("not_a_path_object.json", must_exist=False)


@pytest.mark.db
def test_validate_filepath_rejects_non_json_suffix(tmp_path):
    with pytest.raises(ValueError):
        validate_filepath(tmp_path / "data.csv", must_exist=False)


@pytest.mark.db
def test_validate_filepath_requires_existing_file_when_asked(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_filepath(tmp_path / "missing.json", must_exist=True)


@pytest.mark.db
def test_validate_filepath_accepts_existing_file_when_required(tmp_path):
    filepath = tmp_path / "present.json"
    filepath.write_text("[]")

    validate_filepath(filepath, must_exist=True)  # must not raise


@pytest.mark.db
def test_save_state_and_load_state_round_trip(tmp_path):
    state_path = tmp_path / "applicant_data.state.json"

    save_state({"next_url": "https://example.com/page/2"}, state_path)

    assert load_state(state_path) == {"next_url": "https://example.com/page/2"}


@pytest.mark.db
def test_load_state_returns_none_when_file_missing(tmp_path):
    assert load_state(tmp_path / "no_state_here.json") is None
