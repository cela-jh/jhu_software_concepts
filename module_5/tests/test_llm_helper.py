"""
`test_llm_helper.py`
Covers llm_hosting/llm_helper.py: locating or downloading the model file,
JSON Lines persistence, the resume/dedup logic across output files and
leftover chunk files, and run_parallel()'s orchestration - with
subprocess.Popen and the model download mocked (no real worker processes
or network) and STATE_DIR redirected to tmp_path (never the real
llm_hosting/.llm_state).
"""
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import llm_hosting.llm_helper as llm_helper


@pytest.fixture(autouse=True)
def fake_state_dir(tmp_path, monkeypatch):
    """Redirects STATE_DIR to a throwaway directory for every test in this
    file, so nothing here ever touches the real llm_hosting/.llm_state."""
    state_dir = tmp_path / ".llm_state"
    monkeypatch.setattr(llm_helper, "STATE_DIR", state_dir)
    return state_dir


@pytest.mark.web
def test_read_jsonl_skips_blank_lines(tmp_path):
    path = tmp_path / "chunk.jsonl"
    path.write_text('{"url": "a"}\n\n{"url": "b"}\n')

    assert llm_helper._read_jsonl(path) == [{"url": "a"}, {"url": "b"}]


@pytest.mark.web
def test_safe_write_json_writes_new_file(tmp_path):
    output_path = tmp_path / "out.json"

    llm_helper._safe_write_json([{"url": "a"}], output_path)

    assert json.loads(output_path.read_text()) == [{"url": "a"}]


@pytest.mark.web
def test_safe_write_json_refuses_to_shrink_existing_result(tmp_path):
    output_path = tmp_path / "out.json"
    output_path.write_text(json.dumps([{"url": "a"}, {"url": "b"}]))

    with pytest.raises(RuntimeError):
        llm_helper._safe_write_json([{"url": "a"}], output_path)


@pytest.mark.web
def test_safe_write_json_treats_corrupted_existing_file_as_empty(tmp_path):
    output_path = tmp_path / "out.json"
    output_path.write_text("{not valid json")

    llm_helper._safe_write_json([{"url": "a"}], output_path)  # must not raise

    assert json.loads(output_path.read_text()) == [{"url": "a"}]


@pytest.mark.web
def test_jsonl_to_json_round_trip(tmp_path):
    jsonl_path = tmp_path / "chunk.jsonl"
    jsonl_path.write_text('{"url": "a"}\n{"url": "b"}\n')
    json_path = tmp_path / "out.json"

    llm_helper.jsonl_to_json(jsonl_path, json_path)

    assert json.loads(json_path.read_text()) == [{"url": "a"}, {"url": "b"}]


@pytest.mark.web
def test_load_completed_returns_empty_when_nothing_exists(tmp_path):
    assert llm_helper._load_completed(tmp_path / "missing.json", "url") == {}


@pytest.mark.web
def test_load_completed_reads_existing_output_file(tmp_path):
    output_path = tmp_path / "out.json"
    output_path.write_text(json.dumps([{"url": "a", "x": 1}]))

    assert llm_helper._load_completed(output_path, "url") == {"a": {"url": "a", "x": 1}}


@pytest.mark.web
def test_load_completed_treats_corrupted_output_file_as_empty(tmp_path):
    output_path = tmp_path / "out.json"
    output_path.write_text("not json")

    assert llm_helper._load_completed(output_path, "url") == {}


@pytest.mark.web
def test_load_completed_merges_leftover_chunk_files_and_they_win_on_conflict(tmp_path, fake_state_dir):
    output_path = tmp_path / "out.json"
    output_path.write_text(json.dumps([{"url": "a", "version": "old"}]))
    fake_state_dir.mkdir()
    (fake_state_dir / "chunk_0_0.jsonl").write_text(
        json.dumps({"url": "a", "version": "new"}) + "\n" + json.dumps({"url": "b"}) + "\n"
    )

    completed = llm_helper._load_completed(output_path, "url")

    assert completed["a"]["version"] == "new"  # chunk file overrides the output file
    assert "b" in completed


