"""Offline controls for the scope checker's saved planner JSON input."""
import json
import subprocess
import sys

import pytest

from scripts.relief import rebuild_plan
from tests._support import ROOT
from tests.unit.test_rebuild_plan_cli import record


EAST, WEST = 'east-test', 'west-test'


@pytest.fixture(scope='module')
def saved_plan(tmp_path_factory):
    out = tmp_path_factory.mktemp('scope-receipts')
    current = rebuild_plan._stage_digests()
    record(out, EAST, 'select', current['select'])
    record(out, EAST, 'digests', current['digests'], upstream=[('tiles', 'public')])
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


def invoke(tmp_path, plan, allow):
    plan_path, allow_path = tmp_path / 'plan.json', tmp_path / 'allow.json'
    plan_path.write_text(json.dumps(plan), encoding='utf-8')
    allow_path.write_text(json.dumps(allow), encoding='utf-8')
    return subprocess.run([
        sys.executable, '-B', str(ROOT / 'scripts/relief/rebuild_scope_check.py'),
        '--plan', str(plan_path), '--allow', str(allow_path), EAST, WEST,
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
        'unexpected_regions': [], 'missing_stages': {}, 'summary_matches': True,
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
