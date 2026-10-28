"""SC-METADATA-OBJECT: cached metadata must decode to a JSON object before it is cached.

``cached_inventory.read_metadata`` memoizes decoded metadata by descriptor. Every
consumer indexes the result as a dictionary, so an array, null or scalar document
must be refused with a stable ``ValueError`` after the bounded verified read and
before any schema access or cache insertion. The bytes actually read stay charged;
a failed parse is never cached; a valid object is reused without another read.

Synthetic JSON metadata only, written under pytest's ``tmp_path``. No real cached
source, payload cache, network endpoint or model client is touched. Network and
model-client sentinels are installed before the production module is imported and
removed at module teardown. Test names: ``test_a1_*`` positive contract,
``test_a2_*`` failure and preservation contract, ``test_a3_*`` mutation controls.
"""
import contextlib
import hashlib
import http.client
import importlib.abc
import inspect
import json
import socket
import sys
from unittest.mock import patch
import urllib.request

import pytest

MODEL_CLIENTS = ('openai', 'anthropic', 'ollama', 'litellm', 'google.generativeai')


def _offline(*_args, **_kwargs):
    raise AssertionError('offline sentinel: network access attempted')


class _ModelClientBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in MODEL_CLIENTS or name in MODEL_CLIENTS:
            raise AssertionError('offline sentinel: model client import ' + name)
        return None


NETWORK_TARGETS = ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.create_connection',
                   'socket.getaddrinfo', 'urllib.request.urlopen', 'http.client.HTTPConnection.connect')


@contextlib.contextmanager
def offline_sentinels():
    """Scoped: never left installed for other modules in a shared pytest session."""
    blocker = _ModelClientBlocker()
    with contextlib.ExitStack() as stack:
        for target in NETWORK_TARGETS:
            stack.enter_context(patch(target, _offline))
        sys.meta_path.insert(0, blocker)
        stack.callback(sys.meta_path.remove, blocker)
        yield


# Sentinels are active while the production module is imported ...
with offline_sentinels():
    from skippercast.coastal import cached_inventory as ci
    from tests._support import FIXTURES

GENERIC = 'cached-source-json-v1'
SCHEMA = ci.LEAD_SCHEMA
CONTRACTS = (GENERIC, SCHEMA)
OBJECT_REQUIRED = 'metadata JSON object required'
CASES = json.loads((FIXTURES / 'sc_metadata_object' / 'nonobject-cases.json').read_text())['nonobject']


@pytest.fixture(autouse=True)
def _offline_test():
    # ... and again around every test in this module.
    with offline_sentinels():
        assert socket.create_connection is _offline and urllib.request.urlopen is _offline
        assert http.client.HTTPConnection.connect is _offline
        yield


@pytest.fixture(autouse=True)
def _metadata_only(monkeypatch):
    """Fail if anything but the synthetic .json metadata files is resolved or read."""
    original_owned, original_read = ci.owned, ci.bounded_metadata_read

    def owned(root, name):
        assert isinstance(name, str) and name.endswith('.json'), f'non-metadata path {name!r}'
        return original_owned(root, name)

    def bounded(root, name, expected):
        assert name.endswith('.json'), f'non-metadata read {name!r}'
        return original_read(root, name, expected)
    monkeypatch.setattr(ci, 'owned', owned)
    monkeypatch.setattr(ci, 'bounded_metadata_read', bounded)


def usage():
    return dict(metadata_bytes=0, metadata_files=0)


def descriptor(root, name, data, contract):
    (root / name).write_bytes(data)
    return dict(path=name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), contract=contract)


def valid_object(contract):
    if contract == GENERIC:
        return dict(sha256='a' * 64, bytes=4, url='https://example.org/source.bag')
    return dict(schema=SCHEMA, lead_id='synthetic-object', lifecycle='pending')


# A1 positive contract ---------------------------------------------------------

def test_a1_read_metadata_has_no_bound_defaults_to_redirect():
    signature = inspect.signature(ci.read_metadata)
    assert list(signature.parameters) == ['root', 'descriptor', 'cache', 'usage']
    assert all(p.default is inspect.Parameter.empty for p in signature.parameters.values())


