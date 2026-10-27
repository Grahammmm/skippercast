"""S-029 refrozen 2026-10-24 11:44 PDT: partial producer evidence stays HELD.

All inputs are inert synthetic metadata. Producer is inspected via AST only,
never imported: no downloader defaults, payload, store, network or retry access.
"""
import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket

import pytest

from research.scripts.coast_mvp import prefetch_receipts_check as c
from tests._support import ROOT

URL = 'https://reviewed.example/source.bag'
DIGEST = hashlib.sha256(b'synthetic payload identity; never fetched').hexdigest()


def receipt():
    # Exact final-file shape emitted at prefetch.py:536-542. Path is opaque.
    return {'url': URL, 'final_url': URL, 'bytes': 49, 'sha256': DIGEST,
            'etag': '"strong"', 'last_modified': None,
            'fetched_at': '2026-10-24T11:00:00+00:00', 'licence': 'public-domain',
            'segments': ['C1'], 'path': '/not-accessible/raw/source.bag',
            'review_required': True, 'verification': 'publisher-sha256'}


def inventory():
    return {'schema_version': 1, 'unresolved': [], 'files': [
        {'url': URL, 'bytes': 49, 'sha256': DIGEST, 'source': 'noaa-nos',
         'licence': 'public-domain', 'segments': ['C1']}]}


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    # Network must not even be reachable. These doubles never probe a real target.
    def forbidden(*args, **kwargs):
        raise AssertionError('Network access attempted')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    (tmp_path / 'receipts').mkdir()
    write_json(tmp_path / 'inventory.json', inventory())
    write_json(tmp_path / 'reviewed-hosts.json', ['reviewed.example'])
    (tmp_path / 'receipts' / 'manifest.jsonl').write_text(json.dumps(receipt()) + '\n')
    return tmp_path


def gates(result):
    assert [r['gate'] for r in result['gates']] == list(c.GATES)
    return {r['gate']: r for r in result['gates']}


def put_receipts(root, *rows):
    (root / 'receipts' / 'manifest.jsonl').write_text(
        ''.join(json.dumps(row) + '\n' for row in rows))


def assert_supported_pass(result):
    by = gates(result)
    for name in ('input_schema', 'receipt_schema', 'inventory_coverage',
                 'sha256_inventory', 'bytes_inventory', 'reviewed_endpoint_hosts'):
        assert by[name]['status'] == 'PASS', by[name]
    return by


def test_fixture_fields_are_exact_actual_producer_shape():
    tree = ast.parse((ROOT / 'src/skippercast/coastal/prefetch.py').read_bytes())
    dicts = [{key.value for key in node.keys if isinstance(key, ast.Constant)}
             for node in ast.walk(tree) if isinstance(node, ast.Dict)]
    assert set(receipt()) in dicts
    assert any({'transfer_bytes_this_pass', 'parked_hosts', 'sources'} <= keys for keys in dicts)
    # Explicitly pin the independent policy constants, not RESERVE or enumerator limits.
    assert c.RECEIVED_CAP_BYTES == 80000000000
    assert c.RAW_GROWTH_CAP_BYTES == 100000000000
    assert c.DURATION_CAP_SECONDS == 86400
    assert c.REQUESTS_PER_HOST_CAP == 2


def test_valid_producer_shape_is_partial_not_qualified(evidence):
    result = c.check(evidence)
    by = assert_supported_pass(result)
    for name in ('received_bytes', 'raw_growth', 'duration', 'requests_per_host',
                 'contact_history', 'retry_pacing'):
        assert by[name] == {'gate': name, 'status': 'HELD', 'reason': 'NOT_ESTABLISHED'}
    assert result['exit_code'] == 3
    assert result['prefetch_qualified'] is False
    assert result['semantic_approval'] is False and result['review_required'] is True
    bindings = {row['path']: row for row in result['inputs']}
    for name in ('inventory.json', 'reviewed-hosts.json', 'receipts/manifest.jsonl'):
        data = (evidence / name).read_bytes()
        assert bindings[name] == {'path': name, 'bytes': len(data),
                                  'sha256': hashlib.sha256(data).hexdigest()}


@pytest.mark.parametrize('value,state', [(0, 'PASS'), (79999999999, 'PASS'),
                                         (80000000000, 'PASS'), (80000000001, 'FAIL')])
