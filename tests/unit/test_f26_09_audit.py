"""Regression for acceptance recorders counting a setup pass as a test pass."""
import importlib
import sys

import pytest


@pytest.fixture(params=['catalog', 'terrain'])
def recorder(request, monkeypatch):
    # The standalone runners disable bytecode at import; don't change it for other tests.
    monkeypatch.setattr(sys, 'dont_write_bytecode', True)
    if request.param == 'catalog':
        module = importlib.import_module('research.scripts.accept_sc_catalog_rows')
        plugin = module.Recorder()
        return plugin, plugin.results
    module = importlib.import_module('research.scripts.accept_sc34_terrain_json')
    plugin = module.Outcomes()
    return plugin, plugin.reports


@pytest.mark.parametrize('reports, expected', [
    ([('setup', 'passed')], 'incomplete'),
    ([('setup', 'passed'), ('teardown', 'passed')], 'incomplete'),
    ([('setup', 'passed'), ('call', 'passed')], 'incomplete'),
    ([('setup', 'passed'), ('call', 'passed'), ('teardown', 'passed')], 'passed'),
    ([('setup', 'passed'), ('call', 'failed'), ('teardown', 'passed')], 'not passed'),
    ([('setup', 'passed'), ('call', 'passed'), ('teardown', 'failed')], 'not passed'),
    ([('setup', 'skipped'), ('teardown', 'passed')], 'not passed'),
    ([('setup', 'passed'), ('call', 'xfailed'), ('teardown', 'passed')], 'not passed'),
    ([('setup', 'passed'), ('call', 'xpassed'), ('teardown', 'passed')], 'not passed'),
], ids=['setup-only', 'missing-call', 'missing-teardown', 'complete', 'body-failed',
        'teardown-failed', 'skipped', 'xfailed', 'xpassed'])
def test_acceptance_requires_all_phases(recorder, reports, expected):
    plugin, rows = recorder
    nodeid = 'test_synthetic.py::test_body'
    for phase, state in reports:
        xfail = state in ('xfailed', 'xpassed')
        outcome = {'xfailed': 'skipped', 'xpassed': 'passed'}.get(state, state)
        report = pytest.TestReport(nodeid, ('test_synthetic.py', 0, 'test_body'), {},
                                   outcome, None, phase, **({'wasxfail': 'synthetic'} if xfail else {}))
        plugin.pytest_runtest_logreport(report)
    assert set(rows) == {nodeid}
    if expected == 'not passed':
        assert rows[nodeid]['outcome'] not in {'passed', 'incomplete'}
    else:
        assert rows[nodeid]['outcome'] == expected
