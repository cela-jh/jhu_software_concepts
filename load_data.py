"""
`load_data.py`
Takes cleaned applicant data and loads it into a PostgreSQL database
"""
import json


def load_data(filepath):
    """
    Loads and outputs a JSON file to the console.
    Returns none.
    """
    with open(filepath, "r") as f:
        data = json.load(f)

    print(json.dumps(data, indent=2))
    