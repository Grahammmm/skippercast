"""SC34: the terrain CLI JSON reader rejects ambiguous documents (duplicate keys, non-finite numbers).

``terrain_only.bounded_json`` reads the external ``--acceptance`` and ``--style``
files. It must refuse a duplicate key at any depth (the plain decoder silently
keeps the last one), refuse NaN/Infinity tokens, and refuse finite-looking
numbers that overflow to infinity (``1e999``). Duplicate-free documents must
parse exactly as before: same key order, int/float types, negative zero,
Unicode and nulls. See docs/engineering/sc34_terrain_json.md.

Every test copies its synthetic bytes into pytest's per-run ``tmp_path`` first.
No raster, renderer, source or network is used. The CLI cases replace
``terrain_only.preview`` with a stub that fails, so a regression cannot start a
render.
"""
import json
import math
import os
import shutil

import pytest

from skippercast.coastal.render import terrain_only
from tests._support import FIXTURES

FIXTURE_DIR = FIXTURES / 'sc34_terrain_json'
STYLE = FIXTURE_DIR / 'style-producer.json'
ACCEPTANCE = FIXTURE_DIR / 'acceptance-reference.json'

DUPLICATE = 'cli_json_duplicate_key'
OVERFLOW = 'cli_json_nonfinite:overflow'


# --------------------------------------------------------------------------- helpers

def put(tmp_path, data, name='input.json'):
    path = tmp_path / name
    path.write_bytes(data.encode('utf-8') if isinstance(data, str) else data)
    return path


def copy_fixture(tmp_path, fixture):
    target = tmp_path / fixture.name
    shutil.copyfile(fixture, target)
    return target


