"""PC9v1 -> shared-v2 adapter: native v1 contracts, per-window evidence, sequencing.

Queue mechanics are real (Store, ticks, leases); scientific stage outputs come
from the existing synthetic dispatcher. No scientific acceptance is asserted.
"""
import copy
import json

import pytest

from tests.coast_contract_factory import ROOT, SHARED, load_helper, native_schemas
from tests.unit.test_coastal_bridge_run import (CLOCK, enqueue, offline_and_provenance, run,  # noqa: F401
                                                synthetic_dispatch, world)

refs = load_helper('coast_refs')
versions = load_helper('coast_receipt_versions')
validator = load_helper('validate_coast_receipt')


@pytest.mark.parametrize('name', sorted(native_schemas()))
def test_native_v1_schemas_are_committed_exactly(name):
    assert refs.loads((SHARED / 'schemas' / (name + '.schema.json')).read_bytes()) == native_schemas()[name]


def ref(w, relative):
    raw = (w.root / relative).read_bytes()
    return dict(root_id=w.namespace, path=relative, sha256=refs.sha256(raw), bytes=len(raw))


def put(w, relative, value):
    raw = refs.canonical(value)
    path = w.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return dict(root_id=w.namespace, path=relative, sha256=refs.sha256(raw), bytes=len(raw))


def check_v2(doc):
    validator.validate_schema(doc)
    validator._consistency(doc)


def test_two_window_run_keeps_v1_bytes_and_one_cells_record_per_window(world, synthetic_dispatch, monkeypatch):
    monkeypatch.setenv('COAST_CARD_ID', 't_1fe0dd30')
    w = world
    receipt = enqueue(w)
    summary = run(w)
    assert receipt['schema'] == 'coast-enqueue-receipt-v1' and summary['schema'] == 'coast-run-summary-v1'
    paths = ('plans/pilot01/bridge/enqueue-receipt.json', 'plans/pilot01/runs/run-00.json')
    before = {p: (w.root / p).read_bytes() for p in paths}
    for p in paths:  # PC9 native v1 wire format matches its exact native schema
        validator.validate_schema(refs.loads(before[p]))
    legacy_enqueue, legacy_run = (ref(w, p) for p in paths)
    enqueue_doc = versions.enqueue_v2(refs.loads(before[paths[0]]), legacy_enqueue)
    check_v2(enqueue_doc)
    assert [j['root_job_id'] for j in enqueue_doc['jobs']] == summary['enqueued_job_ids']
    assert (enqueue_doc['code_sha256'], enqueue_doc['deps_sha256']) == (receipt['code_sha'], receipt['deps_sha'])
    enqueue_ref = put(w, 'plans/pilot01/shared/enqueue-v2.json', enqueue_doc)
    run_doc = versions.run_v2(summary, legacy_run, enqueue_ref)
    check_v2(run_doc)
    assert {p: (w.root / p).read_bytes() for p in paths} == before  # adapter never rewrites v1 bytes
    assert run_doc['sequence'] == summary['sequence'] == 0
    cells = run_doc['window_cells']
    assert len(cells) == 2 and [c['window_index'] for c in cells] == [0, 1]
    assert len({c['producer']['path'] for c in cells}) == 2
    for record in cells:
        # Synthetic producer declares p80 'unknown': kept explicit, never invented.
        assert (record['count'], record['min'], record['max'], record['mean'], record['p80']) == (16, 1.0, 16.0, 8.5, None)
        assert record['unknown'] == ['depth_m.p80'] and record['absent'] == []
    assert run_doc['store_status_evidence']['kind'] == 'legacy_embedded'
    assert run_doc['store_status_evidence']['independent_snapshot'] is False


