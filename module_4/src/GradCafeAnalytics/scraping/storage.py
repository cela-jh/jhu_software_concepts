"""
`storage.py`
Includes functions to save to and load data from JSON.
"""
import json
import os
from pathlib import Path


def save_data(parsed_results, filepath):
    """
    Takes a single page's list of parsed results dictionaries and appends
    them to the existing JSON array on disk. Builds the new file's full
    contents in a temp file, reusing the existing file's data plus the newly 
    appended rows before atomically replacing the original. A crash or interrupt
    can only ever be caught before or after the replace.
    Returns none.
    """
    items_json = ",\n".join(json.dumps(r, indent=2) for r in parsed_results)
    is_new = not filepath.exists() or filepath.stat().st_size == 0
    tmp_path = filepath.with_suffix(filepath.suffix + ".tmp")

    if is_new:
        prefix = b"[\n"
        body = items_json
    else:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(0)
            prefix = f.read(size - 2)  # drop trailing "\n]"
        body = ",\n" + items_json

    with open(tmp_path, "wb") as f:
        f.write(prefix)
        f.write(body.encode("utf-8"))
        f.write(b"\n]")

    os.replace(tmp_path, filepath)


def load_existing_urls(filepath):
    """
    Reads the `url` field of every row already saved in filepath, if it
    exists. Used to skip re-scraping/duplicating rows already on disk when
    growing a results file that a prior run already completed.
    Returns a set of urls (empty if the file doesn't exist yet or is empty).
    """
    if not filepath.exists() or filepath.stat().st_size == 0:
        return set()
    with open(filepath) as f:
        data = json.load(f)
    return {row["url"] for row in data if row.get("url")}


def validate_filepath(filepath, must_exist=False):
    """
    Validates a filepath from the CLI so it can be used to save or load data.
    File must be JSON.
    Returns none if valid, else raises an error.
    """
    if not isinstance(filepath, Path):
        raise TypeError(f"Expected a Path object, got {type(filepath).__name__}")
    if filepath.suffix != ".json":
        raise ValueError(f"'{filepath}' is not a JSON file")
    if must_exist and not filepath.is_file():
        raise FileNotFoundError(f"'{filepath}' does not exist")


def save_state(state, filepath):
    """
    Writes scrape progress state (next URL) to a sidecar file.
    Returns none.
    """
    with open(filepath, "w") as f:
        json.dump(state, f)


def load_state(filepath):
    """
    Loads scrape progress state if it exists.
    Returns the state dict, or None if no state file exists.
    """
    if not filepath.is_file():
        return None
    with open(filepath) as f:
        return json.load(f)
