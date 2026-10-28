"""Producer-exact owned BAG + raw JSONL + native execution; no network/live data."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest
import rasterio
from pyproj import Transformer

from tests.coast_contract_factory import load_helper
from tests._coastal_operations import policy
from tests.gis.test_coastal_vr_refinements import vr_bag, emit
from skippercast.coastal import prefetch, stage_cli, vertical
from skippercast.coastal.coordinator import catalog_bridge as bridge, loop
from skippercast.coastal.coordinator.segments import segment
from skippercast.coastal.coordinator.store import Store
from skippercast.coastal.handoff import mapping_input
from skippercast.coastal.handoff.common import ref, write

pytestmark = pytest.mark.gis
refs = load_helper('coast_refs')
load_helper('coast_ledger')
raw_contracts = load_helper('coast_raw')
validator = load_helper('validate_coast_receipt')
ROOT = 'queue:synthetic'
HEADER = dict(created_utc='2026-10-21T00:00:00Z', author_profile='synthetic-producer',
              author_model='offline-synthetic', card_id='t_f9cfca4f', code_commit='1'*40, skill_commit='2'*40)
NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


@pytest.fixture
def retained(vr_bag, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('offline only'))
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: pytest.fail('no DNS'))
    root, bag, original, inventory, metadata = vr_bag
    raw_root = root.parent / (root.name + '-raw')
    raw_root.mkdir()
    mirror = root / 'mirror'
    mirror.mkdir()
    (raw_root / 'synthetic').mkdir()
    raw_path = raw_root / 'synthetic' / bag.name
    raw_path.write_bytes(bag.read_bytes())
    def typed(path, root_id=ROOT, base=root):
        raw = path.read_bytes()
        return dict(root_id=root_id, path=path.relative_to(base).as_posix(), sha256=refs.sha256(raw), bytes=len(raw))
    def put(name, doc):
        write(root / name, doc)
        return typed(root / name)
    # Real load_plan normalization (URL policy checks only, no requests/DNS).
    plan_path = root / 'prefetch-plan.json'
    write(plan_path, dict(schema_version=1, files=[dict(source='synthetic', url=inventory['url'],
        licence='owned synthetic fixture', segments=['C2', 'C1', 'C1'], bytes=original['bytes'], sha256=original['sha256'])]))
    normalized = prefetch.load_plan(plan_path, prefetch.Session())['files'][0]
    row = {k: normalized[k] for k in ('url', 'licence', 'segments', 'bytes', 'sha256')}
    row.update(final_url=row['url'], etag=None, last_modified=None, fetched_at=prefetch.stamp(),
               path=str(raw_path), review_required=True, verification='publisher-sha256')
    other = dict(row, url=row['url'] + '.unselected', final_url=row['url'] + '.unselected',
                 path=str(raw_root / 'synthetic' / 'absent.bag'), sha256='0'*64, bytes=12)
    producer = SimpleNamespace(root=raw_root, mirror=mirror,
        records={'synthetic': {row['url']: row, other['url']: other}}, guard=lambda *a: None)
    prefetch.Prefetch.flush_manifest(producer, 'synthetic')
    snapshot = (raw_root / 'synthetic' / 'manifest.jsonl').read_bytes()
    (root / 'snapshot.jsonl').write_bytes(snapshot)
    (root / 'row.jsonl').write_bytes(snapshot.splitlines(keepends=True)[0])
    vr = emit(vr_bag)
    source = vr['outputs'][-1]['artifact']
    # GDAL read-only statistics create a real PAM sidecar; pinned TIFF unchanged.
    with rasterio.open(root / source['path']) as ds:
        ds.statistics(1)
    with rasterio.open(root / source['path']) as ds:
        observation = vertical.from_raster(ds, source_sha256=source['sha256'])
        block = dict(schema='vertical-v1', **observation['facts'], conflicts=[], evidence=[vertical.evidence_from_observation(observation)])
        x, y = Transformer.from_crs(ds.crs, 'EPSG:3310', always_xy=True).transform(*ds.xy(0, 0))
        window = [0, 0, ds.width, ds.height]
    record = dict(segment(int(x // 5000)*5000, int(y // 5000)*5000, region='synthetic'), synthetic=True)
    record['bbox_crs84'] = list(Transformer.from_crs('EPSG:3310', 'OGC:CRS84', always_xy=True).transform_bounds(*record['bbox'], densify_pts=41))
    put('rights.json', dict(schema='coast-native-rights-evidence-v1', **HEADER, statement='Owned synthetic fixture', synthetic=True))
    rights = dict(private_use=True, evidence=[ref(root, root / 'rights.json', 'coast-native-rights-evidence-v1')])
    selection = dict(source_id=inventory['id'], source=source, source_row=inventory,
                     metadata_sha256=metadata, window=window, vertical=block, rights=rights)
    plan = dict(schema=bridge.PLAN, catalog_id='synthetic-catalog', catalog_sha256='4'*64,
                segment={k: record[k] for k in ('segment_id', 'bbox_crs84')}, synthetic=True,
                max_total_bytes=10000000, budget=dict(requests=0, wall_s=60, memory_bytes=1073741824, bytes=10000000), selections=[selection])
    plan_ref = put('plan.json', plan)
    produced = mapping_input.produce(root, source, segment_id=record['segment_id'], segment=record,
        window=window, vertical=block, rights=rights, output_dir='prequalification', synthetic=True,
        source_row=inventory, metadata_sha256=metadata)
    assert produced['machine_holds'] == []
    put('review.json', dict(schema='coastal-private-input-review-v2', independent=True,
        reviewer_id='synthetic-reviewer', facts_digest=produced['facts_digest'], checked_at='2026-10-20T00:00:00Z',
        valid_until='2026-10-23T00:00:00Z', decision='accept', holds_added=[]))
    selection['review'] = ref(root, root / 'review.json', 'coastal-private-input-review-v2')
    plan_ref = put('plan.json', plan)
    native = bridge.native_job(plan, selection, dict(source=source, source_id=inventory['id'],
        publisher_id='synthetic', access_url=inventory['url'], catalog_hash_binding='synthetic'),
        dict(catalog_id=plan['catalog_id'], sha256=plan['catalog_sha256']))
    put('native.json', native)
    store = Store(root / 'store.sqlite', root=root, clock=lambda: NOW.timestamp(),
                  policy=policy(budgets={'wall_s': 3600, 'bytes': 40000000, 'requests': 0}))
    executions = []
    def dispatch(job, path, out, callback, deadline):
        result = stage_cli.execute(job, out, now=NOW)
        write(out / 'result.json', result)
        for name in ('stdout.log', 'stderr.log'):
            (path.parent / name).write_bytes(b'')
        executions.append(dict(schema='coast-native-execution-v1', **HEADER, job=typed(path),
            result=typed(out / 'result.json'), logs=[typed(path.parent / n) for n in ('stdout.log', 'stderr.log')]))
        return SimpleNamespace(rc=0 if result['state'] == 'done' else 3)
    try:
        store.add_segment(record)
        code, deps = loop.implementation_hashes(root)
        store.enqueue(record['segment_id'], 'acquire', code_sha=code, deps_sha=deps,
            input_manifest=ref(root, root / 'native.json', native['schema']), budget=plan['budget'])
        coordinator = loop.Coordinator(store, dispatcher=dispatch, clock=lambda: NOW.timestamp())
        for stage in ('acquire', 'qualify', 'map'):
            outcome = coordinator.tick(reconcile=False)
            assert outcome['state'] == 'done', (stage, outcome)
    finally:
        store.close()
    # Explicit enumeration of the synthetic producer documents, not runtime
    # filename discovery in the validator/consumer API.
    documents = [typed(root / 'native.json')]
    for execution in executions:
        result = refs.loads((root / execution['result']['path']).read_bytes())
        for artifact in result['artifacts']:
            if artifact.get('contract') in raw_contracts.NATIVE:
                documents.append(typed(root / artifact['path']))
    documents = list({refs.canonical(r): r for r in documents}.values())
    raw_ref = typed(raw_path, 'raw:campaign', raw_root)
    envelope = dict(schema=raw_contracts.ENVELOPE, **HEADER, source_id=inventory['id'], plan=plan_ref,
        snapshot=typed(root / 'snapshot.jsonl'), selections=[dict(line=1, row=typed(root / 'row.jsonl'),
        raw=raw_ref, inventory_row=inventory, metadata_sha256=metadata, originals=[typed(bag)],
        derivation=typed(root / 'derived/vr-refinements-receipt.json'), native_documents=documents)])
    envelope_ref = put('envelope.json', envelope)
    bindings = {ROOT: str(root), 'raw:campaign': str(raw_root)}
    resolver = refs.Resolver(bindings, allowed_root_ids=set(bindings))
    resolver.original_raw_roots = {'raw:campaign': str(raw_root)}
    return SimpleNamespace(root=root, raw_root=raw_root, raw_path=raw_path, resolver=resolver, put=put,
        typed=typed, envelope=envelope, envelope_ref=envelope_ref, plan=plan, vr=vr, executions=executions,
        snapshot=snapshot, row=row, other=other)


def test_complete_raw_derived_native_graph(retained):
    f = retained
    before = {p: p.read_bytes() for p in f.root.rglob('*') if p.is_file()}
    graph = validator.GraphValidator(f.resolver, raw_provenance=[f.envelope_ref])
    for execution in f.executions:
        graph.document(execution, root_id=ROOT)
    paths = {refs.loads(k[0])['path'] for k in graph.verified}
    assert {'row.jsonl', 'snapshot.jsonl', 'native.json', 'derived/vr-supergrids.csv'} <= paths
    assert all(o['artifact']['sha256'] != f.envelope['selections'][0]['raw']['sha256'] for o in f.vr['outputs'])
    assert len(f.vr['outputs']) == 3
    assert all(o['artifact']['path'] in paths for o in f.vr['outputs'])
    assert f.snapshot == (f.root / 'snapshot.jsonl').read_bytes()
    assert not (f.raw_root / 'synthetic/absent.bag').exists()
    assert all(p.read_bytes() == data for p, data in before.items())


def test_without_explicit_envelope_refuses(retained):
    f = retained
    for document in f.envelope['selections'][0]['native_documents']:
        with pytest.raises(ValueError, match='held:'):
            validator.GraphValidator(f.resolver).reference(document)
    with pytest.raises(ValueError, match='not supplied up front'):
        validator.GraphValidator(f.resolver).reference(f.envelope_ref)


@pytest.mark.parametrize('missing', ['raw', 'original', 'output0', 'output1', 'output2', 'table', 'auxiliary'])
def test_missing_required_bytes_refuse(retained, missing):
    f = retained
    if missing == 'raw':
        path = f.raw_path
    elif missing == 'original':
        path = f.root / f.envelope['selections'][0]['originals'][0]['path']
    elif missing.startswith('output'):
        path = f.root / f.vr['outputs'][int(missing[-1])]['artifact']['path']
    elif missing == 'table':
        path = f.root / f.vr['supergrid_table']['path']
    else:
        candidates = list(f.root.rglob('*.aux.xml'))
        assert candidates, 'producer must exercise actual GDAL auxiliary edge'
        path = candidates[0]
    path.unlink()
    with pytest.raises((ValueError, OSError)):
        validator.GraphValidator(f.resolver, raw_provenance=[f.envelope_ref])


@pytest.mark.parametrize('mutation', ['origin_missing', 'origin_extra', 'origin_prefix', 'origin_overlap',
    'row_changed', 'snapshot_changed', 'line', 'raw_root', 'traversal', 'metadata', 'inventory_extra',
    'inventory_trim', 'inventory_unknown', 'plan_row', 'plan_missing', 'plan_root', 'plan_selection_missing',
    'plan_selection_duplicate', 'plan_metadata', 'plan_source', 'native_unregistered', 'derivation_schema'])
def test_envelope_refusals(retained, mutation):
    f = retained
    env = deepcopy(f.envelope)
    selection = env['selections'][0]
    plan = deepcopy(f.plan)
    if mutation.startswith('origin_'):
        if mutation == 'origin_missing':
            del f.resolver.original_raw_roots
        elif mutation == 'origin_extra':
            f.resolver.original_raw_roots['raw:extra'] = '/synthetic'
        elif mutation == 'origin_prefix':
            f.resolver.original_raw_roots['raw:campaign'] += '-sibling'
        else:
            f.resolver.original_raw_roots['raw:campaign'] = str(f.root)
    elif mutation in ('row_changed', 'snapshot_changed'):
        path = f.root / ('row.jsonl' if mutation == 'row_changed' else 'snapshot.jsonl')
        path.write_bytes(path.read_bytes() + b' ')
    elif mutation == 'line':
        selection['line'] = 2
    elif mutation == 'raw_root':
        selection['raw']['root_id'] = ROOT
    elif mutation == 'traversal':
        selection['raw']['path'] = '../' + selection['raw']['path']
    elif mutation == 'metadata':
        selection['metadata_sha256'] = 'f'*64
    elif mutation.startswith('inventory_'):
        if mutation == 'inventory_extra':
            selection['inventory_row']['evidence'] = ['dist/data/unretained.json#/x']
        elif mutation == 'inventory_trim':
            del selection['inventory_row']['title']
        else:
            selection['inventory_row']['horizontal_crs'] = 'unknown'
    elif mutation == 'plan_missing':
        del env['plan']
    elif mutation == 'plan_root':
        env['plan']['root_id'] = 'raw:campaign'
    elif mutation.startswith('plan_'):
        if mutation == 'plan_row':
            plan['selections'][0]['source_row']['title'] = 'drift'
        elif mutation == 'plan_selection_missing':
            plan['selections'][0]['source_id'] = 'different'
        elif mutation == 'plan_selection_duplicate':
            plan['selections'].append(deepcopy(plan['selections'][0]))
        elif mutation == 'plan_metadata':
            plan['selections'][0]['metadata_sha256'] = 'f'*64
        else:
            plan['selections'][0]['source'] = f.vr['supergrid_table']
        env['plan'] = f.put('mutated-plan.json', plan)
    elif mutation == 'native_unregistered':
        selection['native_documents'] = [r for r in selection['native_documents'] if r['path'] != 'native.json']
        env_ref = f.put('mutated.json', env)
        graph = validator.GraphValidator(f.resolver, raw_provenance=[env_ref])
        with pytest.raises(ValueError, match='unregistered'):
            graph.reference(f.typed(f.root / 'native.json'))
        return
    else:
        derivation = deepcopy(f.vr)
        derivation['schema'] = 'unsupported-history-v1'
        selection['derivation'] = f.put('bad-derivation.json', derivation)
    env_ref = f.put('mutated.json', env)
    with pytest.raises((ValueError, OSError)):
        validator.GraphValidator(f.resolver, raw_provenance=[env_ref])


def test_unenveloped_row_snapshot_refuse_via_ledger_branch(retained):
    """A snapshot/row Ref pinned without its envelope never hashes as opaque bytes."""
    f = retained
    for name in ('row.jsonl', 'snapshot.jsonl'):
        with pytest.raises(ValueError, match='workflow receipt needs a schema'):
            validator.GraphValidator(f.resolver).reference(f.typed(f.root / name))
        with pytest.raises(ValueError, match='workflow receipt needs a schema'):
            validator.GraphValidator(f.resolver, raw_provenance=[f.envelope_ref]).walk([f.typed(f.root / name)], root_id=ROOT)


def test_envelope_outside_raw_provenance_slot_refuses(retained):
    f = retained
    graph = validator.GraphValidator(f.resolver, raw_provenance=[f.envelope_ref])
    with pytest.raises(ValueError, match='pinned outside admission raw_provenance'):
        graph.walk({'retained_inputs': [f.envelope_ref]}, root_id=ROOT)
    with pytest.raises(ValueError, match='explicit supplied Ref'):
        graph.document(f.envelope, root_id=ROOT)


def test_header_only_envelope_reemission_refuses_r_plan(retained):
    """Binding note (a): R-PLAN keys on the full envelope tuple, not its closure."""
    f = retained
    other = f.put('envelope-reemitted.json', dict(f.envelope, created_utc='2026-10-22T00:00:00Z'))
    assert other != f.envelope_ref
    for order in ([f.envelope_ref, other], [other, f.envelope_ref]):
        with pytest.raises(ValueError, match='conflicting plan selection envelopes'):
            validator.GraphValidator(f.resolver, raw_provenance=order)
    # Byte-identical supplied twice collapses to one registration (L0).
    graph = validator.GraphValidator(f.resolver, raw_provenance=[f.envelope_ref, dict(f.envelope_ref)])
    assert len(graph.provenance.envelopes) == 1


def second_plan_envelope(f, *, originals=None, native_documents=None):
    """A different pinned plan selecting the same raw bytes (historical round)."""
    plan = deepcopy(f.plan)
    plan['catalog_sha256'] = '5' * 64
    plan_ref = f.put('plan-round2.json', plan)
    selection = dict(f.envelope['selections'][0], originals=originals or f.envelope['selections'][0]['originals'])
    if native_documents is not None:
        selection['native_documents'] = native_documents
    return f.put('envelope-round2.json', dict(f.envelope, plan=plan_ref, selections=[selection]))


def test_compatible_historical_envelopes_coexist_order_independently(retained):
    f = retained
    second = second_plan_envelope(f)
    for order in ([f.envelope_ref, second], [second, f.envelope_ref]):
        graph = validator.GraphValidator(f.resolver, raw_provenance=order)
        assert set(graph.provenance.envelopes) == {refs.canonical(f.envelope_ref), refs.canonical(second)}
        assert len(graph.provenance.plan_registry) == 2 and len(graph.provenance.raw_registry) == 1
        for execution in f.executions:
            graph.document(execution, root_id=ROOT)


def retained_edges(envelope):
    """Every edge an envelope must leave in the retention set (plan, snapshot, row, raw, originals)."""
    edges = [envelope['plan'], envelope['snapshot']]
    for selection in envelope['selections']:
        edges += [selection['row'], selection['raw']] + list(selection['originals'])
    return {refs.canonical(e) for e in edges}


def retained_keys(graph):
    return {key[0] for key in graph.verified}


def test_preflight_retention_is_order_independent(retained):
    """Per-envelope traversal-cache isolation must not drop earlier envelopes' retained edges."""
    f = retained
    second = second_plan_envelope(f)
    docs = {refs.canonical(r): refs.loads((f.root / r['path']).read_text()) for r in (f.envelope_ref, second)}
    expected = set().union(*(retained_edges(d) for d in docs.values())) | set(docs)
    assert refs.canonical(f.envelope['plan']) != refs.canonical(docs[refs.canonical(second)]['plan'])
    for order in ([f.envelope_ref, second], [second, f.envelope_ref]):
        graph = validator.GraphValidator(f.resolver, raw_provenance=order)
        assert expected <= retained_keys(graph), order
        for execution in f.executions:
            graph.document(execution, root_id=ROOT)
        assert expected <= retained_keys(graph), order


