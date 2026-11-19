"""SCA-593: regional boundary and freshness controls (invented features only).

Run as a module with NumPy, Node 22+ and locked web dependencies for the
read-only baseline comparison.
Pytest exercises the Python side without requiring Node in the Python jobs.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests._support import ROOT

REGIONS = ('fixture-west', 'fixture-east')
NOW = '2000-01-03T00:00:00Z'
STALE = '2000-01-01T00:00:00Z'
INSIDE = {REGIONS[0]: True, REGIONS[1]: False}


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding='utf-8')
    return path


def _fixture(root):
    for i, region in enumerate(REGIONS):
        x = 4 * i
        asset = f'data/{region}.geojson'
        _write(root / 'dist/regions' / region / 'region.json', {
            'schema_version': 1, 'id': region, 'forecast_points': [{'id': 'fixture'}],
            'assets': {'protected_areas': asset},
            'mpa': {'bounds': [-10, -10, 10, 10], 'minimum_features': 1}})
        _write(root / 'dist' / asset, {
            'type': 'FeatureCollection', 'checked_at': NOW, 'features': [{
                'type': 'Feature', 'properties': {'NAME': region}, 'geometry': {
                    'type': 'Polygon', 'coordinates': [[[x-1, -1], [x+1, -1], [x+1, 1], [x-1, 1], [x-1, -1]]]}}]})
    return _write(root / 'export.geojson', {'type': 'FeatureCollection', 'features': [{
        'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [0, 0]},
        'properties': {'id': 'reef', 'waypoint': {'longitude': 0, 'latitude': 0}}}]})


def _selection(root, region, export):
    from skippercast.seafloor import protected_screen as ps

    loaded = ps.load_screen(root, region)
    assert loaded is not None, f'no boundary for {region}'
    bounds, boundary, (relative,) = loaded
    artifact = root / 'dist' / relative
    raw = artifact.read_bytes()
    doc = json.loads(raw)
    assert doc['features'] == boundary  # the exact selected file must feed both engines
    feature, = json.loads(export.read_bytes())['features']
    verdict = ps.verdicts(boundary, bounds, [('reef', feature['geometry'], 0, 0)])['reef']
    assert verdict['screened'] and verdict['inside'] is INSIDE[region]
    return artifact, hashlib.sha256(raw).hexdigest()


def _current(path, now):
    checked = datetime.fromisoformat(json.loads(path.read_bytes())['checked_at'])
    return -timedelta(minutes=5) <= datetime.fromisoformat(now) - checked <= timedelta(hours=36)


@pytest.mark.gis
def test_regional_selection_resolves_distinct_artifacts_and_verdicts(tmp_path):
    export = _fixture(tmp_path)
    west, east = (_selection(tmp_path, region, export) for region in REGIONS)
    assert west[0] != east[0] and west[1] != east[1]


# A file-based Node bootstrap freezes the clock and initializes the synthetic
# region before importing the real browser screen (its envelope is import-time).
BOOT = '''
import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const [mode, config, now, entry, input, out, ...args] = process.argv.slice(2);
const RealDate = Date;
globalThis.Date = class extends RealDate {
  constructor(...args) { super(...(args.length ? args : [now])); }
  static now() { return RealDate.parse(now); }
};
globalThis.fetch = () => { throw Error('offline fixture: unexpected fetch'); };
globalThis.CustomEvent = class {};
globalThis.document = {getElementById: () => ({classList: {toggle() {}}}), dispatchEvent() {}};
const region = JSON.parse(readFileSync(config));
const {setRegion} = await import('./dist/region.js');
setRegion(region);
if (mode === 'legacy') {
  process.argv = [process.execPath, entry, input, out, ...args];
  await import(pathToFileURL(entry).href);
} else {
  const raw = readFileSync(entry);
  const {initProtectedAreas} = await import('./dist/protected-areas.js');
  const {screenPlace} = await import('./dist/geo-screen.js');
  const screen = await initProtectedAreas(null, () => {}, async url => {
    if (url !== region.assets.protected_areas) throw Error('wrong artifact request');
    return JSON.parse(raw);  // no freshening or reserialization of the input bytes
  });
  const {geometry} = JSON.parse(readFileSync(input)).features[0];
  const verdicts = screen.ready() ? {reef: screenPlace(screen, {
    latitude: 0, longitude: 0, geometries: [geometry],
  })} : {};
  writeFileSync(out, JSON.stringify({fingerprint: screen.fingerprint(), verdicts, ms: 0,
    ready: screen.ready(), sha256: createHash('sha256').update(raw).digest('hex')}));
}
'''


def _stage_node(root):
    # Copy just the real CLI so its fixed default reads the *synthetic* west
    # artifact. The browser code itself is imported unchanged from the checkout.
    scripts = root / 'scripts'
    scripts.mkdir()
    oracle = scripts / 'protected_screen_oracle.mjs'
    shutil.copyfile(ROOT / 'scripts' / oracle.name, oracle)
    for name in ('region.js', 'protected-areas.js', 'geo-screen.js'):
        (root / 'dist' / name).symlink_to(ROOT / 'dist' / name)
    default = root / 'dist/data/protected-areas.geojson'
    default.symlink_to(f'{REGIONS[0]}.geojson')
    boot = root / 'boot.mjs'
    boot.write_text(BOOT, encoding='utf-8')
    return oracle, boot


def _baseline(root):
    from scripts import protected_screen_parity as parity

    export = _fixture(root)
    oracle, boot = _stage_node(root)
    out = root / 'oracle.json'

    def node(mode, region, entry, input_path, *args):
        config = root / 'dist/regions' / region / 'region.json'
        run = subprocess.run(['node', str(boot), mode, str(config), NOW, str(entry),
                              str(input_path), str(out), *args], capture_output=True, text=True, timeout=30)
        if run.stdout:
            print(run.stdout, end='')
        return run

    gap = False
    for region in REGIONS:
        asset, digest = _selection(root, region, export)
        assert _current(asset, NOW)
        # A reference process loads the same requested bytes and test clock.
        node('reference', region, asset, export).check_returncode()
        reference = json.loads(out.read_bytes())
        assert reference['ready'] and reference['sha256'] == digest
        args = [str(export), '--region', region, '--workers', '1']
        with patch.multiple(parity, REPO=root, ProcessPoolExecutor=ThreadPoolExecutor):
            print(f'{region}: same-byte reference (sha256={digest})', flush=True)
            assert parity.main([*args, '--oracle', str(out)]) == 0
            default_output = f'/tmp/protected-screen-oracle-{region}.json'

            def run_oracle(cmd, *, check):
                exe, entry, input_path, output, *rest = cmd
                assert check and (exe, entry, input_path, output) == (
                    'node', str(oracle), str(export), str(out))
                result = node('legacy', REGIONS[0], entry, input_path, *rest)
                assert result.returncode == 0, result.stderr

            # Relocate only the hard-coded output path and supply a synthetic
            # default region; the production comparator still picks its argv.
            with patch.multiple(parity, Path=lambda p: out if p == default_output else Path(p),
                                subprocess=SimpleNamespace(run=run_oracle)):
                code = parity.main(args)
            print(f'{region}: {"PASS" if code == 0 else "GAP"}; baseline parity exit {code}')
            if region == REGIONS[0]:
                assert code == 0, 'default-region positive control failed'
            gap |= code != 0

    # Separate freshness control: explicitly pass the stale bytes to the
    # real oracle, so timestamp laundering cannot be mistaken for wrong region.
    west = root / 'dist/data' / f'{REGIONS[0]}.geojson'
    stale = _write(root / 'stale.geojson', {**json.loads(west.read_bytes()), 'checked_at': STALE})
    assert not _current(stale, NOW)
    node('reference', REGIONS[0], stale, export).check_returncode()
    reference = json.loads(out.read_bytes())
    assert not reference['ready'] and not reference['verdicts']
    assert reference['sha256'] == hashlib.sha256(stale.read_bytes()).hexdigest()
    out.unlink()
    result = node('legacy', REGIONS[0], oracle, export, '--boundaries', str(stale))
    if result.returncode:
        assert 'oracle screen is not current' in result.stderr, result.stderr
        assert not out.exists(), 'stale refusal left an oracle result'
        print('stale: oracle refused')
    else:
        actual = json.loads(out.read_bytes())
        assert actual['fingerprint'] and actual['verdicts']['reef']['screened']
        print('stale: GAP; fixed-clock reference withheld verdict, baseline emitted a screened verdict')
        gap = True
    return int(gap)


if __name__ == '__main__':
    with TemporaryDirectory(prefix='f21-14-') as scratch:
        raise SystemExit(_baseline(Path(scratch)))