def test_zero_based_continuations_convert_against_converted_predecessor(world, synthetic_dispatch, monkeypatch):
    monkeypatch.setenv('COAST_CARD_ID', 't_1fe0dd30')
    w = world
    enqueue(w)
    first = run(w, until=CLOCK.timestamp() + 0.1)
    second = run(w, sequence=1, continuation=True, ticks=1)
    assert (first['sequence'], second['sequence']) == (0, 1)
    enqueue_ref = put(w, 'plans/pilot01/shared/enqueue-v2.json',
                      versions.enqueue_v2(refs.loads((w.p / 'bridge/enqueue-receipt.json').read_bytes()),
                                          ref(w, 'plans/pilot01/bridge/enqueue-receipt.json')))
    run00 = versions.run_v2(first, ref(w, 'plans/pilot01/runs/run-00.json'), enqueue_ref)
    check_v2(run00)
    assert all(c['producer'] is None and c['count'] is None and c['unknown'] for c in run00['window_cells'])
    run00_ref = put(w, 'plans/pilot01/shared/run-00-v2.json', run00)
    with pytest.raises(ValueError, match='converted predecessor'):
        versions.run_v2(second, ref(w, 'plans/pilot01/runs/run-01.json'), enqueue_ref)
    with pytest.raises(ValueError, match='converted predecessor'):
        versions.run_v2(first, ref(w, 'plans/pilot01/runs/run-00.json'), enqueue_ref, run00_ref)
    run01 = versions.run_v2(second, ref(w, 'plans/pilot01/runs/run-01.json'), enqueue_ref, run00_ref)
    check_v2(run01)
    assert run01['sequence'] == 1 and run01['continuation_of'] == run00_ref


def committed_run():
    return refs.loads((ROOT / 'tests/fixtures/coast/queue/valid/run-summary.json').read_bytes())


@pytest.mark.parametrize('change,message', [
    (lambda d: d.update(window_cells=[]), 'one record per window'),
    (lambda d: d['window_cells'][0].update(window_index=1), 'one record per window'),
    (lambda d: d['window_cells'][0].update(count=0), 'explicitly unknown'),
    (lambda d: d['window_cells'][0].update(unknown=[]), 'explicitly unknown'),
    (lambda d: d['window_cells'][0].update(producer_contract='coastal-terrain-summary-v1'), 'producer binding'),
    (lambda d: d['store_status_evidence'].update(source=d['admission']), 'original run receipt'),
    (lambda d: d.update(sequence=1), 'zero-based'),
    (lambda d: d.update(continuation_of=d['legacy_run']), 'zero-based'),
])
def test_v2_run_consistency_refusals(change, message):
    doc = committed_run()
    check_v2(doc)
    change(doc)
    with pytest.raises(ValueError, match=message):
        check_v2(doc)


@pytest.mark.parametrize('change', [
    lambda d: d.update(cells=dict(count=0)),
    lambda d: d.update(store_snapshot=d['legacy_run']),
    lambda d: d['store_status_evidence'].update(independent_snapshot=True),
    lambda d: d['store_status_evidence'].update(store_consistent_claim=True),
    lambda d: d.update(sequence=-1),
    lambda d: d.update(schema='coast-run-summary-v1'),
])
def test_v2_run_schema_refuses_aggregates_snapshot_claims_and_version_swaps(change):
    doc = committed_run()
    change(doc)
    with pytest.raises(ValueError, match='schema'):
        validator.validate_schema(doc)


def test_adapter_refuses_wrong_versions():
    doc = committed_run()
    with pytest.raises(ValueError, match='requires coast-run-summary-v1'):
        versions.run_v2(doc, doc['legacy_run'], doc['enqueue'])
    with pytest.raises(ValueError, match='requires coast-enqueue-receipt-v1'):
        versions.enqueue_v2(dict(schema='coast-enqueue-receipt-v2'), doc['enqueue'])
    with pytest.raises(ValueError, match='typed Ref'):
        versions.typed(dict(path='a.json', sha256='0' * 64, bytes=1))
    with pytest.raises(ValueError, match='typed Ref'):
        versions.typed(dict(copy.deepcopy(doc['legacy_run']), extra=1))
    assert json.loads(json.dumps(versions.typed(dict(doc['legacy_run'], contract='x', kind='input')))) == doc['legacy_run']