@pytest.mark.parametrize('contract', CONTRACTS)
def test_a1_object_is_returned_charged_once_and_reused(tmp_path, contract, monkeypatch):
    value = valid_object(contract)
    data = ci.encoded(value)
    ref = descriptor(tmp_path, 'meta.json', data, contract)
    cache, use = {}, usage()
    first = ci.read_metadata(tmp_path, ref, cache, use)
    assert first == value
    assert use == dict(metadata_bytes=len(data), metadata_files=1)
    assert list(cache) == [ci.digest(ref)] and cache[ci.digest(ref)] is first
    # Identical descriptor: served from the cache with no stat, read or charge.
    monkeypatch.setattr(ci, 'bounded_metadata_read', lambda *a: pytest.fail('cached read repeated'))
    second = ci.read_metadata(tmp_path, dict(ref), cache, use)
    assert second is first
    assert use == dict(metadata_bytes=len(data), metadata_files=1)


def test_a1_schema_mismatch_object_still_refused_charged_and_not_cached(tmp_path):
    data = ci.encoded(dict(schema='some-other-schema-v1'))
    ref = descriptor(tmp_path, 'meta.json', data, SCHEMA)
    cache, use = {}, usage()
    with pytest.raises(ValueError, match='^metadata schema changed$'):
        ci.read_metadata(tmp_path, ref, cache, use)
    assert cache == {} and use == dict(metadata_bytes=len(data), metadata_files=1)


def _refusals(tmp_path):
    data = ci.encoded(valid_object(GENERIC))
    good = descriptor(tmp_path, 'meta.json', data, GENERIC)
    (tmp_path / 'meta.txt').write_bytes(data)
    return [
        ('exact metadata descriptor required', ['not-a-dict']),
        ('exact metadata descriptor required', dict(good, extra=1)),
        ('bounded positive integer required', dict(good, bytes=0)),
        ('bounded positive integer required', dict(good, bytes=ci.MAX_FILE + 1)),
        ('bounded positive integer required', dict(good, bytes=True)),
        ('metadata hash required', dict(good, sha256='A' * 64)),
        ('owned relative path required', dict(good, path=str(tmp_path / 'meta.json'))),
        ('owned relative path required', dict(good, path='../meta.json')),
        ('metadata identity changed', dict(good, bytes=len(data) + 1)),
    ]


def test_a1_pre_read_cap_and_path_checks_are_preserved(tmp_path, monkeypatch):
    refusals = _refusals(tmp_path)
    monkeypatch.setattr(ci, 'bounded_metadata_read', lambda *a: pytest.fail('read before pre-read checks'))
    for message, ref in refusals:
        cache, use = {}, usage()
        with pytest.raises(ValueError, match='^' + message + '$'):
            ci.read_metadata(tmp_path, ref, cache, use)
        assert cache == {} and use == usage(), message
    monkeypatch.undo()
    # Suffix check (the autouse guard would itself refuse a .txt name, so call it unguarded).
    data = (tmp_path / 'meta.txt').read_bytes()
    ref = dict(path='meta.txt', sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), contract=GENERIC)
    with pytest.raises(ValueError, match='^only JSON metadata admitted$'):
        ci.read_metadata(tmp_path, ref, {}, usage())


def test_a1_metadata_allowance_is_checked_before_the_read(tmp_path, monkeypatch):
    data = ci.encoded(valid_object(GENERIC))
    ref = descriptor(tmp_path, 'meta.json', data, GENERIC)
    monkeypatch.setattr(ci, 'MAX_METADATA', len(data))  # redirected runtime constant
    monkeypatch.setattr(ci, 'bounded_metadata_read', lambda *a: pytest.fail('read past allowance'))
    cache, use = {}, usage()
    with pytest.raises(ValueError, match='^metadata allowance exhausted$'):
        ci.read_metadata(tmp_path, ref, cache, use)
    assert cache == {} and use == usage()


# A2 failure and preservation contract ----------------------------------------

@pytest.mark.parametrize('case', sorted(CASES))
@pytest.mark.parametrize('contract', CONTRACTS)
def test_a2_nonobject_refused_with_value_error_charged_and_not_cached(tmp_path, contract, case):
    data = CASES[case].encode()
    assert not isinstance(json.loads(data), dict)
    ref = descriptor(tmp_path, 'meta.json', data, contract)
    cache, use = {}, usage()
    with pytest.raises(ValueError) as caught:
        ci.read_metadata(tmp_path, ref, cache, use)
    assert type(caught.value) is ValueError and str(caught.value) == OBJECT_REQUIRED
    assert cache == {}
    assert use == dict(metadata_bytes=len(data), metadata_files=1)


