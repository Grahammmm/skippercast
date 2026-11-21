"""Offline tests of the standalone depth-coverage command through region.py."""
import hashlib
import json

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.warp import transform_geom

from scripts.relief import region as cli, run_region
from skippercast.relief import receipts


TRANSFORM = Affine(10, 0, 100_000, 0, -10, -200_000)
GENERATION = 'b' * 64
NODATA = -9999


def _tif(path, values, transform=TRANSFORM, dtype='float32', nodata=NODATA):
    cells = np.array(values, dtype=dtype)
    with rasterio.open(path, 'w', driver='GTiff', count=1, dtype=dtype, nodata=nodata,
                       width=cells.shape[1], height=cells.shape[0], crs='EPSG:3310', transform=transform) as dst:
        dst.write(cells, 1)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def region(tmp_path):
    region = receipts.Region(tmp_path / 'out', 'tiny')
    folder = region.dir / 'mosaic/public'
    folder.mkdir(parents=True)
    _tif(folder / 'elevation.tif', [[-10, -40, NODATA, NODATA, NODATA, -150]])
    _tif(folder / 'support_class.tif', [[3, 2, 0, 0, 0, 3]], dtype='uint8', nodata=0)
    mosaic = {
        'schema': 'sc-stage-receipt/1', 'region': 'tiny', 'stage': 'mosaic', 'scope': 'public',
        'status': 'ok', 'generation': GENERATION, 'attempt': 1,
        'outputs': [{'path': region.record(p), 'sha256': _sha(p), 'bytes': p.stat().st_size}
                    for p in sorted(folder.iterdir())],
        'upstream': [{'stage': 'select', 'generation': 'a' * 64}],
    }
    select = dict(mosaic, stage='select', scope=None, generation='a' * 64, upstream=[], outputs=[])
    # Raw regional water includes cells 0–4, not the measured abyss on land.
    water = region.dir / 'water.geojson'
    ring = [[100000, -200010], [100050, -200010], [100050, -200000], [100000, -200000], [100000, -200010]]
    geometry = transform_geom('EPSG:3310', 'EPSG:4326', {'type': 'Polygon', 'coordinates': [ring]})
    water.write_text(json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {}, 'geometry': geometry},
    ]}), encoding='utf-8')
    zone = dict(mosaic, stage='zone', generation='c' * 64, outputs=[], inputs=[
        {'role': 'water', 'path': region.record(water), 'sha256': _sha(water)},
    ])
    receipts.write_json_atomic(region.receipt_path('select'), select)
    receipts.write_json_atomic(region.receipt_path('mosaic', 'public'), mosaic)
    receipts.write_json_atomic(region.receipt_path('zone', 'public'), zone)
    return region


def _argv(region):
    return ['depth-coverage', '--region', region.id, '--out', str(region.out_root)]


def _report(region):
    return region.dir / 'coverage/depth-coverage.json'


def _expected(*, shallow=(100, 0, 0), deeper=(0, 100, 0), unknown=300, sha=None):
    return {
        'bands': {
            name: dict(measured_m2=measured, estimated_m2=estimated, unsurveyed_m2=unsurveyed)
            for name, (measured, estimated, unsurveyed) in (
                ('0-66ft', shallow), ('66-300ft', deeper), ('unknown-band', (0, 0, unknown))
            )
        },
        'deepest_m': 40.0, 'reaches_300ft': False,
        'region': 'tiny', 'mosaic_generation': GENERATION, 'coarse_sha256': sha,
    }


@pytest.mark.parametrize('use_coarse', [
    pytest.param(False, id='C1: without coarse, gaps stay unknown'),
    pytest.param(True, id='C1: coarse assigns bands without adding survey'),
])
def test_C1_report(region, tmp_path, use_coarse):
    # Nonaligned cells must be sampled onto the 10 m mosaic, with nodata kept unknown.
    args = _argv(region)
    expected = _expected()
    if use_coarse:
        coarse = tmp_path / 'coarse.tif'
        _tif(coarse, [[-130, -130, -10, -130, -40, NODATA, -1]], Affine(8, 0, 100_002, 0, -20, -200_000))
        args += ['--coarse', str(coarse)]
        expected = _expected(shallow=(100, 0, 100), deeper=(0, 100, 100), unknown=100, sha=_sha(coarse))
    assert cli.main(args) == 0
    assert json.loads(_report(region).read_bytes()) == expected


