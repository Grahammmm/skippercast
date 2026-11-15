"""Offline validation of the frozen 19-01 inventory; no runtime or record reads."""
import copy
import hashlib
import json
import re
import subprocess

import pytest

from tests._support import ROOT

MANIFEST = ROOT / 'docs/engineering/subsystem-retirement.manifest.json'
OWNER_IDS = {'retain-product', 'advisor-history', 'privacy-maintenance',
             'private-fleet', 'private-coastal-research'}
HEX64 = re.compile(r'[0-9a-f]{64}')
PRIVATE_KEY = re.compile(r'(^|_)(email|token|user_id|phone|password|secret|transcript|contact_id)($|_)', re.I)
PRIVATE_VALUE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+|\+\d{10,15}\b|\bBearer\s+\S+|\b(?:sk|ghp)[_-][A-Za-z0-9]{12,}', re.I)


def exact_fields(value, fields):
    assert isinstance(value, dict) and set(value) == set(fields.split()), 'unexpected or missing fields'


def safe_path(path):
    assert isinstance(path, str) and path and not path.startswith('/')
    assert not set(path.split('/')) & {'.', '..', ''}, f'unsafe path: {path}'


def no_private_data(value):
    if isinstance(value, dict):
        for key, item in value.items():
            assert not PRIVATE_KEY.search(key), 'private key'
            no_private_data(item)
    elif isinstance(value, list):
        for item in value:
            no_private_data(item)
    elif isinstance(value, str):
        assert not PRIVATE_VALUE.search(value), 'private value'


def validate_owners(owners, tracked):
    assert {o['id'] for o in owners} == OWNER_IDS and len(owners) == len(OWNER_IDS)
    claimed = {}
    for owner in owners:
        exact_fields(owner, 'id destination path_prefixes tracked_paths')
        assert isinstance(owner['destination'], str) and owner['destination'].strip()
        assert type(owner['tracked_paths']) is int and owner['tracked_paths'] > 0
        assert isinstance(owner['path_prefixes'], list) and owner['path_prefixes']
        owned = []
        for prefix in owner['path_prefixes']:
            safe_path(prefix.rstrip('/'))
            matches = [p for p in tracked if p.startswith(prefix)] if prefix.endswith('/') else [p for p in tracked if p == prefix]
            assert matches, f'empty prefix: {prefix}'
            for path in matches:
                assert path not in claimed, f'overlap: {path}'
                claimed[path] = owner['id']
                owned.append(path)
        assert len(owned) == owner['tracked_paths'], 'owner count mismatch'
    assert set(claimed) == set(tracked), 'unassigned tracked path'


def migration_paths(tracked):
    return {p for p in tracked if p.startswith('drizzle/meta/') or
            (p.startswith('drizzle/') and p.count('/') == 1 and p.endswith('.sql'))}


def validate_migrations(entries, root, tracked):
    listed = []
    for entry in entries:
        exact_fields(entry, 'path sha256')
        path = entry['path']
        safe_path(path)
        assert HEX64.fullmatch(entry['sha256']), 'invalid migration hash'
        assert path not in listed, f'duplicate migration: {path}'
        listed.append(path)
        assert (root / path).is_file(), f'missing migration: {path}'
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == entry['sha256'], f'changed migration: {path}'
    expected = migration_paths(tracked)
    assert set(listed) == expected, f'migration inventory mismatch: {sorted(set(listed) ^ expected)}'


def validate_runtime(facts):
    assert isinstance(facts, list) and facts
    names = set()
    for fact in facts:
        exact_fields(fact, 'name value custodian state')
        assert isinstance(fact['name'], str) and fact['name'] not in names, 'duplicate runtime fact'
        names.add(fact['name'])
        assert isinstance(fact['custodian'], str) and fact['custodian'].strip(), 'missing custodian'
        value = fact['value']
        assert value == 'UNKNOWN' or (type(value) is int and value >= 0), 'invalid runtime count'
        assert fact['state'] in {'HOLD', 'RECEIPT'}, 'invalid runtime state'
        assert value != 'UNKNOWN' or fact['state'] == 'HOLD', 'unknown must hold'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode()


