"""
`paths.py`
Filesystem locations shared across GradCafeAnalytics, resolved relative to
this file so they hold regardless of the current working directory or how
a script here is invoked.
"""
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

DATA_DIR = PROJECT_DIR / "data"
STATE_DIR = DATA_DIR / ".state"

DEFAULT_DATA_FILE = DATA_DIR / "applicant_data.json"
DEFAULT_LLM_DATA_FILE = DATA_DIR / "llm_extend_applicant_data.json"


def state_path_for(data_filepath):
    """
    Return the sidecar state-file path in STATE_DIR matching the given
    data file's basename, creating STATE_DIR if it doesn't exist yet.

    :param data_filepath: Path to the data file this state file tracks.
    :type data_filepath: str or pathlib.Path
    :returns: Path to the corresponding `.state.json` file in STATE_DIR.
    :rtype: pathlib.Path
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / Path(data_filepath).with_suffix(".state.json").name
