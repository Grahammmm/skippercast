"""Adversarial repro tests are opt-in: they fail on purpose where a defect is open.

Run: COAST_ADVERSARIAL=1 python -m pytest tests/adversarial_repro -p no:cacheprovider
Needs the [test,survey] extras. Synthetic rasters only; no network, no real data.
"""
import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get('COAST_ADVERSARIAL') == '1':
        return
    skip = pytest.mark.skip(reason='set COAST_ADVERSARIAL=1 to run adversarial repro tests')
    for item in items:
        if 'adversarial_repro' in str(item.fspath):
            item.add_marker(skip)
