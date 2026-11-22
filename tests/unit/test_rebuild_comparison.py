"""Compare saved, synthetic planner outputs with independently declared inventories."""
import json
import subprocess
import sys

import pytest

from skippercast.relief.rebuild_plan import plan
from tests._support import ROOT


def block(region, docs, **style):
    return {'region': region, 'stages': plan(docs, {'stage_digest': {}, 'style': style})}


def invoke(tmp_path, blocks, inventory):
    saved_plan = tmp_path / 'plan.json'
    saved_plan.write_text(json.dumps({'regions': blocks}), encoding='utf-8')
    declared = tmp_path / 'inventory.json'
    declared.write_text(json.dumps(inventory), encoding='utf-8')
    return subprocess.run([
        sys.executable, '-B', str(ROOT / 'scripts/relief/rebuild_comparison.py'),
        '--plan', str(saved_plan), '--inventory', str(declared),
    ], cwd=tmp_path, capture_output=True, text=True, timeout=10)


def report(result):
    assert (result.returncode, result.stderr) == (0, '')
    return json.loads(result.stdout)


def assert_refused(result, message):
    assert result.returncode == 2
    assert result.stdout == ''
    assert message in result.stderr


def test_paint_only_zero_rebuilds(tmp_path):
    """Zero rebuilds avoids the entire inventory, not zero pairs or an undefined fraction."""
    docs = {'tiles.public': {'params': {'baked': 'same', 'paint': 'before'}}}
    result = invoke(tmp_path, [block('east-test', docs, baked='same', paint='after')],
                    [['east-test', 'tiles.public']])
    assert report(result) == {
        'rebuild_all_pairs': 1, 'planned_reuse': 1, 'planned_rebuild': 0,
        'unknown': 0, 'fraction_avoided': 1.0,
    }
    assert {p.name for p in tmp_path.iterdir()} == {'plan.json', 'inventory.json'}


def test_baked_change_rebuilds_only_scoped_subset(tmp_path):
    """Count full region/stage/scope identities; grouping by region or base stage loses decisions."""
    docs = {'tiles.public': {'params': {'baked': 'before'}}, 'tiles.private': {}}
    blocks = [block('east-test', docs, baked='after'), block('west-test', docs, baked='before')]
    inventory = [['west-test', 'tiles.public'], ['west-test', 'tiles.private'],
                 ['east-test', 'tiles.public'], ['east-test', 'tiles.private']]
    assert report(invoke(tmp_path, blocks, inventory)) == {
        'rebuild_all_pairs': 4, 'planned_reuse': 3, 'planned_rebuild': 1,
        'unknown': 0, 'fraction_avoided': 0.75,
    }


def test_missing_region_and_missing_scope_are_unknown(tmp_path):
    """Neither a missing region nor a missing scope is reuse or removed from the denominator."""
    blocks = [block('east-test', {'tiles.public': {}})]
    inventory = [['east-test', 'tiles.public'], ['east-test', 'tiles.private'],
                 ['west-test', 'tiles.public'], ['west-test', 'tiles.private']]
    assert report(invoke(tmp_path, blocks, inventory)) == {
        'rebuild_all_pairs': 4, 'planned_reuse': 1, 'planned_rebuild': 0,
        'unknown': 3, 'fraction_avoided': 0.25,
    }


@pytest.mark.parametrize(('region', 'stage', 'message'), [
    ('west-test', 'tiles.public', 'unexpected or invalid plan region'),
    ('east-test', 'tiles.private', 'plan pair outside inventory'),
])
def test_extra_plan_pairs_are_refused(tmp_path, region, stage, message):
    """Reject instead of intersecting away an out-of-inventory region or scope."""
    blocks = [block('east-test', {'tiles.public': {}})]
    if region == 'east-test':
        blocks[0]['stages'].extend(block(region, {stage: {}})['stages'])
    else:
        blocks.append(block(region, {stage: {}}))
    assert_refused(invoke(tmp_path, blocks, [['east-test', 'tiles.public']]), message)


@pytest.mark.parametrize(('inventory', 'message'), [
    ([], 'nonempty list'),
    ([['east-test', 'tiles.public']] * 2, 'duplicate inventory pair'),
    ([['east-test', 'tiles.']], 'invalid scope'),
])
def test_invalid_inventory_cannot_define_a_baseline(tmp_path, inventory, message):
    """Reject zero, double-counted or malformed denominator entries even with no plan rows."""
    assert_refused(invoke(tmp_path, [], inventory), message)


def test_invalid_plan_action_is_refused(tmp_path):
    """The comparison must retain the adapter's action checks, not count a typo as rebuild."""
    region = block('east-test', {'tiles.public': {}})
    region['stages'][0]['action'] = 'verified'
    assert_refused(invoke(tmp_path, [region], [['east-test', 'tiles.public']]),
                   'invalid action or reasons')
