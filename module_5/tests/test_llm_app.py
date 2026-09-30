"""
`test_llm_app.py`
Covers llm_hosting/app.py: canonical-name normalization, the standardize
route, and the CLI file processor - with the actual LLM (Llama) and any
model download always mocked, so nothing here ever loads a real model or
touches the network. Loaded via importlib under the name "llm_app" since
a bare `import app` would resolve to the already-cached Flask `app`
package instead (see conftest.py).
"""
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

LLM_HOSTING_DIR = Path(__file__).resolve().parent.parent / "src" / "llm_hosting"
if str(LLM_HOSTING_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_HOSTING_DIR))

# app.py reads these as cwd-relative by default; point them at the real
# files by absolute path so canonical-name matching is exercised for real,
# regardless of pytest's invocation directory.
os.environ.setdefault("CANON_UNIS_PATH", str(LLM_HOSTING_DIR / "canon_universities.txt"))
os.environ.setdefault("CANON_PROGS_PATH", str(LLM_HOSTING_DIR / "canon_programs.txt"))

_spec = importlib.util.spec_from_file_location("llm_app", LLM_HOSTING_DIR / "app.py")
llm_app = importlib.util.module_from_spec(_spec)
sys.modules["llm_app"] = llm_app
_spec.loader.exec_module(llm_app)


