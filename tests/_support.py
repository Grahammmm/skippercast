"""Shared helpers for the Python test layers (``tests/`` and ``research/tests/``).

Tests import ``ROOT`` and ``FIXTURES`` from here instead of computing paths from
``__file__``, so a module can move between layers without changing what it reads.
The layer hooks are used by ``tests/conftest.py`` and ``research/tests/conftest.py``.
See docs/engineering/testing.md.
"""
import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures'

# Top-level import names installed by requirements-survey.txt (the `survey` extra).
# Every test under a `gis/` directory may import any of them at module level.
GIS_PACKAGES = ('affine', 'h5py', 'laspy', 'lazrs', 'lerc', 'numpy', 'pyproj', 'pypdf',
                'rasterio', 'scipy', 'shapefile', 'shapely')
# Set by the survey-science CI job: a missing package is then an error, not a quiet omission.
REQUIRE_GIS = 'SKIPPERCAST_REQUIRE_GIS'
# Opt in to tests marked `network`; every other run is offline.
ALLOW_NETWORK = 'SKIPPERCAST_NETWORK'


def missing_gis_packages():
    return [name for name in GIS_PACKAGES if importlib.util.find_spec(name) is None]


def is_gis_path(path):
    return 'gis' in Path(path).parts


def ignore_gis_directory(collection_path):
    """True for a `gis/` test directory when the survey stack is absent (and not required).

    Without the packages those modules cannot even be imported, so they are left
    out of collection instead of failing it; `pytest -m "not gis"` then selects the
    same tests whether or not the packages happen to be installed.
    """
    if os.environ.get(REQUIRE_GIS) == '1':
        return False
    path = Path(collection_path)
    return path.is_dir() and path.name == 'gis' and bool(missing_gis_packages())


def mark_items(items, base, claims=False):
    """Apply the directory-derived markers to the items collected under ``base``."""
    import pytest
    base = Path(base).resolve()
    for item in items:
        path = Path(str(item.path)).resolve()
        if base not in path.parents:
            continue
        relative = path.relative_to(base)
        if claims:
            item.add_marker(pytest.mark.claims)
        if is_gis_path(relative):
            item.add_marker(pytest.mark.gis)
        if 'network' in item.keywords and os.environ.get(ALLOW_NETWORK) != '1':
            item.add_marker(pytest.mark.skip(reason=f'network test; set {ALLOW_NETWORK}=1 to run'))
