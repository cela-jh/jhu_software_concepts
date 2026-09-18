# -*- coding: utf-8 -*-
"""Flask + tiny local LLM standardizer with incremental JSONL CLI output."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import difflib
from pathlib import Path
from typing import Any, Dict, List, Tuple

from flask import Flask, jsonify, request
from huggingface_hub import hf_hub_download
from llama_cpp import Llama  # CPU-only by default if N_GPU_LAYERS=0

from llm_helper import run_parallel

app = Flask(__name__)

# ---------------- Model config ----------------
MODEL_REPO = os.getenv(
    "MODEL_REPO",
    "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
)
MODEL_FILE = os.getenv(
    "MODEL_FILE",
    "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
)

N_THREADS = int(os.getenv("N_THREADS", str(os.cpu_count() or 2)))
N_CTX = int(os.getenv("N_CTX", "1024"))
N_GPU_LAYERS = int(os.getenv("N_GPU_LAYERS", "0"))  # 0 → CPU-only

CANON_UNIS_PATH = os.getenv("CANON_UNIS_PATH", "canon_universities.txt")
CANON_PROGS_PATH = os.getenv("CANON_PROGS_PATH", "canon_programs.txt")

# Precompiled, non-greedy JSON object matcher to tolerate chatter around JSON
JSON_OBJ_RE = re.compile(r"\{.*?\}", re.DOTALL)

# ---------------- Canonical lists + abbrev maps ----------------
def _read_lines(path: str) -> List[str]:
    """Read non-empty, stripped lines from a file (UTF-8)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except FileNotFoundError:
        return []


CANON_UNIS = _read_lines(CANON_UNIS_PATH)
CANON_PROGS = _read_lines(CANON_PROGS_PATH)

# Maps each canonical name's lowercase form back to its properly-cased form,
# so lookups can match case-insensitively while still returning the
# canonical casing. Without this, an output like "Eth Zurich" never matches
# the canonical "ETH Zurich" entry because both the exact-match and fuzzy
# comparisons below are case-sensitive.
CANON_UNIS_LOWER: Dict[str, str] = {name.lower(): name for name in CANON_UNIS}
CANON_PROGS_LOWER: Dict[str, str] = {name.lower(): name for name in CANON_PROGS}

ABBREV_UNI: Dict[str, str] = {
    r"(?i)^mcg(\.|ill)?$": "McGill University",
    r"(?i)^(ubc|u\.?b\.?c\.?)$": "University of British Columbia",
    r"(?i)^uoft$": "University of Toronto",
}

COMMON_UNI_FIXES: Dict[str, str] = {
    "McGiill University": "McGill University",
    "Mcgill University": "McGill University",
    # Normalize 'Of' → 'of'
    "University Of British Columbia": "University of British Columbia",
}

COMMON_PROG_FIXES: Dict[str, str] = {
    "Mathematic": "Mathematics",
    "Info Studies": "Information Studies",
}

# ---------------- Few-shot prompt ----------------
SYSTEM_PROMPT = (
    "You are a data cleaning assistant. Standardize degree program and university "
    "names.\n\n"
    "Rules:\n"
    "- Input provides a single string under key `program` that may contain both "
    "program and university.\n"
    "- Split into (program name, university name).\n"
    "- Trim extra spaces and commas.\n"
    "- Keep the program name's wording as given. Only fix spelling and "
    "capitalization; never rephrase, generalize, or substitute different "
    "words for it.\n"
    '- Expand obvious abbreviations (e.g., "McG" -> "McGill University", '
    '"UBC" -> "University of British Columbia").\n'
    "- Use Title Case for program; use official capitalization for university "
    "names (e.g., \"University of X\").\n"
    '- Ensure correct spelling (e.g., "McGill", not "McGiill").\n'
    '- If university cannot be inferred, return the original university name.\n\n'
    "Return JSON ONLY with keys:\n"
    "  llm_generated_program, llm_generated_university\n"
)

FEW_SHOTS: List[Tuple[Dict[str, str], Dict[str, str]]] = [
    (
        {"program": "Information Studies, McGill University"},
        {
            "llm_generated_program": "Information Studies",
            "llm_generated_university": "McGill University",
        },
    ),
    (
        {"program": "Information, McG"},
        {
            "llm_generated_program": "Information Studies",
            "llm_generated_university": "McGill University",
        },
    ),
    (
        {"program": "Mathematics, University Of British Columbia"},
        {
            "llm_generated_program": "Mathematics",
            "llm_generated_university": "University of British Columbia",
        },
    ),
    (
        {"program": "Comparative Literature, New York University"},
        {
            "llm_generated_program": "Comparative Literature",
            "llm_generated_university": "New York University",
        },
    ),
    (
        {"program": "Landscape Architecture, University of Pennsylvania"},
        {
            "llm_generated_program": "Landscape Architecture",
            "llm_generated_university": "University of Pennsylvania",
        },
    ),
]

