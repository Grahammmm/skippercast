"""Offline B1a rev4 acceptance and hostile-input controls; no scientific claims."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.coast_contract_factory import ROOT, SHARED, SCRIPTS, load_helper, materialize, schema_file, schemas

refs = load_helper('coast_refs')
sampling = load_helper('coast_sample')
tiles = load_helper('coast_tiles')
validator = load_helper('validate_coast_receipt')
ledger = load_helper('coast_ledger')


@pytest.mark.parametrize('name', sorted(schemas()))
def test_committed_schema_roundtrip_without_scientific_graph(name):
    """Core validates every schema; native lattice traversal runs in gis/."""
    root = ROOT/'tests/fixtures/coast/queue'
    value = refs.loads((root/'valid'/f'{name}.json').read_bytes())
    assert refs.loads(refs.canonical(value)) == value
    validator.validate_schema(value)
    with pytest.raises(ValueError, match='schema'):
        validator.validate_schema(refs.loads((root/'invalid'/f'{name}.json').read_bytes()))
    assert refs.loads((SHARED/'schemas'/schema_file(name)).read_bytes()) == schemas()[name]


















def test_root_binding_unknown_overlap_symlinks(tmp_path):
    root = tmp_path/'root'
    root.mkdir()
    with pytest.raises(ValueError,match='unexpected'):
        refs.Resolver({'queue:a':str(root)},allowed_root_ids={'queue:b'})
    child = root/'child'
    child.mkdir()
    with pytest.raises(ValueError,match='overlapping'):
        refs.Resolver({'queue:a':str(root),'raw:campaign':str(child)},allowed_root_ids={'queue:a','raw:campaign'})
    alias = tmp_path/'alias'
    alias.symlink_to(root,target_is_directory=True)
    with pytest.raises(OSError):
        refs.Resolver({'queue:a':str(alias)},allowed_root_ids={'queue:a'})






@pytest.mark.parametrize(('done','flagged','size'),[(0,0,0),(1,0,1),(4,0,4),(16,12,4),(16,16,0),(16,2,8)])
def test_six_sampling_populations(done,flagged,size):
    keys=[f'source#{"a"*64}#{i}' for i in range(done)]
    kwargs=dict(plan_sha256='b'*64,bridge_sha256='c'*64)
    a=sampling.sample(keys,keys[flagged:],**kwargs)
    b=sampling.sample(list(reversed(keys)),list(reversed(keys[flagged:])),**kwargs)
    assert a['size'] == size
    assert refs.canonical(a) == refs.canonical(b)




@pytest.mark.parametrize(('idx','cols','rows','total','expected'),[(0,1,1,1,[]),(2,3,2,6,[1,5]),(3,3,2,6,[0,4]),(4,3,2,5,[1,3]),(2,3,2,5,[1])])
def test_bounded_adjacency(idx,cols,rows,total,expected):
    assert tiles.neighbours(idx,cols,rows,total) == expected


@pytest.mark.parametrize('args',[(1,1,1,1),(-1,2,2,4),(0,0,1,1),(0,3,3,4),(True,1,1,1)])
def test_invalid_adjacency(args):
    with pytest.raises(ValueError):
        tiles.neighbours(*args)


def payload(row):
    return {k:v for k,v in row.items() if k not in ('seq','prev_row_sha256')}






def test_duplicate_nonfinite_and_write_once(tmp_path):
    for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}'):
        with pytest.raises(ValueError):
            refs.loads(raw)
    path=tmp_path/'one.json'
    refs.write_once(path,{'a':1})
    with pytest.raises(FileExistsError):
        refs.write_once(path,{'a':2})
    assert refs.loads(path.read_bytes()) == {'a':1}






def test_all_four_typed_namespaces_are_independent(tmp_path):
    ids=['queue:synthetic','repo:'+'1'*40,'archive:synthetic:close01','raw:campaign']
    bindings={}
    raw=b'bounded synthetic bytes\n'
    for i,root_id in enumerate(ids):
        path=tmp_path/str(i)
        path.mkdir()
        (path/'same-name.dat').write_bytes(raw)
        bindings[root_id]=str(path)
    resolver=refs.Resolver(bindings,allowed_root_ids=ids)
    for root_id in ids:
        ref=dict(root_id=root_id,path='same-name.dat',sha256=refs.sha256(raw),bytes=len(raw))
        assert resolver.read(ref)==raw
        assert resolver.read(ref,retain=False)==b''
    (Path(bindings['raw:campaign'])/'same-name.dat').write_bytes(b'changed')
    assert resolver.read(dict(root_id=ids[0],path='same-name.dat',sha256=refs.sha256(raw),bytes=len(raw)))==raw
    with pytest.raises(ValueError):
        resolver.read(dict(root_id='raw:campaign',path='same-name.dat',sha256=refs.sha256(raw),bytes=len(raw)))




def test_default_thresholds_and_no_operational_pairings():
    thresholds=refs.loads((SHARED/'config/tier2-thresholds.json').read_bytes())
    assert thresholds['edge_step_should_m']==2
    assert thresholds['edge_step_must_m']==10
    assert thresholds['mask_continuity_min']==0.8
    assert thresholds['tier1_valid_fraction_min']==0.5
    assert thresholds['tier1_edge_valid_min']==0.5
    assert thresholds['tier1_slope_p99_max_deg']==60
    assert thresholds['history']
    routing=refs.loads((SHARED/'config/review-routing.json').read_bytes())
    validator.validate_schema(routing)
    assert routing['qualified_reviewers']==[] and routing['allowed_pairs']==[]
    assert routing['allow_profile_fallback'] is False
    assert not (SHARED/'SKILL.md').exists()


FIXTURE_ROOTS = {'queue:synthetic': 'queue', 'archive:synthetic:close01': 'archive', 'raw:campaign': 'raw'}


def _tracked_fixture_paths():
    out = subprocess.run(['git', 'ls-files', '-z', '--', 'tests/fixtures/coast'], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return {p for p in out.decode().split('\0') if p}


def _iter_refs(value):
    if isinstance(value, dict):
        if set(value) == {'root_id', 'path', 'sha256', 'bytes'}:
            yield value
        for item in value.values():
            yield from _iter_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_refs(item)


def untracked_fixture_refs(base, starts, tracked):
    """Follow typed Refs from start fixtures; return every target that is not a tracked file.

    CI checks out only tracked files, so a Ref that resolves locally to an
    ignored/untracked file (for example under var/ or runs/) breaks there.
    """
    missing, seen, todo = [], set(), list(starts)
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        try:
            value = json.loads((base/rel).read_bytes())
        except (OSError, ValueError):
            continue
        for ref in _iter_refs(value):
            sub = FIXTURE_ROOTS.get(ref['root_id'])
            if sub is None or not isinstance(ref['path'], str):
                continue
            target = f'tests/fixtures/coast/{sub}/{ref["path"]}'
            if target not in tracked:
                missing.append((rel, ref['root_id'], ref['path']))
            elif target.endswith('.json'):
                todo.append(target)
    return missing


def test_committed_fixture_refs_resolve_to_tracked_files():
    tracked = _tracked_fixture_paths()
    starts = sorted(p for p in tracked if p.startswith(('tests/fixtures/coast/queue/valid/',
                                                        'tests/fixtures/coast/queue/diagnostic/')))
    assert len(starts) >= len(schemas())
    for wanted in ('tests/fixtures/coast/queue/plans/plan01/runs/run-00.json',
                   'tests/fixtures/coast/queue/valid/run-summary.json'):
        assert wanted in tracked
    assert any(p.startswith('tests/fixtures/coast/queue/var/coastal/enqueue-intents/') for p in tracked)
    assert untracked_fixture_refs(ROOT, starts, tracked) == []


def test_untracked_fixture_ref_is_reported(tmp_path):
    """Negative control: a Ref whose target exists only in the working tree is reported."""
    base = tmp_path
    (base/'tests/fixtures/coast/queue/var/x').mkdir(parents=True)
    (base/'tests/fixtures/coast/queue/var/x/leaf.json').write_text('{}')
    start = 'tests/fixtures/coast/queue/valid/a.json'
    (base/'tests/fixtures/coast/queue/valid').mkdir(parents=True)
    ref = dict(root_id='queue:synthetic', path='var/x/leaf.json', sha256='0'*64, bytes=2)
    (base/start).write_text(json.dumps({'nested': [ref]}))
    assert untracked_fixture_refs(base, [start], {start}) == [(start, 'queue:synthetic', 'var/x/leaf.json')]
    assert untracked_fixture_refs(base, [start], {start, 'tests/fixtures/coast/queue/var/x/leaf.json'}) == []