@pytest.mark.parametrize('contract', CONTRACTS)
def test_a2_hash_mismatch_precedes_decode_and_type(tmp_path, contract):
    data = CASES['array'].encode()
    ref = descriptor(tmp_path, 'meta.json', data, contract)
    ref['sha256'] = hashlib.sha256(b'other').hexdigest()
    cache, use = {}, usage()
    with pytest.raises(ValueError, match='^metadata hash changed$'):
        ci.read_metadata(tmp_path, ref, cache, use)
    assert cache == {} and use == dict(metadata_bytes=len(data), metadata_files=1)


@pytest.mark.parametrize('contract', CONTRACTS)
def test_a2_malformed_json_keeps_decoder_error_and_is_not_cached(tmp_path, contract):
    data = b'[{"unterminated": '
    ref = descriptor(tmp_path, 'meta.json', data, contract)
    cache, use = {}, usage()
    with pytest.raises(json.JSONDecodeError):
        ci.read_metadata(tmp_path, ref, cache, use)
    assert cache == {} and use == dict(metadata_bytes=len(data), metadata_files=1)


@pytest.mark.parametrize('contract', CONTRACTS)
def test_a2_corrected_retry_reads_its_new_descriptor_not_a_failed_entry(tmp_path, contract):
    bad = CASES['array'].encode()
    failed = descriptor(tmp_path, 'meta.json', bad, contract)
    cache, use = {}, usage()
    with pytest.raises(ValueError, match='^' + OBJECT_REQUIRED + '$'):
        ci.read_metadata(tmp_path, failed, cache, use)
    good = ci.encoded(valid_object(contract))
    corrected = descriptor(tmp_path, 'meta.json', good, contract)
    assert corrected != failed
    value = ci.read_metadata(tmp_path, corrected, cache, use)
    assert value == valid_object(contract)
    assert list(cache) == [ci.digest(corrected)]
    assert use == dict(metadata_bytes=len(bad) + len(good), metadata_files=2)
    # The stale failed descriptor is never answered from the cache.
    with pytest.raises(ValueError, match='^metadata (identity|hash) changed$'):
        ci.read_metadata(tmp_path, failed, cache, use)
    assert list(cache) == [ci.digest(corrected)]


def test_a2_cached_source_inventory_refuses_array_manifest_with_value_error(tmp_path):
    data = CASES['array'].encode()
    ref = descriptor(tmp_path, 'source.json', data, GENERIC)
    plan = dict(schema=ci.PLAN, region='synthetic',
                candidates=[dict(source_manifest=ref, cache_path='never-opened.json', window_set=[[0, 0, 4, 4]])],
                metadata_bytes=ci.MAX_METADATA, output_bytes=ci.MAX_OUTPUT, network_bytes=0,
                source_read_bytes=0, output_root=str(tmp_path / 'output'))
    with pytest.raises(ValueError) as caught:
        ci.inventory(tmp_path, plan, now=100, horizon=200)
    assert type(caught.value) is ValueError and str(caught.value) == OBJECT_REQUIRED
    assert not (tmp_path / 'never-opened.json').exists() and not (tmp_path / 'output').exists()


def test_a2_held_inventory_refuses_array_lead_with_value_error(tmp_path):
    data = CASES['array'].encode()
    ref = descriptor(tmp_path, 'lead-0.json', data, SCHEMA)
    plan = dict(schema=ci.LEAD_PLAN, region='synthetic', candidates=[dict(lead=ref)],
                metadata_bytes=ci.MAX_METADATA, output_bytes=ci.MAX_OUTPUT, network_bytes=0,
                source_read_bytes=0, output_root=str(tmp_path / 'output'),
                proposed_limits=dict(pending_candidates=1, native_active=1))
    with pytest.raises(ValueError) as caught:
        ci.inventory(tmp_path, plan, now=100, horizon=200)
    assert type(caught.value) is ValueError and str(caught.value) == OBJECT_REQUIRED


# A3 mutation controls ---------------------------------------------------------
# Test-local callables rebuilt from the production primitives. MUTATIONS restore
# the defect (or a near miss of the fix); the submitted source is never edited.

