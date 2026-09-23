"""Run dependency-light app tests on every supported core Python version.

The separate survey-science CI job installs pinned GIS packages and runs the
entire suite, including the modules excluded here.
"""
from pathlib import Path
import sys
import unittest


GIS_TEST_MODULES = {
    'test_bottom_targets',
    'test_cdfw_substrate_pipeline',
    'test_native_sector_leads',
    'test_regular_bag_hard',
    'test_search_plan_geometry',
    'test_usgs_context_pipeline',
    'test_vr_native_depth',
}


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'src'))
    names = [p.stem for p in sorted((root / 'tests').glob('test_*.py'))]
    missing = GIS_TEST_MODULES - set(names)
    if missing:
        raise SystemExit(f'GIS test classification is stale: {sorted(missing)}')
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName('tests.' + name)
                               for name in names if name not in GIS_TEST_MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
