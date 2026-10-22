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