@pytest.mark.web
def test_merge_and_write_combines_and_returns_count(tmp_path, fake_state_dir):
    output_path = tmp_path / "out.json"
    fake_state_dir.mkdir()
    (fake_state_dir / "chunk_0_0.jsonl").write_text(json.dumps({"url": "a"}) + "\n")

    count = llm_helper._merge_and_write(output_path, "url")

    assert count == 1
    assert json.loads(output_path.read_text()) == [{"url": "a"}]


@pytest.mark.web
def test_parse_args_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["llm_helper.py", "in.json", "out.json"])

    args = llm_helper.parse_args()

    assert str(args.input_path) == "in.json"
    assert str(args.output_path) == "out.json"
    assert args.n_workers == 4
    assert args.n_threads == 1
    assert args.key == "url"


class _FakeWorkerProcess:
    """Stands in for subprocess.Popen's return value for one launched
    worker: no real process ever runs. `wait_effects` is a queue of
    exceptions to raise (or None for a normal return) consumed one per
    .wait() call, for tests that need more than one distinct outcome
    across the initial wait and _terminate_workers()'s own follow-up wait."""

    def __init__(self, returncode=0, wait_effects=None):
        self.returncode = returncode
        self._wait_effects = list(wait_effects) if wait_effects is not None else []
        self._waited = False
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        if self._wait_effects:
            effect = self._wait_effects.pop(0)
            if effect is not None:
                raise effect
        self._waited = True
        return self.returncode

    def poll(self):
        return self.returncode if self._waited else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


@pytest.fixture
def fake_model_path(monkeypatch):
    """Stands in for get_model_path() so run_parallel() never downloads a
    real model; records each call so tests can confirm it ran first."""
    calls = []
    monkeypatch.setattr(llm_helper, "get_model_path",
                        lambda: calls.append(1) or "/fake/model.gguf")
    return calls


@pytest.fixture
def fake_models_dir(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    monkeypatch.setattr(llm_helper, "MODELS_DIR", models_dir)
    return models_dir


@pytest.mark.web
def test_get_model_path_reuses_existing_file(fake_models_dir):
    fake_models_dir.mkdir()
    model_file = fake_models_dir / llm_helper.MODEL_FILE
    model_file.write_text("fake gguf bytes")

    assert llm_helper.get_model_path() == str(model_file)


@pytest.mark.web
def test_get_model_path_downloads_when_missing(fake_models_dir, monkeypatch):
    download_calls = []

    def _fake_download(repo_id, filename, local_dir):
        download_calls.append((repo_id, filename, local_dir))
        return "/fake/downloaded/model.gguf"

    monkeypatch.setattr(llm_helper, "hf_hub_download", _fake_download)

    result = llm_helper.get_model_path()

    assert result == "/fake/downloaded/model.gguf"
    assert download_calls == [
        (llm_helper.MODEL_REPO, llm_helper.MODEL_FILE, str(fake_models_dir))
    ]


@pytest.mark.web
def test_run_parallel_raises_when_input_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        llm_helper.run_parallel(tmp_path / "missing.json", tmp_path / "out.json")


@pytest.mark.web
def test_run_parallel_raises_on_invalid_input_structure(tmp_path, fake_model_path):
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps({"not": "a list of rows"}))

    with pytest.raises(ValueError):
        llm_helper.run_parallel(input_path, tmp_path / "out.json")

    assert fake_model_path == [1]  # get_model_path was still called first


@pytest.mark.web
def test_run_parallel_returns_early_when_nothing_remains(tmp_path, fake_model_path, monkeypatch):
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps([{"url": "a"}]))
    output_path = tmp_path / "out.json"
    output_path.write_text(json.dumps([{"url": "a"}]))  # already completed

    popen_calls = []
    monkeypatch.setattr(llm_helper.subprocess, "Popen", lambda *a, **kw: popen_calls.append(1))

    llm_helper.run_parallel(input_path, output_path, n_workers=2)

    assert popen_calls == []  # no workers needed


