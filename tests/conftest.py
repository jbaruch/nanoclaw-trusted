import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, relpath: str):
    """Load a hyphenated-filename Python script as a module.

    Tile scripts use kebab-case filenames (e.g. `register-session.py`)
    that aren't valid Python module identifiers, so they can't be
    imported normally. This loader sets up a unique module name per
    call so each test can monkeypatch the module-level constants
    without leaking state across tests."""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
