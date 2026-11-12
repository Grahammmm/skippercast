"""RF1315-7: the internal terrain demo refuses duplicate-key JSON members.

A hash-bound receipt (or NPZ vertical metadata) that repeats a decoded member
name is ambiguous: the decoder would silently keep the last value. The shared
``_json`` decoder must refuse it, so no demo output is created. All inputs are
synthetic bytes under ``tmp_path``.
"""
import hashlib
import io
import json
import zipfile
from contextlib import redirect_stdout

import pytest

np = pytest.importorskip('numpy')
pytest.importorskip('rasterio')

from skippercast.coastal.handoff.common import ref
from skippercast.coastal.render import terrain_demo, terrain_only
from tests.gis.test_coastal_terrain_dispatch_adoption_guards import accepted  # noqa: F401  (fixture)

NOW = '2026-10-09T00:00:00Z'
DUP = 'duplicate_json_key'


@pytest.mark.parametrize('data', [
    b'{"x":1,"x":2}',
    b'{"x":1,"x":1}',
    b'{"outer":{"x":1,"x":1}}',
    b'{"a":[{"x":1},{"y":1,"y":2}]}',
    b'{"x":1,"\\u0078":2}',
    b'{"q\\"k":1,"q\\u0022k":2}',
    '{"é":1,"\\u00e9":2}'.encode(),
], ids=['conflict', 'equal', 'nested', 'in_array', 'escaped', 'quote', 'non_ascii'])
def test_duplicate_decoded_names_refuse_at_every_depth(data):
    with pytest.raises(ValueError) as caught:
        terrain_demo._json(data)
    assert str(caught.value) == DUP


def test_distinct_names_and_order_preserved():
    assert list(terrain_demo._json(b'{"z":1,"a":2,"Z":3}')) == ['z', 'a', 'Z']
    # Canonically equivalent but differently encoded names stay distinct.
    decoded = terrain_demo._json('{"\u00e9":1,"e\u0301":2}'.encode())
    assert list(decoded) == ['\u00e9', 'e\u0301']
    assert terrain_demo._json(b'{"a":[{"x":1},{"x":2}],"b":null,"c":-0.5,"d":"s"}') == \
        {'a': [{'x': 1}, {'x': 2}], 'b': None, 'c': -0.5, 'd': 's'}
    with pytest.raises(ValueError, match='json_object_required'):
        terrain_demo._json(b'[{"x":1}]')
    with pytest.raises(json.JSONDecodeError):
        terrain_demo._json(b'{"x":1,')
    with pytest.raises(ValueError, match='nonfinite_json'):
        terrain_demo._json(b'{"x":NaN}')


def _render(root, document):
    terrain_only.preview(root, document, output_dir='terrain', now=NOW)
    return root / 'terrain/render-receipt.json'


def _main(root, descriptor, out):
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = terrain_demo.main(['--root', str(root), '--render-receipt', descriptor['path'],
                                  '--receipt-sha256', descriptor['sha256'],
                                  '--receipt-bytes', str(descriptor['bytes']), '--output-dir', out])
    return code, stream.getvalue()


def _assert_held(root, descriptor, out):
    code, stdout = _main(root, descriptor, out)
    assert code == 2
    assert json.loads(stdout) == dict(schema=terrain_demo.SCHEMA, state='held', holds=[DUP], **terrain_demo.FLAGS)
    assert not (root / out).exists()
    assert not any(p.name.startswith('.' + out + '.') for p in root.iterdir())


def _variant(root, name, data):
    (root / name).write_bytes(data)
    return ref(root, name, terrain_only.RESULT)


def test_contradictory_receipt_root_never_builds(accepted):  # noqa: F811
    root, document, *_ = accepted
    raw = _render(root, document).read_bytes()
    healthy = _variant(root, 'healthy.json', raw)
    result = terrain_demo.build_demo(root, healthy, output_dir='demo-ok')
    assert result['state'] == 'done' and result['triangles'] == 420
    assert result['publication_prohibited'] is True
    html_bytes = (root / 'demo-ok/terrain-demo.html').read_bytes()
    assert html_bytes == terrain_demo.html(terrain_demo.payload(root, healthy))
    duplicate = _variant(root, 'dup.json', b'{"publication_prohibited":false,' + raw[1:])
    with pytest.raises(ValueError, match=DUP):
        terrain_demo.build_demo(root, duplicate, output_dir='demo-dup')
    assert not (root / 'demo-dup').exists()
    _assert_held(root, duplicate, 'cli-dup')


def test_nested_acceptance_duplicate_never_builds(accepted):  # noqa: F811
    root, document, *_ = accepted
    raw = _render(root, document).read_bytes()
    assert b'"acceptance":{' in raw
    data = raw.replace(b'"acceptance":{', b'"acceptance":{"publication_prohibited":false,', 1)
    assert data != raw
    _assert_held(root, _variant(root, 'nested.json', data), 'demo-nested')


def test_npz_vertical_json_uses_same_gate(accepted):  # noqa: F811
    root, document, *_ = accepted
    receipt_path = _render(root, document)
    receipt = json.loads(receipt_path.read_bytes())
    (entry,) = [a for a in receipt['artifacts'] if a['path'].endswith('terrain-mesh.npz')]
    npz_path = root / entry['path']
    with np.load(npz_path, allow_pickle=False) as saved:
        arrays = {key: saved[key] for key in saved.files}
    text = str(arrays['vertical_json'].item())
    first, value = next(iter(json.loads(text).items()))
    # Repeat the first member with its own value: same decoded meaning, ambiguous bytes.
    arrays['vertical_json'] = np.array('{' + json.dumps(first) + ':' + json.dumps(value) + ',' + text[1:])
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    npz_path.write_bytes(buffer.getvalue())
    with zipfile.ZipFile(npz_path) as archive:
        assert sorted(archive.namelist()) == sorted(n + '.npy' for n in terrain_demo.ARRAY_NAMES)
    entry.update(bytes=npz_path.stat().st_size, sha256=hashlib.sha256(npz_path.read_bytes()).hexdigest())
    descriptor = _variant(root, 'npz-dup.json', json.dumps(receipt).encode())
    _assert_held(root, descriptor, 'demo-npz')


@pytest.mark.parametrize('change', ['digest', 'length', 'cap'])
def test_hash_and_size_precede_duplicate_check(accepted, change):  # noqa: F811
    root, document, *_ = accepted
    raw = _render(root, document).read_bytes()
    descriptor = _variant(root, 'dup.json', b'{"publication_prohibited":false,' + raw[1:])
    descriptor.update(dict(digest=dict(sha256='0' * 64), length=dict(bytes=descriptor['bytes'] - 1),
                           cap=dict(bytes=terrain_demo.MAX_JSON_BYTES + 1))[change])
    code, stdout = _main(root, descriptor, 'demo-' + change)
    assert code == 2
    assert json.loads(stdout)['holds'] in (['artifact_hash_or_bytes_changed'], ['artifact_bytes_changed'],
                                           ['artifact_descriptor_invalid'])
