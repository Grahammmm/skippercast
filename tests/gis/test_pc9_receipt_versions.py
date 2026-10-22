"""PC9v1 -> shared-v2 adapter through the real producer graph (GIS stages, offline).

The PC9 driver, Store, Coordinator ticks and the real acquire/qualify/map stage
producers run unpatched on tiny synthetic rasters. The admission is completed to
the shared coast-admission-v1 contract. Nothing here is scientific acceptance:
the validator only proves structurally self-consistent, hash-bound evidence.
"""
import copy
import hashlib
import json
import math
import shutil
from types import SimpleNamespace

import pytest

from skippercast.coastal.coordinator import catalog_bridge, loop
from skippercast.coastal.coordinator.segments import from_bbox
from skippercast.coastal.coordinator.stages import digest
from skippercast.coastal.handoff.common import write
from tests._support import FIXTURES, NOW
from tests.coast_contract_factory import load_helper
from tests.unit.test_coastal_bridge_run import enqueue, offline_and_provenance, run, world  # noqa: F401

pytestmark = pytest.mark.gis
refs = load_helper('coast_refs')
sampling = load_helper('coast_sample')
versions = load_helper('coast_receipt_versions')
validator = load_helper('validate_coast_receipt')

HEADER = dict(created_utc='2026-10-22T00:00:00Z', author_profile='synthetic-builder', author_model='synthetic-test-model',
              card_id='t_1fe0dd30', code_commit='1' * 40, skill_commit='2' * 40)


def put(root, relative, value):
    raw = value if isinstance(value, bytes) else refs.canonical(value)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return dict(root_id='queue:' + root.name, path=relative, sha256=refs.sha256(raw), bytes=len(raw))


def footprint(definition, pixel):
    """Same 42-step boundary densification the shared admission validator uses."""
    from pyproj import Transformer
    from shapely.geometry import Polygon
    col, row, width, height = pixel
    a, b, c, d, e, f = definition['affine_transform']
    geographic = Transformer.from_crs(definition['raster_crs'], 'OGC:CRS84', always_xy=True)
    corners = [(col, row), (col + width, row), (col + width, row + height), (col, row + height)]
    points = []
    for start, end in zip(corners, corners[1:] + corners[:1]):
        for step in range(42):
            px = start[0] + (end[0] - start[0]) * step / 42
            py = start[1] + (end[1] - start[1]) * step / 42
            points.append(geographic.transform(a * px + b * py + c, d * px + e * py + f))
    return Polygon(points)


def shared_admission(w, tmp_path):
    """Complete the PC9 fixture admission to the shared contract (both validators read it)."""
    from shapely.geometry import box
    root, admission = w.root, copy.deepcopy(w.admission)
    campaign = json.loads((root / 'campaign.json').read_text())
    plan = w.plan
    keys = [window['window_key'] for window in admission['windows']]
    source_ids = [s['source_id'] for s in plan['selections']]
    admission['campaign'] = put(root, 'campaign.json', dict(schema='coast-campaign-v1', **HEADER,
        campaign_segment_id=root.name, bbox_crs84=campaign['bbox_crs84'], lane='offline-synthetic',
        source_inventory=source_ids, intended_windows=keys))
    evidence = put(root, 'discovery/synthetic-response.xml', b'<metadata synthetic="true">offline fixture</metadata>\n')
    admission['discovery'] = put(root, 'discovery/evidence.json', dict(schema='coast-discovery-evidence-v1', **HEADER,
        catalog=admission['catalog'], evidence=[evidence]))
    raw_root = tmp_path / 'raw'
    raw_root.mkdir()
    sources = []
    for selection in plan['selections']:
        hot = dict(root_id='queue:' + root.name, **{k: selection['source'][k] for k in ('path', 'sha256', 'bytes')})
        name = selection['source']['path'].rsplit('/', 1)[-1]
        (raw_root / name).write_bytes((root / selection['source']['path']).read_bytes())
        sources.append(dict(source_id=selection['source_id'], raw_provenance=[dict(hot, root_id='raw:campaign', path=name)],
                            retained_inputs=[], hot_cache=[hot], rights='synthetic private use', datum='MLLW', reader='native-raster-v1'))
    records = from_bbox(campaign['bbox_crs84'], region=root.name)
    for grid, window in zip(admission['grids'], admission['windows']):
        grid.update(source_id=window['source_id'], cols=1, rows=1, total=1)
        shape = footprint(grid['definition'], window['pixel_window'])
        window['footprint'] = list(shape.bounds)
        window['overlapping_segment_ids'] = sorted(r['segment_id'] for r in records if shape.intersection(box(*r['bbox_crs84'])).area > 0)
    dry = json.loads((w.p / 'dry/bridge-dry-run-receipt.json').read_text())
    admission.update(HEADER, sources=sources, budgets=dict(requests=0, bytes=plan['max_total_bytes'], wall_s=plan['budget']['wall_s'],
        cells=catalog_bridge.MAX_WINDOW_CELLS), usage_before=dict(requests=0, bytes=0, wall_s=0), usage_delta=dict(requests=0, bytes=0, wall_s=0),
        would_enqueue_count=len(dry['would_enqueue']), selected_source_ids=dry['selected_source_ids'], held_source_ids=dry['held_source_ids'],
        replacement_plan_of=None)
    (w.p / 'admission.json').write_bytes(refs.canonical(admission))
    w.admission = admission
    bindings = {'queue:' + root.name: str(root), 'raw:campaign': str(raw_root)}
    return refs.Resolver(bindings, allowed_root_ids=set(bindings))