def test_admission_walk_retains_every_supplied_envelope(retained):
    """Admission root walk with two compatible envelopes: pinned and historical (supplied, unreached) both retained."""
    f = retained
    admission, env_ref, plan_ref = admission_for(f)
    env_doc = refs.loads((f.root / env_ref['path']).read_text())
    expected = retained_edges(env_doc) | retained_edges(f.envelope) | {refs.canonical(env_ref), refs.canonical(f.envelope_ref),
                                                                      refs.canonical(plan_ref), refs.canonical(f.envelope['plan'])}
    for order in ([env_ref, f.envelope_ref], [f.envelope_ref, env_ref]):
        graph = validator.GraphValidator(f.resolver, raw_provenance=order)
        assert expected <= retained_keys(graph), order
        graph.document(deepcopy(admission), root_id=ROOT)
        assert expected <= retained_keys(graph), order


def test_conflicting_raw_identity_refuses_r_raw(retained):
    f = retained
    original = f.envelope['selections'][0]['originals'][0]
    copy = f.root / 'copy-of-original.bag'
    copy.write_bytes((f.root / original['path']).read_bytes())
    second = second_plan_envelope(f, originals=[original, f.typed(copy)])
    validator.GraphValidator(f.resolver, raw_provenance=[second])  # individually valid
    for order in ([f.envelope_ref, second], [second, f.envelope_ref]):
        with pytest.raises(ValueError, match='conflicting raw identity'):
            validator.GraphValidator(f.resolver, raw_provenance=order)


