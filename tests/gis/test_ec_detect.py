"""EC1 ec_detect: the known error classes in one native grid, on tiny GeoTIFFs written into tmp_path."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis
_spec = importlib.util.spec_from_file_location('ec_detect', ROOT / 'scripts' / 'ec_detect.py')
det = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(det)


def _tif(path, values, x0=7e5, y0=3.9e6, cell=2.0, crs='EPSG:32610', dtype='float32', nodata=-9999.0, driver='GTiff'):
    import rasterio
    from rasterio.transform import from_origin
    values = np.asarray(values, dtype=dtype)
    values = values[None] if values.ndim == 2 else values
    with rasterio.open(path, 'w', driver=driver, width=values.shape[2], height=values.shape[1], count=values.shape[0],
                       dtype=dtype, crs=crs, transform=from_origin(x0, y0, cell, cell), nodata=nodata) as ds:
        ds.write(values)
    return path


@pytest.fixture
def d(tmp_path):
    """Non-fixture grids: tmp_path/grids, or a /var/tmp directory when the base temp carries FIXTURE_PATH tokens."""
    clean = not det.ec.FIXTURE_PATH.search(str((tmp_path / 'grids').resolve()))
    path = tmp_path / 'grids' if clean else Path(tempfile.mkdtemp(prefix='ec-detect-', dir='/var/tmp'))
    path.mkdir(exist_ok=True)
    yield path
    if not clean:
        shutil.rmtree(path)


def _run(capsys, path, receipt, *extra, source='usgs-test'):
    code = det.main([str(path), '--source-id', source, '--receipt', str(receipt), *extra])
    out = capsys.readouterr()
    doc = json.loads(Path(receipt).read_text()) if code == 0 else None
    if doc is not None:
        assert det.ec.check_receipt('ec-detect-v1', doc) == []
        assert json.loads(out.out) == {'disposition': doc['disposition'], 'receipt': str(receipt)}
    return code, doc, out.err


def _slope():
    return np.tile(-10.0 - 50.0 * np.arange(64) / 63.0, (64, 1))  # -10 m at column 0 to -60 m at column 63


def _acceptance_grid():
    v = _slope()
    v[30, 10] = -9999.0  # 1-cell hole
    v[20:22, 40:42] = -9999.0  # 2x2 hole
    v[40:44, 20:24] = -9999.0  # 4x4 hole: 16 cells > hole_max_cells(2 m) = 9
    v[10:13, 12:15] = -20.0
    v[11, 13] = -40.0  # pit in a -20 m ring
    v[51:54, 18:21] = -25.0
    v[52, 19] = -5.0  # spike in a -25 m ring
    return v


def test_acceptance_grid_lists_holes_pit_spike_and_is_fix(d, capsys):
    tif = _tif(d / 'slope.tif', _acceptance_grid())
    code, doc, _err = _run(capsys, tif, d / 'a.json')
    assert code == 0 and doc['disposition'] == 'FIX'
    assert [(h['cells'], h['disposition']) for h in doc['holes']] == [(4, 'fill'), (1, 'fill'), (16, 'hole')]
    assert set(doc['holes'][2]) == {'cells', 'bbox', 'disposition'} and doc['holes'][2]['bbox'] == [20, 40, 24, 44]
    assert doc['holes'][1]['bbox'] == [10, 30, 11, 31]
    assert [(p['cells'], p['bbox']) for p in doc['pits']] == [(1, [13, 11, 14, 12])]
    assert doc['pits'][0]['ring_median_m'] == -20.0 and doc['pits'][0]['deviation_m'] == -20.0
    assert [(s['cells'], s['bbox'], s['deviation_m']) for s in doc['spikes']] == [(1, [19, 52, 20, 53], 20.0)]
    assert doc['clusters_deep'] == [] and doc['sentinel_cells'] == 0 and doc['nodata'] == -9999.0
    assert doc['counts'] == {'measured': 64 * 64 - 21 - 2, 'measured-suspect-shoal': 1, 'filled-hole': 5,
                             'filled-pit': 1, 'unresolved-hole': 16, 'unresolved-ring-range': 0, 'masked-sentinel': 0,
                             'nodata': 0}
    assert doc['fixture'] == {'refused': False, 'reasons': []} and doc['sign']['refused'] is False
    assert doc['duplicate_signature'][:4] == [64, 64, 'EPSG:32610', 2.0] and doc['file_name'] == 'slope.tif'
    assert str(d) not in Path(d / 'a.json').read_text()
    code, _again, _err = _run(capsys, tif, d / 'fresh' / 'b.json', '--strip-rows', '7')
    assert code == 0 and (d / 'a.json').read_bytes() == (d / 'fresh' / 'b.json').read_bytes()


def test_ring_range_edge_land_and_sentinel_holes(d, capsys):
    v = _slope()
    v[30:34, 4:8] = -14.0
    v[30, 4], v[33, 7] = -10.0, -18.0  # ring spans -10..-18: range 8 m > max(2, 0.1 * 10) = 2 m
    v[31:33, 5:7] = np.nan
    v[0, 30] = np.nan  # touches the raster edge
    v[50, 50], v[50, 51] = np.nan, 0.0  # a 0 m neighbour
    v[45, 45], v[45, 46] = 9999.0, np.nan  # sentinel joins a NaN cell into one 2-cell hole
    code, doc, _err = _run(capsys, _tif(d / 'nan.tif', v, nodata=np.nan), d / 'r.json')
    assert code == 0 and doc['nodata'] is None and doc['sentinel_cells'] == 1
    assert [(h['cells'], h['bbox'], h['disposition']) for h in doc['holes']] == [
        (4, [5, 31, 7, 33], 'ring-range'), (2, [45, 45, 47, 46], 'fill')]
    assert doc['holes'][0]['ring_shallowest_m'] == -10.0 and doc['holes'][0]['ring_range_m'] == 8.0
    assert doc['counts']['unresolved-ring-range'] == 4 and doc['counts']['filled-hole'] == 2
    assert doc['counts']['masked-sentinel'] == 0 and doc['counts']['nodata'] == 2
    assert sum(doc['counts'].values()) == 64 * 64 and doc['disposition'] == 'FIX'
    v2 = _slope()
    v2[5, 5] = 9999.0  # a lone sentinel next to water: still a hole, under the declared nodata -9999
    _code, doc2, _err = _run(capsys, _tif(d / 'sent.tif', v2), d / 's.json')
    assert doc2['sentinel_cells'] == 1 and doc2['holes'][0]['cells'] == 1 and doc2['counts']['filled-hole'] == 1
    v3 = _slope()
    v3[40:43, 40:43] = -5.0  # a 3x3 shoal patch: 9 spike cells, nothing to fix -> VERIFY
    _code, doc3, _err = _run(capsys, _tif(d / 'shoal.tif', v3), d / 'v.json')
    assert doc3['disposition'] == 'VERIFY' and doc3['counts']['measured-suspect-shoal'] >= 1 and doc3['holes'] == []
    _code, doc4, _err = _run(capsys, _tif(d / 'clean.tif', _slope()), d / 'p.json')
    assert doc4['disposition'] == 'PASS' and doc4['counts']['measured'] == 64 * 64


def test_all_positive_and_fixture_grids_are_refused(d, tmp_path, capsys):
    code, doc, _err = _run(capsys, _tif(d / 'land.tif', -_slope()), d / 'land.json')
    assert code == 0 and doc['disposition'] == 'REFUSED' and doc['sign']['reason'] == 'all-positive'
    assert doc['sign']['positive_fraction'] == 1.0 and doc['holes'] == [] and doc['counts'] == {}
    (fixture_dir := tmp_path / 'pytest-basetemp-0').mkdir()
    code, doc, _err = _run(capsys, _tif(fixture_dir / 'slope.tif', _acceptance_grid()), d / 'fx.json')
    assert code == 0 and doc['disposition'] == 'REFUSED' and doc['fixture'] == {'refused': True, 'reasons': ['path']}
    assert doc['holes'] == doc['pits'] == doc['spikes'] == [] and doc['sign']['positive_fraction'] is None
    flat = np.full((64, 64), -20.0)
    flat[0, 0] = -9999.0
    _code, doc, _err = _run(capsys, _tif(d / 'flat.tif', flat), d / 'flat.json')
    assert doc['fixture']['reasons'] == ['distinct', 'range'] and doc['disposition'] == 'REFUSED'
    _code, doc, _err = _run(capsys, _tif(d / 'tiny.tif', _slope()[:32]), d / 'tiny.json')
    assert doc['fixture']['reasons'] == ['pixels']


@pytest.mark.parametrize('case, field', [
    ('adapter', 'adapter: bag is wave 2'), ('bands', 'bands:'), ('receipt', 'receipt:'), ('pixels', 'pixels:'),
    ('source', 'source_id: required'), ('driver', 'driver:'), ('crs', 'crs:'), ('strip', 'strip_rows:')])
def test_refusals_name_the_field_before_any_stats(d, capsys, monkeypatch, case, field):
    monkeypatch.setattr(det, 'scan', lambda *a: pytest.fail('stats computed before the refusal'))
    tif, extra, receipt, source = _tif(d / 'g.tif', _slope()), [], d / 'out.json', 'usgs-test'
    if case == 'adapter':
        extra = ['--adapter', 'bag']
    elif case == 'bands':
        tif = _tif(d / 'two.tif', np.stack([_slope(), _slope()]))
    elif case == 'receipt':
        receipt.write_text('{}')
    elif case == 'pixels':
        extra = ['--max-pixels', '1000']
    elif case == 'strip':
        extra = ['--strip-rows', '0']
    elif case == 'source':
        source = ' '  # blank counts as missing
    elif case == 'driver':
        tif = _tif(d / 'g.bil', _slope(), driver='ENVI')
    else:
        tif = _tif(d / 'geo.tif', _slope(), x0=-121.0, y0=35.5, cell=0.0001, crs='EPSG:4326')
    code, _doc, err = _run(capsys, tif, receipt, *extra, source=source)
    assert code == 2 and err.startswith(f'detect refused: {field}')
    assert receipt.read_text() == '{}' if case == 'receipt' else not receipt.exists()