def run_real_stages(w, monkeypatch):
    from skippercast.coastal.stage_cli import execute
    enqueue(w)
    original_init = loop.Coordinator.__init__
    def dispatch(job, job_path, out, identity_callback, deadline):
        value = execute(job, out, now=NOW)
        write(out / 'result.json', value)
        return SimpleNamespace(rc={'done': 0, 'held': 3}[value['state']])
    def initialize(coordinator, store, **kwargs):
        original_init(coordinator, store, dispatcher=dispatch, **kwargs)
    monkeypatch.setattr(loop.Coordinator, '__init__', initialize)
    return run(w)


def convert(w):
    """Write v2 records next to the untouched v1 receipts; return refs and documents."""
    root = w.root
    def ref(relative):
        raw = (root / relative).read_bytes()
        return dict(root_id='queue:' + root.name, path=relative, sha256=refs.sha256(raw), bytes=len(raw))
    legacy_enqueue = ref('plans/pilot01/bridge/enqueue-receipt.json')
    legacy_run = ref('plans/pilot01/runs/run-00.json')
    enqueue_doc = versions.enqueue_v2(json.loads((root / legacy_enqueue['path']).read_text()), legacy_enqueue)
    enqueue_ref = put(root, 'plans/pilot01/shared/enqueue-receipt-v2.json', enqueue_doc)
    run_doc = versions.run_v2(json.loads((root / legacy_run['path']).read_text()), legacy_run, enqueue_ref)
    run_ref = put(root, 'plans/pilot01/shared/run-00-v2.json', run_doc)
    return SimpleNamespace(legacy_enqueue=legacy_enqueue, legacy_run=legacy_run, enqueue=enqueue_doc,
                           enqueue_ref=enqueue_ref, run=run_doc, run_ref=run_ref)


@pytest.fixture
def graph(world, tmp_path, monkeypatch):
    monkeypatch.setenv('COAST_CARD_ID', HEADER['card_id'])
    resolver = shared_admission(world, tmp_path)
    summary = run_real_stages(world, monkeypatch)
    assert summary['stop_reason'] == 'terminal', summary['problems']
    v1_bytes = {p: (world.root / p).read_bytes() for p in ('plans/pilot01/bridge/enqueue-receipt.json', 'plans/pilot01/runs/run-00.json')}
    converted = convert(world)
    return SimpleNamespace(w=world, resolver=resolver, summary=summary, v1_bytes=v1_bytes, v2=converted,
                           root_id='queue:' + world.root.name)


