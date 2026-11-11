"""RF0755-7: the internal terrain demo reader contains excessive JSON nesting.

A hash-bound, below-cap receipt whose JSON nests deeper than the decoder can
handle must produce the existing held response (exit 2), not an uncaught
RecursionError. The shared ``_json`` decoder normalizes it to ValueError.
All inputs are synthetic bytes under ``tmp_path``.
"""
import hashlib
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip('numpy')
pytest.importorskip('rasterio')

from skippercast.coastal.handoff.common import ref
from skippercast.coastal.render import terrain_demo, terrain_only
from tests.gis.test_coastal_terrain_dispatch_adoption_guards import accepted  # noqa: F401  (fixture)

DEPTH = 20_000
NOW = '2026-10-09T00:00:00Z'
NESTING = 'json_nesting_excessive'


def _deep_array():
    return b'{"x":' + b'[' * DEPTH + b'0' + b']' * DEPTH + b'}'


def _deep_object():
    return b'{"x":' + b'{"a":' * DEPTH + b'0' + b'}' * DEPTH + b'}'


def _run(root, name, data, *, sha=None, size=None, out='out'):
    (root / name).write_bytes(data)
    argv = ['--root', str(root), '--render-receipt', name,
            '--receipt-sha256', sha or hashlib.sha256(data).hexdigest(),
            '--receipt-bytes', str(len(data) if size is None else size), '--output-dir', out]
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = terrain_demo.main(argv)
    return code, stream.getvalue()


def test_deep_receipt_returns_held_json(tmp_path):
    data = _deep_array()
    assert len(data) < terrain_demo.MAX_JSON_BYTES
    code, stdout = _run(tmp_path, 'deep.json', data)
    assert code == 2
    response = json.loads(stdout)
    assert response == dict(schema=terrain_demo.SCHEMA, state='held', holds=[NESTING], **terrain_demo.FLAGS)
    assert not (tmp_path / 'out').exists()
    assert [p.name for p in tmp_path.iterdir()] == ['deep.json']


@pytest.mark.parametrize('data', [_deep_array(), _deep_object()], ids=['array', 'object'])
def test_shared_decoder_normalizes_array_and_object_depth(data):
    with pytest.raises(ValueError, match=NESTING) as caught:
        terrain_demo._json(data)
    assert isinstance(caught.value.__cause__, RecursionError)


def test_shallow_invalid_receipt_keeps_reason(tmp_path):
    code, stdout = _run(tmp_path, 'shallow.json', b'{"x":[]}')
    assert code == 2
    assert json.loads(stdout)['holds'] == ['internal_render_receipt_required']


def test_ordinary_json_semantics_unchanged():
    assert terrain_demo._json('{"a":[1,2.5,null,"é\\u00e9"],"b":{"c":-0.0}}') == \
        {'a': [1, 2.5, None, 'éé'], 'b': {'c': -0.0}}
    assert list(terrain_demo._json(b'{"z":1,"a":2}')) == ['z', 'a']
    assert type(terrain_demo._json(b'{"i":1,"f":1.0}')['i']) is int
    assert type(terrain_demo._json(b'{"i":1,"f":1.0}')['f']) is float
    with pytest.raises(ValueError, match='json_object_required'):
        terrain_demo._json(b'[1]')
    with pytest.raises(json.JSONDecodeError):
        terrain_demo._json(b'{"a":')
    for token in (b'NaN', b'Infinity', b'-Infinity'):
        with pytest.raises(ValueError, match='nonfinite_json'):
            terrain_demo._json(b'{"a":' + token + b'}')
    # Nesting just below the decoder's capacity is still parsed normally.
    assert terrain_demo._json(b'{"x":' + b'[' * 50 + b']' * 50 + b'}')['x']


@pytest.mark.parametrize('change', ['digest', 'length', 'cap'])
def test_hash_and_size_precede_decode(tmp_path, change):
    data = _deep_array()
    kwargs = dict(digest=dict(sha='0' * 64), length=dict(size=len(data) - 1),
                  cap=dict(size=terrain_demo.MAX_JSON_BYTES + 1))[change]
    with patch.object(terrain_demo, '_json', side_effect=AssertionError('decoded before bytes were verified')):
        code, stdout = _run(tmp_path, 'deep.json', data, **kwargs)
    assert code == 2
    holds = json.loads(stdout)['holds']
    assert holds and NESTING not in holds[0]


def test_healthy_demo_still_builds(accepted):  # noqa: F811
    root, document, *_ = accepted
    terrain_only.preview(root, document, output_dir='terrain', now=NOW)
    receipt = ref(root, 'terrain/render-receipt.json', terrain_only.RESULT)
    args = ['--root', str(root), '--render-receipt', receipt['path'],
            '--receipt-sha256', receipt['sha256'], '--receipt-bytes', str(receipt['bytes'])]
    results = []
    for out in ('demo-a', 'demo-b'):
        stream = io.StringIO()
        with redirect_stdout(stream):
            assert terrain_demo.main(args + ['--output-dir', out]) == 0
        results.append(json.loads(stream.getvalue()))
    first, second = results
    assert first['state'] == 'done'
    assert first['triangles'] > 0 and first['vertices'] > 0
    assert first['html'] == second['html'] and first['payload_sha256'] == second['payload_sha256']
    html_a = (root / 'demo-a/terrain-demo.html').read_bytes()
    assert html_a == (root / 'demo-b/terrain-demo.html').read_bytes()
    assert hashlib.sha256(html_a).hexdigest() == first['html']['sha256']
    data = terrain_demo.payload(root, receipt)
    assert terrain_demo.html(data) == html_a
    assert first['payload_sha256'] == terrain_demo.digest(data)
    assert all(first[key] == value for key, value in terrain_demo.FLAGS.items())
    assert 'holds' not in first
