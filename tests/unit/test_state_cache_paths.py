"""RF0510-5: reach_paths/shared_paths name a damaged receipt by its path under var/seafloor."""
import json
import re

import pytest

from skippercast.seafloor import state_cache

A, B, C, D, E = (ch * 64 for ch in 'abcde')
REACH = 'Damaged private reach state: '
SNAPSHOT = '^Damaged screen snapshot: screen/snapshot\\.json$'


def old_reach_paths(root, reach):
    """Oracle: reach_paths as it was on main before RF0510-5 (good trees only)."""
    base = root/'var/seafloor'
    folders = [base/'reaches'/reach, base/'private-reaches'/reach]
    hashes = set()
    for folder in folders:
        if (folder/'coverage-checkpoint.json').exists():
            hashes.update(json.loads((folder/'coverage-checkpoint.json').read_text()).get('source_hashes', []))
        if (folder/'run.json').exists():
            inputs = json.loads((folder/'run.json').read_text()).get('inputs', {})
            hashes.update(r['sha256'] for r in inputs.get('sources', []))
            hashes.update(b['row']['sha256'] for b in inputs.get('substrate_bindings', {}).values())
        if (folder/'classified-run.json').exists():
            for s in json.loads((folder/'classified-run.json').read_text())['inputs']['physical']['sources']:
                hashes.update([s['depth_source']['sha256'], s['classification_binding']['row']['sha256']])
    directories = folders + [base/'cache'/h for h in sorted(hashes)]
    return [p for d in directories for p in d.rglob('*')
            if p.is_file() and state_cache.SAFE.fullmatch(p.relative_to(base).as_posix())]


def put(root, relative, value):
    path = root/'var/seafloor'/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    return path


def good_run():
    return {'inputs': {'sources': [{'sha256': B}], 'substrate_bindings': {'geo': {'row': {'sha256': C}}}}}


def good_classified():
    return {'inputs': {'physical': {'sources': [
        {'depth_source': {'sha256': D}, 'classification_binding': {'row': {'sha256': E}}}]}}}


def test_good_reach_tree_gives_the_same_list_as_before(tmp_path):
    put(tmp_path, 'reaches/r1/coverage-checkpoint.json', {'source_hashes': [A]})
    put(tmp_path, 'reaches/r1/run.json', good_run())
    put(tmp_path, 'private-reaches/r1/classified-run.json', good_classified())
    put(tmp_path, 'private-reaches/r1/run.json', {})  # no inputs: still no hashes, as before
    for h in (A, D):
        put(tmp_path, f'cache/{h}/source.zip', b'zip')
    put(tmp_path, f'cache/{"f" * 64}/source.zip', b'unrelated')
    paths = state_cache.reach_paths(tmp_path, 'r1')
    assert paths == old_reach_paths(tmp_path, 'r1')
    names = sorted(p.relative_to(tmp_path/'var/seafloor').as_posix() for p in paths)
    assert names == sorted([f'cache/{A}/source.zip', f'cache/{D}/source.zip', 'private-reaches/r1/classified-run.json',
                            'private-reaches/r1/run.json', 'reaches/r1/coverage-checkpoint.json', 'reaches/r1/run.json'])


@pytest.mark.parametrize('relative, value', [
    ('reaches/r1/coverage-checkpoint.json', []),
    ('reaches/r1/coverage-checkpoint.json', {'source_hashes': 'abc'}),
    ('reaches/r1/coverage-checkpoint.json', {'source_hashes': {A: 1}}),
    ('reaches/r1/coverage-checkpoint.json', {'source_hashes': [A, 7]}),
    ('reaches/r1/coverage-checkpoint.json', {'source_hashes': None}),
    ('reaches/r1/coverage-checkpoint.json', b'not json'),
    ('reaches/r1/run.json', {'inputs': {'sources': [{'bytes': 3}]}}),
    ('reaches/r1/run.json', {'inputs': {'sources': [B]}}),
    ('reaches/r1/run.json', {'inputs': {'sources': {}}}),
    ('reaches/r1/run.json', {'inputs': {'sources': [{'sha256': ['x']}]}}),
    ('reaches/r1/run.json', {'inputs': {'substrate_bindings': {'geo': {'sha256': C}}}}),
    ('reaches/r1/run.json', {'inputs': {'substrate_bindings': [{'row': {'sha256': C}}]}}),
    ('reaches/r1/run.json', {'inputs': []}),
    ('private-reaches/r1/run.json', b'"text"'),
    ('reaches/r1/classified-run.json', {'inputs': {}}),
    ('private-reaches/r1/classified-run.json', {'inputs': {'physical': {'sources': [{'depth_source': {'sha256': D}}]}}}),
    ('private-reaches/r1/classified-run.json', {'inputs': {'physical': {'sources': 'x'}}}),
    ('private-reaches/r1/classified-run.json', b'{"inputs": "\xff"}'),
])
def test_damaged_reach_receipt_is_named_with_its_relative_path(tmp_path, relative, value):
    put(tmp_path, 'reaches/r1/run.json', good_run())  # overwritten when it is the damaged receipt
    put(tmp_path, relative, value)
    with pytest.raises(ValueError, match='^' + re.escape(REACH + relative) + '$'):
        state_cache.reach_paths(tmp_path, 'r1')


def test_bad_hex_in_a_well_shaped_receipt_keeps_the_hex_message(tmp_path):
    put(tmp_path, 'reaches/r1/coverage-checkpoint.json', {'source_hashes': ['../private']})
    with pytest.raises(ValueError, match='^Invalid source hash in private reach state$'):
        state_cache.reach_paths(tmp_path, 'r1')


def snapshot(tmp_path, value):
    return put(tmp_path, 'screen/snapshot.json', value)


@pytest.mark.parametrize('value', [
    {'layers': []},
    {'layers': {'mpa': {'name': 'no file'}}},
    {'layers': {'mpa': {'file': '../escape.json'}}},
    {'layers': {'mpa': {'file': 'sub/escape.json'}}},
    {'layers': {'mpa': {'file': '..'}}},
    {'layers': {'mpa': {'file': '.'}}},
    {'layers': {'mpa': {'file': ''}}},
    {'layers': {'mpa': {'file': 7}}},
    {'layers': {'mpa': 'mpa.json'}},
    {},
    [],
    b'\xff',
    b'{',
])
def test_damaged_snapshot_is_named(tmp_path, value):
    snapshot(tmp_path, value)
    with pytest.raises(ValueError, match=SNAPSHOT):
        state_cache.shared_paths(tmp_path)


def test_good_snapshot_lists_its_layer_files(tmp_path):
    name = f'cdfw-mpa-{A}.json'
    path = snapshot(tmp_path, {'layers': {'mpa': {'file': name}, 'fed': {'file': 'noaa_federal-1.json'}}})
    receipts = put(tmp_path, 'screen/source-receipts.json', {})
    base = tmp_path/'var/seafloor'
    assert state_cache.shared_paths(tmp_path) == [
        base/'reference/cells.json', base/'reference/run.json', path,
        base/'screen'/name, base/'screen/noaa_federal-1.json', receipts]


def test_no_snapshot_gives_reference_paths_and_existing_receipts_only(tmp_path):
    base = tmp_path/'var/seafloor'
    assert state_cache.shared_paths(tmp_path) == [base/'reference/cells.json', base/'reference/run.json']
    failure = put(tmp_path, 'screen/refresh-failure.json', {})
    assert state_cache.shared_paths(tmp_path) == [
        base/'reference/cells.json', base/'reference/run.json', failure]
