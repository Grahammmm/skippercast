"""Drive the coarse stage through the real region CLI with local GeoTIFFs."""

import hashlib
import json
import shutil

import pytest

from scripts.relief import region as cli

_REGION = 'synthetic-coast'
_FAMILY = 'noaa-bluetopo'
_BBOX = [-123.0, 37.998, -122.994, 38.003]
_CRS = 'EPSG:26910+5703'
_CELL = 20
_OUTPUTS = ('coarse-3310.tif', 'coarse.json')


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_census(region, doc):
    (region / 'census.json').write_text(json.dumps(doc), encoding='utf-8')


@pytest.fixture
def census(tmp_path):
    import numpy as np
    import rasterio as rio

    out = tmp_path / 'out'
    region = out / _REGION
    (region / 'tiles').mkdir(parents=True)

    def tile(name, family, depth, x, pin_field):
        rel = f'tiles/{name}.tif'
        path = region / rel
        with rio.open(path, 'w', driver='GTiff', crs=_CRS, count=1, width=56, height=56,
                      dtype='float32', nodata=np.nan, transform=rio.Affine(16, 0, x, 0, -16, 4_206_400)) as raster:
            raster.write(np.full((56, 56), depth, dtype='float32'), 1)
        return {'path': rel, 'family': family, 'crs': _CRS, pin_field: _sha(path)}

    # Real census aliases, both pin fields, two different depths, and an unrelated decoy.
    east = tile('b', 'nbs_bluetopo', -50, 500_400, 'sha256')
    west = tile('a', 'nbs_bluetopo', -25, 500_000, 'sha256_receipt')
    decoy = tile('decoy', 'cudem_ninth', -80, 500_000, 'sha256_receipt')
    doc = {'summary': {'region': _REGION, 'bbox': _BBOX}, 'files': [east, decoy, west]}
    _write_census(region, doc)
    pins = [{'path': west['path'], 'sha256': west['sha256_receipt']},
            {'path': east['path'], 'sha256': east['sha256']}]
    return out, region, doc, pins


def _run(out, family=_FAMILY):
    return cli.main(['coarse', '--out', str(out), '--region', _REGION,
                     '--family', family, '--cell-m', str(_CELL)])


def _receipt_path(region):
    return region / 'stages' / 'coarse.json'


def _receipt(region):
    return json.loads(_receipt_path(region).read_bytes())


def _inputs(region, pins):
    return [{'path': 'census.json', 'role': 'census', 'sha256': _sha(region / 'census.json')},
            *[dict(pin, role='coarse-tile') for pin in pins]]


def _output_paths(region):
    return [region / 'coarse' / name for name in _OUTPUTS]


def _no_output(region):
    assert not (region / 'coarse').exists()
    assert list(region.glob('coarse*/*')) == []


def test_C1_receipt_and_outputs(census, capsys):
    """C1: Omitting a tile, including another family, or losing bbox/cell size changes the receipt or grid."""
    import numpy as np
    import rasterio as rio
    from skippercast.relief.coarse import build_coarse

    out, region, _, pins = census
    assert _run(out) == 0
    receipt = _receipt(region)
    assert capsys.readouterr() == (f'[coarse] OK generation {receipt["generation"][:12]}: 2 outputs, attempt 1\n', '')
    assert (receipt['status'], receipt['rc'], receipt['held_reason'], receipt['error']) == ('ok', 0, None, None)
    assert receipt['inputs'] == _inputs(region, pins)
    assert receipt['params'] == {'family': _FAMILY, 'cell_m': _CELL}
    assert receipt['upstream'] == []
    assert receipt['target'] == 'coarse'
    tiff, report_path = _output_paths(region)
    assert receipt['outputs'] == [
        {'path': f'coarse/{path.name}', 'sha256': _sha(path), 'bytes': path.stat().st_size}
        for path in (tiff, report_path)
    ]
    # Core tests own the raster math; here the stage must wire the chosen census
    # paths, bounds, and resolution to it and persist both results.
    tiles = [(region / pin['path'], pin['sha256'], 'NAVD88-up') for pin in pins]
    array, transform, report = build_coarse(tiles, _BBOX, cell_m=_CELL)
    with rio.open(tiff) as raster:
        assert raster.crs.to_epsg() == 3310
        assert raster.transform == transform
        np.testing.assert_array_equal(raster.read(1), array)
    assert json.loads(report_path.read_bytes()) == {
        'region': _REGION, 'bbox': _BBOX, 'family': _FAMILY, 'cell_m': _CELL,
        'hole_report': report, 'inputs': {'census_sha256': _sha(region / 'census.json'), 'tiles': pins},
    }