@pytest.fixture
def fake_models_dir(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    monkeypatch.setattr(llm_app, "MODELS_DIR", models_dir)
    return models_dir


@pytest.mark.web
def test_read_lines_returns_stripped_nonempty_lines(tmp_path):
    path = tmp_path / "lines.txt"
    path.write_text("  first  \n\nsecond\n   \n")

    assert llm_app._read_lines(str(path)) == ["first", "second"]


@pytest.mark.web
def test_read_lines_returns_empty_list_when_file_missing(tmp_path):
    assert llm_app._read_lines(str(tmp_path / "missing.txt")) == []


@pytest.mark.web
def test_get_model_path_reuses_existing_file(fake_models_dir):
    fake_models_dir.mkdir()
    model_file = fake_models_dir / llm_app.MODEL_FILE
    model_file.write_text("fake gguf bytes")

    assert llm_app._get_model_path() == str(model_file)


@pytest.mark.web
def test_get_model_path_downloads_when_missing(fake_models_dir, monkeypatch):
    download_calls = []

    def _fake_download(repo_id, filename, local_dir):
        download_calls.append((repo_id, filename, local_dir))
        return "/fake/downloaded/model.gguf"

    monkeypatch.setattr(llm_app, "hf_hub_download", _fake_download)

    result = llm_app._get_model_path()

    assert result == "/fake/downloaded/model.gguf"
    assert download_calls == [(llm_app.MODEL_REPO, llm_app.MODEL_FILE, str(fake_models_dir))]


@pytest.mark.web
def test_load_llm_caches_across_calls(monkeypatch):
    monkeypatch.setattr(llm_app, "_LLM", None)
    monkeypatch.setattr(llm_app, "_get_model_path", lambda: "/fake/model.gguf")
    construct_calls = []
    monkeypatch.setattr(llm_app, "Llama", lambda **kwargs: construct_calls.append(kwargs) or "fake_llm")

    first = llm_app._load_llm()
    second = llm_app._load_llm()

    assert first == "fake_llm"
    assert second == "fake_llm"
    assert len(construct_calls) == 1  # only constructed once, then cached


@pytest.mark.web
@pytest.mark.parametrize("text,expected_prog,expected_uni", [
    ("Computer Science, Test University", "Computer Science", "Test University"),
    ("Computer Science at Test University", "Computer Science", "Test University"),
    ("Computer Science @ Test University", "Computer Science", "Test University"),
    # str.title() lowercases embedded capitals, so "McGill" -> "Mcgill" here;
    # _post_normalize_university (not this fallback) is what fixes casing.
    ("Information, McG", "Information", "Mcgill University"),
    ("Math, UBC", "Math", "University of British Columbia"),
    ("just one part", "Just One Part", ""),
    ("", "", ""),
])
def test_split_fallback(text, expected_prog, expected_uni):
    assert llm_app._split_fallback(text) == (expected_prog, expected_uni)


@pytest.mark.web
def test_best_match_returns_none_for_empty_input():
    assert llm_app._best_match("", {"a": "A"}, cutoff=0.8) is None
    assert llm_app._best_match("x", {}, cutoff=0.8) is None


@pytest.mark.web
def test_best_match_finds_close_match():
    lower_map = {"mcgill university": "McGill University"}
    assert llm_app._best_match("mcgil university", lower_map, cutoff=0.8) == "McGill University"


@pytest.mark.web
def test_best_match_returns_none_when_nothing_close_enough():
    lower_map = {"mcgill university": "McGill University"}
    assert llm_app._best_match("completely unrelated text", lower_map, cutoff=0.9) is None


@pytest.mark.web
def test_post_normalize_program_applies_common_fix():
    assert llm_app._post_normalize_program("Mathematic") == "Mathematics"


@pytest.mark.web
def test_post_normalize_program_passes_through_when_no_canon_match():
    assert llm_app._post_normalize_program("Underwater Basket Weaving") == "Underwater Basket Weaving"


@pytest.mark.web
def test_post_normalize_university_expands_abbreviation_and_confirms_canon():
    assert llm_app._post_normalize_university("mcg") == "McGill University"


@pytest.mark.web
def test_post_normalize_university_applies_common_fix_and_of_normalization():
    assert llm_app._post_normalize_university("University Of British Columbia") == \
        "University of British Columbia"


@pytest.mark.web
def test_post_normalize_university_passes_through_when_no_canon_match():
    assert llm_app._post_normalize_university("Totally Made Up University") == "Totally Made Up University"


class _FakeLlmResponse:
    """Builds the nested dict shape _call_llm expects from create_chat_completion."""

    @staticmethod
    def build(content, finish_reason="length"):
        return {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}


@pytest.mark.web
def test_call_llm_parses_valid_json_response(monkeypatch):
    response = _FakeLlmResponse.build(
        json.dumps({"llm_generated_program": "Computer Science", "llm_generated_university": "mcg"})
    )
    fake_llm = SimpleNamespace(create_chat_completion=lambda **kw: response)
    monkeypatch.setattr(llm_app, "_load_llm", lambda: fake_llm)

    result = llm_app._call_llm("Computer Science, McG")

    assert result["llm_generated_program"] == "Computer Science"
    assert result["llm_generated_university"] == "McGill University"


@pytest.mark.web
def test_call_llm_restores_stop_truncated_brace(monkeypatch):
    truncated = '{"llm_generated_program": "Computer Science", "llm_generated_university": "McGill University"'
    response = _FakeLlmResponse.build(truncated, finish_reason="stop")
    fake_llm = SimpleNamespace(create_chat_completion=lambda **kw: response)
    monkeypatch.setattr(llm_app, "_load_llm", lambda: fake_llm)

    result = llm_app._call_llm("Computer Science, McGill University")

    assert result["llm_generated_program"] == "Computer Science"


@pytest.mark.web
def test_call_llm_falls_back_on_unparseable_response(monkeypatch):
    response = _FakeLlmResponse.build("not json at all, sorry")
    fake_llm = SimpleNamespace(create_chat_completion=lambda **kw: response)
    monkeypatch.setattr(llm_app, "_load_llm", lambda: fake_llm)

    # A name with no realistic overlap in the real canonical list, so this
    # asserts the fallback-parse path itself, not incidental fuzzy-matching.
    result = llm_app._call_llm("Computer Science, Xyzzqrp Nonexistent Place")

    assert result["llm_generated_program"] == "Computer Science"
    assert result["llm_generated_university"] == "Xyzzqrp Nonexistent Place"


@pytest.mark.web
def test_call_llm_defaults_university_to_program_text_when_blank(monkeypatch):
    response = _FakeLlmResponse.build(
        json.dumps({"llm_generated_program": "Something", "llm_generated_university": ""})
    )
    fake_llm = SimpleNamespace(create_chat_completion=lambda **kw: response)
    monkeypatch.setattr(llm_app, "_load_llm", lambda: fake_llm)

    result = llm_app._call_llm("Something, Unknown Place")

    assert result["llm_generated_university"] != ""


@pytest.mark.web
def test_normalize_input_accepts_list():
    assert llm_app._normalize_input([{"a": 1}]) == [{"a": 1}]


@pytest.mark.web
def test_normalize_input_accepts_rows_dict():
    assert llm_app._normalize_input({"rows": [{"a": 1}]}) == [{"a": 1}]


@pytest.mark.web
def test_normalize_input_returns_empty_for_anything_else():
    assert llm_app._normalize_input("not a valid payload") == []
    assert llm_app._normalize_input({"no_rows_key": []}) == []


@pytest.mark.web
def test_health_route_returns_ok():
    client = llm_app.app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


@pytest.mark.web
def test_standardize_route_adds_llm_fields(monkeypatch):
    monkeypatch.setattr(
        llm_app, "_call_llm",
        lambda program_text: {"llm_generated_program": "CS", "llm_generated_university": "Test U"},
    )
    client = llm_app.app.test_client()

    response = client.post("/standardize", json=[{"program": "Computer Science, Test University"}])

    assert response.status_code == 200
    rows = response.get_json()["rows"]
    assert rows[0]["llm-generated-program"] == "CS"
    assert rows[0]["llm-generated-university"] == "Test U"


@pytest.mark.web
@pytest.mark.parametrize("seconds,expected", [
    (5, "0:05"),
    (65, "1:05"),
    (3661, "1:01:01"),
])
def test_format_duration(seconds, expected):
    assert llm_app._format_duration(seconds) == expected


@pytest.mark.web
def test_cli_process_file_writes_jsonl_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        llm_app, "_call_llm",
        lambda program_text: {"llm_generated_program": "CS", "llm_generated_university": "Test U"},
    )
    in_path = tmp_path / "in.json"
    in_path.write_text(json.dumps([{"program": "Computer Science, Test U", "url": "u1"}]))
    out_path = tmp_path / "out.jsonl"

    llm_app._cli_process_file(str(in_path), str(out_path), append=False, to_stdout=False)

    lines = out_path.read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["llm-generated-program"] == "CS"


@pytest.mark.web
def test_cli_process_file_appends_when_requested(tmp_path, monkeypatch):
    monkeypatch.setattr(
        llm_app, "_call_llm",
        lambda program_text: {"llm_generated_program": "CS", "llm_generated_university": "Test U"},
    )
    in_path = tmp_path / "in.json"
    in_path.write_text(json.dumps([{"program": "Computer Science, Test U", "url": "u1"}]))
    out_path = tmp_path / "out.jsonl"
    out_path.write_text(json.dumps({"program": "Existing Row"}) + "\n")

    llm_app._cli_process_file(str(in_path), str(out_path), append=True, to_stdout=False)

    assert len(out_path.read_text().splitlines()) == 2


@pytest.mark.web
def test_cli_process_file_writes_to_stdout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        llm_app, "_call_llm",
        lambda program_text: {"llm_generated_program": "CS", "llm_generated_university": "Test U"},
    )
    in_path = tmp_path / "in.json"
    in_path.write_text(json.dumps([{"program": "Computer Science, Test U", "url": "u1"}]))

    llm_app._cli_process_file(str(in_path), None, append=False, to_stdout=True)

    out = capsys.readouterr().out
    assert '"llm-generated-program": "CS"' in out
