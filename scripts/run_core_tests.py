"""Run dependency-light app tests on every supported core Python version.

Test modules are classified automatically: a module that cannot be imported
because one of the pinned scientific/GIS packages is absent is reported and
left to the separate survey-science CI job, which installs those packages and
runs the entire suite. Any other import failure (a typo, a missing project
module, a non-GIS dependency) still fails this run.

The classification used to be a hand-maintained list; new GIS tests were added
without being listed, which broke both CI and the live-conditions refresh.
"""
from pathlib import Path
import importlib
import sys
import unittest


# Top-level import names installed only by requirements-survey/-sst/-ocean.txt.
SCIENTIFIC_PACKAGES = frozenset({
    'affine', 'eccodes', 'h5py', 'laspy', 'lazrs', 'lerc', 'netCDF4', 'numpy',
    'pyproj', 'pypdf', 'rasterio', 'scipy', 'shapefile', 'shapely',
})


def classify(names):
    """Return (core modules, {module: missing scientific package})."""
    core, deferred = [], {}
    for name in names:
        try:
            importlib.import_module('tests.' + name)
        except ModuleNotFoundError as error:
            missing = (error.name or '').split('.')[0]
            if missing not in SCIENTIFIC_PACKAGES:
                raise
            deferred[name] = missing
        else:
            core.append(name)
    return core, deferred


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'src'))
    names = [p.stem for p in sorted((root / 'tests').glob('test_*.py'))]
    core, deferred = classify(names)
    if deferred:
        print(f'Deferring {len(deferred)} module(s) to the survey-science job '
              '(scientific packages not installed):', file=sys.stderr)
        for name, package in sorted(deferred.items()):
            print(f'  {name}  (needs {package})', file=sys.stderr)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName('tests.' + name)
                               for name in core)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun == 0:
        raise SystemExit('No core tests ran')
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
