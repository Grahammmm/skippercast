"""Run the offline Python tests that need no scientific/GIS packages (a thin pytest wrapper).

The layers, markers and the rule that keeps GIS modules out of collection when the
survey packages are absent live in pyproject.toml ([tool.pytest.ini_options]) and
tests/conftest.py; see docs/engineering/testing.md. This script only chooses what
to run:

  --scope core  every test not marked `gis` (what CI's `check` job runs)
  --scope live  the product tests covering code the scheduled live-conditions job
                runs, so an unrelated test can never stop the public feed

Extra arguments after `--` are passed to pytest unchanged, for example
`python scripts/run_core_tests.py -- -k pipeline -x`.
"""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]

# Code the scheduled live-conditions job actually runs. Its pre-publish tests are
# limited to product test modules exercising this code.
LIVE_CODE = re.compile(r'skippercast\.pipeline|skippercast import pipeline|scripts[./](refresh_regions|'
                       r'check_saved_trips|prune_habitat_tiles|live_loop|report_conditions|publish_branch_snapshot)')


def live_modules(root=ROOT):
    """Product test modules (tests/, never the claims pins) that exercise live code."""
    return [path for path in sorted((root / 'tests').rglob('test_*.py'))
            if LIVE_CODE.search(path.read_text(encoding='utf-8'))]


def pytest_args(scope, extra=(), root=ROOT):
    if scope == 'live':
        return [*(str(path) for path in live_modules(root)), *extra]
    return ['-m', 'not gis', *extra]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--scope', choices=('core', 'live'), default='core',
                        help='live: only tests covering the scheduled conditions pipeline')
    parser.add_argument('pytest_args', nargs='*', help='passed to pytest (put them after --)')
    args = parser.parse_args(argv)
    import pytest
    raise SystemExit(int(pytest.main(['--rootdir', str(ROOT), '-c', str(ROOT / 'pyproject.toml'),
                                      *pytest_args(args.scope, args.pytest_args)])))


if __name__ == '__main__':
    main()
