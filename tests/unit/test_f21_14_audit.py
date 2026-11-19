"""SCA-593/446: synthetic regional parity and separate freshness controls.

Run as a module with NumPy, Node 22+ and locked web dependencies to replay
both real engines offline. Pytest exercises the Python input pin without Node.
"""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from tests._support import ROOT

REGIONS = ('fixture-west', 'fixture-east')
NOW = '2000-01-03T00:00:00Z'
STALE = '2000-01-01T00:00:00Z'
LATER = '2000-01-03T01:00:00Z'
INSIDE = dict(zip(REGIONS, (True, False), strict=True))


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding='utf-8')
    return path


def _asset(root, region):
    return root / 'dist/data' / f'{region}.geojson'


def _boundary(x, name):
    return {'type': 'Feature', 'properties': {'NAME': name}, 'geometry': {
        'type': 'Polygon', 'coordinates': [[[x-1, -1], [x+1, -1], [x+1, 1], [x-1, 1], [x-1, -1]]]}}


def _fixture(root):
    for i, region in enumerate(REGIONS):
        assets = {'protected_areas': f'data/{region}.geojson'}
        if i:
            assets['closures'] = 'data/extra.geojson'
            _write(root / 'dist' / assets['closures'], {
                'type': 'FeatureCollection', 'checked_at': NOW, 'region_id': region,
                'features': [_boundary(6, 'Additional exclusion')]})
        _write(root / 'dist/regions' / region / 'region.json', {
            'schema_version': 1, 'id': region, 'forecast_points': [{'id': 'fixture'}],
            'assets': assets, 'mpa': {'bounds': [-10 + i, -10, 10, 10], 'minimum_features': 1}})
        _write(_asset(root, region), {'type': 'FeatureCollection', 'checked_at': NOW,
                                    'features': [_boundary(4 * i, region)]})
    return _write(root / 'export.geojson', {'type': 'FeatureCollection', 'features': [{
        'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [0, 0]},
        'properties': {'id': 'reef', 'waypoint': {'longitude': 0, 'latitude': 0}}}]})


@pytest.mark.gis
def test_regional_selection_pins_ordered_exact_artifact_bytes_and_clock(tmp_path):
    from scripts import protected_screen_parity as parity

    _fixture(tmp_path)
    now = 946857600000  # NOW in epoch milliseconds
    with patch.object(parity, 'REPO', tmp_path):
        for i, region in enumerate(REGIONS):
            loaded = parity._pin(region, now)
            assert loaded is not None
            bounds, features, current, packet = loaded
            pinned = json.loads(packet)
            assert current and pinned['now'] == now and pinned['region']['id'] == region
            paths = [_asset(tmp_path, region)]
            if i:
                paths.append(tmp_path / 'dist/data/extra.geojson')
            assert {key: base64.b64decode(raw) for key, raw in pinned['assets'].items()} == {
                path.relative_to(tmp_path / 'dist').as_posix(): path.read_bytes() for path in paths}
            assert [parity.ps.feature_name(f) for f in features] == [region] + (['Additional exclusion'] if i else [])
            verdict = parity.ps.verdicts(features, bounds, [('reef', {'type': 'Point', 'coordinates': [0, 0]}, 0, 0)])['reef']
            assert verdict['screened'] and verdict['inside'] is INSIDE[region]


def _stage_node(root):
    # A hard-coded default would see the synthetic west asset, not live data.
    scripts = root / 'scripts'
    scripts.mkdir()
    oracle = scripts / 'protected_screen_oracle.mjs'
    shutil.copyfile(ROOT / 'scripts' / oracle.name, oracle)
    shutil.copyfile(ROOT / 'scripts/protected_screen_parity.py', scripts / 'protected_screen_parity.py')
    (root / 'src').symlink_to(ROOT / 'src', target_is_directory=True)
    for name in ('region.js', 'protected-areas.js', 'geo-screen.js'):
        # Keep real module identity even when Node preserves symlinks.
        source = (ROOT / 'dist' / name).as_uri()
        (root / 'dist' / name).write_text(f'export * from {json.dumps(source)};\n')
    (root / 'dist/data/protected-areas.geojson').symlink_to(f'{REGIONS[0]}.geojson')


def _regional_parity(root, compare):
    # Default-region reuse or import-time envelope binding breaks east;
    # losing the supplemental closure also changes east's fingerprint.
    saved = []
    for region in REGIONS:
        out = root / f'{region}.json'
        assert compare(region, NOW, '--limit', '1', '--write-oracle', str(out)).returncode == 0
        record = json.loads(out.read_bytes())
        verdict = record['verdicts']['reef']
        assert verdict['screened'] and verdict['inside'] is INSIDE[region]
        saved.append(record['inputSha256'])
        assert compare(region, NOW, '--oracle', str(out)).returncode == 0
    assert saved[0] != saved[1]
    print('regional parity: two matching fingerprints, different pinned inputs and inside verdicts', flush=True)

    # Changes invisible to the geometry fingerprint must still invalidate reuse.
    west = REGIONS[0]
    out = root / f'{west}.json'
    wrong_clock = compare(west, LATER, '--oracle', str(out))
    assert wrong_clock.returncode == 1 and 'oracle inputs or test clock do not match' in wrong_clock.stderr
    asset = _asset(root, west)
    asset.write_bytes(asset.read_bytes() + b'\n')
    wrong_bytes = compare(west, NOW, '--oracle', str(out))
    assert wrong_bytes.returncode == 1 and 'oracle inputs or test clock do not match' in wrong_bytes.stderr
    print('oracle reuse: changed clock and whitespace-only boundary change refused', flush=True)


def _stale_parity(root, compare):
    # Keep the region, geometries and clock fixed; only the stored check time
    # changes. The real browser oracle must refuse, not stamp the file current.
    west = REGIONS[0]
    asset = _asset(root, west)
    _write(asset, {**json.loads(asset.read_bytes()), 'checked_at': STALE})
    out = root / 'stale.json'
    generated = compare(west, NOW, '--write-oracle', str(out))
    assert generated.returncode == 1 and 'oracle screen is not current' in generated.stderr
    assert not out.exists()
    reused = compare(west, NOW, '--oracle', str(root / f'{west}.json'))
    assert reused.returncode == 1 and 'boundary snapshot is not current' in reused.stderr
    print('stale parity: Node refused the original timestamp; Python refused cached verdicts', flush=True)


def _replay(root):
    export = _fixture(root)
    _stage_node(root)

    def compare(region, now, *args):
        result = subprocess.run([sys.executable, str(root / 'scripts/protected_screen_parity.py'), str(export),
                                 '--region', region, '--workers', '1', '--at', now, *args],
                                capture_output=True, text=True, timeout=30)
        print(f'{region}: exit {result.returncode}\n{result.stdout}{result.stderr}', end='', flush=True)
        return result

    _regional_parity(root, compare)
    _stale_parity(root, compare)


if __name__ == '__main__':
    with TemporaryDirectory(prefix='f21-14-') as scratch:
        _replay(Path(scratch))
