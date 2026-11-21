"""Synthetic ENC-EXTRACT v1 documents through the unchanged region dispatcher."""
import hashlib
import json
import subprocess
import sys

import pytest

from skippercast.relief import receipts
from tests._support import ROOT

REGION = 'synthetic-harbor'
BOUNDS = [0, 0, 2, 2]
HAZARDS = ('WRECKS', 'OBSTRN', 'UWTROC')
PRIVATE = {'private_only': True, 'publication_allowed': False}
LAYER = 'layers/enc/enc-hazards.geojson'


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _feature(lnam, coords, *, geometry='Point', **attrs):
    return {'type': 'Feature', 'id': 'private-producer-id',
            'geometry': {'type': geometry, 'coordinates': coords},
            'properties': {'enc_source_cell': 'SYN00001', 'enc_edition': '2', 'LNAM': lnam,
                           'private_notes': 'not a map property', **attrs}}


@pytest.fixture
def extract(tmp_path, monkeypatch):
    catalog = tmp_path / 'synthetic-catalog'
    config = catalog / 'regions' / REGION / 'region.json'
    _json(config, {'id': REGION, 'bounds': BOUNDS})
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(catalog))
    root = tmp_path / 'enc-work'
    manifest = root / 'ENC-EXTRACT.json'
    report = {'schema_version': 1, 'policy': PRIVATE, 'reaches': []}

    def reach(rid, extent, entries=None, hold=None, *, write=True):
        row = {'id': rid, 'bbox': extent, 'hold': hold, 'files': {}}
        for kind in (*HAZARDS, 'SOUNDG', 'DEPCNT', 'SBDARE'):
            name = f'{rid}.{kind}.geojson'
            features = (entries or {}).get(kind, [])
            doc = {'type': 'FeatureCollection', 'features': features,
                   'enc_extract': {'reach_id': rid, 'object_class': kind, **PRIVATE}}
            # Legacy report paths belong to the original producer's filesystem.
            row['files'][kind] = {'path': f'/not-the-fixture-root/out/{name}',
                                  'sha256': _json(root / 'out' / name, doc) if write else '0' * 64}
        report['reaches'].append(row)

    repeated = _feature('same-wreck', [1, 1], VALSOU=12.5, enc_depth_unit_code=1)
    reach('west', [-2, -1, 1, 3], {
        'WRECKS': [repeated],
        'UWTROC': [_feature('rock-line', [[-1, 0.5], [3, 0.5]], geometry='LineString'),
                   _feature('outside', [-1, 1])],
        'SOUNDG': [_feature('sounding', [1, 1], DEPTH=8)],
        'DEPCNT': [_feature('contour', [[0, 1], [1, 1]], geometry='LineString')],
        'SBDARE': [_feature('seabed', [1, 1])],
    })
    reach('east', [1, -1, 4, 3], {
        'WRECKS': [repeated, _feature('distinct-wreck', [1, 1], VALSOU=12.5, enc_depth_unit_code=1)],
        'OBSTRN': [_feature('haven', [1.5, 1], enc_fish_haven=True, CATOBS=5),
                   _feature('other', [1.75, 1], enc_fish_haven=False, CATOBS=1)],
        'UWTROC': [_feature('rock-line', [[1.5, 1.5], [1.9, 1.5]], geometry='LineString')],
    })
    # No files exist for these reaches: selection and the hold check must use report metadata.
    reach('distant', [9, 9, 10, 10], write=False)
    reach('san-clemente', [20, 20, 21, 21], hold='Military/access/publication', write=False)
    reach('san-nicolas', [22, 22, 23, 23], hold='Military/access/publication', write=False)
    _json(manifest, report)
    return root, manifest, report, config


def _cli(stage, *args):
    return subprocess.run([sys.executable, str(ROOT / 'scripts/relief/region.py'), stage, *map(str, args)],
                          capture_output=True, text=True, check=False)


def _enc(root, out, *args, region=REGION):
    return _cli('enc', '--region', region, '--out', out, '--enc-root', root, *args)


