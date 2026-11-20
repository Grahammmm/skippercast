"""Fixture-only checks of the local screenshot-camera advisory."""
import hashlib
import json
import math
import subprocess
import sys

import pytest

from scripts.coast_diagnostics import relief_digest_footprint as footprint
from tests._support import ROOT

ROOT_KEY = 'layers/public/relief.digests/root.json'
CHUNK8 = '8/2_2.json'
CHUNK10 = '10/10_8.json'
CHUNK15 = '15/320_256.json'
NOTE = 'A missing centre tile does not mean an empty viewport.'


def write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding='utf-8')


@pytest.fixture
def release(tmp_path):
    manifest = tmp_path / 'release' / 'fixture-generation' / 'release.json'
    root = tmp_path / ROOT_KEY
    pins = {}
    layers = [{'path': 'layers/public/tiles/relief.pmtiles', 'bytes': 1, 'sha256': '0' * 64}]

    def record(file):
        raw = file.read_bytes()
        row = dict(path=file.relative_to(tmp_path).as_posix(), bytes=len(raw),
                   sha256=hashlib.sha256(raw).hexdigest())
        layers.append(row)
        return row['sha256']

    # No archive or real survey data. z10 has a neighbour in the right block;
    # z13 has no block at all. Both are legitimate sparse-index misses.
    for name, x, y in ((CHUNK8, 160, 128), (CHUNK10, 641, 512), (CHUNK15, 20480, 16384)):
        file = root.parent / name
        write_json(file, [[x, y, 'a' * 64]])
        pins[name] = record(file)
    write_json(root, {'chunks': pins})
    root_pin = record(root)
    write_json(manifest, dict(schema='sc-relief-release/1', private=False, minzoom=8, maxzoom=15,
                              digest_root_sha256=root_pin, layers=sorted(layers, key=lambda row: row['path'])))
    return manifest, root


def args(manifest):
    return ['--release', str(manifest), '--lon', '45', '--lat', '0']


def test_default_capture_zooms_and_sparse_tiles_are_advisory(release):
    manifest, root = release

    def snapshot():
        return {p: p.read_bytes() for p in root.parents[3].rglob('*') if p.is_file()}

    before = snapshot()
    # Invoke the real entry point from elsewhere: catches cwd-relative lookup,
    # unintentional archive reads and an off-by-one camera/source zoom offset.
    run = subprocess.run([sys.executable, str(ROOT / 'scripts/coast_diagnostics/relief_digest_footprint.py'),
                          *args(manifest), '--json'], cwd=manifest.parent, capture_output=True, text=True, check=True)
    assert json.loads(run.stdout) == {
        'status': 'checked', 'advisory': NOTE,
        'tiles': [dict(z=8, x=160, y=128, status='indexed'), dict(z=10, x=640, y=512, status='missing'),
                  dict(z=13, x=5120, y=4096, status='missing'), dict(z=15, x=20480, y=16384, status='indexed')],
    }
    assert snapshot() == before


def test_custom_zooms_read_only_relevant_chunks(release, capsys):
    manifest, root = release
    (root.parent / CHUNK15).unlink()
    assert footprint.main([*args(manifest), '--zooms', '10', '8', '10']) == 0
    result = capsys.readouterr()
    assert result.out.splitlines() == ['8/160/128: indexed', '10/640/512: missing', NOTE]
    assert not result.err


@pytest.mark.parametrize('z', range(8, 18))
def test_xyz_math_at_each_capture_zoom(z):
    # Pick interior points on opposite sides of the equator via the inverse
    # projection (not a round-trip through the implementation's forward math).
    # Fractional tile positions catch rounding instead of flooring.
    n = 1 << z
    for x, y in ((n // 4 - 1, n // 4), (n // 2 + 2, 3 * n // 4 - 1)):
        lon = (x + 0.875) * 360 / n - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.875) / n))))
        assert footprint.centre_tile(lon, lat, z) == (x, y)
    assert footprint.centre_tile(-180, 90, z) == (0, 0)
    assert footprint.centre_tile(180, -90, z) == (n - 1, n - 1)


@pytest.mark.parametrize('fault', ['root_bytes', 'root_size', 'root_manifest', 'root_missing_layer',
                                   'chunk_bytes', 'chunk_size', 'chunk_manifest', 'chunk_missing_layer',
                                   'chunk_missing_root_entry'])
def test_pin_failure_is_not_reported_as_a_sparse_miss(release, capsys, fault):
    manifest, root = release
    doc = json.loads(manifest.read_bytes())
    chunk_key = str((root.parent / CHUNK10).relative_to(root.parents[3]))
    rows = {row['path']: row for row in doc['layers']}
    if fault.endswith('_bytes'):
        path = root if fault.startswith('root_') else root.parent / CHUNK10
        # Same-length changes leave valid JSON: length/parse alone is not a pin check.
        path.write_bytes(path.read_bytes().replace(b'a', b'b', 1))
    elif fault.endswith('_size'):
        rows[ROOT_KEY if fault.startswith('root_') else chunk_key]['bytes'] += 1
    elif fault == 'root_manifest':
        doc['digest_root_sha256'] = 'b' * 64
    elif fault == 'chunk_manifest':
        rows[chunk_key]['sha256'] = 'b' * 64
    elif fault.endswith('_missing_layer'):
        doc['layers'].remove(rows[ROOT_KEY if fault.startswith('root_') else chunk_key])
    else:
        index = json.loads(root.read_bytes())
        del index['chunks'][CHUNK10]
        write_json(root, index)
        rows[ROOT_KEY].update(bytes=root.stat().st_size, sha256=hashlib.sha256(root.read_bytes()).hexdigest())
        doc['digest_root_sha256'] = rows[ROOT_KEY]['sha256']
    write_json(manifest, doc)
    # z8 is good; a later failed pin must not emit a partial advisory.
    assert footprint.main([*args(manifest), '--json']) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'pin_mismatch'
    assert 'tiles' not in report


@pytest.mark.parametrize('fault', ['missing_file', 'pinned_row_in_wrong_block'])
def test_invalid_index_is_not_reported_as_a_sparse_miss(release, capsys, fault):
    manifest, root = release
    chunk = root.parent / CHUNK10
    if fault == 'missing_file':
        chunk.unlink()
    else:
        # Matching hashes do not make an out-of-block row valid. A reader that
        # only checks membership would silently call this a legitimate miss.
        doc = json.loads(manifest.read_bytes())
        rows = {row['path']: row for row in doc['layers']}
        index = json.loads(root.read_bytes())
        write_json(chunk, [[639, 512, 'a' * 64]])
        chunk_pin = hashlib.sha256(chunk.read_bytes()).hexdigest()
        rows[chunk.relative_to(root.parents[3]).as_posix()].update(bytes=chunk.stat().st_size, sha256=chunk_pin)
        index['chunks'][CHUNK10] = chunk_pin
        write_json(root, index)
        root_pin = hashlib.sha256(root.read_bytes()).hexdigest()
        rows[ROOT_KEY].update(bytes=root.stat().st_size, sha256=root_pin)
        doc['digest_root_sha256'] = root_pin
        write_json(manifest, doc)
    assert footprint.main([*args(manifest), '--json']) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'invalid'
    assert 'tiles' not in report


@pytest.mark.parametrize('override', [['--lon', 'nan'], ['--lat', '91'], ['--zooms', '16']])
def test_invalid_camera_or_zoom_is_not_reported_as_coverage(release, capsys, override):
    manifest, _ = release
    assert footprint.main([*args(manifest), *override, '--json']) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'invalid'
