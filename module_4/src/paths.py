"""
`paths.py`
Filesystem locations shared across GradCafeAnalytics, resolved relative to
this file so they hold regardless of the current working directory or how
a script here is invoked.
"""
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

SCRAPE_SCRIPT = PACKAGE_DIR / "scraping" / "scrape.py"

DATA_DIR = PROJECT_DIR / "data"
STATE_DIR = DATA_DIR / ".state"

DEFAULT_DATA_FILE = DATA_DIR / "applicant_data.json"
DEFAULT_LLM_DATA_FILE = DATA_DIR / "llm_extend_applicant_data.json"


def state_path_for(data_filepath):
    """
    Returns the sidecar state-file path in STATE_DIR matching the given
    data file's basename, creating STATE_DIR if it doesn't exist yet.
    Returns a Path.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / Path(data_filepath).with_suffix(".state.json").name
