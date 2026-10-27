"""Exercise core-only collection while scientific packages are unavailable.

This is an import-denial simulation, not an assertion about installed packages.
Run from the checkout with PYTHONPATH=src python tests/coast_no_gis_probe.py.
"""
import importlib.abc
import importlib.util
import sys
from pathlib import Path

# A file invocation sets sys.path[0] to tests/, not the checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

GIS = {'pyproj', 'rasterio', 'shapely', 'h5py', 'numpy', 'scipy'}


class NoGIS(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in GIS:
            raise ModuleNotFoundError('no-GIS verification: ' + fullname, name=fullname)


if __name__ == '__main__':
    original_find_spec = importlib.util.find_spec
    importlib.util.find_spec = lambda name, package=None: None if name.split('.')[0] in GIS else original_find_spec(name, package)
    sys.meta_path.insert(0, NoGIS())
    raise SystemExit(pytest.main(['-q', '--disable-warnings',
        'tests/unit/test_coast_contracts.py', 'tests/unit/test_coast_native_contracts.py',
        'tests/unit/test_coast_projection_portability.py', 'tests/unit/test_coast_sign_off.py',
        'tests/contract/test_research_boundary.py']))