_LLM: Llama | None = None

MODELS_DIR = Path(__file__).parent / "models"


def _get_model_path() -> str:
    """Downloads the GGUF file if not already present, otherwise reuses it."""
    local_path = MODELS_DIR / MODEL_FILE
    if local_path.is_file():
        return str(local_path)
    return hf_hub_download(
        repo_id=MODEL_REPO,
        filename=MODEL_FILE,
        local_dir=str(MODELS_DIR),
    )


def _load_llm() -> Llama:
    """Initialize llama.cpp using the (already downloaded) GGUF file."""
    global _LLM
    if _LLM is not None:
        return _LLM

    model_path = _get_model_path()

    _LLM = Llama(
        model_path=model_path,
        n_ctx=N_CTX,
        n_threads=N_THREADS,
        # llama-cpp-python defaults n_threads_batch to multiprocessing.cpu_count()
        # when left unset, ignoring N_THREADS entirely for prompt-processing.
        # This causes every worker to burst to a full 14 threads during prefill.
        n_threads_batch=N_THREADS,
        n_gpu_layers=N_GPU_LAYERS,
        verbose=False,
    )
    return _LLM


def _split_fallback(text: str) -> Tuple[str, str]:
    """Simple, rules-first parser if the model returns non-JSON."""
    s = re.sub(r"\s+", " ", (text or "")).strip().strip(",")
    parts = [p.strip() for p in re.split(r",| at | @ ", s) if p.strip()]
    prog = parts[0] if parts else ""
    uni = parts[1] if len(parts) > 1 else ""

    # High-signal expansions
    if re.fullmatch(r"(?i)mcg(ill)?(\.)?", uni or ""):
        uni = "McGill University"
    if re.fullmatch(
        r"(?i)(ubc|u\.?b\.?c\.?|university of british columbia)",
        uni or "",
    ):
        uni = "University of British Columbia"

    # Title-case program; normalize 'Of' → 'of' for universities
    prog = prog.title()
    if uni:
        uni = re.sub(r"\bOf\b", "of", uni.title())
    return prog, uni


def _best_match(name: str, lower_map: Dict[str, str], cutoff: float) -> str | None:
    """Fuzzy match a name against a lowercase-to-canonical map, case-insensitively."""
    if not name or not lower_map:
        return None
    matches = difflib.get_close_matches(name.lower(), lower_map.keys(), n=1, cutoff=cutoff)
    return lower_map[matches[0]] if matches else None


def _post_normalize_program(prog: str) -> str:
    """Apply common fixes, title case, then canonical/fuzzy mapping."""
    p = (prog or "").strip()
    p = COMMON_PROG_FIXES.get(p, p)
    p = p.title()
    canon_match = CANON_PROGS_LOWER.get(p.lower())
    if canon_match:
        return canon_match
    match = _best_match(p, CANON_PROGS_LOWER, cutoff=0.84)
    return match or p


def _post_normalize_university(uni: str) -> str:
    """Expand abbreviations, apply common fixes, capitalization, and canonical map."""
    u = (uni or "").strip()

    # Abbreviations
    for pat, full in ABBREV_UNI.items():
        if re.fullmatch(pat, u):
            u = full
            break

    # Common spelling fixes
    u = COMMON_UNI_FIXES.get(u, u)

    # Normalize 'Of' → 'of'
    if u:
        u = re.sub(r"\bOf\b", "of", u.title())

    # Canonical or fuzzy map
    canon_match = CANON_UNIS_LOWER.get(u.lower())
    if canon_match:
        return canon_match
    match = _best_match(u, CANON_UNIS_LOWER, cutoff=0.86)
    return match or u


def _call_llm(program_text: str) -> Dict[str, str]:
    """Query the tiny LLM and return standardized fields."""
    llm = _load_llm()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for x_in, x_out in FEW_SHOTS:
        messages.append(
            {"role": "user", "content": json.dumps(x_in, ensure_ascii=False)}
        )
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(x_out, ensure_ascii=False),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": json.dumps({"program": program_text}, ensure_ascii=False),
        }
    )

    out = llm.create_chat_completion(
        messages=messages,
        temperature=0.0,
        max_tokens=64,
        top_p=1.0,
        stop=["}"],
    )

    text = (out["choices"][0]["message"]["content"] or "").strip()
    # llama.cpp excludes a matched stop string from the returned text, so
    # the "}" that ended generation early needs restoring before JSON parsing
    if out["choices"][0].get("finish_reason") == "stop":
        text += "}"
    try:
        match = JSON_OBJ_RE.search(text)
        obj = json.loads(match.group(0) if match else text)
        std_prog = str(obj.get("llm_generated_program", "")).strip()
        std_uni = str(obj.get("llm_generated_university", "")).strip()
    except Exception:
        std_prog, std_uni = _split_fallback(program_text)

    if not std_uni:
        std_uni = program_text

    std_prog = _post_normalize_program(std_prog)
    std_uni = _post_normalize_university(std_uni)
    return {
        "llm_generated_program": std_prog,
        "llm_generated_university": std_uni,
    }