def test_C1_atomic_replacement(region, monkeypatch, capsys):
    # An interrupted replacement must leave the previous report, not a partial JSON file.
    destination = _report(region)
    destination.parent.mkdir()
    old = b'{"previous": true}\n'
    destination.write_bytes(old)

    def interrupted(source, target):
        assert target == destination and source.parent == target.parent and source != target
        assert target.read_bytes() == old
        assert json.loads(source.read_bytes()) == _expected()
        raise PermissionError('synthetic rename refusal')

    monkeypatch.setattr(receipts.os, 'replace', interrupted)
    assert cli.main(_argv(region)) == 1
    assert capsys.readouterr().err == 'depth-coverage: synthetic rename refusal\n'
    assert {p.name: p.read_bytes() for p in destination.parent.iterdir()} == {destination.name: old}


def test_C2_report_does_not_advance_release_stages(region):
    # The on-demand command must not create or update even a stage receipt or lock.
    before = {p.name: p.read_bytes() for p in region.stages_dir.iterdir()}
    assert cli.main(_argv(region)) == 0
    assert {p.name: p.read_bytes() for p in region.stages_dir.iterdir()} == before
    assert not {'depth-coverage', 'depth_coverage'}.intersection(run_region.STAGES)


def test_C1_unattested_support_is_not_measured(region):
    # Older mosaics can lack support classes; a leftover TIFF must not claim measurements.
    path = region.receipt_path('mosaic', 'public')
    doc = receipts.read_receipt(path)
    assert doc is not None
    doc['outputs'] = [row for row in doc['outputs'] if not row['path'].endswith('support_class.tif')]
    receipts.write_json_atomic(path, doc)
    assert cli.main(_argv(region)) == 0
    assert json.loads(_report(region).read_bytes()) == _expected(shallow=(0, 100, 0))


@pytest.mark.parametrize(('case', 'detail'), [
    pytest.param('missing', 'mosaic.public not done (missing: no receipt)', id='C3: missing receipt'),
    pytest.param('failed', 'mosaic.public not done (failed: attempt 1: failed fixture)', id='C3: failed receipt'),
    pytest.param('stale', 'mosaic.public not done (stale: upstream select has no receipt)', id='C3: stale upstream'),
    pytest.param('elevation.tif', 'mosaic.public not done (unproved: output changed: mosaic/public/elevation.tif)',
                 id='C3: elevation hash mismatch'),
    pytest.param('support_class.tif',
                 'mosaic.public not done (unproved: output changed: mosaic/public/support_class.tif)',
                 id='C3: support hash mismatch'),
    pytest.param('unattested', 'mosaic.public does not attest elevation.tif', id='C3: unbound elevation'),
    pytest.param('water', 'public zone water input changed', id='C3: water input hash mismatch'),
])
def test_C3_refusal_without_raster_reads_or_report(region, monkeypatch, capsys, case, detail):
    # A present TIFF isn't proof; same-size tampering must also be refused before GDAL opens anything.
    path = region.receipt_path('mosaic', 'public')
    if case == 'missing':
        path.rename(path.with_suffix('.absent'))
    elif case == 'stale':
        select = region.receipt_path('select')
        select.rename(select.with_suffix('.absent'))
    elif case in ('failed', 'unattested'):
        doc = receipts.read_receipt(path)
        assert doc is not None
        if case == 'failed':
            doc.update(status='failed', error='failed fixture')
        else:
            doc['outputs'] = [row for row in doc['outputs'] if not row['path'].endswith('elevation.tif')]
        receipts.write_json_atomic(path, doc)
    elif case == 'water':
        water = region.dir / 'water.geojson'
        water.write_bytes(water.read_bytes() + b'\n')
    else:
        raster = region.dir / 'mosaic/public' / case
        data = raster.read_bytes()
        raster.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    monkeypatch.setattr(rasterio, 'open', lambda *_a, **_kw: pytest.fail('read unverified mosaic'))
    assert cli.main(_argv(region)) == 1
    assert capsys.readouterr().err == f'depth-coverage: {detail}\n'
    assert not _report(region).parent.exists()