def test_synthetic_received_boundary_does_not_qualify_other_gates(evidence, value, state):
    write_json(evidence / 'accounting.json', {'schema': 's029-synthetic-received-v1',
                                            'synthetic': True, 'received_bytes': value})
    result = c.check(evidence, synthetic_accounting='accounting.json')
    by = assert_supported_pass(result)
    assert by['received_bytes']['status'] == state
    assert by['received_bytes']['reason'] == 'SYNTHETIC_ONLY'
    assert by['received_bytes']['measured'] == value
    assert by['received_bytes']['limit'] == 80000000000
    assert by['retry_pacing']['status'] == 'HELD'
    assert result['exit_code'] == (1 if state == 'FAIL' else 3)
    assert result['prefetch_qualified'] is False


@pytest.mark.parametrize('value', [-1, True, 1.0, '80000000000', None])
def test_malformed_synthetic_accounting_is_not_zero(evidence, value):
    write_json(evidence / 'accounting.json', {'schema': 's029-synthetic-received-v1',
                                            'synthetic': True, 'received_bytes': value})
    result = c.check(evidence, synthetic_accounting='accounting.json')
    assert gates(result)['input_schema']['status'] == 'FAIL'
    assert result['exit_code'] == 1


@pytest.mark.parametrize('record', [{}, {'received_bytes': 0},
    {'schema': 's029-synthetic-received-v1', 'synthetic': False, 'received_bytes': 0},
    {'schema': 's029-synthetic-received-v1', 'synthetic': True, 'received_bytes': 0, 'qualified': True}])
def test_only_declared_synthetic_schema_accepted(record):
    with pytest.raises(c.Invalid):
        c.cap_comparison(record)


@pytest.mark.parametrize('field', ['url', 'final_url'])
def test_excluded_endpoint_is_the_deciding_gate(evidence, field):
    r = receipt()
    r[field] = 'https://excluded.example/source.bag'
    if field == 'url':
        plan = inventory()
        plan['files'][0]['url'] = r[field]
        write_json(evidence / 'inventory.json', plan)
    put_receipts(evidence, r)
    result = c.check(evidence)
    by = gates(result)
    assert by['reviewed_endpoint_hosts']['reason'] == 'EXCLUDED_ENDPOINT_HOST'
    assert by['reviewed_endpoint_hosts']['status'] == 'FAIL'
    assert all(by[g]['status'] == 'PASS' for g in
               ('input_schema', 'receipt_schema', 'inventory_coverage', 'sha256_inventory', 'bytes_inventory'))
    assert result['exit_code'] == 1


@pytest.mark.parametrize('missing_hash', [False, True])
def test_mismatched_or_unverified_inventory_hash_fails_in_isolation(evidence, missing_hash):
    plan = inventory()
    plan['files'][0]['sha256'] = None if missing_hash else 'a' * 64
    write_json(evidence / 'inventory.json', plan)
    result = c.check(evidence)
    by = gates(result)
    assert by['sha256_inventory']['reason'] == 'UNVERIFIED_OR_MISMATCHED_HASH'
    assert by['sha256_inventory']['status'] == 'FAIL'
    assert by['bytes_inventory']['status'] == by['reviewed_endpoint_hosts']['status'] == 'PASS'
    assert by['inventory_coverage']['status'] == by['receipt_schema']['status'] == 'PASS'
    assert result['exit_code'] == 1


def test_local_hash_receipt_is_not_publisher_verification(evidence):
    r = receipt()
    r['verification'] = 'http-size-and-local-sha256'
    put_receipts(evidence, r)
    plan = inventory()
    plan['files'][0]['sha256'] = None
    write_json(evidence / 'inventory.json', plan)
    by = gates(c.check(evidence))
    assert by['receipt_schema']['status'] == 'PASS'
    assert by['sha256_inventory']['status'] == 'FAIL'


@pytest.mark.parametrize('size', [48, None])
def test_inventory_byte_count_mismatch_or_unknown_is_not_received_count(evidence, size):
    plan = inventory()
    plan['files'][0]['bytes'] = size
    write_json(evidence / 'inventory.json', plan)
    result = c.check(evidence)
    by = gates(result)
    assert by['bytes_inventory']['status'] == 'FAIL'
    assert by['sha256_inventory']['status'] == by['reviewed_endpoint_hosts']['status'] == 'PASS'
    assert by['received_bytes']['status'] == 'HELD'
    assert result['exit_code'] == 1


