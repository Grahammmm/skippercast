"""SC-CATALOG-ROWS: frozen catalog rows need unique, literal candidate identities.

`live_discovery._candidates` maps catalog rows by `source_id` before `diff`
compares two catalogs. A plain dict comprehension silently kept the LAST of two
rows that share an ID, so an ambiguous inventory diffed like a unique one. The
row gate now rejects non-object rows, absent/non-string/empty IDs and every
duplicate ID (byte-identical or conflicting) with a ValueError naming the row
index and the ID.

Synthetic, pure and offline: no discovery run, no HTTP, no file writes. A
scoped audit sentinel refuses sockets, subprocesses and model-client imports
while the target module is imported and while each test here runs.

Selectors: test_a1_* positive contract, test_a2_* failure/preservation
contract, test_a3_* decisive negative control (a test-local last-wins double
replaces only the new row gate; the duplicate regression must then fail with
pytest's DID NOT RAISE while unique-row controls stay green).
"""
import copy
import json
import sys

import pytest

from tests._support import FIXTURES

BLOCKED_EVENTS = frozenset({
    'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
    'socket.bind', 'socket.sendto', 'urllib.Request', 'http.client.connect', 'subprocess.Popen',
    'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork', 'webbrowser.open'})
MODEL_MODULES = frozenset({'openai', 'anthropic', 'ollama', 'litellm', 'google.generativeai'})
_ARMED = []  # non-empty only while this module imports its target or runs one of its tests
SENTINEL_HITS = []


def _sentinel(event, args):
    if not _ARMED:
        return
    name = str(args[0]) if event == 'import' and args else ''
    if event in BLOCKED_EVENTS or any(name == m or name.startswith(m + '.') for m in MODEL_MODULES):
        SENTINEL_HITS.append(event)
        raise RuntimeError(f'SC-CATALOG-ROWS offline sentinel refused {event}')


sys.addaudithook(_sentinel)
_ARMED.append('import')
try:
    from skippercast.coastal import live_discovery as ld  # noqa: E402  (imported under the sentinel)
finally:
    _ARMED.clear()

SOURCE_SCHEMA = 'coastal-source-v1'
DUPLICATE_FIXTURE = FIXTURES / 'sc_catalog_rows' / 'duplicate-conflicting.json'
UNIQUE_FIXTURE = FIXTURES / 'sc_catalog_rows' / 'unique.json'
NOTE = 'Catalog metadata diff only; no candidate is accepted for mapping or rendering.'


@pytest.fixture(autouse=True)
def offline_sentinel():
    _ARMED.append('test')
    try:
        yield
    finally:
        _ARMED.clear()
    assert SENTINEL_HITS == []


def row(source_id, **fields):
    value = dict(source_id=source_id, access_url=f'https://synthetic.invalid/{source_id}', metadata=None,
                 extent=None, rejection_reasons=[], unknowns=[], terrain=dict(accepted=False))
    value.update(fields)
    return value


def catalog(rows, schema=ld.CATALOG, **fields):
    return dict(schema=schema, candidates=rows, **fields)


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


# Shared regression bodies: used by the A2 contract AND the A3 mutation control,
# so the negative control exercises exactly the production assertions.
def assert_duplicate_rejected(document, source_id, index):
    with pytest.raises(ValueError) as current:
        ld.diff(None, document)
    message = str(current.value)
    assert f'candidate {index}' in message and repr(source_id) in message and 'duplicate' in message
    assert message.startswith('current ')
    with pytest.raises(ValueError) as previous:
        ld.diff(document, catalog([]))
    assert str(previous.value).startswith('previous ') and repr(source_id) in str(previous.value)


def assert_unique_diff():
    old = load(UNIQUE_FIXTURE)
    new = copy.deepcopy(old)
    new['catalog_id'] = 'synthetic-unique-next'
    new['candidates'] = [copy.deepcopy(new['candidates'][2]), copy.deepcopy(new['candidates'][0]),
                         row('synthetic:delta')]
    new['candidates'][0]['metadata'] = dict(crs='EPSG:3857')
    change = ld.diff(old, new, previous_ref='ref')
    assert change == dict(schema=ld.DIFF, previous='ref', current_catalog_id='synthetic-unique-next',
                          added=['synthetic:delta'], removed=['synthetic:bravo'],
                          changed=[dict(source_id='synthetic:charlie', fields=['metadata'])],
                          unchanged=1, note=NOTE)


# ---------------------------------------------------------------- A1 positive


def test_a1_empty_catalogs_diff_to_nothing():
    for previous in (None, catalog([]), catalog([], schema=SOURCE_SCHEMA)):
        change = ld.diff(previous, catalog([], catalog_id='empty'))
        assert change == dict(schema=ld.DIFF, previous=None, current_catalog_id='empty', added=[], removed=[],
                              changed=[], unchanged=0, note=NOTE)
    assert ld._candidates(catalog([])) == {}