def staged_reader(mutation):
    def read(root, descriptor_value, cache, use):
        if not isinstance(descriptor_value, dict) or set(descriptor_value) != {'path', 'sha256', 'bytes', 'contract'}:
            raise ValueError('exact metadata descriptor required')
        ci.integer(descriptor_value['bytes'], ci.MAX_FILE)
        path = ci.owned(root, descriptor_value['path'])
        key = ci.digest(descriptor_value)
        if key in cache:
            return cache[key]
        info = path.lstat()
        data = ci.bounded_metadata_read(root, descriptor_value['path'], info)
        use['metadata_bytes'] += len(data)
        use['metadata_files'] += 1
        if hashlib.sha256(data).hexdigest() != descriptor_value['sha256']:
            raise ValueError('metadata hash changed')
        value = json.loads(data)
        if mutation == 'legacy-generic-bypass':  # the pre-fix code path
            if descriptor_value['contract'] != GENERIC and value.get('schema') != descriptor_value['contract']:
                raise ValueError('metadata schema changed')
            cache[key] = value
            return value
        if mutation == 'cache-before-check':
            cache[key] = value
        if not isinstance(value, dict):
            if mutation == 'refund-on-reject':
                use['metadata_bytes'] -= len(data)
                use['metadata_files'] -= 1
            raise ValueError(OBJECT_REQUIRED)
        if descriptor_value['contract'] != GENERIC and value.get('schema') != descriptor_value['contract']:
            raise ValueError('metadata schema changed')
        cache[key] = value
        return value
    return read


def check_nonobject_refused(reader, root, contract):
    """Tagged assertions; any other exception escapes as an unrelated failure."""
    data = CASES['array'].encode()
    ref = descriptor(root, 'array.json', data, contract)
    cache, use = {}, usage()
    try:
        reader(root, ref, cache, use)
    except ValueError as error:
        assert str(error) == OBJECT_REQUIRED, 'STABLE_MESSAGE: ' + str(error)
    except AttributeError as error:
        raise AssertionError('CONTROLLED_VALUEERROR: got AttributeError ' + str(error)) from None
    else:
        assert cache == {}, 'ARRAY_NOT_CACHED: nonobject metadata was cached'
        raise AssertionError('CONTROLLED_VALUEERROR: nonobject metadata was returned')
    assert cache == {}, 'ARRAY_NOT_CACHED: nonobject metadata was cached'
    assert use == dict(metadata_bytes=len(data), metadata_files=1), 'CHARGE_RETAINED: ' + repr(use)


def check_valid_object(reader, root, contract):
    value = valid_object(contract)
    data = ci.encoded(value)
    ref = descriptor(root, 'object.json', data, contract)
    cache, use = {}, usage()
    assert reader(root, ref, cache, use) == value
    assert reader(root, ref, cache, use) == value
    assert list(cache) == [ci.digest(ref)] and use == dict(metadata_bytes=len(data), metadata_files=1)


# (control name, mutation, contract, required failure tag)
MUTATION_CONTROLS = (
    ('legacy-generic-bypass', 'legacy-generic-bypass', GENERIC, 'ARRAY_NOT_CACHED'),
    ('legacy-schema-attribute-error', 'legacy-generic-bypass', SCHEMA, 'CONTROLLED_VALUEERROR'),
    ('cache-before-check', 'cache-before-check', GENERIC, 'ARRAY_NOT_CACHED'),
    ('refund-on-reject', 'refund-on-reject', SCHEMA, 'CHARGE_RETAINED'),
)


def run_mutation_control(root, mutation, contract, tag):
    """Return (detected, positive_passed, message) for one restored-defect callable."""
    reader = staged_reader(mutation)
    (root / 'positive').mkdir()
    (root / 'mutant').mkdir()
    check_valid_object(reader, root / 'positive', contract)  # healthy positive must pass
    try:
        check_nonobject_refused(reader, root / 'mutant', contract)
    except AssertionError as error:
        message = str(error)
        return message.startswith(tag + ':'), True, message
    return False, True, 'mutation was not detected'


@pytest.mark.parametrize('name,mutation,contract,tag', MUTATION_CONTROLS, ids=[c[0] for c in MUTATION_CONTROLS])
def test_a3_restored_defect_fails_the_specific_assertion(tmp_path, name, mutation, contract, tag):
    detected, positive, message = run_mutation_control(tmp_path, mutation, contract, tag)
    assert positive
    assert detected, f'{name}: expected {tag}, got {message}'


@pytest.mark.parametrize('contract', CONTRACTS)
def test_a3_production_and_unmutated_staged_reader_pass_both_checks(tmp_path, contract):
    for label, reader in (('production', ci.read_metadata), ('staged', staged_reader('none'))):
        root = tmp_path / label
        root.mkdir()
        check_valid_object(reader, root, contract)
        check_nonobject_refused(reader, root, contract)
