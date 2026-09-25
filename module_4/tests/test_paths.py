"""
`test_paths.py`
Covers paths.py's state_path_for(), the one function here with real
logic (everything else is plain module-level constants).
"""
from pathlib import Path

import pytest

import paths


@pytest.mark.db
def test_state_path_for_derives_name_from_data_file(tmp_path, monkeypatch):
    """The sidecar state path should live in STATE_DIR, named after the
    data file's own basename with a .state.json suffix."""
    fake_state_dir = tmp_path / ".state"
    monkeypatch.setattr(paths, "STATE_DIR", fake_state_dir)

    result = paths.state_path_for(Path("/some/where/applicant_data.json"))

    assert result == fake_state_dir / "applicant_data.state.json"


@pytest.mark.db
def test_state_path_for_creates_state_dir_if_missing(tmp_path, monkeypatch):
    """STATE_DIR may not exist yet on a fresh checkout; state_path_for
    must create it rather than fail."""
    fake_state_dir = tmp_path / "brand_new" / ".state"
    monkeypatch.setattr(paths, "STATE_DIR", fake_state_dir)
    assert not fake_state_dir.exists()

    paths.state_path_for(Path("applicant_data.json"))

    assert fake_state_dir.is_dir()