@pytest.mark.parametrize('field,value', [('sha256', None), ('sha256', 'x' * 64), ('bytes', True),
    ('bytes', -1), ('bytes', 0), ('fetched_at', 'yesterday'), ('fetched_at', None),
    ('verification', 'verified'), ('review_required', False), ('path', '../escape'),
    ('url', 'http://reviewed.example/a'), ('final_url', 'https://reviewed.example:bad/a'),
    ('final_url', 'https://reviewed.example@excluded.example/a'),
    ('final_url', 'https://reviewed.example/a\n'), ('segments', []), ('segments', [None])])
def test_malformed_receipts_fail_closed(evidence, field, value):
    r = receipt()
    r[field] = value
    put_receipts(evidence, r)
    result = c.check(evidence)
    assert gates(result)['receipt_schema']['status'] == 'FAIL'
    assert result['exit_code'] == 1


@pytest.mark.parametrize('contents', ['{broken}\n', '{"url":1,"url":2}\n', 'NaN\n', '\n', '[]\n', 'null\n'])
def test_malformed_jsonl_or_record_fails(evidence, contents):
    (evidence / 'receipts' / 'manifest.jsonl').write_text(contents)
    result = c.check(evidence)
    assert result['exit_code'] == 1


def test_empty_directory_and_empty_manifest_not_success(evidence):
    put_receipts(evidence)
    result = c.check(evidence)
    assert result['exit_code'] == 3
    assert gates(result)['receipt_schema']['reason'] == 'NOT_ESTABLISHED'
    assert gates(result)['sha256_inventory']['status'] == 'HELD'
    (evidence / 'empty').mkdir()
    assert c.check(evidence, receipts='empty')['exit_code'] == 3


def test_duplicate_receipts_not_double_counted(evidence):
    put_receipts(evidence, receipt(), receipt())
    result = c.check(evidence)
    assert gates(result)['receipt_schema']['reason'] == 'DUPLICATE_RECEIPT_IDENTITY'
    assert result['exit_code'] == 1


@pytest.mark.parametrize('change', ['extra', 'missing', 'unresolved'])
def test_complete_inventory_required(evidence, change):
    plan = inventory()
    if change == 'extra':
        extra = deepcopy(plan['files'][0])
        extra['url'] += '?other'
        plan['files'].append(extra)
    elif change == 'missing':
        plan['files'] = []
    else:
        plan['unresolved'] = [{'id': 'held-source'}]
    write_json(evidence / 'inventory.json', plan)
    result = c.check(evidence)
    assert gates(result)['inventory_coverage']['status'] == 'FAIL'
    assert result['exit_code'] == 1


def test_status_or_extra_attestation_cannot_supply_missing_history(evidence):
    r = receipt()
    r.update(received_bytes=0, transfer_bytes_this_pass=0,
             parked_hosts={}, pacing_verified=True, requests_per_host=0)
    put_receipts(evidence, r)
    write_json(evidence / 'status.json', {'schema_version': 1,
        'transfer_bytes_this_pass': 0, 'parked_hosts': {}, 'state': 'complete'})
    result = c.check(evidence)
    by = assert_supported_pass(result)
    assert result['exit_code'] == 3
    for gate in ('received_bytes', 'requests_per_host', 'contact_history', 'retry_pacing'):
        assert by[gate]['reason'] == 'NOT_ESTABLISHED'


@pytest.mark.parametrize('name', ['/absolute', '../escape', 'sub/../../escape', './inventory.json',
                                  'sub//inventory.json', 'sub\\file', 'null\x00file', 'line\nfile'])
def test_unsafe_path_refused_before_read(evidence, name, monkeypatch):
    reads = []
    original = c.Metadata.read_at
    def track(self, *args):
        reads.append(args)
        return original(self, *args)
    monkeypatch.setattr(c.Metadata, 'read_at', track)
    assert c.check(evidence, inventory=name)['exit_code'] == 1
    assert reads == []