def _assert_held(region, reason, inputs, capsys):
    receipt = _receipt(region)
    assert capsys.readouterr() == (f'[coarse] HELD generation {receipt["generation"][:12]}: {reason}\n', '')
    assert (receipt['status'], receipt['held_reason'], receipt['error'], receipt['outputs']) == (
        'held', reason, None, [],
    )
    assert receipt['inputs'] == inputs
    _no_output(region)


def test_C2_no_matching_family(census, capsys):
    """C2: A usable different family must not fill in for absent census rows."""
    out, region, _, _ = census
    assert _run(out, 'unknown-family') == 4
    _assert_held(region, "no census rows for family 'unknown-family' in region 'synthetic-coast'",
                 _inputs(region, []), capsys)


@pytest.mark.parametrize('missing', [
    pytest.param('tiles/b.tif', id='C2: missing declared tile'),
    pytest.param('census.json', id='C2: missing census'),
])
def test_C2_runner_blocks_missing_input(census, missing, capsys, monkeypatch):
    """C2: Missing files never reach build and cannot quietly reduce the tile set."""
    from skippercast.relief import coarse

    out, region, _, _ = census
    path = region / missing
    path.rename(path.with_suffix('.absent'))

    def unexpected_build(*args):
        pytest.fail('blocked inputs must not invoke build')

    monkeypatch.setattr(coarse, 'build', unexpected_build)
    assert _run(out) == 3
    assert capsys.readouterr() == (f'[coarse] BLOCKED generation -: input missing: {path.resolve()}\n', '')
    assert not _receipt_path(region).exists()
    _no_output(region)


def test_C2_mismatched_pin(census, capsys):
    """C2: A mismatched second tile is held at its census pin, not re-pinned to local bytes."""
    out, region, _, pins = census
    changed = pins[1]
    path = region / changed['path']
    shutil.copyfile(region / pins[0]['path'], path)  # Different but valid TIFF.
    observed = _sha(path)
    assert _run(out) == 4
    reason = f'SHA-256 mismatch for {changed["path"]}: expected {changed["sha256"]}, observed {observed}'
    _assert_held(region, reason, _inputs(region, [pins[0], dict(changed, sha256=observed)]), capsys)


@pytest.mark.parametrize('case,reason', [
    pytest.param('region', 'ReceiptError: census region mismatch', id='C1: reject another region census'),
    pytest.param('crs', 'ValueError: Expected NAVD88-up in census CRS for tiles/a.tif',
                 id='C1: reject no vertical datum'),
])
def test_C1_invalid_census_metadata(census, case, reason):
    """C1: A wrong-region bbox or horizontal-only CRS cannot attest the output."""
    out, region, doc, _ = census
    if case == 'region':
        doc['summary']['region'] = 'other-region'
    else:
        doc['files'][2]['crs'] = 'EPSG:26910'
    _write_census(region, doc)
    assert _run(out) == 1
    receipt = _receipt(region)
    assert (receipt['status'], receipt['rc'], receipt['error'], receipt['outputs']) == ('failed', 1, reason, [])
    _no_output(region)


def test_C3_receipt_no_op_and_clean_output_bytes(census, tmp_path, capsys, monkeypatch):
    """C3: Rebuilding a done generation or embedding output-root/time data breaks reuse."""
    from skippercast.relief import coarse

    out, region, _, _ = census
    second = tmp_path / 'fresh-out'
    fresh_region = second / _REGION
    shutil.copytree(region, fresh_region)  # Only the inputs exist so far.
    assert _run(out) == _run(second) == 0
    capsys.readouterr()
    receipt = _receipt(region)
    assert _receipt(fresh_region)['generation'] == receipt['generation']
    receipt_bytes = _receipt_path(region).read_bytes()
    expected = [path.read_bytes() for path in _output_paths(region)]
    assert [path.read_bytes() for path in _output_paths(fresh_region)] == expected

    def unexpected_build(*args):
        pytest.fail('a done generation must not invoke build')

    monkeypatch.setattr(coarse, 'build', unexpected_build)
    assert _run(out) == 0
    assert capsys.readouterr() == (
        f'[coarse] DONE generation {receipt["generation"][:12]}: no work: receipt ok, outputs re-hash, upstream current\n',
        '',
    )
    assert _receipt_path(region).read_bytes() == receipt_bytes
    assert [path.read_bytes() for path in _output_paths(region)] == expected
