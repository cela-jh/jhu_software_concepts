"""
`data.py`
Includes functions to save to and load data from JSON.
"""
import json
from pathlib import Path


def save_data(parsed_results, filepath):
    """
    Takes a single page's list of parsed results dictionaries and writes them 
    to JSON. This is called after each clean operation and appends to a file.
    Returns none.
    """
    # result gets seralized to JSON, then adds a comma and newline between each
    items_json = ",\n".join(json.dumps(r, indent=2) for r in parsed_results)
    is_new = not filepath.exists() or filepath.stat().st_size == 0

    # if file doesn't exist or has no data
    if is_new:
        with open(filepath, "w") as f:
            f.write("[\n" + items_json + "\n]")
    else:
        with open(filepath, "r+") as f:
            f.seek(0, 2)            # point to the end of file to begin appending
            f.seek(f.tell() - 2)    # moves pointer before last newline"
            f.truncate()            # deletes the newline and closing array bracket
            new_data = ",\n" + items_json + "\n]"
            f.write(new_data)


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
    Writes scrape progress state (next URL, result count) to a sidecar file.
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