@pytest.mark.parametrize('world', ['real-stages-shared'], indirect=True)
def test_real_multiwindow_run_converts_per_window_and_validates_full_graph(graph):
    g = graph
    run_doc = g.v2.run
    # Original PC9 v1 bytes, IDs, job IDs and zero-based sequence are untouched.
    for path, raw in g.v1_bytes.items():
        assert (g.w.root / path).read_bytes() == raw
    legacy = json.loads(g.v1_bytes['plans/pilot01/runs/run-00.json'])
    assert legacy['schema'] == 'coast-run-summary-v1' and legacy['sequence'] == 0
    assert run_doc['sequence'] == 0 and run_doc['continuation_of'] is None
    assert [w['root_job_id'] for w in legacy['windows']] == legacy['enqueued_job_ids']
    # Two complete windows: two producer records, each with its own Ref/SHA; no aggregate.
    cells = run_doc['window_cells']
    assert [c['window_key'] for c in cells] == [w['window_key'] for w in legacy['windows']]
    assert len({c['producer']['sha256'] for c in cells}) == 2
    assert 'cells' not in run_doc and 'store_snapshot' not in run_doc
    for record, window in zip(cells, legacy['windows']):
        depth = window['stages']['map']['depth_m']
        assert record['producer'] == versions.typed(window['stages']['map']['products']['cells'])
        assert [record[k] for k in versions.STATS] == [depth[k] for k in versions.STATS]
        assert record['unknown'] == [] and record['absent'] == []
    assert cells[0]['mean'] != cells[1]['mean']  # distinct per-window statistics are kept, not merged
    evidence = run_doc['store_status_evidence']
    assert evidence == dict(kind='legacy_embedded', field='store_status', source=g.v2.legacy_run,
                            status_sha256=refs.object_digest(legacy['store_status']),
                            independent_snapshot=False, store_consistent_claim=False)
    # The complete multi-window evidence does not HOLD; the full producer graph
    # (admission, bridge, jobs, results, mapping inputs incl. native rights
    # evidence, bound segments, mapping runs and cells) validates.
    assert validator.validate(run_doc, g.resolver, root_id=g.root_id) == run_doc
    assert validator.validate(g.v2.enqueue, g.resolver, root_id=g.root_id) == g.v2.enqueue


def mapping_input(g):
    stage = g.summary['windows'][0]['stages']['qualify']
    ref = versions.typed(stage['products']['private-mapping-input-v2'])
    return json.loads((g.w.root / ref['path']).read_text())


def rehash(doc):
    doc['facts_digest'] = digest(doc['native_facts'])
    return doc


def check(g, doc):
    validator.GraphValidator(g.resolver).document(doc, root_id=g.root_id)


@pytest.mark.parametrize('world', ['real-stages-shared'], indirect=True)
def test_native_rights_evidence_refs_refuse_unknown_tampered_traversal_and_namespace(graph):
    g = graph
    good = mapping_input(g)
    check(g, good)  # producer-declared native_facts.rights.evidence.* resolves
    def variant(change):
        doc = copy.deepcopy(good)
        for rights in (doc['rights'], doc['native_facts']['rights']):
            change(rights['evidence'][0])
        return rehash(doc)
    cases = [
        (lambda e: e.update(contract='unknown-rights-v1'), 'unknown rights evidence contract'),
        (lambda e: e.update(sha256='f' * 64), 'SHA256/bytes mismatch'),
        (lambda e: e.update(sha256='not-a-sha'), 'invalid reference SHA256'),
        (lambda e: e.update(path='../fixture-evidence.json'), 'invalid reference path component'),
        (lambda e: e.update(path='/etc/passwd'), 'relative POSIX path'),
        (lambda e: e.update(root_id='queue:other'), 'unknown native ref field'),
    ]
    for change, message in cases:
        with pytest.raises(ValueError, match=message):
            check(g, variant(change))
    # Tampered evidence bytes behind an unchanged Ref refuse.
    evidence_path = g.w.root / good['rights']['evidence'][0]['path']
    original = evidence_path.read_bytes()
    evidence_path.write_bytes(original.replace(b'true', b'false'))
    try:
        with pytest.raises(ValueError, match='SHA256/bytes mismatch|byte count'):
            check(g, good)
    finally:
        evidence_path.write_bytes(original)
    # Wrong queue namespace for native producer records refuses before traversal.
    with pytest.raises(ValueError, match='original queue root namespace'):
        validator.GraphValidator(g.resolver).document(good, root_id='raw:campaign')
    # Synthetic stand-in evidence cannot back a non-synthetic producer record.
    doc = copy.deepcopy(good)
    doc['synthetic'] = doc['native_facts']['synthetic'] = False
    with pytest.raises(ValueError, match='synthetic rights evidence'):
        check(g, rehash(doc))