@pytest.mark.web
def test_run_parallel_launches_workers_and_cleans_up_on_success(tmp_path, fake_model_path, monkeypatch):
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps([{"url": "a"}, {"url": "b"}]))
    output_path = tmp_path / "out.json"

    popen_calls = []

    def _fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return _FakeWorkerProcess(returncode=0)

    monkeypatch.setattr(llm_helper.subprocess, "Popen", _fake_popen)

    llm_helper.run_parallel(input_path, output_path, n_workers=2)

    assert len(popen_calls) == 2
    # Workers run the standardizer as a package module from src/, with
    # the same interpreter as this process.
    (command,), kwargs = popen_calls[0]
    assert command[:3] == [sys.executable, "-m", llm_helper.WORKER_MODULE]
    assert kwargs["cwd"] == llm_helper.WORKER_CWD
    # No failures, so every chunk_* file (the input slices we really did
    # write, since no real worker ran to produce .jsonl output) is cleaned up.
    assert list(llm_helper.STATE_DIR.glob("chunk_*")) == []


@pytest.mark.web
def test_run_parallel_avoids_colliding_with_leftover_chunk_names(tmp_path, fake_model_path, monkeypatch):
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps([{"url": "a"}]))
    output_path = tmp_path / "out.json"
    llm_helper.STATE_DIR.mkdir(parents=True)
    (llm_helper.STATE_DIR / "chunk_0_0.json").write_text("[]")  # forces run_id to skip 0

    launched_paths = []

    def _fake_popen(args, **kwargs):
        launched_paths.append(args[args.index("--file") + 1])
        return _FakeWorkerProcess(returncode=0)

    monkeypatch.setattr(llm_helper.subprocess, "Popen", _fake_popen)

    llm_helper.run_parallel(input_path, output_path, n_workers=1)

    assert all("chunk_1_" in path for path in launched_paths)


@pytest.mark.web
def test_run_parallel_reports_failed_chunks_and_skips_cleanup(tmp_path, fake_model_path, monkeypatch, capsys):
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps([{"url": "a"}]))
    output_path = tmp_path / "out.json"

    monkeypatch.setattr(llm_helper.subprocess, "Popen", lambda *a, **kw: _FakeWorkerProcess(returncode=1))

    llm_helper.run_parallel(input_path, output_path, n_workers=1)

    assert "chunks failed" in capsys.readouterr().out
    # Leftover chunk_* files remain since this run had a failure.
    assert list(llm_helper.STATE_DIR.glob("chunk_*")) != []


@pytest.mark.web
def test_run_parallel_terminates_workers_and_reraises_on_interrupt(tmp_path, fake_model_path, monkeypatch):
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps([{"url": "a"}]))
    output_path = tmp_path / "out.json"

    interrupting_process = _FakeWorkerProcess(wait_effects=[KeyboardInterrupt()])
    monkeypatch.setattr(llm_helper.subprocess, "Popen", lambda *a, **kw: interrupting_process)

    with pytest.raises(KeyboardInterrupt):
        llm_helper.run_parallel(input_path, output_path, n_workers=1)

    assert interrupting_process.terminated


@pytest.mark.web
def test_run_parallel_force_kills_worker_that_wont_terminate(tmp_path, fake_model_path, monkeypatch):
    """If a worker doesn't exit within _terminate_workers()'s own timeout
    after being asked to, it should be force-killed."""
    input_path = tmp_path / "in.json"
    input_path.write_text(json.dumps([{"url": "a"}]))
    output_path = tmp_path / "out.json"

    stubborn_process = _FakeWorkerProcess(wait_effects=[
        KeyboardInterrupt(),  # the initial wait, in the main try block
        subprocess.TimeoutExpired(cmd="app.py", timeout=15),  # _terminate_workers' own wait
        None,  # the wait() right after kill() succeeds
    ])
    monkeypatch.setattr(llm_helper.subprocess, "Popen", lambda *a, **kw: stubborn_process)

    with pytest.raises(KeyboardInterrupt):
        llm_helper.run_parallel(input_path, output_path, n_workers=1)

    assert stubborn_process.terminated
    assert stubborn_process.killed


@pytest.mark.web
def test_main_delegates_to_run_parallel(monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm_helper, "run_parallel",
        lambda inp, outp, workers, threads, key: calls.append((inp, outp, workers, threads, key)),
    )
    args = SimpleNamespace(input_path="in.json", output_path="out.json", n_workers=2, n_threads=1, key="url")

    llm_helper.main(args)

    assert calls == [("in.json", "out.json", 2, 1, "url")]
