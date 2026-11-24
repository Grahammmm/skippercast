"""Synthetic controls at the saved plan and owner-list boundary."""
import json
import subprocess
import sys

import pytest

from skippercast.relief import rebuild_plan, receipts
from tests._support import ROOT


@pytest.fixture
def saved_plan(tmp_path):
    public = receipts.Ref('tiles', 'public').key
    private = receipts.Ref('tiles', 'private').key
    old = {'code': {'stage_digest': 'old'}}
    stages = rebuild_plan.plan(
        {public: old, private: old, 'select': old},
        {'stage_digest': {public: 'new', private: 'old', 'select': 'old'}, 'style': {}},
    )
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps({'regions': [{'region': 'east-test', 'stages': stages}]}),
                    encoding='utf-8')
    return path


def invoke_report(saved_plan, owners):
    path = saved_plan.with_name('owners.json')
    path.write_text(json.dumps(owners), encoding='utf-8')
    return subprocess.run([
        sys.executable, '-B', str(ROOT / 'scripts/relief/rebuild_retained_outputs.py'),
        '--plan', str(saved_plan), '--owners', str(path),
    ], cwd=saved_plan.parent, capture_output=True, text=True, timeout=10)


def run_report(saved_plan, owners):
    result = invoke_report(saved_plan, owners)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_true_retained_output_intersection(saved_plan):
    """Catch missing matches or keeping only one retained ID per writer."""
    ids = ['east-test/prior/relief.pmtiles', 'east-test/older/relief.pmtiles']
    owners = [{'artifact_id': ident, 'region': 'east-test', 'stage': 'tiles.public'}
              for ident in ids]
    assert run_report(saved_plan, owners) == {'affected': sorted(ids), 'unaffected': []}


@pytest.mark.parametrize(('region', 'stage', 'artifact_id'), [
    # A basename or stage-only join would flag the unrelated region's tile.
    pytest.param('west-test', 'tiles.public', 'west-test/prior/relief.pmtiles',
                 id='same-basename-unrelated-region'),
    # Removing the scope would treat a public rebuild as a private write.
    pytest.param('east-test', 'tiles.private', 'east-test/private/private-relief.pmtiles',
                 id='same-stage-different-scope'),
    # Treating all named stages as writes would include an explicit reuse row.
    pytest.param('east-test', 'select', 'east-test/prior/sources.json',
                 id='explicit-reuse-not-a-write'),
])
def test_nonintersecting_retained_output_stays_unaffected(saved_plan, region, stage, artifact_id):
    affected = 'east-test/prior/relief.pmtiles'
    owners = [
        {'artifact_id': affected, 'region': 'east-test', 'stage': 'tiles.public'},
        {'artifact_id': artifact_id, 'region': region, 'stage': stage},
    ]
    assert run_report(saved_plan, owners) == {'affected': [affected], 'unaffected': [artifact_id]}


@pytest.mark.parametrize('contradictory', [
    pytest.param(True, id='reuse-then-rebuild'),
    pytest.param(False, id='identical-reuse-in-second-block'),
])
def test_duplicate_plan_stage_refuses_before_classifying(saved_plan, contradictory):
    """A rebuild-only set silently classifies artifacts despite repeated plan rows."""
    plan = json.loads(saved_plan.read_text(encoding='utf-8'))
    block = plan['regions'][0]
    reuse = next(row for row in block['stages'] if row['stage'] == 'tiles.private')
    if contradictory:
        block['stages'].append({**reuse, 'action': 'rebuild'})
    else:
        plan['regions'].append({'region': block['region'], 'stages': [dict(reuse)]})
    saved_plan.write_text(json.dumps(plan), encoding='utf-8')
    result = invoke_report(saved_plan, [
        {'artifact_id': 'private-tiles', 'region': block['region'], 'stage': reuse['stage']},
    ])
    assert result.returncode == 2, result.stdout or result.stderr
    assert result.stdout == ''
    assert "('east-test', 'tiles.private'): duplicate plan stage" in result.stderr