RIGHTS_ROW = dict(id='TEST_ONLY_SYNTHETIC_SOURCE', title='TEST_ONLY_SYNTHETIC.bag', kind='bathymetry', format='bag',
                  url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/TEST/BAG/TEST_ONLY_SYNTHETIC.bag')


def rights_leaf(source, row=RIGHTS_ROW):
    """Complete producer-declared coastal-rights-evidence-v1 leaf (authenticated.py fields)."""
    return dict(schema='coastal-rights-evidence-v1', independent=True, reviewer_id='synthetic-rights-reviewer', private_use=True,
                decision='accepted_private_processing_conditional_on_exact_expected_source_identity',
                accepted_source_rights_for_declared_private_purpose=True, holds_added=[], source_sha256=source['sha256'],
                source_bytes=source['bytes'], source_id=row['id'], source_url=row['url'], product_title=row['title'],
                synthetic=True, checked_at='2026-10-01T00:00:00Z', valid_until='2027-10-01T00:00:00Z')


def with_rights_leaf(g, good, value, *, row=RIGHTS_ROW):
    """Mapping input whose doc and native_facts rights both carry one leaf Ref (full graph)."""
    name = 'rights-' + hashlib.sha256(refs.canonical(value)).hexdigest()[:8] + '.json'
    ref = put(g.w.root, name, value)
    evidence = dict(path=ref['path'], sha256=ref['sha256'], bytes=ref['bytes'], contract='coastal-rights-evidence-v1')
    doc = copy.deepcopy(good)
    doc['source_row'] = None if row is None else dict(row, sha256=good['source']['sha256'])
    doc['rights'] = dict(private_use=True, evidence=[evidence])
    doc['native_facts']['rights'] = copy.deepcopy(doc['rights'])
    return rehash(doc)


@pytest.mark.parametrize('world', ['real-stages-shared'], indirect=True)
def test_rights_leaf_binds_owning_source_row_identity_and_refuses_unknown_fields(graph):
    g = graph
    good = mapping_input(g)
    leaf = rights_leaf(good['source'])
    # Complete positive control through the full mapping-input graph
    # (rights.evidence.* and native_facts.rights.evidence.* slots).
    check(g, with_rights_leaf(g, good, leaf))
    check(g, with_rights_leaf(g, good, dict(leaf, support_policy='declared-partial-support')))
    cases = [
        (dict(reviewer_id=''), 'rights binding'),
        (dict(private_use=False), 'rights binding'),
        (dict(source_sha256='0' * 64), 'rights binding'),
        (dict(source_bytes=True), 'rights binding'),
        (dict(valid_until='2026-09-01T00:00:00Z'), 'validity'),
        # Must-fix 1: each source identity component, wrong and missing, separately.
        (dict(source_id='OTHER_SOURCE'), 'rights binding'),
        (dict(source_url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/OTHER/BAG/OTHER.bag'), 'rights binding'),
        (dict(product_title='OTHER.bag'), 'rights binding'),
        # Must-fix 2: undeclared scalar and nested reference fields refuse.
        (dict(not_a_producer_field='invented'), 'unknown producer field: rights evidence not_a_producer_field'),
        (dict(undeclared_evidence=dict(path='../MUST-NOT-RESOLVE.json', sha256='0' * 64, bytes=1)),
         'unknown producer field: rights evidence undeclared_evidence'),
        (dict(support_policy=1), 'producer field type invalid: support_policy'),
    ]
    for broken, message in cases:
        with pytest.raises(ValueError, match=message):
            check(g, with_rights_leaf(g, good, dict(leaf, **broken)))
    for field in ('source_id', 'source_url', 'product_title', 'schema', 'checked_at'):
        value = {k: v for k, v in leaf.items() if k != field}
        with pytest.raises(ValueError, match='rights evidence missing producer field: ' + field):
            check(g, with_rights_leaf(g, good, value))
    # No owning source_row, or an incomplete/ambiguous one, refuses: absent
    # values never match absent evidence identity.
    bare = {k: v for k, v in leaf.items() if k not in ('source_id', 'source_url', 'product_title')}
    for value, row in [(leaf, None), (dict(bare, source_id=None, source_url=None, product_title=None), None),
                       (leaf, {k: v for k, v in RIGHTS_ROW.items() if k != 'title'}), (leaf, dict(RIGHTS_ROW, url=''))]:
        with pytest.raises(ValueError, match='owning source_row identity unavailable'):
            check(g, with_rights_leaf(g, good, value, row=row))
    doc = with_rights_leaf(g, good, leaf)
    doc['source_row']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='owning source_row identity unavailable'):
        check(g, rehash(doc))


def test_native_job_rights_slot_binds_owning_source_row(tmp_path):
    """coastal-native-job-v1 rights.evidence.* parent slot: same leaf rules, and
    a job that declares no source_row cannot back present evidence."""
    root = tmp_path / 'queue'
    shutil.copytree(FIXTURES / 'coast' / 'queue', root)
    job = json.loads((root / 'plans/plan01/pc9-bridge/native-job-00.json').read_text())
    resolver = refs.Resolver({'queue:job': str(root)}, allowed_root_ids={'queue:job'})
    leaf = dict(rights_leaf(job['source']), synthetic=job['synthetic'] is True)

    def run(value, *, row=RIGHTS_ROW):
        doc = copy.deepcopy(job)
        if row is not None:
            doc['source_row'] = dict(row)
        raw = refs.canonical(value)
        name = 'rights-' + hashlib.sha256(raw).hexdigest()[:8] + '.json'
        (root / name).write_bytes(raw)
        doc['rights'] = dict(private_use=True, evidence=[dict(path=name, sha256=refs.sha256(raw), bytes=len(raw),
                                                               contract='coastal-rights-evidence-v1')])
        validator.GraphValidator(resolver).document(doc, root_id='queue:job')

    validator.GraphValidator(resolver).document(copy.deepcopy(job), root_id='queue:job')  # structural empty evidence
    run(leaf)  # complete positive
    for field, other in (('source_id', 'OTHER'), ('source_url', 'https://example.invalid/OTHER.bag'), ('product_title', 'OTHER')):
        with pytest.raises(ValueError, match='rights binding'):
            run(dict(leaf, **{field: other}))
        with pytest.raises(ValueError, match='missing producer field: ' + field):
            run({k: v for k, v in leaf.items() if k != field})
    with pytest.raises(ValueError, match='owning source_row identity unavailable'):
        run(leaf, row=None)
    with pytest.raises(ValueError, match='unknown producer field: rights evidence not_a_producer_field'):
        run(dict(leaf, not_a_producer_field='invented'))
    with pytest.raises(ValueError, match='unknown producer field: rights evidence undeclared_evidence'):
        run(dict(leaf, undeclared_evidence=dict(path='../MUST-NOT-RESOLVE.json', sha256='0' * 64, bytes=1)))


@pytest.mark.parametrize('world', ['real-stages-shared'], indirect=True)
def test_native_facts_unknown_scalar_and_segment_contract_refuse(graph):
    g = graph
    good = mapping_input(g)
    doc = copy.deepcopy(good)
    doc['native_facts']['not_a_producer_field'] = 1
    with pytest.raises(ValueError, match='unknown producer field'):
        check(g, rehash(doc))
    doc = copy.deepcopy(good)
    doc['native_facts']['segment']['halo_m'] = 5
    with pytest.raises(ValueError, match='bound native segment'):
        check(g, rehash(doc))
    doc = copy.deepcopy(good)
    doc['native_facts']['segment']['bbox_crs84'] = [0, 0, 1, 1]
    with pytest.raises(ValueError, match='unknown producer field'):
        check(g, rehash(doc))
    doc = copy.deepcopy(good)
    doc['native_facts']['valid_count'] += 1  # facts changed without a matching digest
    with pytest.raises(ValueError, match='native facts binding'):
        check(g, doc)


@pytest.mark.parametrize('world', ['real-stages-shared'], indirect=True)
def test_v2_records_refuse_tampering_selection_and_snapshot_claims(graph):
    g = graph
    run_doc = g.v2.run
    def refused(change, message):
        doc = copy.deepcopy(run_doc)
        change(doc)
        with pytest.raises(ValueError, match=message):
            validator.validate(doc, g.resolver, root_id=g.root_id)
    refused(lambda d: d['window_cells'][1].update(mean=d['window_cells'][0]['mean']), 'adapter output')
    refused(lambda d: d.update(window_cells=d['window_cells'][:1]), 'one record per window')
    refused(lambda d: d['store_status_evidence'].update(independent_snapshot=True), 'schema')
    refused(lambda d: d['store_status_evidence'].update(kind='store_snapshot'), 'schema')
    refused(lambda d: d.update(sequence=1), 'zero-based')
    refused(lambda d: d['legacy_run'].update(sha256='0' * 64), 'SHA256/bytes mismatch|original run receipt')
    refused(lambda d: d.update(window_cells=d['window_cells'], cells={}), 'schema')
    # The legacy edge must stay in its queue namespace.
    legacy = json.loads(g.v1_bytes['plans/pilot01/runs/run-00.json'])
    with pytest.raises(ValueError, match='original queue root namespace'):
        validator.GraphValidator(g.resolver).document(legacy, root_id='raw:campaign')
    moved = copy.deepcopy(legacy)
    moved['bridge']['root_id'] = 'raw:campaign'
    with pytest.raises(ValueError, match='leaves its queue namespace'):
        validator.GraphValidator(g.resolver).document(moved, root_id=g.root_id)