def test_native_registry_conflicts_are_symmetric(retained):
    """R-NAT: identical values share; any unequal value refuses regardless of order.

    Between individually valid envelopes this is unreachable (a native document's
    bytes pin its own identity tuple), so the registry rule is exercised directly.
    """
    f = retained
    graph = validator.GraphValidator(f.resolver, raw_provenance=[f.envelope_ref])
    key, value = next(iter(graph.provenance.native.items()))
    graph.provenance.register(graph.provenance.native, key, value, 'native identity')
    drifted = (dict(value[0], title='drift'), value[1], value[2])
    with pytest.raises(ValueError, match='conflicting native identity'):
        graph.provenance.register(graph.provenance.native, key, drifted, 'native identity')
    fresh = raw_contracts.Provenance(graph)
    fresh.register(fresh.native, key, drifted, 'native identity')
    with pytest.raises(ValueError, match='conflicting native identity'):
        fresh.register(fresh.native, key, value, 'native identity')


def test_json_disguised_as_raw_payload_refuses(retained):
    f = retained
    disguised = b'{"schema":"coast-raw-provenance-v1","note":"not a BAG"}\n'
    raw_path = f.raw_root / 'synthetic' / 'disguised.bag'
    raw_path.write_bytes(disguised)
    (f.root / 'disguised.bag').write_bytes(disguised)
    row = dict(f.row, path=str(raw_path), sha256=refs.sha256(disguised), bytes=len(disguised))
    producer = SimpleNamespace(root=f.raw_root, mirror=f.root / 'mirror', records={'synthetic': {row['url']: row}}, guard=lambda *a: None)
    prefetch.Prefetch.flush_manifest(producer, 'synthetic')
    snapshot = (f.raw_root / 'synthetic' / 'manifest.jsonl').read_bytes()
    (f.root / 'snapshot2.jsonl').write_bytes(snapshot)
    (f.root / 'row2.jsonl').write_bytes(snapshot)
    plan = deepcopy(f.plan)
    plan['selections'][0]['source'] = dict(path='disguised.bag', sha256=row['sha256'], bytes=row['bytes'], contract='native-raster-v1')
    plan['selections'][0]['source_row'] = dict(plan['selections'][0]['source_row'], sha256=row['sha256'])
    selection = dict(line=1, row=f.typed(f.root / 'row2.jsonl'), raw=f.typed(raw_path, 'raw:campaign', f.raw_root),
                     inventory_row=plan['selections'][0]['source_row'], metadata_sha256=f.envelope['selections'][0]['metadata_sha256'],
                     originals=[f.typed(f.root / 'disguised.bag')], derivation=None, native_documents=[])
    env_ref = f.put('envelope-disguised.json', dict(f.envelope, plan=f.put('plan-disguised.json', plan),
                                                   snapshot=f.typed(f.root / 'snapshot2.jsonl'), selections=[selection]))
    with pytest.raises(ValueError, match='cannot hide structured provenance'):
        validator.GraphValidator(f.resolver, raw_provenance=[env_ref])


