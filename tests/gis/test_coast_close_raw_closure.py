"""B1d shared-edge correction + archive-only raw/derived/native closure.

Real producer bytes from the admitted #832 fixture (owned BAG -> three
non-identical VR-derived GTiffs, real prefetch snapshot/row serializer, real
Store acquire/qualify/map jobs). Synthetic temp files only.

Regression for the run-1114 diagnostic: the archive-manifest file table is an
identity table (retained bytes hash-checked, source_ref never opened), so
envelope/snapshot/row entries no longer refuse; every original refusal remains
where the SCIENTIFIC graph reaches those bytes.
"""
from pathlib import Path

import pytest

from tests._support import ROOT as REPO
from tests.gis.test_coast_raw_provenance import retained, vr_bag, emit, HEADER, ROOT  # noqa: F401
from tests.coast_contract_factory import load_helper
from tests.gis.test_coast_segment_close import close_common

pytestmark = pytest.mark.gis
refs = load_helper('coast_refs')
validator = load_helper('validate_coast_receipt')
ledger = load_helper('coast_ledger')


AID = 'archive:synthetic:close01'


def archive_resolver(f, archive):
    bindings = dict(f.resolver.bindings, **{AID: str(archive)})
    resolver = refs.Resolver({k: str(v) for k, v in bindings.items()}, allowed_root_ids=bindings)
    resolver.original_raw_roots = f.resolver.original_raw_roots
    resolver.original_queue_roots = {ROOT: str(f.root)}
    return resolver


def manifest_for(f, files, *, inventory=None, candidates=()):
    leaf = f.typed(f.root / 'rights.json')
    return dict(schema='coast-archive-manifest-v1', **HEADER, campaign_segment_id='synthetic', close_id='close01',
                inventory=inventory or leaf, selected_verdicts=[], original_segment_tip_sha256='0' * 64,
                original_campaign_tip_sha256='0' * 64, files=files, lineage_snapshot=leaf, cache_candidates=list(candidates))


def retain(f, archive, source):
    raw = f.resolver.read(source)
    target = archive / Path(source['path']).name
    target.write_bytes(raw)
    return dict(source_ref=source, retained_ref=dict(source, root_id=AID, path=target.name))


@pytest.fixture
def table(retained, tmp_path_factory):
    f = retained
    archive = tmp_path_factory.mktemp('b1d-archive')
    resolver = archive_resolver(f, archive)
    entries = {label: retain(f, archive, source) for label, source in [
        ('envelope', f.envelope_ref), ('snapshot', f.envelope['snapshot']), ('row', f.envelope['selections'][0]['row'])]}
    return f, archive, resolver, entries


@pytest.mark.parametrize('label', ['envelope', 'snapshot', 'row'])
def test_identity_table_accepts_former_run1114_refusals(table, label):
    f, archive, resolver, entries = table
    manifest = manifest_for(f, [entries[label]])
    validator.GraphValidator(resolver, raw_provenance=[f.envelope_ref]).document(manifest, root_id=AID)


def test_identity_table_never_opens_source_and_rehashes_retained(table):
    f, archive, resolver, entries = table
    entry = entries['snapshot']
    hidden = dict(entry, source_ref=dict(entry['source_ref'], root_id='queue:unbound'))  # never opened
    manifest = manifest_for(f, [hidden])
    validator.GraphValidator(resolver, raw_provenance=[f.envelope_ref]).document(manifest, root_id=AID)
    (archive / entry['retained_ref']['path']).write_bytes(b'tampered\n')
    with pytest.raises(ValueError, match='byte count mismatch|SHA256/bytes mismatch'):
        validator.GraphValidator(resolver, raw_provenance=[f.envelope_ref]).document(manifest_for(f, [entry]), root_id=AID)


@pytest.mark.parametrize('slot,source,reason', [
    ('envelope', 'envelope', 'envelope pinned outside admission raw_provenance'),
    ('snapshot', 'snapshot', 'workflow receipt needs a schema'),
    ('row', 'row', 'workflow receipt needs a schema'),
])
def test_scientific_slots_still_refuse_raw_bytes(table, slot, source, reason):
    """Isolated negative: same bytes in a SCIENTIFIC slot (inventory) still refuse."""
    f, archive, resolver, entries = table
    manifest = manifest_for(f, [], inventory=entries[source]['source_ref'])
    with pytest.raises(ValueError, match=reason):
        validator.GraphValidator(resolver, raw_provenance=[f.envelope_ref]).document(manifest, root_id=AID)


