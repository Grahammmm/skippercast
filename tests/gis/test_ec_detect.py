"""EC1 ec_detect: the known error classes in one native grid, on tiny GeoTIFFs written into tmp_path."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

import numpy as np
import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis
_spec = importlib.util.spec_from_file_location('ec_detect', ROOT / 'scripts' / 'ec_detect.py')
det = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(det)
SLOPE = np.tile(-10.0 - 50.0 * np.arange(64) / 63.0, (64, 1))  # -10 m at column 0 to -60 m at column 63


def _tif(path, values, x0=7e5, y0=3.9e6, cell=2.0, crs='EPSG:32610', dtype='float32', nodata=-9999.0, driver='GTiff',
         mask=None, internal_mask=True):
    import rasterio
    from rasterio.transform import from_origin
    values = np.asarray(values, dtype=dtype)
    values = values[None] if values.ndim == 2 else values
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=internal_mask), rasterio.open(
            path, 'w', driver=driver, width=values.shape[2], height=values.shape[1], count=values.shape[0],
            dtype=dtype, crs=crs, transform=from_origin(x0, y0, cell, cell), nodata=nodata) as ds:
        ds.write(values)
        if mask is not None:  # GDAL's own per-dataset validity mask (internal unless internal_mask=False: .msk)
            ds.write_mask(mask)
    return path


@pytest.fixture
def d(tmp_path):
    """Non-fixture grids: tmp_path/grids, or a /var/tmp directory when the base temp carries FIXTURE_PATH tokens."""
    with tempfile.TemporaryDirectory(prefix='ec-detect-', dir='/var/tmp') as spare:
        clean = not det.ec.FIXTURE_PATH.search(str((tmp_path / 'grids').resolve()))
        path = tmp_path / 'grids' if clean else Path(spare)
        path.mkdir(exist_ok=True)
        yield path


def _run(capsys, path, receipt, *extra, source='usgs-test'):
    before = Path(path).read_bytes()
    code = det.main([str(path), '--source-id', source, '--receipt', str(receipt), *extra])
    out = capsys.readouterr()
    doc = json.loads(Path(receipt).read_text()) if code == 0 else None
    assert Path(path).read_bytes() == before  # the input is never modified
    if doc is not None:
        assert det.ec.check_receipt('ec-detect-v1', doc) == []
        assert doc['path_sha256'] == hashlib.sha256(before).hexdigest()
        assert json.loads(out.out) == {'disposition': doc['disposition'], 'receipt': str(receipt)}
    return code, doc, out.err


def _acceptance_grid():
    v = SLOPE.copy()
    v[30, 10] = v[20:22, 40:42] = v[40:44, 20:24] = -9999.0  # 1-cell, 2x2 and 4x4 holes; 16 > hole_max_cells(2 m) = 9
    v[10:13, 12:15], v[51:54, 18:21] = -20.0, -25.0
    v[11, 13], v[52, 19] = -40.0, -5.0  # a pit in the -20 m ring, a spike in the -25 m ring
    return v


def test_acceptance_grid_lists_holes_pit_spike_and_is_fix(d, capsys):
    tif = _tif(d / 'slope.tif', _acceptance_grid())
    code, doc, _err = _run(capsys, tif, d / 'a.json')
    assert code == 0 and doc['disposition'] == 'FIX' and doc['nodata'] == -9999.0 and doc['clusters_deep'] == []
    assert [(h['cells'], h['bbox'], h['disposition']) for h in doc['holes']] == [
        (4, [40, 20, 42, 22], 'fill'), (1, [10, 30, 11, 31], 'fill'), (16, [20, 40, 24, 44], 'hole')]
    assert set(doc['holes'][2]) == {'cells', 'bbox', 'disposition'} and doc['file_name'] == 'slope.tif'
    assert doc['pits'] == [{'cells': 1, 'bbox': [13, 11, 14, 12], 'ring_median_m': -20.0, 'deviation_m': -20.0}]
    assert doc['spikes'] == [{'cells': 1, 'bbox': [19, 52, 20, 53], 'ring_median_m': -25.0, 'deviation_m': 20.0}]
    assert doc['counts'] == {'measured': 4073, 'measured-suspect-shoal': 1, 'filled-hole': 5, 'filled-pit': 1,
                             'unresolved-hole': 16, 'unresolved-ring-range': 0, 'masked-sentinel': 0, 'nodata': 0}
    assert doc['fixture'] == {'refused': False, 'reasons': []} and not doc['sign']['refused']
    assert doc['duplicate_signature'][:4] == [64, 64, 'EPSG:32610', 2.0] and str(d) not in (d / 'a.json').read_text()
    code, _again, _err = _run(capsys, tif, d / 'fresh' / 'b.json', '--strip-rows', '7')
    assert code == 0 and (d / 'a.json').read_bytes() == (d / 'fresh' / 'b.json').read_bytes()
    hole, same = _acceptance_grid() == -9999.0, ('holes', 'pits', 'spikes', 'sign', 'counts', 'duplicate_signature')
    for name, values, kw in [('inf', np.inf, {'nodata': np.inf}), ('-inf', -np.inf, {'nodata': -np.inf}),
                             ('mask', 50.0, {'mask': np.where(hole, 0, 255).astype(np.uint8)})]:
        # +/-inf nodata -> null; cells invalid only in the internal mask (50 m backing) count nowhere: same findings
        tif = _tif(d / f'{name}.tif', np.where(hole, values, _acceptance_grid()), **kw)
        code, doc_i, _err = _run(capsys, tif, d / f'{name}.json')
        assert code == 0 and doc_i['nodata'] == (-9999.0 if name == 'mask' else None)
        assert {k: doc_i[k] for k in same} == {k: doc[k] for k in same} and doc_i['sentinel_cells'] == 0


def test_ring_range_edge_land_and_sentinel_holes(d, capsys):
    v = SLOPE.copy()
    v[30:34, 4:8] = -14.0
    v[30, 4], v[33, 7] = -10.0, -18.0  # ring spans -10..-18: range 8 m > max(2, 0.1 * 10) = 2 m
    v[31:33, 5:7] = v[0, 30] = np.nan  # the ring-range hole; [0, 30] touches the raster edge
    v[50, 50], v[50, 51] = np.nan, 0.0  # a 0 m neighbour
    v[45, 45], v[45, 46] = 9999.0, np.nan  # sentinel joins a NaN cell into one 2-cell hole
    code, doc, _err = _run(capsys, _tif(d / 'nan.tif', v, nodata=np.nan), d / 'r.json')
    assert code == 0 and doc['nodata'] is None and doc['sentinel_cells'] == 1
    assert [(h['cells'], h['bbox'], h['disposition']) for h in doc['holes']] == [
        (4, [5, 31, 7, 33], 'ring-range'), (2, [45, 45, 47, 46], 'fill')]
    assert doc['holes'][0]['ring_shallowest_m'] == -10.0 and doc['holes'][0]['ring_range_m'] == 8.0
    assert [doc['counts'][k] for k in ('unresolved-ring-range', 'filled-hole', 'masked-sentinel')] == [4, 2, 0]
    assert doc['counts']['nodata'] == 2 and sum(doc['counts'].values()) == 64 * 64 and doc['disposition'] == 'FIX'
    v2 = SLOPE.copy()
    v2[5, 5] = 9999.0  # a lone sentinel next to water: still a hole, under the declared nodata -9999
    _code, doc2, _err = _run(capsys, _tif(d / 'sent.tif', v2), d / 's.json')
    assert doc2['sentinel_cells'] == 1 and doc2['holes'][0]['cells'] == 1 and doc2['counts']['filled-hole'] == 1
    v3, mask = SLOPE.copy(), np.full((64, 64), 255, np.uint8)
    v3[20:24, 20:24], mask[20:24, 20:24] = -30.0, 0  # 16 finite cells invalid only in the internal mask
    _code, doc3, _err = _run(capsys, _tif(d / 'masked.tif', v3, mask=mask), d / 'v.json')
    assert (doc3['disposition'], doc3['counts']['measured'], doc3['counts']['unresolved-hole']) == ('VERIFY', 4080, 16)
    _code, doc4, _err = _run(capsys, _tif(d / 'clean.tif', SLOPE, nodata=None), d / 'p.json')
    assert doc4['disposition'] == 'PASS' and doc4['counts']['measured'] == 64 * 64 and doc4['nodata'] is None


@pytest.mark.parametrize('excluded', [np.nan, -9999.0, 9999.0, 0.0])
@pytest.mark.parametrize('value, kind, deviation', [(-40.0, 'pits', -20.0), (-5.0, 'spikes', 15.0)])
def test_outliers_beside_excluded_cells_use_water_median(d, capsys, excluded, value, kind, deviation):
    v = SLOPE.copy()
    v[10:13, 12:15] = -20.0
    v[10:13, 12] = excluded  # nodata, sentinel or land must not participate in the median
    v[11, 13] = value
    code, doc, _err = _run(capsys, _tif(d / 'edge.tif', v), d / 'edge.json')
    assert code == 0 and doc['spikes' if kind == 'pits' else 'pits'] == []
    assert doc[kind] == [{'cells': 1, 'bbox': [13, 11, 14, 12], 'ring_median_m': -20.0, 'deviation_m': deviation}]


def test_all_positive_and_fixture_grids_are_refused(d, tmp_path, capsys):
    code, doc, _err = _run(capsys, _tif(d / 'land.tif', -SLOPE), d / 'land.json')
    assert code == 0 and doc['disposition'] == 'REFUSED' and doc['sign']['reason'] == 'all-positive'
    assert doc['sign']['positive_fraction'] == 1.0 and doc['holes'] == [] and doc['counts'] == {}
    (fixture_dir := tmp_path / 'pytest-basetemp-0').mkdir()
    code, doc, _err = _run(capsys, _tif(fixture_dir / 'slope.tif', _acceptance_grid()), d / 'fx.json')
    assert code == 0 and doc['disposition'] == 'REFUSED' and doc['fixture'] == {'refused': True, 'reasons': ['path']}
    assert doc['holes'] == doc['pits'] == doc['spikes'] == [] and doc['sign']['positive_fraction'] is None
    flat = np.where(SLOPE < -59.9, -9999.0, -20.0)  # one finite value plus a nodata column
    _code, doc, _err = _run(capsys, _tif(d / 'flat.tif', flat), d / 'flat.json')
    assert doc['fixture']['reasons'] == ['distinct', 'range'] and doc['disposition'] == 'REFUSED'
    _code, doc, _err = _run(capsys, _tif(d / 'tiny.tif', SLOPE[:32]), d / 'tiny.json')
    assert doc['fixture']['reasons'] == ['pixels']


@pytest.mark.parametrize('case, field', [
    ('adapter', 'adapter: bag is wave 2'), ('bands', 'bands:'), ('receipt', 'receipt:'), ('pixels', 'pixels:'),
    ('source', 'source_id: required'), ('driver', 'driver:'), ('crs', 'crs:'), ('strip', 'strip_rows:'),
    ('sidecar', 'sidecar: g.tif.msk not covered by path_sha256')])
def test_refusals_name_the_field_before_any_stats(d, capsys, monkeypatch, case, field):
    monkeypatch.setattr(det, 'scan', lambda *a: pytest.fail('stats computed before the refusal'))
    s, receipt = SLOPE, d / 'out.json'
    tif = {'bands': lambda: _tif(d / 'two.tif', [s, s]), 'driver': lambda: _tif(d / 'g.bil', s, driver='ENVI'),
           'crs': lambda: _tif(d / 'geo.tif', s, x0=-121.0, y0=35.5, cell=0.0001, crs='EPSG:4326'),
           'sidecar': lambda: _tif(d / 'g.tif', s, mask=np.full(s.shape, 255, np.uint8), internal_mask=False),
           }.get(case, lambda: _tif(d / 'g.tif', s))()
    extra = {'adapter': ['--adapter', 'bag'], 'pixels': ['--max-pixels', '1000'], 'strip': ['--strip-rows', '0']}
    if case == 'receipt':
        receipt.write_text('{}')
    code, _doc, err = _run(capsys, tif, receipt, *extra.get(case, []), source=' ' if case == 'source' else 'usgs-test')
    assert code == 2 and err.startswith(f'detect refused: {field}')
    assert receipt.read_text() == '{}' if case == 'receipt' else not receipt.exists()
