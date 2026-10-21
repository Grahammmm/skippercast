"""Real producer admission regressions; source-free and synthetic only."""
import copy
from pathlib import Path

import pytest

from tests.coast_real_admission_factory import real_admission, refs
from tests.coast_contract_factory import load_helper
from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.coastal.coordinator.stages import digest

validator = load_helper('validate_coast_receipt')


@pytest.fixture
def real(tmp_path):
    admission, bindings = real_admission(tmp_path)
    resolver = refs.Resolver(bindings,allowed_root_ids=set(bindings))
    return admission, bindings, resolver


def repin(admission, bindings, field, change):
    ref = admission[field]
    target = Path(bindings[ref['root_id']])/ref['path']
    value = refs.loads(target.read_bytes())
    change(value)
    raw = refs.canonical(value)
    # Replace only this test's synthetic immutable producer output.
    target.unlink()
    target.write_bytes(raw)
    admission[field] = dict(ref,sha256=refs.sha256(raw),bytes=len(raw))
    return value


def test_real_producer_admission_graph(real):
    admission, bindings, resolver = real
    before = copy.deepcopy(admission)
    assert validator.validate(admission,resolver,root_id='queue:synthetic') == before
    assert admission == before
    for field in ('campaign','segment_record','catalog','plan_file','dry_run','discovery'):
        assert admission[field]['path'].endswith('.json')
    dry = refs.loads(resolver.read(admission['dry_run']))
    assert isinstance(dry['would_enqueue'],list)
    assert admission['would_enqueue_count'] == len(dry['would_enqueue']) == 1
    assert admission['grids'][0]['grid_sha256'] == digest(admission['grids'][0]['definition'])
    assert admission['sources'][0]['raw_provenance'][0]['root_id'] == 'raw:campaign'


@pytest.mark.parametrize('field', ['campaign','segment_record','catalog','plan_file','dry_run','discovery'])
def test_real_pin_hash_refusal(real,field):
    admission, _, resolver = real
    admission[field]['sha256'] = 'f'*64
    with pytest.raises(ValueError,match='SHA256'):
        validator.validate(admission,resolver,root_id='queue:synthetic')


@pytest.mark.parametrize(('field','change','error'), [
    ('segment_record',lambda d:d.update(segment_id='seg:3310:0:0:5000'),'lattice'),
    ('segment_record',lambda d:d['bbox'].__setitem__(2,d['bbox'][2]+1),'lattice'),
    ('segment_record',lambda d:d['bbox_crs84'].__setitem__(0,0),'lattice'),
    ('plan_file',lambda d:d['segment'].update(segment_id='seg:3310:0:0:5000'),'segment binding'),
    ('dry_run',lambda d:d.update(plan_sha256='f'*64),'digest binding'),
    ('dry_run',lambda d:d['would_enqueue'][0].update(native_job_sha256='f'*64),'native job binding'),
    ('campaign',lambda d:d.update(source_inventory=[]),'inventory'),
    ('campaign',lambda d:d.update(intended_windows=[]),'inventory'),
    ('campaign',lambda d:d.update(bbox_crs84=[-119,34,-118,35]),'campaign lattice'),
])
def test_rehashed_wrong_binding_refusal(real,field,change,error):
    admission, bindings, resolver = real
    repin(admission,bindings,field,change)
    with pytest.raises(ValueError,match=error):
        validator.validate(admission,resolver,root_id='queue:synthetic')


@pytest.mark.parametrize('change', [
    lambda a:a['grids'][0]['definition'].update(pixel_window=[1,0,3,4]),
    lambda a:a['windows'][0].update(pixel_window=[0,0,3,4]),
    lambda a:a.update(would_enqueue_count=0),
    lambda a:a.update(selected_source_ids=[]),
    lambda a:a['grids'].append(copy.deepcopy(a['grids'][0])),
    lambda a:a['windows'][0].update(footprint=[0,0,1,1]),
    lambda a:a['windows'][0].update(overlapping_segment_ids=[]),
    lambda a:a['sources'][0].update(hot_cache=[]),
])
def test_real_population_grid_refusal(real,change):
    admission, _, resolver = real
    change(admission)
    with pytest.raises(ValueError):
        validator.validate(admission,resolver,root_id='queue:synthetic')