def admission_for(f, *, raw_items=None, retained_inputs=(), envelope_plan_copy=False):
    """Real catalog_bridge dry-run admission around the owned BAG (P6 BAG branch)."""
    from tests import _coastal_catalog_fixture as fx
    from skippercast.coastal.coordinator.segments import from_bbox
    from skippercast.coastal.coordinator.stages import digest
    sampling = load_helper('coast_sample')
    root, source_id = f.root, 'ncei:input.bag'
    original = f.envelope['selections'][0]['originals'][0]
    source = dict({k: original[k] for k in ('path', 'sha256', 'bytes')}, contract='native-raster-v1')
    extent = [-120.60, 34.45, -120.59, 34.46]
    cx, cy = Transformer.from_crs('OGC:CRS84', 'EPSG:3310', always_xy=True).transform(-120.595, 34.455)
    record = next(r for r in from_bbox(extent, region='synthetic')
                  if r['bbox'][0] <= cx < r['bbox'][2] and r['bbox'][1] <= cy < r['bbox'][3])
    segment_ref = f.put('plans/plan01/segment.json', record)
    catalog = fx.frozen_catalog([fx.candidate('input.bag', size=source['bytes'], source_hash=source['sha256'])])
    catalog_path = root / 'discovery/d01/catalog.json'
    catalog_path.parent.mkdir(parents=True)
    catalog_sha = fx.write_catalog(catalog_path, catalog)
    catalog_ref = f.typed(catalog_path)
    selection = f.envelope['selections'][0]
    plan = fx.plan(catalog, catalog_sha, [fx.selection(source_id, source, source_row=selection['inventory_row'],
                   metadata_sha256=selection['metadata_sha256'])], bbox=record['bbox_crs84'], segment_id=record['segment_id'])
    plan_ref = f.put('plans/plan01/plan.json', plan)
    bridge.dry_run(root, catalog_path, plan, root / 'plans/plan01/dry', now=1792540800)
    dry_ref = f.typed(root / 'plans/plan01/dry/bridge-dry-run-receipt.json')
    definition = dict(source_sha256=source['sha256'], raster_crs='EPSG:3310', affine_transform=[1, 0, cx - 2, 0, -1, cy + 2],
                      width=4, height=4, tile_width=4, tile_height=4, tiling_version='single-selected-v1', pixel_window=[0, 0, 4, 4])
    grid_sha = digest(definition)
    key = sampling.window_key(source_id, grid_sha, 0)
    campaign_ref = f.put('campaign.json', dict(schema='coast-campaign-v1', **HEADER, campaign_segment_id='synthetic', bbox_crs84=extent,
                                              lane='offline-synthetic', source_inventory=[source_id], intended_windows=[key]))
    (root / 'discovery/d01/response.xml').write_bytes(b'<metadata synthetic="true">offline fixture</metadata>\n')
    discovery_ref = f.put('discovery/d01/evidence.json', dict(schema='coast-discovery-evidence-v1', **HEADER, catalog=catalog_ref,
                                                              evidence=[f.typed(root / 'discovery/d01/response.xml')]))
    footprint = list(Transformer.from_crs('EPSG:3310', 'OGC:CRS84', always_xy=True).transform_bounds(cx - 2, cy - 2, cx + 2, cy + 2, densify_pts=41))
    # A byte-different copy of the same plan is individually valid but is not plan_file.
    envelope_plan = f.put('plans/plan01/plan-copy.json', plan) if envelope_plan_copy else plan_ref
    envelope = dict(f.envelope, source_id=source_id, plan=envelope_plan,
                    selections=[dict(selection, native_documents=[])])
    env_ref = f.put('admission-envelope.json', envelope)
    usage = dict(requests=0, bytes=0, wall_s=0)
    admission = dict(schema='coast-admission-v1', **HEADER, campaign_segment_id='synthetic', coordinator_segment_id=record['segment_id'],
        plan_id='plan01', plan_sha256=digest(plan), campaign=campaign_ref, plan_file=plan_ref, segment_record=segment_ref,
        catalog=catalog_ref, discovery=discovery_ref,
        sources=[dict(source_id=source_id, raw_provenance=[selection['raw'], env_ref] if raw_items is None else raw_items,
                      retained_inputs=list(retained_inputs), hot_cache=[dict(root_id=ROOT, **{k: source[k] for k in ('path', 'sha256', 'bytes')})],
                      rights='synthetic private use', datum='unknown', reader='native-raster-v1')],
        grids=[dict(source_id=source_id, grid_sha256=grid_sha, definition=definition, cols=1, rows=1, total=1)],
        windows=[dict(window_key=key, window_dir=sampling.window_dir(key), source_id=source_id, grid_sha256=grid_sha, idx=0,
                      pixel_window=[0, 0, 4, 4], owner_segment_id=record['segment_id'], footprint=footprint,
                      overlapping_segment_ids=[record['segment_id']])],
        budgets=dict(requests=0, bytes=plan['max_total_bytes'], wall_s=plan['budget']['wall_s'], cells=bridge.MAX_WINDOW_CELLS),
        usage_before=usage, usage_delta=usage, dry_run=dry_ref, would_enqueue_count=1, selected_source_ids=[source_id],
        held_source_ids=[], preconditions=dict(exclusive_writer=True, attested_by='synthetic fixture only; no live authorization'),
        holds=[], replacement_plan_of=None)
    return admission, env_ref, plan_ref


