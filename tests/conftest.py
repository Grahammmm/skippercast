"""pytest wiring for tests/: layer markers and the GIS collection rule (see tests/_support.py)."""
import os
from pathlib import Path

from tests import _support

HERE = Path(__file__).resolve().parent


def pytest_ignore_collect(collection_path, config):
    return True if _support.ignore_gis_directory(collection_path) else None


def pytest_collection_modifyitems(config, items):
    _support.mark_items(items, HERE)


def pytest_report_header(config):
    missing = _support.missing_gis_packages()
    if not missing:
        return 'GIS stack: installed (gis tests collected)'
    if os.environ.get(_support.REQUIRE_GIS) == '1':
        return f'GIS stack: MISSING {", ".join(missing)} ({_support.REQUIRE_GIS}=1, gis modules will fail to import)'
    return f'GIS stack: not installed (missing {", ".join(missing)}); gis/ directories not collected'