@pytest.mark.parametrize('schema', [bridge.PLAN,bridge.CATALOG,bridge.DRY_RUN,bridge.RECEIPT])
def test_unknown_native_ref_slots_refuse(real,schema):
    admission, _, resolver = real
    field = {bridge.PLAN:'plan_file',bridge.CATALOG:'catalog',bridge.DRY_RUN:'dry_run'}.get(schema,'dry_run')
    doc = refs.loads(resolver.read(admission[field]))
    # Test nested unknown ref slots, even when content hashes are correctly rebound.
    if schema == bridge.RECEIPT:
        doc['schema'] = schema
        del doc['would_enqueue']
        doc.update(jobs=[],budget={},segment={})
    doc['decoy'] = {'path':'cache/source/input.bag','sha256':'a'*64,'bytes':1}
    with pytest.raises(ValueError,match='unknown producer field|unknown native ref slot'):
        validator.GraphValidator(resolver).document(doc,root_id='queue:synthetic')


def test_unknown_producer_and_ref_metadata_refusal(real):
    admission, _, resolver = real
    graph = validator.GraphValidator(resolver)
    with pytest.raises(ValueError,match='unsupported JSON producer'):
        graph.document(dict(schema='unadmitted-producer-v1'),root_id='queue:synthetic')
    plan = refs.loads(resolver.read(admission['plan_file']))
    plan['selections'][0]['source']['hidden'] = dict(path='bad',sha256='a'*64,bytes=1)
    with pytest.raises(ValueError,match='unknown native ref field'):
        graph.document(plan,root_id='queue:synthetic')
    plan = refs.loads(resolver.read(admission['plan_file']))
    with pytest.raises(ValueError,match='original queue'):
        graph.document(plan,root_id='raw:campaign')
    plan['selections'][0]['unadmitted_path'] = 'secret.json'
    with pytest.raises(ValueError,match='unknown native path field'):
        graph.document(plan,root_id='queue:synthetic')


def test_no_text_or_extension_bypass(real):
    admission, bindings, resolver = real
    queue = Path(bindings['queue:synthetic'])
    raw = b'opaque campaign masquerade\n'
    (queue/'not-a-campaign.txt').write_bytes(raw)
    admission['campaign'] = dict(root_id='queue:synthetic',path='not-a-campaign.txt',sha256=refs.sha256(raw),bytes=len(raw))
    with pytest.raises(ValueError):
        validator.validate(admission,resolver,root_id='queue:synthetic')


@pytest.mark.parametrize('change', [
    lambda a:a.update(preconditions=[]),
    lambda a:a['windows'][0].update(pixel_window=dict(col_off=0,row_off=0,width=4,height=4)),
    lambda a:a['grids'][0].update(pixel_window=[0,0,4,4]),
])
def test_legacy_or_mixed_execution_shapes_refuse(real,change):
    admission, _, _ = real
    change(admission)
    with pytest.raises(ValueError,match='schema'):
        validator.validate_schema(admission)


def test_rehashed_wrong_centre_owner(real):
    admission, bindings, resolver = real
    grid = admission['grids'][0]
    grid['definition']['affine_transform'][2] += 5000
    sha = digest(grid['definition'])
    grid['grid_sha256'] = sha
    window = admission['windows'][0]
    window['grid_sha256'] = sha
    window['window_key'] = window['source_id']+'#'+sha+'#0'
    sampling = load_helper('coast_sample')
    window['window_dir'] = sampling.window_dir(window['window_key'])
    repin(admission,bindings,'campaign',lambda d:d.update(intended_windows=[window['window_key']]))
    with pytest.raises(ValueError,match='pixel centre owner'):
        validator.validate(admission,resolver,root_id='queue:synthetic')


def test_native_bridge_run_receipt_graph(real):
    admission, bindings, resolver = real
    root = Path(bindings['queue:synthetic'])
    plan = refs.loads(resolver.read(admission['plan_file']))
    bridge.run(root,root/admission['catalog']['path'],plan,root/'plans/plan01/bridge',now=1792540800)
    # Serialized receipt, not the API-return-only output descriptor (which is not in file bytes).
    path = root/'plans/plan01/bridge/bridge-receipt.json'
    raw = path.read_bytes()
    validator.GraphValidator(resolver).reference(dict(root_id='queue:synthetic',path=path.relative_to(root).as_posix(),sha256=refs.sha256(raw),bytes=len(raw)))
