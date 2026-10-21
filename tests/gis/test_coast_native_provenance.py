"""Actual synthetic raster producers plus real Store/Coordinator job serialization.

In-process dispatch executes the real stage algorithm (not the subprocess runner).
No native bytes from outside tmp_path, no sockets, no scientific acceptance claim.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from tests.coast_contract_factory import load_helper
from tests._coastal_operations import policy
from skippercast.coastal import stage_cli, vertical
from skippercast.coastal.coordinator import loop
from skippercast.coastal.coordinator.segments import segment
from skippercast.coastal.coordinator.store import Store
from skippercast.coastal.handoff import mapping_input
from skippercast.coastal.handoff.common import ref, write

pytestmark = pytest.mark.gis
refs = load_helper('coast_refs')
validator = load_helper('validate_coast_receipt')
NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
HEADER = dict(created_utc='2026-10-21T00:00:00Z', author_profile='synthetic-producer', author_model='offline-synthetic',
              card_id='t_0da2d434', code_commit='1'*40, skill_commit='2'*40)


@pytest.fixture
def native_graph(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('offline test'))
    root = tmp_path / 'queue'
    root.mkdir()
    record = dict(segment(0, 0, region='synthetic'), synthetic=True)
    source_path = root / 'native.tif'
    with rasterio.open(source_path, 'w', driver='GTiff', width=4, height=4,
                       count=1, dtype='float32', crs='EPSG:3310',
                       transform=from_origin(10, 20, 2, 2), nodata=np.nan) as ds:
        ds.write(-np.arange(1, 17, dtype='float32').reshape(4, 4), 1)
        ds.set_band_unit(1, 'm')
        ds.update_tags(vertical_sign='positive_up', vertical_datum='MLLW', scale_offset_applied='false')
    source = ref(root, source_path, 'native-raster-v1')
    with rasterio.open(source_path) as ds:
        observed = vertical.from_raster(ds, source_sha256=source['sha256'])
    block = dict(schema='vertical-v1', **observed['facts'], conflicts=[], evidence=[vertical.evidence_from_observation(observed)])
    write(root / 'segment.json', record)
    write(root / 'rights.json', dict(schema='coast-native-rights-evidence-v1', **HEADER, statement='Synthetic private-use evidence only', synthetic=True))
    rights = dict(private_use=True, evidence=[ref(root, root / 'rights.json', 'coast-native-rights-evidence-v1')])
    produced = mapping_input.produce(root, source, segment_id=record['segment_id'], segment=record,
        window=[0, 0, 4, 4], vertical=block, rights=rights, output_dir='prequalification', synthetic=True)
    assert produced['machine_holds'] == []
    write(root / 'review.json', dict(schema='coastal-private-input-review-v2', independent=True,
        reviewer_id='synthetic-reviewer', facts_digest=produced['facts_digest'], checked_at='2026-10-20T00:00:00Z',
        valid_until='2026-10-23T00:00:00Z', decision='accept', holds_added=[]))
    manifest = dict(schema='coastal-native-job-v1', synthetic=True, segment_id=record['segment_id'],
        source=source, window=[0, 0, 4, 4], vertical=block, rights=rights,
        review=ref(root, root / 'review.json', 'coastal-private-input-review-v2'))
    write(root / 'native.json', manifest)
    clock = lambda: NOW.timestamp()
    store = Store(root / 'store.sqlite', root=root, clock=clock,
                  policy=policy(budgets={'wall_s': 3600, 'bytes': 1000000, 'requests': 0}))
    store.add_segment(record)
    code, deps = loop.implementation_hashes(root)
    store.enqueue(record['segment_id'], 'acquire', code_sha=code, deps_sha=deps,
                  input_manifest=ref(root, root / 'native.json', manifest['schema']),
                  budget=dict(wall_s=60, memory_bytes=1073741824, bytes=100000, requests=0))
    receipts = []
    def typed(path):
        native = ref(root, path, 'unused')
        return dict(root_id='queue:synthetic', **{k: native[k] for k in ('path', 'sha256', 'bytes')})
    def dispatch(job, job_path, out, callback, deadline):
        # Job bytes were serialized by Coordinator, unchanged from real Store.claim.
        assert refs.loads(job_path.read_bytes()) == job
        result = stage_cli.execute(job, out, now=NOW)
        write(out / 'result.json', result)
        for name in ('stdout.log', 'stderr.log'):
            (job_path.parent / name).write_bytes(b'')
        receipts.append(dict(schema='coast-native-execution-v1', **HEADER, job=typed(job_path), result=typed(out / 'result.json'),
                             logs=[typed(job_path.parent / n) for n in ('stdout.log', 'stderr.log')]))
        return SimpleNamespace(rc=0 if result['state'] == 'done' else 3)
    try:
        coordinator = loop.Coordinator(store, dispatcher=dispatch, clock=clock)
        for expected in ('acquire', 'qualify', 'map'):
            outcome = coordinator.tick(reconcile=False)
            assert outcome['state'] == 'done', outcome
            assert refs.loads((root / receipts[-1]['job']['path']).read_bytes())['stage'] == expected
        resolver = refs.Resolver({'queue:synthetic': str(root)}, allowed_root_ids={'queue:synthetic'})
        yield root, receipts, resolver
    finally:
        store.close()


def test_complete_native_execution_graph(native_graph):
    root, receipts, resolver = native_graph
    graph = validator.GraphValidator(resolver)
    original = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    for receipt in receipts:
        graph.document(receipt, root_id='queue:synthetic')
    visited = {refs.loads(key[0])['path'] for key in graph.verified}
    assert {'native.json', 'native.tif', 'review.json', 'rights.json'} <= visited
    for suffix in ('job.json', 'observation.json', 'mapping-input.json', 'run.json', 'cells.json', 'terrain.tif', 'support.tif', 'native-support.tif', 'result.json', 'stdout.log', 'stderr.log'):
        assert any(p.endswith('/' + suffix) for p in visited), suffix
    assert all(p.read_bytes() == raw for p, raw in original.items())


@pytest.mark.parametrize('mutation', ['missing_input', 'changed_input', 'wrong_contract', 'extra_path', 'cross_root', 'result_identity', 'historical'])
def test_native_fail_closed(native_graph, mutation):
    root, receipts, resolver = native_graph
    receipt = deepcopy(receipts[-1])
    job = refs.loads((root / receipt['job']['path']).read_bytes())
    if mutation in ('missing_input', 'changed_input'):
        path = root / job['input_manifest']['path']
        path.unlink() if mutation == 'missing_input' else path.write_bytes(b'changed')
    elif mutation == 'wrong_contract':
        job['input_manifest']['contract'] = 'coastal-mapping-run-v1'
    elif mutation == 'extra_path':
        job['unexpected_path'] = 'missing.bin'
    elif mutation == 'cross_root':
        job['input_manifest']['root_id'] = 'queue:other'
    elif mutation == 'result_identity':
        result = refs.loads((root / receipt['result']['path']).read_bytes())
        result['job_id'] = 'job:' + 'f'*24
        (root / receipt['result']['path']).write_bytes(refs.canonical(result))
        raw = (root / receipt['result']['path']).read_bytes()
        receipt['result'].update(sha256=refs.sha256(raw), bytes=len(raw))
    else:
        # A later map cannot erase the acquire observation's preservation duty.
        receipt = deepcopy(receipts[0])
        result = refs.loads((root / receipt['result']['path']).read_bytes())
        (root / result['artifacts'][0]['path']).write_bytes(b'corrupt normal historical input')
    if mutation in ('wrong_contract', 'extra_path', 'cross_root'):
        raw = refs.canonical(job)
        (root / receipt['job']['path']).write_bytes(raw)
        receipt['job'].update(sha256=refs.sha256(raw), bytes=len(raw))
    with pytest.raises((ValueError, OSError)):
        validator.GraphValidator(resolver).document(receipt, root_id='queue:synthetic')


def test_schema_less_selection_is_not_filename_or_shape(native_graph):
    root, receipts, resolver = native_graph
    job = receipts[0]['job']
    with pytest.raises(ValueError, match='unsupported JSON producer'):
        validator.GraphValidator(resolver).reference(job)
    with pytest.raises(ValueError, match='contract mismatch'):
        validator.GraphValidator(resolver).reference(job, contract='coastal-native-job-v1')
    # Only the typed workflow job edge selects the schema-less adapter.
    validator.GraphValidator(resolver).document(receipts[0], root_id='queue:synthetic')


def test_generic_workflow_traverses_admission_and_native_provenance(native_graph):
    from tests.coast_contract_factory import materialize
    root, receipts, _ = native_graph
    instances, bindings = materialize(root.parent)
    check = deepcopy(instances['tier2-check'])
    for i, receipt in enumerate(receipts):
        path = root / f'execution-{i}.json'
        write(path, receipt)
        raw = path.read_bytes()
        check['verified_inputs'].append(dict(root_id='queue:synthetic', path=path.name, sha256=refs.sha256(raw), bytes=len(raw)))
    resolver = refs.Resolver(bindings, allowed_root_ids=set(bindings))
    validator.validate(check, resolver, root_id='queue:synthetic')
    # The ordinary receipt cannot keep asserting valid historical native inputs.
    (root / receipts[0]['job']['path']).write_bytes(b'corrupted historical job')
    with pytest.raises(ValueError):
        validator.validate(check, resolver, root_id='queue:synthetic')


@pytest.mark.parametrize('field', ['source_row', 'raw_manifest_snapshot', 'derivation'])
def test_unadmitted_provenance_is_held_not_ignored(native_graph, field):
    root, receipts, resolver = native_graph
    job = refs.loads((root / receipts[0]['job']['path']).read_bytes())
    manifest = refs.loads((root / job['input_manifest']['path']).read_bytes())
    manifest[field] = {'path': 'unadmitted.json', 'sha256': '0'*64, 'bytes': 0}
    with pytest.raises(ValueError, match='held:|unknown or missing native producer field'):
        validator.GraphValidator(resolver).document(manifest, root_id='queue:synthetic')


def test_known_json_slot_cannot_hide_renamed_unknown_json(native_graph):
    root, receipts, resolver = native_graph
    job = refs.loads((root / receipts[-1]['job']['path']).read_bytes())
    manifest = refs.loads((root / job['input_manifest']['path']).read_bytes())
    write(root / 'unknown.dat', {'schema': 'unknown-provenance-v1', 'input_path': 'missing'})
    manifest['review'] = ref(root, root / 'unknown.dat', 'coastal-private-input-review-v2')
    with pytest.raises(ValueError, match='contract mismatch'):
        validator.GraphValidator(resolver).document(manifest, root_id='queue:synthetic')