def test_cache_candidate_requires_table_mapping_and_cache_subtree(table):
    f, archive, resolver, entries = table
    entry = entries['row']
    candidate = dict(source_ref=entry['source_ref'], device=1, inode=1, size=entry['source_ref']['bytes'], mtime_ns=1)
    with pytest.raises(ValueError, match='outside the segment cache subtree'):
        validator._consistency(manifest_for(f, [entry], candidates=[candidate]))
    with pytest.raises(ValueError, match='no retained archive/raw mapping'):
        validator._consistency(manifest_for(f, [], candidates=[candidate]))


def archived_payload(f, manifest_ref):
    leaf = f.typed(f.root / 'rights.json')
    return dict(schema='coast-segment-ledger-v1', **HEADER, campaign_segment_id='synthetic',
                coordinator_segment_id=f.plan['segment']['segment_id'], plan_id='diagnostic',
                plan_sha256=refs.object_digest(f.plan), ledger_role='segment', segment_row_sha256=None,
                kind='archived', close_id='close01', manifest=manifest_ref, inventory=leaf,
                previous_segment_tip_sha256='0' * 64, previous_campaign_tip_sha256='0' * 64)


def test_archived_append_forwards_explicit_envelope_union(table):
    """The scientific inventory reaches an envelope via admission raw_provenance."""
    from tests.gis.test_coast_raw_provenance import admission_for
    f, archive, resolver, entries = table
    admission, env_ref, _ = admission_for(f)
    admission_ref = f.put('admission-for-close.json', admission)
    manifest = manifest_for(f, list(entries.values()) + [retain(f, archive, env_ref)], inventory=admission_ref)
    path = archive / 'ARCHIVE-MANIFEST.json'
    path.write_bytes(refs.canonical(manifest))
    manifest_ref = dict(root_id=AID, path=path.name, sha256=refs.sha256(path.read_bytes()), bytes=path.stat().st_size)
    target = f.root / 'close-ledger.jsonl'
    # Negative control: without the explicit union the envelope is unsupplied.
    with pytest.raises(ValueError, match='not supplied up front|unregistered admission provenance envelope'):
        ledger.append(target, archived_payload(f, manifest_ref), writer='archive_segment.py', resolver=resolver, root_id=ROOT)
    assert target.read_bytes() == b''
    row, digest = ledger.append(target, archived_payload(f, manifest_ref), writer='archive_segment.py',
                                resolver=resolver, root_id=ROOT, raw_provenance=[env_ref])
    assert ledger.verify(target) == [row] and refs.sha256(target.read_bytes()) == digest
    # Idempotent retry forwards the same union and returns the same row.
    assert ledger.append(target, archived_payload(f, manifest_ref), writer='archive_segment.py',
                         resolver=resolver, root_id=ROOT, raw_provenance=[env_ref]) == (row, digest)
    collected = close_common.collect_envelopes(resolver, [dict(kind='verdict', context=f.put(
        'context-for-close.json', dict(admission=admission_ref)))])
    assert collected == [env_ref]


# ------------------------------------------------ archive-only native closure

def build_archive(f, archive):
    hot = archive_resolver(f, archive)
    recorder = close_common.RecordingResolver(hot)
    recorder.original_raw_roots = hot.original_raw_roots
    recorder.original_queue_roots = hot.original_queue_roots
    def lookup(root_id, path):
        found, _ = close_common.observe(f.root, path)
        return dict(root_id=root_id, **found)
    close_common.traverse(recorder, f.executions, root_id=ROOT, envelopes=[f.envelope_ref], head=HEADER, lookup=lookup)
    files = []
    for key in sorted(recorder.reads):
        ref = recorder.reads[key]
        if ref['root_id'] != ROOT:
            continue
        assert not close_common.excluded(ref)
        relative = close_common.retained_path(ref)
        close_common.write_retained(archive, relative, hot.read(ref))
        files.append(dict(source_ref=ref, retained_ref=dict(ref, root_id=AID, path=relative)))
    return files, recorder