def walk_floats(value):
    if isinstance(value, float):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk_floats(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_floats(item)


def check_rejected(path, reason):
    """Regression assertion shared by the A2 tests and the A3 mutation controls.

    Passes only when ``bounded_json`` raises ValueError with exactly ``reason``.
    A successful parse raises AssertionError starting 'accepted ambiguous document',
    which is what the mutation controls look for.
    """
    try:
        document = terrain_only.bounded_json(path)
    except ValueError as error:
        if str(error) != reason:
            raise AssertionError(f'wrong refusal reason {str(error)!r}, expected {reason!r}') from error
        return
    raise AssertionError(f'accepted ambiguous document: {document!r}'[:300])


def check_equivalent(path):
    """Healthy control: the strict reader equals the plain decoder, byte for byte after dumping."""
    raw = path.read_bytes()
    document = terrain_only.bounded_json(path)
    expected = json.loads(raw.decode('utf-8'))
    if type(document) is not dict:
        raise AssertionError(f'non-dict result {type(document)!r}')
    if json.dumps(document, ensure_ascii=False) != json.dumps(expected, ensure_ascii=False):
        raise AssertionError('parsed document differs from the plain decoder')
    if any(not math.isfinite(x) for x in walk_floats(document)):
        raise AssertionError('non-finite float returned')
    return document


def refusing_preview(*args, **kwargs):
    raise AssertionError('preview reached: the CLI must hold before rendering')


def run_cli(tmp_path, monkeypatch, capsys, acceptance, *extra):
    monkeypatch.setattr(terrain_only, 'preview', refusing_preview)
    code = terrain_only.main(['--root', str(tmp_path), '--acceptance', str(acceptance),
                              '--output-dir', 'render', *extra])
    out = capsys.readouterr().out
    return code, out


# --------------------------------------------------------------------------- A1 valid and boundary behaviour

def test_a1_producer_style_round_trips_unchanged(tmp_path):
    document = check_equivalent(copy_fixture(tmp_path, STYLE))
    assert list(document) == list(terrain_only.DEFAULT_STYLE)
    assert type(document['light_azimuth_degrees']) is int and type(document['light_elevation_degrees']) is float
    assert type(document['contrast']) is int and type(document['contour_interval_m']) is float
    assert math.copysign(1.0, document['uncertainty_overlay']) == -1.0
    assert document['locked_depth_range_m'] == [-0.0, 125.0]
    assert math.copysign(1.0, document['locked_depth_range_m'][0]) == -1.0
    style = terrain_only.style_controls(document)
    assert style == {**terrain_only.DEFAULT_STYLE, **document}


def test_a1_metadata_reference_round_trips_unchanged(tmp_path):
    document = check_equivalent(copy_fixture(tmp_path, ACCEPTANCE))
    # The same key names repeat in distinct sibling objects; that is not a duplicate.
    assert set(document['terrain']) == set(document['mask']) == {'path', 'sha256', 'bytes', 'contract'}
    assert document['vertical']['evidence'] == {'note': None, 'items': [None, {'inner': None}]}
    assert document['segment_id'] == 'synthetic-segment-\u00e9-\u6c34\u6df1'
    assert document['limitations'][1].endswith('\U0001f30a')
    # NFC and NFD spellings are different strings; both survive.
    assert document['limitations'][2:] == ['caf\u00e9', 'cafe\u0301']
    affine = document['affine']
    assert [type(x) for x in affine] == [float, int, float, float, float, float, int, float, int]
    assert math.copysign(1.0, affine[7]) == -1.0 and affine[5] == 4_000_000.0


def test_a1_cli_context_digest_matches_the_plain_decoder(tmp_path, monkeypatch, capsys):
    path = copy_fixture(tmp_path, ACCEPTANCE)
    code, out = run_cli(tmp_path, monkeypatch, capsys, path, '--context-only')
    assert code == 0
    assert out == terrain_only.context(json.loads(path.read_bytes().decode('utf-8'))) + '\n'
    assert not (tmp_path / 'render').exists()


@pytest.mark.parametrize('token, kind', [
    ('0', int), ('-0', int), ('0.0', float), ('-0.0', float), ('1e2', float), ('1E+2', float),
    ('2.5e-3', float), ('-7.25E-1', float), ('1.7976931348623157e308', float),
    ('-1.7976931348623157e308', float), ('123456789e300', float), ('5e-324', float), ('1e-400', float),
    ('-1e-400', float),
    ('12345678901234567890', int)])
def test_a1_finite_number_boundaries_keep_value_and_type(tmp_path, token, kind):
    path = put(tmp_path, '{"a": {"b": [' + token + ']}, "c": ' + token + '}')
    document = check_equivalent(path)
    for value in (document['a']['b'][0], document['c']):
        assert type(value) is kind
        assert repr(value) == repr(json.loads(token))  # keeps -0.0 and underflow-to-zero sign


def test_a1_repeated_key_text_in_distinct_siblings_is_accepted(tmp_path):
    text = '{"a": {"x": 1}, "b": {"x": 2}, "c": [{"x": 3}, {"x": 4, "y": {"x": 5}}], "x": 6}'
    assert check_equivalent(put(tmp_path, text)) == json.loads(text)


def test_a1_unicode_keys_and_null_leaves(tmp_path):
    text = '{"\\u00e9": null, "e\\u0301": [null], "\u6c34": {"\U0001f30a": null}, "": null}'
    document = check_equivalent(put(tmp_path, text))
    assert list(document) == ['\u00e9', 'e\u0301', '\u6c34', '']
    assert document['\u6c34'] == {'\U0001f30a': None}


def test_a1_size_gate_preserved(tmp_path):
    assert terrain_only.MAX_CLI_JSON_BYTES == 2_000_000
    body = '{"x": 1}'
    exact = put(tmp_path, body + ' ' * (terrain_only.MAX_CLI_JSON_BYTES - len(body)), 'exact.json')
    assert exact.stat().st_size == terrain_only.MAX_CLI_JSON_BYTES
    assert terrain_only.bounded_json(exact) == {'x': 1}
    over = put(tmp_path, body + ' ' * (terrain_only.MAX_CLI_JSON_BYTES - len(body) + 1), 'over.json')
    check_rejected(over, 'cli_json_byte_bound')
    # A duplicate beyond the bound is still refused by size first, without parsing.
    dup_over = put(tmp_path, '{"x": 1, "x": 2}' + ' ' * terrain_only.MAX_CLI_JSON_BYTES, 'dup-over.json')
    check_rejected(dup_over, 'cli_json_byte_bound')


@pytest.mark.parametrize('text', ['[]', '[{"x": 1}]', '"x"', '1', '1.5', 'null', 'true'])
def test_a1_object_root_gate_preserved(tmp_path, text):
    check_rejected(put(tmp_path, text), 'cli_json_object_required')


def test_a1_non_regular_files_and_symlinks_refused(tmp_path):
    fifo = tmp_path / 'fifo.json'
    os.mkfifo(fifo)
    check_rejected(fifo, 'cli_json_regular_file_required')
    check_rejected(tmp_path, 'cli_json_regular_file_required')
    real = put(tmp_path, '{"x": 1}', 'real.json')
    link = tmp_path / 'link.json'
    link.symlink_to(real)
    with pytest.raises(OSError):
        terrain_only.bounded_json(link)
    with pytest.raises(FileNotFoundError):
        terrain_only.bounded_json(tmp_path / 'absent.json')


# --------------------------------------------------------------------------- A2 malformed input

DUPLICATE_CASES = {
    'top-equal': '{"x": 1, "x": 1}',
    'top-conflicting': '{"x": 1, "x": 2}',
    'top-null-then-value': '{"x": null, "y": 0, "x": {"z": 1}}',
    'nested-object': '{"a": {"x": 1, "x": 2}}',
    'nested-in-array': '{"a": [{"x": 1}, {"x": 1, "x": 2}]}',
    'deep': '{"a": {"b": {"c": {"d": 0, "d": null}}}}',
    'escaped-ascii': '{"x": 1, "\\u0078": 2}',
    'escaped-latin': '{"\\u00e9": 1, "\u00e9": 2}',
    'escaped-surrogate-pair': '{"\\ud83c\\udf0a": 1, "\U0001f30a": 2}',
    'escaped-both-sides': '{"\\u0061\\u0062": 1, "a\\u0062": 2}',
    'empty-key': '{"": 1, "": 2}',
}


@pytest.mark.parametrize('name', sorted(DUPLICATE_CASES))
def test_a2_duplicate_keys_rejected(tmp_path, name):
    check_rejected(put(tmp_path, DUPLICATE_CASES[name]), DUPLICATE)


def test_a2_duplicate_inside_a_root_array_is_refused_either_way(tmp_path):
    with pytest.raises(ValueError, match=r'^cli_json_(duplicate_key|object_required)$'):
        terrain_only.bounded_json(put(tmp_path, '[{"x": 1, "x": 2}]'))


def test_a2_producer_shaped_duplicates_rejected(tmp_path):
    style = STYLE.read_text(encoding='utf-8')
    injected = style.replace('"vertical_exaggeration": 2.5,', '"vertical_exaggeration": 2.5,\n  "vertical_exaggeration": 9,', 1)
    assert injected != style
    check_rejected(put(tmp_path, injected, 'style-dup.json'), DUPLICATE)
    acceptance = ACCEPTANCE.read_text(encoding='utf-8')
    marker = '"contract": "coastal-native-support-v2"'
    injected = acceptance.replace(marker, marker + ',\n    "sha256": "' + '5' * 64 + '"', 1)
    assert injected != acceptance
    check_rejected(put(tmp_path, injected, 'acceptance-dup.json'), DUPLICATE)


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity'])
@pytest.mark.parametrize('shape', ['{"x": %s}', '{"a": {"b": %s}}', '{"a": [0, [1, %s]]}', '{"a": [{"b": %s}]}'])
def test_a2_nonfinite_constants_rejected(tmp_path, token, shape):
    check_rejected(put(tmp_path, shape % token), 'cli_json_nonfinite:' + token)


@pytest.mark.parametrize('token', ['1e999', '-1e999', '1E400', '-1E+400', '1.8e308', '-1.8e308',
                                   '123456789e305', '0.1e310'])
@pytest.mark.parametrize('shape', ['{"x": %s}', '{"a": {"b": %s}}', '{"a": [0, [1, %s]]}', '{"a": [{"b": %s}]}'])
def test_a2_overflow_exponents_rejected(tmp_path, token, shape):
    check_rejected(put(tmp_path, shape % token), OVERFLOW)


def test_a2_producer_shaped_overflow_rejected(tmp_path):
    style = STYLE.read_text(encoding='utf-8').replace('1.25e2', '1.25e999', 1)
    check_rejected(put(tmp_path, style, 'style-overflow.json'), OVERFLOW)
    acceptance = ACCEPTANCE.read_text(encoding='utf-8').replace('4.0e6', '-4.0e999', 1)
    check_rejected(put(tmp_path, acceptance, 'acceptance-overflow.json'), OVERFLOW)


@pytest.mark.parametrize('data', [b'{"x": "\xff"}', b'{"x": "\xe2\x82"}', b'{"x": "\xc0\xaf"}',
                                  b'{"\xed\xa0\x80": 1}', b'\xef\xbb\xbf{"x": 1}', b'\xff\xfe{\x00}\x00'])
def test_a2_invalid_unicode_is_a_value_error(tmp_path, data):
    with pytest.raises(ValueError):
        terrain_only.bounded_json(put(tmp_path, data))


@pytest.mark.parametrize('text', ['', '{', '{"x": }', '{"x": 1,}', '{"x": 1} {"y": 2}', "{'x': 1}",
                                  '{"x": 01}', '{"x": .5}', '{"x": +1}', '{"x": 1e}', '{"x": nan}'])
def test_a2_malformed_json_is_a_value_error(tmp_path, text):
    with pytest.raises(ValueError):
        terrain_only.bounded_json(put(tmp_path, text))


@pytest.mark.parametrize('text, reason', [
    ('{"x": 1, "x": 2}', DUPLICATE), ('{"a": [{"b": 1e999}]}', OVERFLOW),
    ('{"a": {"b": NaN}}', 'cli_json_nonfinite:NaN'), ('[]', 'cli_json_object_required')])
def test_a2_cli_holds_ambiguous_acceptance_before_any_work(tmp_path, monkeypatch, capsys, text, reason):
    acceptance = put(tmp_path, text, 'acceptance.json')
    for extra in (('--context-only',), ()):
        code, out = run_cli(tmp_path, monkeypatch, capsys, acceptance, *extra)
        result = json.loads(out)
        assert (code, result['state'], result['holds']) == (2, 'held', [reason])
        assert result['source_accessed'] is False and result['publication_prohibited'] is True
    assert not (tmp_path / 'render').exists()


@pytest.mark.parametrize('replace, reason', [
    (('"vertical_exaggeration": 2.5,', '"vertical_exaggeration": 2.5, "vertical_exaggeration": 3,'), DUPLICATE),
    (('1.25e2', '1.25e999'), OVERFLOW)])
def test_a2_cli_holds_ambiguous_style_before_preview(tmp_path, monkeypatch, capsys, replace, reason):
    acceptance = copy_fixture(tmp_path, ACCEPTANCE)
    old, new = replace
    style = put(tmp_path, STYLE.read_text(encoding='utf-8').replace(old, new, 1), 'style.json')
    code, out = run_cli(tmp_path, monkeypatch, capsys, acceptance, '--style', str(style))
    result = json.loads(out)
    assert (code, result['state'], result['holds']) == (2, 'held', [reason])
    assert not (tmp_path / 'render').exists()


def test_a2_cli_contains_invalid_unicode_and_missing_files(tmp_path, monkeypatch, capsys):
    bad = put(tmp_path, b'{"x": "\xff"}', 'bad.json')
    code, out = run_cli(tmp_path, monkeypatch, capsys, bad, '--context-only')
    assert code == 2 and json.loads(out)['state'] == 'held'
    code, out = run_cli(tmp_path, monkeypatch, capsys, tmp_path / 'absent.json', '--context-only')
    assert code == 2 and json.loads(out)['state'] == 'held'


# --------------------------------------------------------------------------- A3 decisive synthetic mutation

class OriginalSettingsJson:
    """Test-local stand-in for terrain_only's ``json`` module.

    ``loads`` drops every keyword except ``parse_constant``. That is the decoder
    call before SC34. The size, descriptor and object-root checks around it stay
    the real code.
    """

    def __init__(self):
        self.calls = []

    def loads(self, text, **kwargs):
        self.calls.append(sorted(kwargs))
        return json.loads(text, parse_constant=kwargs['parse_constant'])

    def __getattr__(self, name):
        return getattr(json, name)


MUTATION_CASES = {
    'duplicate-top-level': ('{"x": 1, "x": 2}', DUPLICATE),
    'duplicate-nested-array': ('{"a": [{"x": 1}, {"x": 1, "x": 2}]}', DUPLICATE),
    'duplicate-escaped': ('{"x": 1, "\\u0078": 2}', DUPLICATE),
    'overflow-positive': ('{"x": 1e999}', OVERFLOW),
    'overflow-negative-nested': ('{"a": {"b": [0, -1e999]}}', OVERFLOW),
    'healthy-control': (None, None),
}


@pytest.mark.parametrize('case', list(MUTATION_CASES))
def test_mutation_controls(tmp_path, monkeypatch, case):
    text, reason = MUTATION_CASES[case]
    path = copy_fixture(tmp_path, ACCEPTANCE) if text is None else put(tmp_path, text)
    shim = OriginalSettingsJson()
    with monkeypatch.context() as patch:
        patch.setattr(terrain_only, 'json', shim)
        if text is None:
            check_equivalent(path)  # the healthy control must still pass under the mutation
            outcome = None
        else:
            with pytest.raises(AssertionError) as outcome:
                check_rejected(path, reason)
    assert shim.calls, 'the mutation did not route through the test-local decoder'
    assert all('parse_constant' in call for call in shim.calls)
    if outcome is not None:
        # The regression assertion failed because the document was ACCEPTED, not for another reason.
        assert str(outcome.value).startswith('accepted ambiguous document'), str(outcome.value)
        # The same assertion passes against the submitted reader.
        check_rejected(path, reason)
    else:
        check_equivalent(path)
    assert terrain_only.json is json