def _normalize_input(payload: Any) -> List[Dict[str, Any]]:
    """Accept either a list of rows or {'rows': [...]}."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]
    return []


@app.get("/")
def health() -> Any:
    """Simple liveness check."""
    return jsonify({"ok": True})


@app.post("/standardize")
def standardize() -> Any:
    """Standardize rows from an HTTP request and return JSON."""
    payload = request.get_json(force=True, silent=True)
    rows = _normalize_input(payload)

    out: List[Dict[str, Any]] = []
    for row in rows:
        program_text = (row or {}).get("program") or ""
        result = _call_llm(program_text)
        row["llm-generated-program"] = result["llm_generated_program"]
        row["llm-generated-university"] = result["llm_generated_university"]
        out.append(row)

    return jsonify({"rows": out})


def _format_duration(seconds: float) -> str:
    """Render a seconds count as H:MM:SS (or M:SS under an hour)."""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _cli_process_file(
    in_path: str,
    out_path: str | None,
    append: bool,
    to_stdout: bool,
) -> None:
    """Process a JSON file and write JSONL incrementally."""
    with open(in_path, "r", encoding="utf-8") as f:
        rows = _normalize_input(json.load(f))

    sink = sys.stdout if to_stdout else None
    if not to_stdout:
        out_path = out_path or (in_path + ".jsonl")
        mode = "a" if append else "w"
        sink = open(out_path, mode, encoding="utf-8")

    assert sink is not None  # for type-checkers

    total = len(rows)
    elapsed_total = 0.0
    pid = os.getpid()

    try:
        for i, row in enumerate(rows, start=1):
            start = time.monotonic()

            program_text = (row or {}).get("program") or ""
            result = _call_llm(program_text)
            row["llm-generated-program"] = result["llm_generated_program"]
            row["llm-generated-university"] = result["llm_generated_university"]

            json.dump(row, sink, ensure_ascii=False)
            sink.write("\n")
            sink.flush()  # persist this row to disk before moving on, so a
            # crash or interrupt on the next row never loses one already written

            elapsed_total += time.monotonic() - start
            avg = elapsed_total / i
            remaining = total - i
            eta = _format_duration(avg * remaining)
            url = (row or {}).get("url", "")
            print(
                f"[pid {pid}] wrote record {i}/{total} "
                f"(url={url}) | avg {avg:.2f}s/record | "
                f"ETA for this worker: {eta}",
                flush=True,
            )
    finally:
        if sink is not sys.stdout:
            sink.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Standardize program/university with a tiny local LLM.",
    )
    parser.add_argument(
        "--file",
        help="Path to JSON input (list of rows or {'rows': [...]})",
        default=None,
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run the HTTP server instead of CLI.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path for JSON Lines (ndjson). "
        "Defaults to <input>.jsonl when --file is set.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to the output file instead of overwriting.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write JSON Lines to stdout instead of a file.",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Split the input across multiple worker subprocesses for faster "
        "processing. Output is a single JSON array, not JSON Lines.",
    )
    parser.add_argument(
        "--n_workers",
        type=int,
        default=4,
        help="Number of parallel worker processes when --parallel is set (default: 4 - "
        "workers use GPU offload by default and aggregate throughput saturates "
        "around 4 concurrent workers; going wider adds per-call latency with no "
        "further gain).",
    )
    parser.add_argument(
        "--n_threads",
        type=int,
        default=1,
        help="Threads per worker process when --parallel is set (default: 1, "
        "to avoid CPU oversubscription).",
    )
    args = parser.parse_args()

    if args.serve or args.file is None:
        port = int(os.getenv("PORT", "8000"))
        app.run(host="0.0.0.0", port=port, debug=False)
    elif args.parallel:
        out_path = args.out or (args.file + ".json")
        run_parallel(args.file, out_path, args.n_workers, args.n_threads)
    else:
        _cli_process_file(
            in_path=args.file,
            out_path=args.out,
            append=bool(args.append),
            to_stdout=bool(args.stdout),
        )
