"""B1b exact documented CLI plus actual Store API; synthetic rasters only."""
from pathlib import Path
import socket

import pytest

from tests.coast_admit_factory import (common, command, refs, smoke, stage, world)
from tests.coast_contract_factory import load_helper
from tests._coastal_operations import policy
from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.coastal.coordinator.store import Store

validator = load_helper('validate_coast_receipt')


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args,**kwargs):
        raise AssertionError('B1b must not open a socket')
    monkeypatch.setattr(socket.socket,'connect',refuse)
    monkeypatch.setattr(socket.socket,'connect_ex',refuse)
    monkeypatch.setattr(socket,'create_connection',refuse)
    monkeypatch.setattr(socket,'getaddrinfo',refuse)


def test_documented_checkout_cwd_smoke_and_actual_store_enqueue(tmp_path):
    w = world(tmp_path,raster=True)
    admission = smoke(w)
    root, p = w['queue'], Path(w['env']['P'])
    bindings = refs.loads(Path(w['env']['ROOTS']).read_bytes())
    resolver = refs.Resolver(bindings,allowed_root_ids=set(bindings))
    validator.validate(admission,resolver,root_id='queue:synthetic-campaign')
    dry = refs.loads((p/'dry/bridge-dry-run-receipt.json').read_bytes())
    assert admission['would_enqueue_count'] == len(dry['would_enqueue']) == 1
    assert admission['holds'] == []
    assert all(x['window_key'] == x['source_id']+'#'+x['grid_sha256']+'#0' for x in admission['windows'])
    record = refs.loads((p/'segment.json').read_bytes())
    assert record['segment_id'] != w['campaign']['campaign_segment_id']
    assert record['region'] == w['campaign']['campaign_segment_id']
    assert not (root/'var/coastal/coordinator.sqlite').exists()
    plan = refs.loads((p/'plan.json').read_bytes())
    receipt = bridge.run(root,root/w['selection']['catalog']['path'],plan,p/'bridge')
    store = Store(root/'var/coastal/coordinator.sqlite',root=root,policy=policy())
    try:
        store.add_segment(record)
        ref = dict(receipt['output'],kind='input',contract=bridge.RECEIPT)
        ids = bridge.enqueue(store,ref,code_sha='a'*64,deps_sha='b'*64)
        rows = store.db.execute('SELECT segment_id,stage,state FROM jobs').fetchall()
        assert len(ids) == len(rows) == 1
        assert tuple(rows[0]) == (record['segment_id'],'acquire','queued')
    finally:
        store.close()


@pytest.mark.parametrize('field',['segment_id','bbox','bbox_crs84'])
def test_frozen_wrong_id_projected_and_crs84_refused_before_admission(tmp_path,field):
    w = world(tmp_path,raster=True)
    for i in range(3):
        result = command(w,i)
        assert result.returncode == 0, result.stderr
    p = Path(w['env']['P'])
    record = refs.loads((p/'segment.json').read_bytes())
    record[field] = 'campaign-label' if field == 'segment_id' else [0,0,1,1]
    (p/'segment.json').write_bytes(refs.canonical(record))
    result = command(w,3)
    assert result.returncode == 3 and 'frozen segment' in result.stderr
    assert not (p/'admission.json').exists()
    assert not (w['queue']/'var').exists()


def test_multi_owner_refusal_prints_partition_and_keeps_inventory(tmp_path):
    from pyproj import Transformer
    cx,cy = Transformer.from_crs('OGC:CRS84','EPSG:3310',always_xy=True).transform(-120.595,34.455)
    w = world(tmp_path,raster=True,centres=[(cx,cy),(cx+5000,cy)])
    original = (w['queue']/'campaign.json').read_bytes()
    assert command(w,0).returncode == 0
    result = command(w,1)
    assert result.returncode == 3 and 'partition inventory' in result.stderr
    for key in w['campaign']['intended_windows']:
        assert key in result.stderr
    assert not Path(w['env']['P']).exists()
    assert (w['queue']/'campaign.json').read_bytes() == original