def verify_only(f, archive, files):
    only = {AID: str(archive), 'raw:campaign': str(f.raw_root)}
    inner = refs.Resolver(only, allowed_root_ids=set(only))
    resolver = close_common.ArchiveResolver(inner, files, original_queue_roots={ROOT: str(f.root)},
                                            original_raw_roots=f.resolver.original_raw_roots)
    by_path = {(i['source_ref']['root_id'], i['source_ref']['path']): i['source_ref'] for i in files}
    hidden = f.root.with_name(f.root.name + '-hidden')
    f.root.rename(hidden)  # the ENTIRE hot queue tree is unavailable
    try:
        graph = close_common.traverse(resolver, f.executions, root_id=ROOT, envelopes=[f.envelope_ref], head=HEADER,
                                      lookup=lambda r, p: by_path[(r, p)])
    finally:
        hidden.rename(f.root)
    return graph


@pytest.fixture
def native(retained, tmp_path_factory):
    archive = tmp_path_factory.mktemp('b1d-native-archive')
    files, recorder = build_archive(retained, archive)
    return retained, archive, files, recorder


def test_archive_only_full_native_raw_derived_closure(native):
    f, archive, files, recorder = native
    graph = verify_only(f, archive, files)
    paths = {refs.loads(k[0])['path'] for k in graph.verified}
    retained_paths = {i['source_ref']['path'] for i in files}
    # raw/derived/row/snapshot/envelope/native/products/job/logs all retained and re-validated.
    for required in ('envelope.json', 'snapshot.jsonl', 'row.jsonl', 'native.json', 'derived/vr-supergrids.csv',
                     'derived/vr-refinements-receipt.json'):
        assert required in retained_paths and required in paths
    assert all(o['artifact']['path'] in retained_paths for o in f.vr['outputs'])
    for leaf in ('terrain.tif', 'support.tif', 'cells.json', 'run.json', 'job.json', 'stdout.log', 'stderr.log', 'result.json'):
        assert any(p.endswith('/' + leaf) for p in retained_paths), leaf
    jobs = [p.split('/') for p in retained_paths if p.endswith('/job.json')]
    assert jobs and all(len(parts) >= 2 and parts[-2] != 'output' for parts in jobs)  # lease-qualified job dir
    assert f.envelope['selections'][0]['raw'] in [refs.loads(k[0]) for k in graph.verified]


def drop(files, suffix):
    return [i for i in files if not i['source_ref']['path'].endswith(suffix)]


@pytest.mark.parametrize('mutation,reason', [
    ('delete-terrain', 'No such file|reference'),
    ('unmapped-terrain', 'unmapped reference'),
    ('unmapped-snapshot', 'unmapped reference'),
    ('unmapped-job', 'missing or ambiguous|KeyError|job.json'),
    ('missing-raw', 'No such file|reference'),
    ('corrupt-derived', 'mismatch'),
])
def test_archive_only_closure_refusals(native, mutation, reason):
    f, archive, files, _ = native
    verify_only(f, archive, files)  # positive control first
    terrain = next(i for i in files if i['source_ref']['path'].endswith('/terrain.tif'))
    if mutation == 'delete-terrain':
        (archive / terrain['retained_ref']['path']).unlink()
    elif mutation == 'unmapped-terrain':
        files = drop(files, '/terrain.tif')
    elif mutation == 'unmapped-snapshot':
        files = drop(files, 'snapshot.jsonl')
    elif mutation == 'unmapped-job':
        files = drop(files, '/job.json')
    elif mutation == 'missing-raw':
        f.raw_path.rename(f.raw_path.with_name('moved.bag'))
    elif mutation == 'corrupt-derived':
        derived = next(i for i in files if i['source_ref']['path'] == f.vr['outputs'][0]['artifact']['path'])
        target = archive / derived['retained_ref']['path']
        raw = bytearray(target.read_bytes())
        raw[-1] ^= 1
        target.write_bytes(bytes(raw))
    with pytest.raises((close_common.Refused, ValueError, OSError, KeyError), match=reason):
        verify_only(f, archive, files)
