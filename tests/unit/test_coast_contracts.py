"""Offline B1a rev4 acceptance and hostile-input controls; no scientific claims."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.coast_contract_factory import ROOT, SHARED, SCRIPTS, load_helper, materialize, schemas

refs = load_helper('coast_refs')
sampling = load_helper('coast_sample')
tiles = load_helper('coast_tiles')
validator = load_helper('validate_coast_receipt')
ledger = load_helper('coast_ledger')


@pytest.fixture
def graph(tmp_path):
    instances, bindings = materialize(tmp_path)
    resolver = refs.Resolver(bindings, allowed_root_ids=set(bindings))
    return instances, bindings, resolver


@pytest.mark.parametrize('name', sorted(schemas()))
def test_schema_roundtrip_and_ref_graph(name, graph):
    instances, _, resolver = graph
    value = instances[name]
    raw = refs.canonical(value)
    assert raw.endswith(b'\n')
    reopened = refs.loads(raw)
    assert reopened == value
    assert refs.sha256(raw) != refs.object_digest(value)
    assert validator.validate(reopened, resolver, root_id='queue:synthetic') == value
    with pytest.raises(ValueError, match='schema'):
        validator.validate(dict(value, self_sha256=refs.sha256(raw)), resolver, root_id='queue:synthetic')
    committed = refs.loads((SHARED/'schemas'/f'coast-{name}-v1.schema.json').read_bytes())
    assert committed == schemas()[name]


@pytest.mark.parametrize('name', sorted(schemas()))
def test_committed_valid_and_invalid_fixtures(name):
    root = ROOT/'tests/fixtures/coast'
    resolver = refs.Resolver({'queue:synthetic':str(root/'queue'), 'archive:synthetic:close01':str(root/'archive')},
                             allowed_root_ids={'queue:synthetic','archive:synthetic:close01'})
    value = refs.loads((root/'queue/valid'/f'{name}.json').read_bytes())
    validator.validate(value,resolver,root_id='queue:synthetic')
    invalid = refs.loads((root/'queue/invalid'/f'{name}.json').read_bytes())
    with pytest.raises(ValueError, match='schema'):
        validator.validate(invalid,resolver,root_id='queue:synthetic')


def test_diagnostic_verdict_does_not_follow_failed_expectations(graph):
    _, bindings, resolver = graph
    queue = Path(bindings['queue:synthetic'])
    value = refs.loads((queue/'diagnostic/verdict.json').read_bytes())
    validator.validate(value,resolver,root_id='queue:synthetic')
    context = refs.loads((queue/'diagnostic/context.json').read_bytes())
    with pytest.raises(ValueError,match='SHA256'):
        validator.validate(context,resolver,root_id='queue:synthetic')
    # Rehashed but corrupted trusted identity bytes cannot use the exception.
    (queue/'diagnostic/context.json').write_bytes(b'corrupted context')
    with pytest.raises(ValueError):
        validator.validate(value,resolver,root_id='queue:synthetic')


def test_diagnostic_cannot_be_accept_or_metrics(graph):
    _, bindings, resolver = graph
    value = refs.loads((Path(bindings['queue:synthetic'])/'diagnostic/verdict.json').read_bytes())
    for change in ({'verdict':'accept'}, {'population':{}}, {'next_tile_card_authorized':True}, {'validation_scope':'full_graph'}):
        with pytest.raises(ValueError,match='schema'):
            validator.validate(dict(value,**change),resolver,root_id='queue:synthetic')


def test_normal_cannot_opt_down(graph):
    instances, _, resolver = graph
    normal = dict(instances['review-verdict'],validation_scope='identity_snapshot')
    with pytest.raises(ValueError,match='schema'):
        validator.validate(normal,resolver,root_id='queue:synthetic')
    with pytest.raises(TypeError):
        validator.validate(instances['review-verdict'],resolver,root_id='queue:synthetic',scope='identity_snapshot')


@pytest.mark.parametrize('path', ['/etc/passwd','../escape','safe/../escape','a//b','./a','a\\b','a/','a\x00b'])
def test_reference_path_refusal(graph,path):
    instances, _, resolver = graph
    bad=dict(instances['admission']['campaign'],path=path)
    with pytest.raises((ValueError,OSError)):
        resolver.read(bad)


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


def test_reference_symlink_parent_leaf_fifo_and_bytes(graph):
    instances, bindings, resolver = graph
    queue=Path(bindings['queue:synthetic'])
    original=instances['admission']['campaign']
    (queue/'alias').symlink_to(queue/'provenance',target_is_directory=True)
    (queue/'leaf').symlink_to(queue/original['path'])
    os.mkfifo(queue/'pipe')
    for path in ('alias/synthetic.txt','leaf','pipe'):
        with pytest.raises((ValueError,OSError)):
            resolver.read(dict(original,path=path))
    for change in ({'sha256':'f'*64},{'bytes':0},{'root_id':'queue:other'},{'bytes':True}):
        with pytest.raises(ValueError):
            resolver.read(dict(original,**change))


def test_native_adapter_preserves_bytes_unknown_slots_refuse(graph):
    instances, _, resolver = graph
    typed = instances['admission']['campaign']
    native = {k:v for k,v in typed.items() if k != 'root_id'} | {'contract':'synthetic-file'}
    doc=dict(schema='coastal-native-job-v1',source=native,segment_id='synthetic',window={'width':1})
    raw=refs.canonical(doc)
    validator.GraphValidator(resolver).document(doc,root_id='queue:synthetic')
    assert refs.canonical(doc) == raw
    with pytest.raises(ValueError,match='unknown native ref slot'):
        validator.GraphValidator(resolver).document(dict(doc,unknown=native),root_id='queue:synthetic')
    with pytest.raises(ValueError,match='unsupported JSON producer'):
        validator.GraphValidator(resolver).document(dict(schema='unknown-v1',source=native),root_id='queue:synthetic')
    with pytest.raises(ValueError,match='unknown path-bearing'):
        validator.GraphValidator(resolver).walk({'not_a_ref':native},root_id='queue:synthetic')


@pytest.mark.parametrize(('done','flagged','size'),[(0,0,0),(1,0,1),(4,0,4),(16,12,4),(16,16,0),(16,2,8)])
def test_six_sampling_populations(done,flagged,size):
    keys=[f'source#{"a"*64}#{i}' for i in range(done)]
    kwargs=dict(plan_sha256='b'*64,bridge_sha256='c'*64)
    a=sampling.sample(keys,keys[flagged:],**kwargs)
    b=sampling.sample(list(reversed(keys)),list(reversed(keys[flagged:])),**kwargs)
    assert a['size'] == size
    assert refs.canonical(a) == refs.canonical(b)


def test_sample_and_window_identity_refusals(graph):
    instances, _, resolver = graph
    assert '/' not in sampling.window_dir(sampling.window_key('../source:bad/a','a'*64,0))
    packet=copy.deepcopy(instances['review-packet'])
    packet['sample']['size']=8
    with pytest.raises(ValueError,match='non-clamped'):
        validator.validate(packet,resolver,root_id='queue:synthetic')
    admission=copy.deepcopy(instances['admission'])
    del admission['windows'][0]['window_key']
    with pytest.raises(ValueError,match='schema'):
        validator.validate(admission,resolver,root_id='queue:synthetic')
    with pytest.raises(ValueError,match='duplicate'):
        sampling.sample(['x','x'],[],plan_sha256='a'*64,bridge_sha256='b'*64)


@pytest.mark.parametrize(('idx','cols','rows','total','expected'),[(0,1,1,1,[]),(2,3,2,6,[1,5]),(3,3,2,6,[0,4]),(4,3,2,5,[1,3]),(2,3,2,5,[1])])
def test_bounded_adjacency(idx,cols,rows,total,expected):
    assert tiles.neighbours(idx,cols,rows,total) == expected


@pytest.mark.parametrize('args',[(1,1,1,1),(-1,2,2,4),(0,0,1,1),(0,3,3,4),(True,1,1,1)])
def test_invalid_adjacency(args):
    with pytest.raises(ValueError):
        tiles.neighbours(*args)


def payload(row):
    return {k:v for k,v in row.items() if k not in ('seq','prev_row_sha256')}


def test_ledger_two_writers_idempotency_corruption_and_index(graph,tmp_path):
    instances, _, resolver=graph
    segment=tmp_path/'ledger.jsonl'
    index=tmp_path/'campaign-ledger.jsonl'
    verdict=payload(instances['segment-ledger'])
    a=ledger.append_index(segment,index,verdict,writer='write_verdict.py',resolver=resolver,root_id='queue:synthetic')
    assert ledger.append_index(segment,index,verdict,writer='write_verdict.py',resolver=resolver,root_id='queue:synthetic') == a
    with pytest.raises(ValueError,match='different payload'):
        ledger.append(segment,dict(verdict,author_profile='other'),writer='write_verdict.py',resolver=resolver,root_id='queue:synthetic')
    archive={k:v for k,v in verdict.items() if k not in ('review_round','attempt','verdict','verdict_file','context','packet','open_report','validation_scope')}
    archive.update(kind='archived',close_id='close01',manifest=instances['release-list']['manifest'],inventory=instances['archive-manifest']['inventory'],
        previous_segment_tip_sha256=a['segment_row_sha256'],previous_campaign_tip_sha256=a['campaign_row_sha256'])
    ledger.append_index(segment,index,archive,writer='archive_segment.py',resolver=resolver,root_id='queue:synthetic')
    rows=ledger.verify(segment)
    assert len(rows) == 2 and rows[1]['prev_row_sha256'] == refs.sha256(refs.canonical(rows[0]))
    assert ledger.verify(index)[0]['segment_row_sha256'] == a['segment_row_sha256']
    raw=segment.read_bytes()
    changed=raw.replace(b'fixture',b'fixturE',1)
    with pytest.raises(ValueError,match='hash mismatch'):
        ledger.verify_bytes(changed)
    with pytest.raises(ValueError,match='missing final newline'):
        ledger.verify_bytes(raw[:-1])
    with pytest.raises(ValueError,match='writer'):
        ledger.append(segment,verdict,writer='other.py',resolver=resolver,root_id='queue:synthetic')


def test_integrity_error_ledger_can_append_without_bad_run(graph,tmp_path):
    instances, bindings, resolver=graph
    queue=Path(bindings['queue:synthetic'])
    raw=(queue/'diagnostic/verdict.json').read_bytes()
    value=refs.loads(raw)
    row=payload(instances['segment-ledger'])
    row.update(verdict='must_fix',context=value['context'],packet=None,open_report=value['open_report'],validation_scope='identity_snapshot',
        verdict_file=dict(root_id='queue:synthetic',path='diagnostic/verdict.json',sha256=refs.sha256(raw),bytes=len(raw)))
    ledger.append(tmp_path/'ledger.jsonl',row,writer='write_verdict.py',resolver=resolver,root_id='queue:synthetic')
    assert ledger.verify(tmp_path/'ledger.jsonl')[0]['packet'] is None


def test_duplicate_nonfinite_and_write_once(tmp_path):
    for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}'):
        with pytest.raises(ValueError):
            refs.loads(raw)
    path=tmp_path/'one.json'
    refs.write_once(path,{'a':1})
    with pytest.raises(FileExistsError):
        refs.write_once(path,{'a':2})
    assert refs.loads(path.read_bytes()) == {'a':1}


def test_cli_roundtrip_and_hash_dir(graph,tmp_path):
    _, bindings, _=graph
    roots=tmp_path/'roots.json'
    roots.write_bytes(refs.canonical(bindings))
    command=[sys.executable,str(SCRIPTS/'validate_coast_receipt.py'),str(Path(bindings['queue:synthetic'])/'valid/review-verdict.json'),
        '--roots',str(roots),'--root-id','queue:synthetic','--allowed-root-id','queue:synthetic','--allowed-root-id','archive:synthetic:close01']
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode == 0,result.stderr
    assert json.loads(result.stdout)['scientific_acceptance'] is False
    result=subprocess.run([sys.executable,str(SCRIPTS/'validate_coast_receipt.py'),'--hash-dir',bindings['queue:synthetic']],capture_output=True,text=True)
    assert result.returncode == 0,result.stderr
    assert len(json.loads(result.stdout)) > 26
    (Path(bindings['queue:synthetic'])/'bad-link').symlink_to('/etc/passwd')
    with pytest.raises(ValueError,match='symlink'):
        validator.hash_dir(bindings['queue:synthetic'])


def test_receipt_extension_cannot_hide_downstream_graph(graph):
    instances, bindings, resolver=graph
    queue=Path(bindings['queue:synthetic'])
    context=instances['review-context']
    raw=refs.canonical(context)
    (queue/'context.dat').write_bytes(raw)
    tier=copy.deepcopy(instances['tier2-check'])
    tier['context']=dict(root_id='queue:synthetic',path='context.dat',sha256=refs.sha256(raw),bytes=len(raw))
    validator.validate(tier,resolver,root_id='queue:synthetic')
    (queue/context['run']['path']).write_bytes(b'changed pinned run')
    with pytest.raises(ValueError,match='byte count mismatch'):
        validator.validate(tier,resolver,root_id='queue:synthetic')


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


def test_ledger_segment_index_partial_append_reconciles(graph,tmp_path,monkeypatch):
    instances, _, resolver=graph
    segment=tmp_path/'segment.jsonl'
    index=tmp_path/'campaign.jsonl'
    original=ledger.append
    def fail_index(path,*args,**kwargs):
        if path == index:
            raise OSError('synthetic index interruption')
        return original(path,*args,**kwargs)
    row=payload(instances['segment-ledger'])
    monkeypatch.setattr(ledger,'append',fail_index)
    with pytest.raises(OSError,match='synthetic index'):
        ledger.append_index(segment,index,row,writer='write_verdict.py',resolver=resolver,root_id='queue:synthetic')
    first=segment.read_bytes()
    monkeypatch.setattr(ledger,'append',original)
    ledger.append_index(segment,index,row,writer='write_verdict.py',resolver=resolver,root_id='queue:synthetic')
    assert segment.read_bytes()==first
    assert len(ledger.verify(index))==1


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
