"""pytest wiring for research/tests/: every test here is a claims pin (marker `claims`);
those under gis/ also need the survey stack (marker `gis`). See tests/_support.py."""
from pathlib import Path

from tests import _support

HERE = Path(__file__).resolve().parent


def pytest_ignore_collect(collection_path, config):
    return True if _support.ignore_gis_directory(collection_path) else None


def pytest_collection_modifyitems(config, items):
    _support.mark_items(items, HERE, claims=True)