def test_real_admission_pins_envelope(retained):
    f = retained
    admission, env_ref, _ = admission_for(f)
    before = deepcopy(admission)
    assert validator.validate(admission, f.resolver, root_id=ROOT, raw_provenance=[env_ref]) == before
    with pytest.raises(ValueError, match='unregistered admission provenance envelope'):
        validator.validate(admission, f.resolver, root_id=ROOT)


@pytest.mark.parametrize('case', ['raw_absent', 'plan_differs', 'outside_slot', 'snapshot_item'])
def test_real_admission_pin_refusals(retained, case):
    f = retained
    if case == 'raw_absent':
        admission, env_ref, _ = admission_for(f)
        admission['sources'][0]['raw_provenance'] = [env_ref]
        message = 'selected raw absent'
    elif case == 'plan_differs':
        admission, env_ref, _ = admission_for(f, envelope_plan_copy=True)
        message = 'source/plan mismatch'
    elif case == 'outside_slot':
        admission, env_ref, _ = admission_for(f)
        admission['sources'][0]['retained_inputs'] = [env_ref]
        message = 'pinned outside admission raw_provenance'
    else:
        admission, env_ref, _ = admission_for(f)
        admission['sources'][0]['raw_provenance'].append(f.typed(f.root / 'snapshot.jsonl'))
        message = 'edge suffix'
    with pytest.raises(ValueError, match=message):
        validator.validate(admission, f.resolver, root_id=ROOT, raw_provenance=[env_ref])