def test_boundary_owner_crossing_window_not_clipped(tmp_path):
    import math
    from pyproj import Transformer
    cx,cy = Transformer.from_crs('OGC:CRS84','EPSG:3310',always_xy=True).transform(-120.595,34.455)
    cx = math.floor(cx/5000)*5000
    w = world(tmp_path,raster=True,centres=[(cx,cy)])
    admission = smoke(w)
    window = admission['windows'][0]
    assert window['owner_segment_id'] == common.owner_id(cx,cy)
    assert len(window['overlapping_segment_ids']) >= 2
    record = refs.loads((Path(w['env']['P'])/'segment.json').read_bytes())
    assert window['footprint'][0] < record['bbox_crs84'][2]
    assert window['pixel_window'] == [0,0,4,4]
    assert window['footprint'][2] > window['footprint'][0]


@pytest.mark.parametrize('scope',['campaign','segment'])
def test_budget_snapshot_both_scopes_refuse_overrun(tmp_path,scope):
    w = world(tmp_path,raster=True)
    path = Path(w['env']['LEDGER_SNAPSHOT'])
    snapshot = refs.loads(path.read_bytes())
    snapshot[scope+'_limits']['bytes'] = 1
    pin = w['put'](path,snapshot)
    w['selection']['ledger_snapshot'] = pin
    w['put'](Path(w['env']['SELECTION']),w['selection'])
    for i in range(3):
        result = command(w,i)
        assert result.returncode == 0, result.stderr
    result = command(w,3)
    assert result.returncode == 3 and scope+' budget cap' in result.stderr
    assert not (Path(w['env']['P'])/'admission.json').exists()


def test_native_grid_metadata_mismatch_refuses_before_plan(tmp_path):
    w = world(tmp_path,raster=True)
    # Keep the campaign/selection internally bound, but lie about raster metadata.
    w['selection']['windows'][0]['grid_definition']['width'] = 5
    key = common.window_key(w['selection']['windows'][0]['source_id'],refs.object_digest(w['selection']['windows'][0]['grid_definition']),0)
    w['campaign']['intended_windows'] = [key]
    w['put'](w['queue']/'campaign.json',w['campaign'])
    w['selection']['campaign_sha256'] = refs.sha256(refs.canonical(w['campaign']))
    w['put'](Path(w['env']['SELECTION']),w['selection'])
    raw = refs.loads(Path(w['env']['RAW_RECEIPT']).read_bytes())
    raw['campaign_sha256'] = w['selection']['campaign_sha256']
    w['put'](Path(w['env']['RAW_RECEIPT']),raw)
    assert command(w,0).returncode == 0
    result = command(w,1)
    assert result.returncode == 3 and 'native metadata' in result.stderr
    assert not Path(w['env']['P']).exists()


def test_held_catalog_keeps_window_and_zero_count(tmp_path):
    w = world(tmp_path,raster=True)
    catalog_path = w['queue']/w['selection']['catalog']['path']
    catalog = refs.loads(catalog_path.read_bytes())
    catalog['usable_source_ids'] = []
    catalog['catalog_id'] = refs.object_digest({k:v for k,v in catalog.items() if k != 'catalog_id'})
    w['selection']['catalog'] = w['put'](catalog_path,catalog)
    evidence_path = w['queue']/w['selection']['discovery']['path']
    evidence = refs.loads(evidence_path.read_bytes())
    evidence['catalog'] = w['selection']['catalog']
    w['selection']['discovery'] = w['put'](evidence_path,evidence)
    w['put'](Path(w['env']['SELECTION']),w['selection'])
    admission = smoke(w)
    assert len(admission['windows']) == 1 and admission['would_enqueue_count'] == 0
    assert admission['holds'] == ['not_a_usable_catalog_lead']
    assert admission['held_source_ids'] == [w['selection']['windows'][0]['source_id']]


