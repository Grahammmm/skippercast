"""Offline controls for the scope checker's saved planner JSON input."""
import json
import subprocess
import sys

import pytest

from scripts.relief import rebuild_plan
from tests._support import ROOT
from tests.unit.test_rebuild_plan_cli import KEYS, record, row


EAST, WEST = 'east-test', 'west-test'


@pytest.fixture(scope='module')
def saved_plan(tmp_path_factory):
    out = tmp_path_factory.mktemp('scope-receipts')
    current = rebuild_plan._stage_digests()
    record(out, EAST, 'select', current['select'])
    record(out, EAST, 'digests', current['digests'], upstream=[('tiles', 'public')])
    return plan_json(out)


def plan_json(out):
    result = subprocess.run([
        sys.executable, '-B', str(ROOT / 'scripts/relief/rebuild_plan.py'),
        '--out', str(out), '--json', EAST, WEST,
    ], cwd=out, capture_output=True, text=True, timeout=20, check=True)
    return result.stdout


@pytest.fixture
def candidate(saved_plan):
    plan = json.loads(saved_plan)
    allow = {block['region']: [row['stage'] for row in block['stages'] if row['action'] == 'rebuild']
             for block in plan['regions']}
    return plan, allow


def invoke(tmp_path, plan, allow, expected_stages=None):
    plan_path, allow_path, inventory_path = (tmp_path / name for name in ('plan.json', 'allow.json', 'inventory.json'))
    plan_path.write_text(json.dumps(plan), encoding='utf-8')
    allow_path.write_text(json.dumps(allow), encoding='utf-8')
    if expected_stages is None:
        expected_stages = {EAST: list(KEYS), WEST: list(KEYS)}
    inventory_path.write_text(json.dumps(expected_stages), encoding='utf-8')
    return subprocess.run([
        sys.executable, '-B', str(ROOT / 'scripts/relief/rebuild_scope_check.py'),
        '--plan', str(plan_path), '--allow', str(allow_path), '--expected-stages', str(inventory_path), EAST, WEST,
    ], cwd=tmp_path, capture_output=True, text=True, timeout=10)


def test_allowed_subset_passes(tmp_path, candidate):
    """Catch exact-set comparison or counting a reused, unapproved stage as a rebuild."""
    plan, allow = candidate
    assert 'select' not in allow[EAST]
    allow['unused-test'] = ['tiles.public']
    result = invoke(tmp_path, plan, allow)
    assert (result.returncode, result.stderr) == (0, '')
    assert json.loads(result.stdout) == {
        'within_ceiling': True, 'outside_ceiling': [], 'missing_regions': [],
        'unexpected_regions': [], 'missing_stages': {}, 'unexpected_stages': {}, 'summary_matches': True,
    }


def test_reports_every_outside_pair_including_downstream_stage(tmp_path, candidate):
    """Catch checking only roots, matching only a region/stage name, or stopping after one miss."""
    plan, allow = candidate
    allow[EAST].remove('digests')              # Region and upstream tiles are still allowed.
    allow[WEST].remove('tiles.public')          # East's approval must not leak to West.
    allow[WEST].append('tiles.private')        # Same base stage, different scope.
    result = invoke(tmp_path, plan, allow)
    assert (result.returncode, result.stderr) == (1, '')
    report = json.loads(result.stdout)
    assert report['within_ceiling'] is False
    assert report['outside_ceiling'] == [
        {'region': EAST, 'stage': 'digests', 'action': 'rebuild', 'reasons': ['upstream:tiles.public']},
        {'region': WEST, 'stage': 'tiles.public', 'action': 'rebuild', 'reasons': ['missing']},
    ]


def test_incomplete_region_fails_even_with_consistent_summary(tmp_path, candidate):
    """Catch using the saved report as its own roster after a caller omits a region."""
    plan, allow = candidate
    plan['regions'].pop()
    plan['summary'] = {'regions': 1, 'rebuild_heavy': 2}
    result = invoke(tmp_path, plan, allow)
    assert (result.returncode, result.stderr) == (1, '')
    report = json.loads(result.stdout)
    assert report['missing_regions'] == [WEST]
    assert report['outside_ceiling'] == []
    assert report['summary_matches'] is True