def test_cli_explicit_origin_and_envelopes(retained, tmp_path):
    f = retained
    receipt = tmp_path / 'execution.json'
    write(receipt, f.executions[0])
    write(tmp_path / 'roots.json', {ROOT: str(f.root), 'raw:campaign': str(f.raw_root)})
    write(tmp_path / 'origins.json', {'raw:campaign': str(f.raw_root)})
    write(tmp_path / 'envelopes.json', [f.envelope_ref])
    base = [str(receipt), '--roots', str(tmp_path / 'roots.json'), '--root-id', ROOT, '--allowed-root-id', ROOT, '--allowed-root-id', 'raw:campaign']
    full = base + ['--original-raw-roots', str(tmp_path / 'origins.json'), '--raw-provenance', str(tmp_path / 'envelopes.json')]
    assert validator.main(full) == 0
    assert validator.main(base) == 3  # held lineage without envelopes
    assert validator.main(base + ['--raw-provenance', str(tmp_path / 'envelopes.json')]) == 3  # no independent origin
    assert validator.main(full[:-4] + ['--original-raw-roots', 'origins.json', full[-2], full[-1]]) == 3
    assert validator.main(full[:7] + full[9:]) == 3  # raw:campaign not card-admitted


@pytest.mark.parametrize('case', ['valid', 'wrong_id', 'missing_title', 'extra', 'nested_extra', 'missing_leaf'])
def test_816_rights_leaf_with_registered_raw_lineage(retained, case):
    """Full #816 leaf dispatch plus #832 envelope; not a science/rights verdict."""
    from tests.gis.test_pc9_receipt_versions import rights_leaf
    f = retained
    inventory = f.envelope['selections'][0]['inventory_row']
    source = deepcopy(f.vr['source'])  # Original BAG, not a relabelled derived raster.
    leaf = rights_leaf(source, inventory)
    if case == 'wrong_id':
        leaf['source_id'] = 'OTHER_SYNTHETIC_SOURCE'
    elif case == 'missing_title':
        del leaf['product_title']
    elif case == 'extra':
        leaf['unknown'] = 'not producer metadata'
    elif case == 'nested_extra':
        leaf['unknown'] = dict(path='../DO-NOT-OPEN.json', sha256='0'*64, bytes=1)
    rights_ref = f.put('native-rights-leaf.json', leaf)
    rights = dict(private_use=True, evidence=[dict(path=rights_ref['path'], sha256=rights_ref['sha256'],
        bytes=rights_ref['bytes'], contract='coastal-rights-evidence-v1')])
    plan = deepcopy(f.plan)
    plan['selections'][0].update(source=source, rights=rights)
    plan['selections'][0].pop('review', None)
    plan_ref = f.put('rights-plan.json', plan)
    job = refs.loads((f.root / 'native.json').read_bytes())
    job.update(source=source, rights=rights)
    job.pop('review', None)
    job_ref = f.put('rights-native-job.json', job)
    envelope = deepcopy(f.envelope)
    envelope.update(plan=plan_ref)
    envelope['selections'][0]['native_documents'] = [job_ref]
    envelope_ref = f.put('rights-envelope.json', envelope)
    if case == 'missing_leaf':
        (f.root / rights_ref['path']).unlink()  # Owned synthetic evidence only.
    if case != 'valid':
        with pytest.raises((ValueError, OSError)):
            validator.GraphValidator(f.resolver, raw_provenance=[envelope_ref])
        return
    graph = validator.GraphValidator(f.resolver, raw_provenance=[envelope_ref])
    graph.reference(job_ref, contract='coastal-native-job-v1')
    assert refs.canonical(rights_ref) in {key[0] for key in graph.verified}
    with pytest.raises(ValueError, match='held:'):
        validator.GraphValidator(f.resolver).reference(job_ref, contract='coastal-native-job-v1')