def test_regional_hazards_build_and_replay(extract, tmp_path):
    # Wrong spatial filtering, collapsing distinct LNAMs, or passing source
    # properties through unfiltered all change the expected feature inventory.
    root, manifest, report, _ = extract
    out = tmp_path / 'normal'
    region = receipts.Region(out, REGION)
    public = region.dir / 'layers/public/contours/sentinel'
    unrelated = region.receipt_path('contour')
    for path in (public, unrelated):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'other stage owns these bytes')
    first = _enc(root, out)
    assert first.returncode == 0, first.stdout + first.stderr
    layer = region.dir / LAYER
    before = layer.read_bytes()
    obj = json.loads(before)
    assert obj['private_only'] is True and obj['publication_allowed'] is False
    properties = {'source_cell': 'SYN00001', 'source_edition': '2', 'nav_warning': 'NOT FOR NAVIGATION'}

    def feature(kind, geometry, coords, **extra):
        return {'type': 'Feature', 'geometry': {'type': geometry, 'coordinates': coords},
                'properties': {**properties, 'kind': kind, **extra}}

    expected = [feature('WRECKS', 'Point', [1, 1], chart_depth=12.5, depth_label='Estimate from chart soundings',
                        chart_depth_unit_code=1)] * 2
    expected += [feature('UWTROC', 'LineString', [[0, 0.5], [2, 0.5]]),
                 feature('UWTROC', 'LineString', [[1.5, 1.5], [1.9, 1.5]]),
                 feature('OBSTRN', 'Point', [1.5, 1], fish_haven=True),
                 feature('OBSTRN', 'Point', [1.75, 1], fish_haven=False)]
    assert sorted(obj['features'], key=lambda x: json.dumps(x, sort_keys=True)) == sorted(
        expected, key=lambda x: json.dumps(x, sort_keys=True))
    verdict = receipts.check(region, 'enc')
    receipt_doc = verdict.receipt
    assert verdict.done and receipt_doc is not None and receipt_doc['status'] == 'ok'
    assert receipt_doc['attempt'] == 1 and receipt_doc['params'] == PRIVATE
    assert receipt_doc['outputs'] == [{'path': LAYER, 'sha256': hashlib.sha256(before).hexdigest(),
                                      'bytes': len(before)}]
    assert {row['role'] for row in receipt_doc['inputs']} == {
        'region', 'extract-report', *(f'enc:{reach}.{kind}.geojson' for reach in ('west', 'east') for kind in HAZARDS)}
    receipt = region.receipt_path('enc')
    original = receipt.read_bytes(), receipt.stat().st_ino, layer.stat().st_ino
    replay = _enc(root, out)
    assert replay.returncode == 0 and 'no work' in replay.stdout
    assert (receipt.read_bytes(), receipt.stat().st_ino, layer.stat().st_ino) == original
    assert layer.read_bytes() == before
    assert public.read_bytes() == unrelated.read_bytes() == b'other stage owns these bytes'

    pinned = root / 'out/west.WRECKS.geojson'
    source = pinned.read_bytes()
    pinned.write_bytes(source + b'\n')
    bad_replay = _enc(root, out)
    assert bad_replay.returncode == 3 and 'SHA-256 does not match' in bad_replay.stdout
    assert (receipt.read_bytes(), receipt.stat().st_ino, layer.stat().st_ino) == original
    assert layer.read_bytes() == before
    pinned.write_bytes(source)

    # Independent rebuild with reversed reach/feature order: cached bytes alone
    # cannot prove deterministic serialization.
    report['reaches'].reverse()
    east = next(row for row in report['reaches'] if row['id'] == 'east')
    file = root / 'out/east.OBSTRN.geojson'
    doc = json.loads(file.read_bytes())
    doc['features'].reverse()
    east['files']['OBSTRN']['sha256'] = _json(file, doc)
    separate_report = manifest.parent.parent / 'separate/ENC-EXTRACT.json'
    _json(separate_report, report)
    fresh = tmp_path / 'independent'
    result = _enc(root, fresh, '--enc-manifest', separate_report)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (fresh / REGION / LAYER).read_bytes() == before


@pytest.mark.parametrize(('bad', 'message', 'rc'), [
    ('missing-root', 'ENC root is missing', 3),
    ('wrong-sha', 'SHA-256 does not match', 3),
    ('geometryless', 'missing feature geometry', 3),
    ('not-private', 'expected a private ENC-EXTRACT.json', 3),
    ('hold-id', 'military island hold', 4),
    ('hold-overlap', 'intersects ENC military/access hold', 4),
])
def test_preflight_refuses_without_writing(extract, tmp_path, bad, message, rc):
    # Each input violates a different preflight guard. Re-pin the geometryless
    # file so that a passing refusal cannot merely be a hash mismatch.
    root, manifest, report, config = extract
    out = tmp_path / 'refused'
    region = REGION
    if bad == 'missing-root':
        root = tmp_path / 'missing'
    elif bad in ('wrong-sha', 'geometryless'):
        file = root / 'out/east.OBSTRN.geojson'
        doc = json.loads(file.read_bytes())
        doc['features'][-1]['geometry'] = None
        sha = _json(file, doc)
        if bad == 'geometryless':
            east = next(row for row in report['reaches'] if row['id'] == 'east')
            east['files']['OBSTRN']['sha256'] = sha
            _json(manifest, report)
    elif bad == 'not-private':
        report['policy'] = {**PRIVATE, 'publication_allowed': True}
        _json(manifest, report)
    elif bad == 'hold-id':
        region = 'san-nicolas'
    else:
        _json(config, {'id': REGION, 'bounds': [19.5, 19.5, 20.5, 20.5]})
    result = _enc(root, out, region=region)
    assert result.returncode == rc and message in result.stdout, result.stdout + result.stderr
    assert not out.exists()


def test_enc_cannot_enter_public_layer_inventory(extract, tmp_path):
    # Real package CLI refuses the ENC sibling even when a caller explicitly
    # lists it, and a preexisting symlink cannot redirect the stage into public.
    root, _, _, _ = extract
    out = tmp_path / 'release'
    layer = out / REGION / LAYER
    public = out / REGION / 'layers/public'
    public.mkdir(parents=True)
    layer.parent.symlink_to(public, target_is_directory=True)
    refused = _enc(root, out)
    assert refused.returncode == 3 and 'symlink in private ENC output path' in refused.stdout
    assert not (public / layer.name).exists() and not (out / REGION / 'stages').exists()
    layer.parent.unlink()
    result = _enc(root, out)
    assert result.returncode == 0 and layer.is_file(), result.stdout + result.stderr
    inventory = tmp_path / 'inventory.json'
    _json(inventory, {'region': REGION, 'bounds': BOUNDS, 'minzoom': 8, 'maxzoom': 12, 'sources': [],
                      'detail_summary': {}, 'native_support_by_zoom': {},
                      'layer_paths': ['layers/public/relief.pmtiles', LAYER]})
    packaged = _cli('package', '--region', REGION, '--out', out, '--upstream', 'enc', '--manifest', inventory)
    assert packaged.returncode == 2 and 'not a public layer path' in packaged.stderr
    assert not (out / REGION / 'release').exists()