def test_a1_unique_rows_map_literally_and_keep_row_objects():
    one = row('ncei:one', vendor_extra=dict(kept=[1, 2]))
    assert ld._candidates(catalog([one])) == {'ncei:one': one}
    assert ld._candidates(catalog([one]))['ncei:one'] is one
    # IDs are literal: no strip, lower-casing, repair or invention.
    rows = [row(' a'), row('a'), row('A'), row('a '), row('ä'), row('0'), row('ncei:x/y?z=1')]
    mapped = ld._candidates(catalog(rows))
    assert list(mapped) == [' a', 'a', 'A', 'a ', 'ä', '0', 'ncei:x/y?z=1']
    assert all(mapped[r['source_id']] is r for r in rows)


def test_a1_both_supported_schemas_compare():
    rows = [row('s:1'), row('s:2')]
    for old_schema in (ld.CATALOG, SOURCE_SCHEMA):
        for new_schema in (ld.CATALOG, SOURCE_SCHEMA):
            change = ld.diff(catalog(copy.deepcopy(rows), old_schema), catalog(copy.deepcopy(rows), new_schema))
            assert (change['added'], change['removed'], change['changed'], change['unchanged']) == ([], [], [], 2)


def test_a1_reordered_unique_rows_are_a_noop():
    rows = [row(f's:{n}', metadata=dict(n=n)) for n in range(5)]
    change = ld.diff(catalog(rows), catalog(list(reversed(copy.deepcopy(rows)))))
    assert (change['added'], change['removed'], change['changed'], change['unchanged']) == ([], [], [], 5)


def test_a1_addition_removal_change_sorted_with_field_order():
    old = catalog([row('b'), row('a'), row('keep'), row('gone-2'), row('gone-1')])
    new = catalog([row('z-new'), row('keep'), row('a', extent=dict(bbox=[0, 0, 1, 1]), access_url='u2',
                                                  vendor_extra='ignored'),
                   row('b', terrain=dict(accepted=False, note='x')), row('m-new')], catalog_id='c2')
    change = ld.diff(old, new)
    assert change['added'] == ['m-new', 'z-new'] and change['removed'] == ['gone-1', 'gone-2']
    assert change['changed'] == [dict(source_id='a', fields=['access_url', 'extent']),
                                 dict(source_id='b', fields=['terrain'])]
    assert change['unchanged'] == 1 and change['current_catalog_id'] == 'c2' and change['note'] == NOTE


def test_a1_previous_none_lists_every_current_id():
    change = ld.diff(None, catalog([row('c'), row('a'), row('b')]))
    assert change['added'] == ['a', 'b', 'c'] and change['removed'] == [] and change['unchanged'] == 0


def test_a1_inputs_are_not_mutated():
    old, new = load(UNIQUE_FIXTURE), load(UNIQUE_FIXTURE)
    new['candidates'][1]['unknowns'] = ['crs']
    before = copy.deepcopy((old, new))
    change = ld.diff(old, new)
    assert (old, new) == before
    assert change['changed'] == [dict(source_id='synthetic:bravo', fields=['unknowns'])]


def test_a1_unique_fixture_control():
    assert_unique_diff()


# ------------------------------------------------- A2 failure and preservation


@pytest.mark.parametrize('order', ['identical', 'conflict-first-wins-order', 'conflict-last-wins-order'])
@pytest.mark.parametrize('side', ['previous', 'current'])
def test_a2_duplicates_rejected_in_either_catalog(order, side):
    first, second = row('dup:x'), row('dup:x')
    if order == 'conflict-first-wins-order':
        second['access_url'] = 'changed'
    elif order == 'conflict-last-wins-order':
        first['access_url'] = 'changed'
    bad = catalog([row('ok:1'), first, row('ok:2'), second])
    good = catalog([row('ok:1'), row('dup:x'), row('ok:2')])
    before = copy.deepcopy(bad)
    with pytest.raises(ValueError) as caught:
        ld.diff(bad, good) if side == 'previous' else ld.diff(good, bad)
    message = str(caught.value)
    assert message == f"{side} candidate 3 duplicates source_id 'dup:x' first seen at candidate 1"
    assert bad == before


def test_a2_duplicate_fixture_rejected_through_real_gate():
    document = load(DUPLICATE_FIXTURE)
    assert_duplicate_rejected(document, 'synthetic:bravo', 2)
    with pytest.raises(ValueError, match=r"catalog candidate 2 duplicates source_id 'synthetic:bravo'"):
        ld._candidates(document)