def test_derived_input_retains_original_and_supported_derivation(tmp_path):
    w = world(tmp_path,raster=True)
    original = w['raw']/'original.bag'
    original.write_bytes(b'Synthetic original BAG placeholder; no BAG reader invoked.\n')
    raw_ref = common.file_ref(original,'raw:campaign',w['raw'])
    (w['queue']/'original.bag').write_bytes(original.read_bytes())
    (w['queue']/'derived.tif').write_bytes((w['raw']/'input0.tif').read_bytes())
    def native(path):
        ref = common.file_ref(w['queue']/path,'queue:synthetic-campaign',w['queue'])
        return {k:ref[k] for k in ('path','sha256','bytes')}
    # Synthetic supported native producer graph with original and output refs;
    # this asserts retention/binding only, not actual conversion or map quality.
    derivation = w['put'](w['queue']/'derivation.json',dict(schema='coastal-mapping-run-v1',
                        source=native('original.bag'),outputs=dict(terrain=native('derived.tif'))))
    window = w['selection']['windows'][0]
    window['raw_provenance'] = [raw_ref]
    window['retained_inputs'] = [derivation]
    w['put'](Path(w['env']['SELECTION']),w['selection'])
    raw = refs.loads(Path(w['env']['RAW_RECEIPT']).read_bytes())
    raw['sources'] = [{k:window[k] for k in ('source_id','input','raw_provenance','retained_inputs')}]
    w['put'](Path(w['env']['RAW_RECEIPT']),raw)
    admission = smoke(w)
    source = admission['sources'][0]
    assert source['raw_provenance'] == [raw_ref]
    assert source['retained_inputs'] == [derivation]
    assert source['hot_cache'][0]['sha256'] != raw_ref['sha256']


@pytest.mark.parametrize('target',['dry','cache','plan'])
def test_changed_producer_bytes_refuse_admission(tmp_path,target):
    w = world(tmp_path,raster=True)
    for i in range(3):
        result = command(w,i)
        assert result.returncode == 0, result.stderr
    p = Path(w['env']['P'])
    if target == 'dry':
        path = p/'dry/bridge-dry-run-receipt.json'
        value = refs.loads(path.read_bytes())
        value['would_enqueue'][0]['native_job_sha256'] = 'f'*64
    elif target == 'plan':
        path = p/'plan.json'
        value = refs.loads(path.read_bytes())
        value['selections'][0]['window'] = [0,0,3,4]
    else:
        stage_receipt = refs.loads(Path(w['env']['CACHE_STAGE_RECEIPT']).read_bytes())
        path = w['queue']/stage_receipt['sources'][0]['hot_cache']['path']
        path.write_bytes(b'tampered')
        value = None
    if value is not None:
        # Tests mutate only their own synthetic write-once producer output.
        path.unlink()
        path.write_bytes(refs.canonical(value))
    result = command(w,3)
    assert result.returncode == 3
    assert not (p/'admission.json').exists()
    assert not (w['queue']/'var').exists()


def test_remaining_campaign_inventory_not_dropped(tmp_path):
    w = world(tmp_path,raster=True)
    extra = 'unselected-source#'+'a'*64+'#0'
    w['campaign']['source_inventory'].append('unselected-source')
    w['campaign']['intended_windows'].append(extra)
    w['put'](w['queue']/'campaign.json',w['campaign'])
    w['selection']['campaign_sha256'] = refs.sha256(refs.canonical(w['campaign']))
    w['put'](Path(w['env']['SELECTION']),w['selection'])
    for path in (Path(w['env']['RAW_RECEIPT']),Path(w['env']['LEDGER_SNAPSHOT'])):
        value = refs.loads(path.read_bytes())
        value['campaign_sha256'] = w['selection']['campaign_sha256']
        ref = w['put'](path,value)
        if path == Path(w['env']['LEDGER_SNAPSHOT']):
            w['selection']['ledger_snapshot'] = ref
    w['put'](Path(w['env']['SELECTION']),w['selection'])
    assert command(w,0).returncode == 0
    result = command(w,1)
    assert result.returncode == 0, result.stderr
    assert refs.loads(result.stdout)['remaining_inventory'] == [extra]
    assert command(w,2).returncode == 0
    result = command(w,3)
    assert result.returncode == 0, result.stderr
    assert extra in refs.loads((w['queue']/'campaign.json').read_bytes())['intended_windows']
