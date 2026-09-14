"""
`llm_helper.py`
General-purpose helper functions supporting the LLM standardizer (`app.py`):
running it in parallel across multiple worker processes, and converting its
JSON Lines output into a single JSON array file.
"""

import json
import os
import subprocess
from pathlib import Path


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
    overwrite an existing, larger result with a smaller/empty one (raising
    instead), and writes via a temp file + atomic rename so a crash
    mid-write can never leave a truncated or corrupted file in its place.
    Returns none.
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


def split_and_run(input_path, output_path, n_workers=12, n_threads=1):
    """
    Splits input_path's JSON array into n_workers chunks, runs app.py on each
    chunk in a separate subprocess (capped to n_threads each, across every
    thread pool that respects it, to avoid CPU oversubscription). Chunks that
    already have partial output (e.g. from a prior interrupted run) resume
    from where they left off instead of reprocessing completed rows. Merges
    the resulting JSONL outputs into a single JSON array at output_path.
    Returns none.
    """
    from app import _get_model_path
    _get_model_path()  # download once before workers race on it

    work_dir = Path(__file__).parent

    with open(input_path) as f:
        rows = json.load(f)

    chunk_size = -(-len(rows) // n_workers)  # ceiling division
    chunks = [rows[i:i + chunk_size] for i in range(0, len(rows), chunk_size)]

    chunk_in_paths = []
    chunk_out_paths = []
    procs = []  # (chunk_index, Popen) pairs
    env = {
        **os.environ,
        "N_THREADS": str(n_threads),
        "VECLIB_MAXIMUM_THREADS": str(n_threads),  # macOS Accelerate/vecLib backend
        "OMP_NUM_THREADS": str(n_threads),
        "OPENBLAS_NUM_THREADS": str(n_threads),
    }

    for i, chunk in enumerate(chunks):
        chunk_out_path = work_dir / f"chunk_{i}.jsonl"
        already_done = len(_read_jsonl(chunk_out_path)) if chunk_out_path.is_file() else 0
        remaining = chunk[already_done:]

        chunk_in_path = work_dir / f"chunk_{i}.json"
        chunk_in_paths.append(chunk_in_path)
        chunk_out_paths.append(chunk_out_path)

        if not remaining:
            continue  # this chunk was already fully completed in a prior run

        chunk_in_path.write_text(json.dumps(remaining))
        procs.append((i, subprocess.Popen(
            ["python", "app.py", "--file", str(chunk_in_path), "--out", str(chunk_out_path), "--append"],
            cwd=work_dir,
            env=env,
        )))

    failed_chunks = []
    for i, p in procs:
        p.wait()
        if p.returncode != 0:
            failed_chunks.append(i)

    if failed_chunks:
        print(f"Warning: {len(failed_chunks)} of {len(chunks)} chunks failed "
              f"(chunks {failed_chunks}); their results may be incomplete in the output.")

    # merge chunk_*.jsonl outputs into one combined JSON array
    merged = []
    for chunk_out_path in chunk_out_paths:
        merged.extend(_read_jsonl(chunk_out_path))

    _safe_write_json(merged, output_path)

    # clean up temp chunk files
    for path in chunk_in_paths + chunk_out_paths:
        path.unlink()


def repartition_and_scale(input_path, output_path, old_n_workers, new_n_workers, n_threads=1):
    """
    One-time recovery/scale-up step: gathers each old chunk's not-yet-
    processed rows (based on existing chunk_i.jsonl progress from a prior
    run with old_n_workers), pools them together, re-splits that pool into
    new_n_workers fresh chunks, runs those in parallel (each pinned to
    n_threads across every thread pool that respects it), then merges every
    old chunk's already-completed rows together with the new chunks'
    output into a single JSON array at output_path.
    Returns none.
    """
    from app import _get_model_path
    _get_model_path()

    work_dir = Path(__file__).parent

    with open(input_path) as f:
        rows = json.load(f)

    old_chunk_size = -(-len(rows) // old_n_workers)  # ceiling division
    old_chunks = [rows[i:i + old_chunk_size] for i in range(0, len(rows), old_chunk_size)]

    completed = []
    remaining_pool = []
    old_out_paths = []
    old_in_paths = []

    for i, chunk in enumerate(old_chunks):
        old_out_path = work_dir / f"chunk_{i}.jsonl"
        old_in_path = work_dir / f"chunk_{i}.json"
        old_out_paths.append(old_out_path)
        old_in_paths.append(old_in_path)

        done_rows = _read_jsonl(old_out_path) if old_out_path.is_file() else []
        completed.extend(done_rows)
        remaining_pool.extend(chunk[len(done_rows):])

    new_chunk_size = -(-len(remaining_pool) // new_n_workers)
    new_chunks = [remaining_pool[i:i + new_chunk_size] for i in range(0, len(remaining_pool), new_chunk_size)]

    new_in_paths = []
    new_out_paths = []
    procs = []
    env = {
        **os.environ,
        "N_THREADS": str(n_threads),
        "VECLIB_MAXIMUM_THREADS": str(n_threads),
        "OMP_NUM_THREADS": str(n_threads),
        "OPENBLAS_NUM_THREADS": str(n_threads),
    }

    for j, chunk in enumerate(new_chunks):
        if not chunk:
            continue
        new_in_path = work_dir / f"chunk_r{j}.json"
        new_out_path = work_dir / f"chunk_r{j}.jsonl"
        new_in_path.write_text(json.dumps(chunk))
        new_in_paths.append(new_in_path)
        new_out_paths.append(new_out_path)

        procs.append((j, subprocess.Popen(
            ["python", "app.py", "--file", str(new_in_path), "--out", str(new_out_path)],
            cwd=work_dir,
            env=env,
        )))

    failed_chunks = []
    for j, p in procs:
        p.wait()
        if p.returncode != 0:
            failed_chunks.append(j)

    if failed_chunks:
        print(f"Warning: {len(failed_chunks)} of {len(new_chunks)} new chunks failed "
              f"(chunks {failed_chunks}); their results may be incomplete in the output.")

    merged = list(completed)
    for new_out_path in new_out_paths:
        merged.extend(_read_jsonl(new_out_path))

    _safe_write_json(merged, output_path)

    for path in old_out_paths + old_in_paths + new_in_paths + new_out_paths:
        if path.exists():
            path.unlink()


def continue_remaining(input_path, output_path, new_n_workers, n_threads=1, key="url"):
    """
    General-purpose continuation step, safe to call after any number of
    prior partial/repartitioned runs. Identifies already-completed rows by
    matching `key` (a stable per-row identifier, e.g. "url") across every
    existing chunk_*.jsonl file in the llm_hosting directory, rather than
    by position - this stays correct even when rows have already been
    pooled and re-split under more than one prior chunking scheme. Splits
    whatever rows from input_path are NOT yet completed into new_n_workers
    fresh chunks, runs them in parallel (each pinned to n_threads across
    every thread pool that respects it), then merges all previously-
    completed rows together with the newly-completed ones into a single
    JSON array at output_path. Removes every chunk_*.json/.jsonl file once
    done, since after this the merged output_path is the single source of
    truth.
    Returns none.
    """
    from app import _get_model_path
    _get_model_path()

    work_dir = Path(__file__).parent

    with open(input_path) as f:
        rows = json.load(f)

    existing_chunk_paths = sorted(work_dir.glob("chunk_*.jsonl"))
    completed = []
    completed_keys = set()
    for path in existing_chunk_paths:
        for row in _read_jsonl(path):
            k = row.get(key)
            if k is not None and k not in completed_keys:
                completed_keys.add(k)
                completed.append(row)

    remaining = [r for r in rows if r.get(key) not in completed_keys]

    print(f"{len(completed)} rows already completed, {len(remaining)} remaining "
          f"-> splitting across {new_n_workers} workers")

    new_chunk_size = -(-len(remaining) // new_n_workers) if remaining else 0
    new_chunks = [remaining[i:i + new_chunk_size] for i in range(0, len(remaining), new_chunk_size)]

    new_in_paths = []
    new_out_paths = []
    procs = []
    env = {
        **os.environ,
        "N_THREADS": str(n_threads),
        "VECLIB_MAXIMUM_THREADS": str(n_threads),
        "OMP_NUM_THREADS": str(n_threads),
        "OPENBLAS_NUM_THREADS": str(n_threads),
    }

    for j, chunk in enumerate(new_chunks):
        if not chunk:
            continue
        new_in_path = work_dir / f"chunk_c{j}.json"
        new_out_path = work_dir / f"chunk_c{j}.jsonl"
        new_in_path.write_text(json.dumps(chunk))
        new_in_paths.append(new_in_path)
        new_out_paths.append(new_out_path)

        procs.append((j, subprocess.Popen(
            ["python", "app.py", "--file", str(new_in_path), "--out", str(new_out_path)],
            cwd=work_dir,
            env=env,
        )))

    failed_chunks = []
    for j, p in procs:
        p.wait()
        if p.returncode != 0:
            failed_chunks.append(j)

    if failed_chunks:
        print(f"Warning: {len(failed_chunks)} of {len(new_chunks)} chunks failed "
              f"(chunks {failed_chunks}); their results may be incomplete in the output.")

    merged = list(completed)
    for new_out_path in new_out_paths:
        merged.extend(_read_jsonl(new_out_path))

    _safe_write_json(merged, output_path)

    for path in existing_chunk_paths + new_in_paths + new_out_paths:
        if path.exists():
            path.unlink()
    for path in work_dir.glob("chunk_*.json"):
        path.unlink()


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
    parser.add_argument("--n_workers", type=int, default=12, help="Number of parallel worker processes (default: 12).")
    parser.add_argument("--n_threads", type=int, default=1, help="Threads per worker process (default: 1, to avoid CPU oversubscription).")
    return parser.parse_args()


def main(args):
    split_and_run(args.input_path, args.output_path, args.n_workers, args.n_threads)


if __name__ == "__main__":
    main(parse_args())
