"""
`storage.py`
Includes functions to save to and load data from JSON.
"""
import json
import os
from pathlib import Path


def save_data(parsed_results, filepath):
    """
    Take a single page's list of parsed results dictionaries and append
    them to the existing JSON array on disk. Builds the new file's full
    contents in a temp file, reusing the existing file's data plus the
    newly appended rows before atomically replacing the original. A
    crash or interrupt can only ever be caught before or after the
    replace.

    :param parsed_results: The page's parsed result dictionaries.
    :type parsed_results: list[dict]
    :param filepath: Path to the JSON file to append to.
    :type filepath: pathlib.Path
    :returns: None.
    :rtype: None
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
    Read the `url` field of every row already saved in filepath, if it
    exists. Used to skip re-scraping/duplicating rows already on disk
    when growing a results file that a prior run already completed.

    :param filepath: Path to the JSON results file to read.
    :type filepath: pathlib.Path
    :returns: The set of urls already saved, empty if the file doesn't
        exist yet or is empty.
    :rtype: set
    """
    if not filepath.exists() or filepath.stat().st_size == 0:
        return set()
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    return {row["url"] for row in data if row.get("url")}


def validate_filepath(filepath, must_exist=False):
    """
    Validate a filepath from the CLI so it can be used to save or load
    data. File must be JSON.

    :param filepath: The filepath to validate.
    :type filepath: pathlib.Path
    :param must_exist: Whether the file must already exist.
    :type must_exist: bool
    :raises TypeError: If filepath isn't a Path object.
    :raises ValueError: If filepath isn't a `.json` file.
    :raises FileNotFoundError: If must_exist is True and the file
        doesn't exist.
    :returns: None.
    :rtype: None
    """
    if not isinstance(filepath, Path):
        raise TypeError(f"Expected a Path object, got {type(filepath).__name__}")
    if filepath.suffix != ".json":
        raise ValueError(f"'{filepath}' is not a JSON file")
    if must_exist and not filepath.is_file():
        raise FileNotFoundError(f"'{filepath}' does not exist")


def save_state(state, filepath):
    """
    Write scrape progress state (next URL) to a sidecar file.

    :param state: The progress state to write.
    :type state: dict
    :param filepath: Path to the sidecar state file.
    :type filepath: pathlib.Path
    :returns: None.
    :rtype: None
    """
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state, f)


def load_state(filepath):
    """
    Load scrape progress state if it exists.

    :param filepath: Path to the sidecar state file.
    :type filepath: pathlib.Path
    :returns: The state dict, or None if no state file exists.
    :rtype: dict or None
    """
    if not filepath.is_file():
        return None
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)