def validate_manifest(data):
    exact_fields(data, 'schema_version source_commit status applied baseline owners migrations edges runtime_facts')
    assert type(data['schema_version']) is int and data['schema_version'] == 1, 'unsupported schema'
    assert re.fullmatch(r'[0-9a-f]{40}', data['source_commit']), 'invalid source commit'
    assert data['applied'] is False
    assert data['status'] == 'CANDIDATE ONLY; UNINSTALLED; REVIEW REQUIRED'
    no_private_data(data)
    tracked = git('ls-tree', '-r', '--name-only', data['source_commit']).splitlines()
    baseline = data['baseline']
    exact_fields(baseline, 'tracked_paths tracked_paths_sha256 product_output_prefix product_output_paths product_output_git_tree_sha256')
    assert baseline['tracked_paths'] == len(tracked)
    assert baseline['tracked_paths_sha256'] == hashlib.sha256(('\n'.join(tracked) + '\n').encode()).hexdigest()
    assert baseline['product_output_prefix'] == 'dist/'
    tree = git('ls-tree', '-r', data['source_commit'], '--', 'dist/')
    assert baseline['product_output_paths'] == len(tree.splitlines())
    assert baseline['product_output_git_tree_sha256'] == hashlib.sha256(tree.encode()).hexdigest()
    validate_owners(data['owners'], tracked)
    # Source snapshot remains immutable; current tracked migrations may neither drift nor disappear.
    current = git('ls-files').splitlines()
    assert migration_paths(current) == migration_paths(tracked), 'migration chain changed since source_commit'
    validate_migrations(data['migrations'], ROOT, current)
    for entry in data['migrations']:
        frozen = subprocess.check_output(['git', 'show', f"{data['source_commit']}:{entry['path']}"], cwd=ROOT)
        assert hashlib.sha256(frozen).hexdigest() == entry['sha256'], 'migration differs from frozen source'
    validate_runtime(data['runtime_facts'])
    assert isinstance(data['edges'], list) and data['edges']
    for edge in data['edges']:
        if edge.get('kind') == 'literal-import':
            exact_fields(edge, 'kind from_owner to_owner references resolution state')
            assert edge['from_owner'] in OWNER_IDS and edge['to_owner'] in OWNER_IDS
            assert edge['from_owner'] != edge['to_owner'] and edge['references']
            for pair in edge['references']:
                assert len(pair) == 2 and all(p in tracked for p in pair)
        else:
            exact_fields(edge, 'kind paths resolution state')
            assert edge['paths'] and all(any(p == s or p.startswith(s + '/') for p in tracked) for s in edge['paths'])
        assert isinstance(edge['resolution'], str) and edge['resolution'].strip()
        assert edge['state'] == 'HOLD'


@pytest.fixture
def manifest():
    return json.loads(MANIFEST.read_text())


def test_manifest_schema_version_and_unknown_fields(manifest):
    validate_manifest(manifest)
    for field, value in [('schema_version', 2), ('schema_version', True), ('extra', 1), ('source_commit', 'stale')]:
        bad = copy.deepcopy(manifest)
        bad[field] = value
        with pytest.raises(AssertionError):
            validate_manifest(bad)


def test_migration_hashes_match_disk_and_detect_edit(manifest, tmp_path):
    current = git('ls-files').splitlines()
    validate_migrations(manifest['migrations'], ROOT, current)
    for entry in manifest['migrations']:
        target = tmp_path / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / entry['path']).read_bytes())
    path = manifest['migrations'][0]['path']
    target = tmp_path / path
    original = target.read_bytes()
    target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    with pytest.raises(AssertionError, match='changed migration'):
        validate_migrations(manifest['migrations'], tmp_path, current)
    with pytest.raises(AssertionError, match='duplicate migration'):
        validate_migrations(manifest['migrations'] + [manifest['migrations'][0]], ROOT, current)


def test_every_owner_prefix_resolves_and_no_overlap(manifest):
    tracked = git('ls-tree', '-r', '--name-only', manifest['source_commit']).splitlines()
    validate_owners(manifest['owners'], tracked)
    for prefix, message in [('absent-source/', 'empty prefix'), (manifest['owners'][0]['path_prefixes'][0], 'overlap')]:
        bad = copy.deepcopy(manifest['owners'])
        bad[0]['path_prefixes'].insert(0, prefix)
        with pytest.raises(AssertionError, match=message):
            validate_owners(bad, tracked)
    with pytest.raises(AssertionError, match='unassigned'):
        validate_owners(manifest['owners'], tracked + ['unassigned.synthetic'])


@pytest.mark.parametrize('value', [-1, 0.5, '12', True, None])
def test_runtime_fact_must_be_nonnegative_int_or_unknown(manifest, value):
    facts = copy.deepcopy(manifest['runtime_facts'])
    facts[0]['value'] = value
    with pytest.raises(AssertionError, match='invalid runtime count'):
        validate_runtime(facts)


def test_runtime_custodian_and_unknown_hold(manifest):
    facts = copy.deepcopy(manifest['runtime_facts'])
    facts[0]['value'] = 0
    validate_runtime(facts)
    facts[0]['value'] = 5
    validate_runtime(facts)
    facts[0].pop('custodian')
    with pytest.raises(AssertionError):
        validate_runtime(facts)
    facts[0]['custodian'] = ' '
    with pytest.raises(AssertionError, match='missing custodian'):
        validate_runtime(facts)
    facts = copy.deepcopy(manifest['runtime_facts'])
    facts[0]['state'] = 'RECEIPT'
    with pytest.raises(AssertionError, match='unknown must hold'):
        validate_runtime(facts)


@pytest.mark.parametrize('key', ['email', 'token', 'user_id', 'access_token'])
def test_no_private_keys_or_values(manifest, key):
    no_private_data(manifest)
    with pytest.raises(AssertionError, match='private key'):
        no_private_data({key: 'redacted'})
    for value in ['synthetic' + '@example.invalid', 'Bearer ' + 'synthetic-secret', '+' + '12345678901']:
        with pytest.raises(AssertionError, match='private value'):
            no_private_data({'nested': [value]})


def test_new_drizzle_file_not_in_manifest_is_reported(manifest, tmp_path):
    tracked = [e['path'] for e in manifest['migrations']]
    for entry in manifest['migrations']:
        target = tmp_path / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / entry['path']).read_bytes())
    for path in ['drizzle/9999_unlisted.sql', 'drizzle/meta/unlisted.json']:
        (tmp_path / path).write_text('synthetic')
        with pytest.raises(AssertionError, match=re.escape(path)):
            validate_migrations(manifest['migrations'], tmp_path, tracked + [path])
