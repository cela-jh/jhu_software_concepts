"""
`llm_helper.py`
General-purpose helper functions supporting the LLM standardizer (`app.py`):
running it in parallel across multiple worker processes, with crash/interrupt-safe
resume based on each row's unique `url`.
"""

import json
import os
import subprocess
from pathlib import Path

WORK_DIR = Path(__file__).parent

# Holds transient per-worker files only. chunk_<i>.json is a worker's input
# slice, a copy of rows still needing processing. chunk_<i>.jsonl is that
# worker's incremental JSON Lines output, flushed to disk after every row.
# Neither the input file nor the final output file is ever written here.
# This directory is consulted on every run, so rows already written to a
# chunk's .jsonl file from a run that crashed or was interrupted before
# merging are never reprocessed. Chunk files are deleted one at a time,
# only after their rows have been safely merged into the real output file.
STATE_DIR = WORK_DIR / ".llm_state"


def _read_jsonl(path):
    """
    Reads a JSON Lines file.
    Returns a list of the parsed row dicts.
    """
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _safe_write_json(rows, output_path):
    """
    Writes rows to output_path as a pretty-printed JSON array. Refuses to
    overwrite an existing, larger result with a smaller or empty one,
    raising instead. Writes via a temp file and an atomic rename, so a
    crash mid-write can never leave a truncated or corrupted file in its
    place. Returns none.
    """
    output_path = Path(output_path)
    if output_path.is_file():
        try:
            existing = json.loads(output_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []
        if isinstance(existing, list) and len(rows) < len(existing):
            raise RuntimeError(
                f"Refusing to overwrite {output_path} ({len(existing)} rows) with "
                f"a smaller result ({len(rows)} rows). Investigate before retrying."
            )

    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        json.dump(rows, f, indent=2)
    os.replace(tmp_path, output_path)


def jsonl_to_json(jsonl_path, json_path):
    """
    Converts a JSON Lines file into a single JSON array file.
    Returns none.
    """
    rows = _read_jsonl(jsonl_path)
    with open(json_path, "w") as f:
        json.dump(rows, f, indent=2)


def _load_completed(output_path, key):
    """
    Gathers every row already known to be done, keyed by `key`, typically
    "url". Includes rows already merged into output_path, plus rows sitting
    in any leftover chunk_*.jsonl file in STATE_DIR from a prior run that
    crashed or was interrupted before its results were merged. Returns a
    dict mapping each key value to its row.
    """
    completed = {}

    output_path = Path(output_path)
    if output_path.is_file():
        try:
            existing = json.loads(output_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []
        for row in existing if isinstance(existing, list) else []:
            k = row.get(key)
            if k is not None:
                completed[k] = row

    if STATE_DIR.is_dir():
        for chunk_path in sorted(STATE_DIR.glob("chunk_*.jsonl")):
            for row in _read_jsonl(chunk_path):
                k = row.get(key)
                if k is not None:
                    completed[k] = row

    return completed


def _merge_and_write(output_path, key):
    """
    Recomputes the completed set from output_path and STATE_DIR chunk
    files, then atomically writes it to output_path. Returns the merged
    row count.
    """
    completed = _load_completed(output_path, key)
    _safe_write_json(list(completed.values()), output_path)
    return len(completed)


def run_parallel(input_path, output_path, n_workers=4, n_threads=1, key="url"):
    """
    Reads input_path and standardizes every row not already present by url
    in output_path or in a leftover chunk_*.jsonl state file. Splits the
    remaining rows across n_workers app.py subprocesses, each writing its
    own chunk_<i>.jsonl in STATE_DIR incrementally.

    Workers default to GPU offload through Metal rather than CPU-only.
    Benchmarking on this machine found GPU offload runs roughly 35 times
    faster per call than single-threaded CPU, and aggregate throughput
    across concurrent workers saturates around 4 workers. Going wider than
    that adds queueing latency per call without further aggregate gain,
    unlike the CPU-only path, where more workers scales roughly linearly.
    Set N_GPU_LAYERS=0 in the calling environment to force CPU-only workers
    instead, such as on a machine without a usable GPU backend.

    Safe to interrupt with Ctrl+C or to kill. On interrupt, already-running
    workers are asked to terminate, then whatever they wrote is merged into
    output_path before returning, so re-running this function with the same
    arguments picks up exactly where it left off. Never deletes or writes
    to input_path. Never deletes output_path, only atomically replaces it
    with a merged version that is never smaller. STATE_DIR chunk files are
    deleted only after their rows are confirmed merged into output_path.

    Raises FileNotFoundError if input_path does not exist, and ValueError
    if it does not contain a JSON array of row objects.

    Returns none.
    """
    input_path = Path(input_path)
    if not input_path.is_file():
        raise FileNotFoundError(
            f"Input file {input_path} does not exist. Check the path and try again."
        )

    from app import _get_model_path
    _get_model_path()  # download once before workers race on it

    STATE_DIR.mkdir(exist_ok=True)

    with open(input_path) as f:
        rows = json.load(f)
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError(
            f"{input_path} must contain a JSON array of row objects. "
            "Check that the file was produced by the scraper and was not truncated."
        )

    completed = _load_completed(output_path, key)
    remaining = [r for r in rows if r.get(key) not in completed]

    print(f"{len(completed)} rows already completed, {len(remaining)} remaining "
          f"-> splitting across {n_workers} workers")

    if not remaining:
        _merge_and_write(output_path, key)
        return

    chunk_size = -(-len(remaining) // n_workers)  # ceiling division
    chunks = [remaining[i:i + chunk_size] for i in range(0, len(remaining), chunk_size)]

    # Fresh, collision-free names each run so a chunk file left behind by a
    # prior interrupted run is never overwritten before it has been folded
    # into `completed` above.
    run_id = 0
    while list(STATE_DIR.glob(f"chunk_{run_id}_*.json*")):
        run_id += 1

    procs = []  # (chunk_index, Popen) pairs
    env = {
        **os.environ,
        "N_THREADS": str(n_threads),
        "VECLIB_MAXIMUM_THREADS": str(n_threads),  # macOS Accelerate/vecLib backend
        "OMP_NUM_THREADS": str(n_threads),
        "OPENBLAS_NUM_THREADS": str(n_threads),
        "N_GPU_LAYERS": os.environ.get("N_GPU_LAYERS", "99"),
    }

    def _launch_all():
        for i, chunk in enumerate(chunks):
            chunk_in_path = STATE_DIR / f"chunk_{run_id}_{i}.json"
            chunk_out_path = STATE_DIR / f"chunk_{run_id}_{i}.jsonl"
            chunk_in_path.write_text(json.dumps(chunk))
            procs.append((i, subprocess.Popen(
                ["python", "app.py", "--file", str(chunk_in_path),
                 "--out", str(chunk_out_path), "--append"],
                cwd=WORK_DIR,
                env=env,
            )))

    def _terminate_all():
        for _, p in procs:
            if p.poll() is None:
                p.terminate()
        for _, p in procs:
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()

    try:
        _launch_all()
        failed_chunks = []
        for i, p in procs:
            p.wait()
            if p.returncode != 0:
                failed_chunks.append(i)
    except (KeyboardInterrupt, SystemExit):
        print("\nInterrupted - stopping workers and saving progress so far...")
        _terminate_all()
        merged_count = _merge_and_write(output_path, key)
        print(f"Progress saved: {merged_count} rows total in {output_path}. "
              f"Re-run with the same arguments to continue.")
        raise

    if failed_chunks:
        print(f"Warning: {len(failed_chunks)} of {len(chunks)} chunks failed "
              f"(chunks {failed_chunks}); their results may be incomplete. "
              f"Re-run to retry the missing rows.")

    merged_count = _merge_and_write(output_path, key)
    print(f"Merged {merged_count} total rows into {output_path}")

    if not failed_chunks:
        # Everything in STATE_DIR is now folded into output_path, including
        # leftovers from any earlier crashed or interrupted run, so all of
        # it is safe to remove, not just this run's own chunk files.
        for path in STATE_DIR.glob("chunk_*"):
            path.unlink(missing_ok=True)


def parse_args():
    """
    Parses CLI arguments for running the parallel standardizer directly.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the LLM standardizer in parallel across multiple worker processes."
    )
    parser.add_argument("input_path", type=Path, help="Input JSON file (list of result rows).")
    parser.add_argument("output_path", type=Path, help="Path to write the merged, standardized JSON output.")
    parser.add_argument("--n_workers", type=int, default=4, help="Number of parallel worker processes (default: 4).")
    parser.add_argument("--n_threads", type=int, default=1, help="Threads per worker process (default: 1, to avoid CPU oversubscription).")
    parser.add_argument("--key", default="url", help="Row field used as the unique identifier for resume/dedup (default: url).")
    return parser.parse_args()


def main(args):
    run_parallel(args.input_path, args.output_path, args.n_workers, args.n_threads, args.key)


if __name__ == "__main__":
    main(parse_args())