def test_missing_downstream_stage_fails_even_with_consistent_summary(tmp_path, candidate):
    """Catch a dropped non-heavy row that neither summary counter would reveal."""
    plan, allow = candidate
    plan['regions'][0]['stages'] = [row for row in plan['regions'][0]['stages'] if row['stage'] != 'digests']
    result = invoke(tmp_path, plan, allow)
    assert (result.returncode, result.stderr) == (1, '')
    report = json.loads(result.stdout)
    assert report['missing_stages'] == {EAST: ['digests']}
    assert report['summary_matches'] is True


@pytest.mark.parametrize('action', ['reuse', 'rebuild'])
def test_stage_outside_regional_inventory_fails_within_allowance(tmp_path, action):
    """Catch checking only missing keys, only rebuilds, or inventory pooled across regions."""
    out = tmp_path / 'receipts'
    out.mkdir()
    current = rebuild_plan._stage_digests()
    # All current receipts give the paint-only (all reuse) control; a stale tile
    # receipt gives the single-region rebuild control.
    for region in (EAST, WEST):
        for key in KEYS:
            stale = action == 'rebuild' and (region, key) == (EAST, 'tiles.public')
            record(out, region, key, '0' * 64 if stale else current[key])
    historical = 'tiles.private'
    record(out, WEST, historical, current['tiles.public'])
    inventory = {EAST: list(KEYS), WEST: [*KEYS, historical]}
    allow = {EAST: ['tiles.public']} if action == 'rebuild' else {}
    plan = json.loads(plan_json(out))
    assert plan['summary']['rebuild_heavy'] == int(action == 'rebuild')
    assert invoke(tmp_path, plan, allow, inventory).returncode == 0

    rows = plan['regions'][0]['stages']
    if action == 'rebuild':
        rows.append(row(historical, 'code'))
        allow[EAST].append(historical)
        plan['summary']['rebuild_heavy'] += 1
    else:
        rows.append(row(historical))
    result = invoke(tmp_path, plan, allow, inventory)
    assert (result.returncode, result.stderr) == (1, ''), result.stdout
    report = json.loads(result.stdout)
    assert report['unexpected_stages'] == {EAST: [historical]}
    assert report['outside_ceiling'] == []
    assert report['missing_stages'] == {}
    assert report['summary_matches'] is True


@pytest.mark.parametrize('omitted', ['zone.private', 'legacy.private'])
def test_missing_historical_or_upstream_rebuild_fails(tmp_path, omitted):
    out = tmp_path / 'receipts'
    out.mkdir()
    current = rebuild_plan._stage_digests()
    record(out, EAST, 'zone.private', '0' * 64)
    record(out, EAST, 'digests', current['digests'], upstream=[('legacy', 'private')])
    plan = json.loads(plan_json(out))
    rows = plan['regions'][0]['stages']
    assert {row['stage'] for row in rows if row['action'] == 'rebuild'} >= {'zone.private', 'legacy.private'}
    allow = {block['region']: [row['stage'] for row in block['stages'] if row['action'] == 'rebuild']
             for block in plan['regions']}
    inventory = {EAST: [*KEYS, 'zone.private', 'legacy.private'], WEST: list(KEYS)}
    assert invoke(tmp_path, plan, allow, inventory).returncode == 0
    allow[EAST].remove(omitted)
    rows[:] = [row for row in rows if row['stage'] != omitted]
    result = invoke(tmp_path, plan, allow, inventory)
    assert result.returncode == 1
    assert json.loads(result.stdout)['missing_stages'] == {EAST: [omitted]}


@pytest.mark.parametrize('inventory', [{EAST: list(KEYS)}, {EAST: [], WEST: list(KEYS)}])
def test_incomplete_inventory_is_rejected(tmp_path, candidate, inventory):
    plan, allow = candidate
    result = invoke(tmp_path, plan, allow, inventory)
    assert (result.returncode, result.stdout) == (2, '')
    assert 'stage inventory' in result.stderr


def test_inconsistent_summary_fails(tmp_path, candidate):
    """Catch a dropped extra heavy scope even when all of the runner's current keys remain."""
    plan, allow = candidate
    plan['summary']['rebuild_heavy'] += 1
    result = invoke(tmp_path, plan, allow)
    assert (result.returncode, result.stderr) == (1, '')
    assert json.loads(result.stdout)['summary_matches'] is False


def test_malformed_ceiling_fails(tmp_path, candidate):
    """Catch treating a string as an iterable of allowed keys or silently ignoring its bad shape."""
    plan, allow = candidate
    allow['unused-test'] = 'tiles.public'
    result = invoke(tmp_path, plan, allow)
    assert (result.returncode, result.stdout) == (2, '')
    assert 'invalid allowed region or stage list' in result.stderr
