"""Archive manifest/release-list edge roles and ledger envelope forwarding.

Offline synthetic controls only; no archive closure or scientific claims.
The manifest ``files`` table is a source_ref -> retained_ref identity table:
source_ref is a lookup key that is never opened, retained_ref bytes are
hash-checked without contract dispatch, and every cache candidate must be
mapped in that table under the segment's ``cache/`` subtree.
"""
import copy
from pathlib import Path

import pytest

from tests.coast_contract_factory import load_helper, materialize

pytestmark = pytest.mark.gis

refs = load_helper('coast_refs')
validator = load_helper('validate_coast_receipt')
ledger = load_helper('coast_ledger')

ARCHIVE = 'archive:synthetic:close01'


@pytest.fixture
def graph(tmp_path):
    instances, bindings = materialize(tmp_path)
    resolver = refs.Resolver(bindings, allowed_root_ids=set(bindings))
    return instances, bindings, resolver


def retained(bindings, path, raw):
    target = Path(bindings[ARCHIVE]) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return dict(root_id=ARCHIVE, path=path, sha256=refs.sha256(raw), bytes=len(raw))


def original(path, raw):
    """Original-namespace key; deliberately absent from the hot queue tree."""
    return dict(root_id='queue:synthetic', path=path, sha256=refs.sha256(raw), bytes=len(raw))


def candidate(source, size=None):
    return dict(source_ref=source, device=1, inode=2, size=source['bytes'] if size is None else size, mtime_ns=3)


def manifest_with(instances, files=(), cache=()):
    value = copy.deepcopy(instances['archive-manifest'])
    value['files'] = value['files'] + list(files)
    value['cache_candidates'] = list(cache)
    return value


def test_file_table_source_ref_is_a_lookup_key_never_opened(graph):
    instances, bindings, resolver = graph
    queue = Path(bindings['queue:synthetic'])
    binary = b'\x00released hot cache bytes\n'
    rows = b'{"url":"synthetic"}\n'
    receipt = b'{"schema":"not-a-registered-contract"}\n'
    entries = []
    for path, raw in (('cache/released.bin', binary), ('raw/snapshot.jsonl', rows), ('jobs/result.json', receipt)):
        assert not (queue / path).exists()
        entries.append(dict(source_ref=original(path, raw), retained_ref=retained(bindings, 'products/' + path, raw)))
    value = manifest_with(instances, entries, [candidate(entries[0]['source_ref'])])
    validator.validate(value, resolver, root_id='queue:synthetic')


def test_file_table_retained_bytes_are_hash_checked(graph):
    instances, bindings, resolver = graph
    raw = b'retained bytes\n'
    ref = retained(bindings, 'products/x.bin', raw)
    (Path(bindings[ARCHIVE]) / 'products/x.bin').write_bytes(b'Retained bytes\n')
    value = manifest_with(instances, [dict(source_ref=original('cache/x.bin', raw), retained_ref=ref)])
    with pytest.raises(ValueError, match='SHA256/bytes mismatch'):
        validator.validate(value, resolver, root_id='queue:synthetic')
    (Path(bindings[ARCHIVE]) / 'products/x.bin').unlink()
    with pytest.raises(OSError):
        validator.validate(value, resolver, root_id='queue:synthetic')


@pytest.mark.parametrize('case,message', [
    ('unmapped', 'no retained archive/raw mapping'),
    ('outside', 'outside the segment cache subtree'),
    ('foreign', 'outside the segment cache subtree'),
    ('size', 'size differs'),
])
def test_cache_candidates_must_be_mapped_cache_files(graph, case, message):
    instances, bindings, resolver = graph
    raw = b'cache bytes\n'
    path = 'jobs/x.bin' if case == 'outside' else 'cache/x.bin'
    source = original(path, raw)
    if case == 'foreign':
        source['root_id'] = 'queue:other'
    entry = dict(source_ref=source, retained_ref=retained(bindings, 'products/x.bin', raw))
    files = [] if case == 'unmapped' else [entry]
    value = manifest_with(instances, files, [candidate(source, size=len(raw) + 1 if case == 'size' else None)])
    with pytest.raises(ValueError, match=message):
        validator.validate(value, resolver, root_id='queue:synthetic')


def test_release_list_validation_observations_are_diagnostic_scalars(graph):
    instances, _, resolver = graph
    value = copy.deepcopy(instances['release-list'])
    value['validation_observations'] = [dict(code='FRESH_VALIDATION', path='cache/x.bin', expected='hash a', observed='hash a')]
    validator.validate(value, resolver, root_id='queue:synthetic')


def test_ledger_append_forwards_explicit_envelope_union(graph, tmp_path, monkeypatch):
    instances, _, resolver = graph
    seen = []
    real = validator.validate

    def recording(value, resolver, *, root_id, raw_provenance=()):
        seen.append(raw_provenance)
        return real(value, resolver, root_id=root_id)

    monkeypatch.setattr(validator, 'validate', recording)
    union = ({'root_id': 'queue:synthetic', 'path': 'sentinel.json', 'sha256': '0' * 64, 'bytes': 0},)
    row = {k: v for k, v in instances['segment-ledger'].items() if k not in ('seq', 'prev_row_sha256')}
    ledger.append_index(tmp_path / 'ledger.jsonl', tmp_path / 'campaign.jsonl', row, writer='write_verdict.py',
                        resolver=resolver, root_id='queue:synthetic', raw_provenance=union)
    ledger.append(tmp_path / 'ledger.jsonl', row, writer='write_verdict.py', resolver=resolver, root_id='queue:synthetic',
                  raw_provenance=union)
    assert seen == [union, union, union]
    seen.clear()
    ledger.append(tmp_path / 'other.jsonl', row, writer='write_verdict.py', resolver=resolver, root_id='queue:synthetic')
    assert seen == [()]