@pytest.mark.parametrize('part', ['root', 'intermediate', 'file', 'receipt'])
def test_symlink_boundaries_are_no_follow(evidence, part, monkeypatch):
    (evidence / 'link').symlink_to(evidence, target_is_directory=True)
    (evidence / 'inventory-link.json').symlink_to(evidence / 'inventory.json')
    if part == 'root':
        result = c.check(evidence / 'link')
    elif part == 'intermediate':
        result = c.check(evidence, inventory='link/inventory.json')
    elif part == 'file':
        result = c.check(evidence, inventory='inventory-link.json')
    else:
        (evidence / 'receipts' / 'link.jsonl').symlink_to(evidence / 'inventory.json')
        result = c.check(evidence)
    assert result['exit_code'] == 1
    assert gates(result)['input_schema']['status'] == 'FAIL'


def test_fifo_refused_without_hanging(evidence):
    os.mkfifo(evidence / 'fifo.json')
    result = c.check(evidence, inventory='fifo.json')
    assert result['exit_code'] == 1


@pytest.mark.parametrize('value', [[], {}, ['*.example'], ['reviewed.example', 'reviewed.example'],
                                    [None], ['https://reviewed.example'], ['REVIEWED.example']])
def test_malformed_reviewed_host_policy_fails_closed(evidence, value):
    write_json(evidence / 'reviewed-hosts.json', value)
    result = c.check(evidence)
    assert gates(result)['input_schema']['status'] == 'FAIL'
    assert result['exit_code'] == 1


@pytest.mark.parametrize('value', [None, [], {}, {'schema_version': True, 'files': []},
                                    {'schema_version': 1, 'files': [None]}])
def test_malformed_inventory_fails_closed(evidence, value):
    write_json(evidence / 'inventory.json', value)
    result = c.check(evidence)
    assert gates(result)['input_schema']['status'] == 'FAIL'
    assert result['exit_code'] == 1


def test_nested_manifests_and_duplicate_inventory_association(evidence):
    plan = inventory()
    plan['files'].append({**plan['files'][0], 'segments': ['C2']})
    write_json(evidence / 'inventory.json', plan)
    put_receipts(evidence)
    (evidence / 'receipts' / 'noaa-nos').mkdir()
    (evidence / 'receipts' / 'noaa-nos' / 'manifest.jsonl').write_text(json.dumps(receipt()) + '\n')
    result = c.check(evidence)
    assert_supported_pass(result)
    assert result == c.check(evidence)


def test_metadata_size_limit(evidence, monkeypatch):
    monkeypatch.setattr(c, 'MAX_METADATA_BYTES', 8)
    assert c.check(evidence)['exit_code'] == 1


def test_no_writes_and_opaque_payload_path(evidence, monkeypatch):
    before = {p.relative_to(evidence).as_posix(): p.read_bytes()
              for p in evidence.rglob('*') if p.is_file()}
    original = os.open
    reads = []
    def read_only(path, flags, *args, **kwargs):
        assert not (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        assert str(path) != receipt()['path']
        reads.append(str(path))
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', read_only)
    assert_supported_pass(c.check(evidence))
    assert 'source.bag' not in reads
    assert before == {p.relative_to(evidence).as_posix(): p.read_bytes()
                      for p in evidence.rglob('*') if p.is_file()}


def test_cli_exit_and_json_report(evidence, capsys):
    assert c.main(['--input-root', str(evidence)]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report['exit_code'] == 3
    assert_supported_pass(report)


def test_fail_dominates_held_and_empty_gate_list_is_not_pass():
    assert c.exit_code([{'status': 'PASS'}]) == 0
    assert c.exit_code([{'status': 'PASS'}, {'status': 'HELD'}]) == 3
    assert c.exit_code([{'status': 'FAIL'}, {'status': 'HELD'}]) == 1
    assert c.exit_code([]) == 3
    with pytest.raises(c.Invalid):
        c.exit_code([{'status': 'unknown'}])


def test_deciding_gate_mutation_control_is_sensitive(evidence, monkeypatch):
    # Break ONLY the actual cap implementation within this inert synthetic test.
    record = {'schema': 's029-synthetic-received-v1', 'synthetic': True, 'received_bytes': 80000000001}
    assert c.cap_comparison(record) == 'FAIL'
    with monkeypatch.context() as patch:
        patch.setattr(c, 'RECEIVED_CAP_BYTES', 80000000001)
        with pytest.raises(AssertionError):
            assert c.cap_comparison(record) == 'FAIL'
    assert c.cap_comparison(record) == 'FAIL'