BAD_IDS = [('absent', None), ('null', None), ('true', True), ('false', False), ('list', ['a']),
           ('empty-list', []), ('int', 0), ('one', 1), ('float', 1.5), ('empty', ''), ('object', {'id': 'a'})]


@pytest.mark.parametrize('label,value', BAD_IDS, ids=[name for name, _ in BAD_IDS])
@pytest.mark.parametrize('side', ['previous', 'current'])
def test_a2_bad_ids_rejected(label, value, side):
    bad_row = row('placeholder')
    if label == 'absent':
        del bad_row['source_id']
    else:
        bad_row['source_id'] = value
    bad = catalog([row('ok:1'), bad_row])
    with pytest.raises(ValueError, match=rf'^{side} candidate 1 needs a nonempty string source_id$'):
        ld.diff(bad, catalog([])) if side == 'previous' else ld.diff(None, bad)


@pytest.mark.parametrize('value', [None, 'ok:1', 1, True, ['ok:1'], ('ok:1',)],
                         ids=['null', 'string', 'int', 'bool', 'list', 'tuple'])
def test_a2_non_object_rows_rejected(value):
    for side in ('previous', 'current'):
        bad = catalog([row('ok:0'), value])
        with pytest.raises(ValueError, match=rf'^{side} candidate 1 must be an object$'):
            ld.diff(bad, catalog([])) if side == 'previous' else ld.diff(None, bad)


@pytest.mark.parametrize('document', [
    dict(schema=ld.CATALOG), dict(schema=ld.CATALOG, candidates=None),
    dict(schema=ld.CATALOG, candidates={'a': row('a')}), dict(schema=ld.CATALOG, candidates='a'),
    dict(schema=ld.CATALOG, candidates=(row('a'),)), dict(schema='other-v1', candidates=[]),
    dict(candidates=[]), [], 'catalog', 0, False, {}],
    ids=['missing', 'null', 'mapping', 'string', 'tuple', 'schema', 'no-schema', 'list', 'str', 'zero', 'false',
         'empty-object'])
def test_a2_invalid_containers_rejected_and_malformed_previous_is_not_missing(document):
    with pytest.raises(ValueError):
        ld.diff(None, document)
    # An explicit but malformed previous is validated, never treated as absent.
    with pytest.raises(ValueError):
        ld.diff(document, catalog([row('a')]))
    assert ld.diff(None, catalog([row('a')]))['added'] == ['a']


def test_a2_current_none_is_not_a_catalog():
    with pytest.raises(ValueError):
        ld.diff(catalog([]), None)


# ------------------------------------------------------ A3 negative control


def last_wins_double(document, label='catalog'):
    """Test-local double: the ORIGINAL pre-fix mapping, container checks unchanged."""
    if not isinstance(document, dict) or document.get('schema') not in (ld.CATALOG, 'coastal-source-v1'):
        raise ValueError('previous catalog must be a frozen catalog or finalized source manifest')
    rows = document.get('candidates')
    if not isinstance(rows, list):
        raise ValueError('previous catalog candidates required')
    return {r['source_id']: r for r in rows}


def test_a3_real_gate_positive_control():
    assert_duplicate_rejected(load(DUPLICATE_FIXTURE), 'synthetic:bravo', 2)
    assert_unique_diff()


def test_a3_last_wins_double_makes_duplicate_regression_fail(monkeypatch):
    monkeypatch.setattr(ld, '_candidates', last_wins_double)
    document = load(DUPLICATE_FIXTURE)
    # The exact inner failure: the ValueError gate is gone, so pytest.raises reports
    # DID NOT RAISE. Any other exception propagates and fails this test.
    with pytest.raises(pytest.fail.Exception, match=r'DID NOT RAISE'):
        assert_duplicate_rejected(document, 'synthetic:bravo', 2)
    # And the lossy diff the gate prevents: three rows collapse to two IDs, last wins.
    change = ld.diff(None, document)
    assert change['added'] == ['synthetic:alpha', 'synthetic:bravo']
    assert last_wins_double(document)['synthetic:bravo']['access_url'].endswith('b-second.bag')


def test_a3_last_wins_double_keeps_unique_controls_green(monkeypatch):
    monkeypatch.setattr(ld, '_candidates', last_wins_double)
    assert_unique_diff()
    assert ld.diff(None, catalog([]))['added'] == []


def test_a3_double_replaces_only_the_row_gate(monkeypatch):
    # Container/schema refusals are identical with and without the double, so the
    # control isolates the new row/uniqueness gate.
    real = ld._candidates
    for document in (dict(schema='other-v1', candidates=[]), dict(schema=ld.CATALOG), []):
        for function in (real, last_wins_double):
            with pytest.raises(ValueError):
                function(document)
    monkeypatch.setattr(ld, '_candidates', last_wins_double)
    assert ld._candidates is last_wins_double and real is not last_wins_double
