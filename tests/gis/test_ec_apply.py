"""scripts/ec_apply.py on synthetic GeoTIFFs with hand-written ec-detect-v1 receipts; writes only under tmp_path."""
import hashlib
import importlib.util
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from skippercast.platform import seafloor_ec as ec
from tests._support import ROOT

pytestmark = pytest.mark.gis
H1, PIT = (5, 5), (22, 20)  # (row, col); the 2x2 hole is rows/cols 12-13. Receipt bboxes are [col0, row0, col1, row1].


def _load():
    spec = importlib.util.spec_from_file_location('ec_apply', ROOT / 'scripts/ec_apply.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tif(path, values, nodata=-9999.0):
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[1], height=values.shape[0], count=1,
                       dtype='float32', crs='EPSG:32610', transform=from_origin(700000, 3900000, 2, 2),
                       nodata=nodata) as ds:
        ds.write(values.astype('float32'), 1)
    return path


def _grid(ring1=np.linspace(-20.0, -21.5, 8)):
    z = -10.0 - np.add.outer(np.arange(32.0), np.arange(32.0)) * 0.25
    z[4:7, 4:7] = np.insert(ring1, 4, -9999.0).reshape(3, 3)
    z[11:15, 11:15] = np.where(np.indices((4, 4)).sum(0) % 2, -31.0, -30.0)
    z[12:14, 12:14] = -9999.0
    z[21:24, 19:22], z[PIT] = -25.0, -45.0
    return z


def _detect(grid, tmp_path, holes=None, pits=None, **over):
    holes = holes if holes is not None else [
        {'cells': 1, 'bbox': [5, 5, 5, 5], 'ring_shallowest_m': -20.0, 'ring_range_m': 1.5, 'disposition': 'fill'},
        {'cells': 4, 'bbox': [12, 12, 13, 13], 'ring_shallowest_m': -30.0, 'ring_range_m': 1.0, 'disposition': 'fill'}]
    pits = pits if pits is not None else [{'cells': 1, 'bbox': [20, 22, 20, 22], 'ring_median_m': -25.0,
                                           'deviation_m': -20.0}]
    doc = {'schema': 'ec-detect-v1', 'ec_version': ec.EC_VERSION, 'source_id': 'synthetic-x', 'cell_m': 2.0,
           'path_sha256': hashlib.sha256(grid.read_bytes()).hexdigest(), 'crs': 'EPSG:32610', 'width': 32,
           'height': 32, 'nodata': -9999.0, 'counts': {}, 'pits': pits, 'spikes': [], 'holes': holes,
           'sentinel_cells': 0, 'fixture': {'refused': False, 'reasons': []}, 'sign': {'refused': False},
           'duplicate_signature': [32, 32, 'EPSG:32610', 2.0, -25.5, -10.0, -17.75], 'disposition': 'FIX', **over}
    path = tmp_path / 'EC-DETECT.json'
    path.write_text(json.dumps(doc))
    return path


def _run(grid, detect, out):
    return _load().main([str(grid), '--detect', str(detect), '--out-dir', str(out)])


def _read(path):
    with rasterio.open(path) as ds:
        return ds.read(1), ds.profile, ds.tags()


def test_fills_with_the_ring_shallowest_and_reruns_byte_identical(tmp_path):
    z = _grid()
    grid = _tif(tmp_path / 'grid.tif', z)
    detect = _detect(grid, tmp_path)
    assert _run(grid, detect, tmp_path / 'a') == 0 and _run(grid, detect, tmp_path / 'b') == 0
    for name in ('corrected.tif', 'provenance.tif', 'EC-APPLY.json'):
        assert (tmp_path / 'a' / name).read_bytes() == (tmp_path / 'b' / name).read_bytes(), name
    out, prof, _ = _read(tmp_path / 'a/corrected.tif')
    codes, pprof, tags = _read(tmp_path / 'a/provenance.tif')
    assert (out[H1], out[PIT]) == (-20.0, -25.0) and (out[12:14, 12:14] == -30.0).all()
    assert (codes[H1], codes[PIT]) == (20, 21) and (codes[12:14, 12:14] == 20).all()
    treated = codes != 10
    assert treated.sum() == 6 and np.array_equal(out[~treated], z.astype('float32')[~treated])
    with rasterio.open(grid) as src:
        assert (prof['crs'], prof['transform'], prof['nodata'], prof['dtype']) == (src.crs, src.transform, -9999.0, 'float32')
    assert (prof['compress'], pprof['dtype'], pprof['nodata']) == ('deflate', 'uint8', 255)
    assert tags['EC_VERSION'] == ec.EC_VERSION and json.loads(tags['SKIPPERCAST_EC_CODES']) == dict(ec.CODES)
    receipt = json.loads((tmp_path / 'a/EC-APPLY.json').read_text())
    assert ec.check_receipt('ec-apply-v1', receipt) == [] and receipt['disposition'] == 'FIX'
    assert {k: v for k, v in receipt['counts'].items() if v} == {'measured': 1018, 'filled-hole': 5, 'filled-pit': 1}
    assert [(f['kind'], f['cells'], f['before_min_m'], f['after_m']) for f in receipt['fixes']] == [
        ('hole', 1, -21.5, -20.0), ('hole', 4, -31.0, -30.0), ('pit', 1, -25.0, -25.0)]
    assert receipt['detect_sha256'] == hashlib.sha256(detect.read_bytes()).hexdigest()
    assert receipt['corrected_sha256'] == hashlib.sha256((tmp_path / 'a/corrected.tif').read_bytes()).hexdigest()


def _hole1(**over):
    return dict({'cells': 1, 'bbox': [5, 5, 5, 5], 'ring_shallowest_m': -20.0, 'ring_range_m': 1.5,
                 'disposition': 'fill'}, **over)


@pytest.mark.parametrize('case, message', [
    ('tampered-ring', 'ring mismatch'), ('refused', 'source refused by detect'), ('wrong-sha', 'detect_sha256'),
    ('ec-version', 'ec_version'), ('duplicate', 'duplicate hole'), ('wrong-cells', 'hole mismatch'),
    ('swapped-bbox', 'pit mismatch'), ('existing-output', 'already holds outputs'), ('in-repo', 'outside the work tree'),
    ('not-json', 'unreadable')])
def test_refusals_write_nothing(tmp_path, capsys, case, message):
    z = _grid(np.linspace(-10.0, -18.0, 8)) if case == 'tampered-ring' else _grid()
    grid = _tif(tmp_path / 'grid.tif', z)
    holes = {'tampered-ring': [_hole1(ring_shallowest_m=-14.0, ring_range_m=4.0)], 'duplicate': [_hole1(), _hole1()],
             'wrong-cells': [_hole1(cells=2)]}.get(case, [])
    pits = [{'cells': 1, 'bbox': [22, 20, 22, 20], 'ring_median_m': -25.0, 'deviation_m': -20.0}] if case == 'swapped-bbox' else []
    over = {'refused': {'disposition': 'REFUSED'}, 'wrong-sha': {'path_sha256': '0' * 64},
            'ec-version': {'ec_version': '0.9'}}.get(case, {})
    detect = _detect(grid, tmp_path, holes, pits, **over)
    out = ROOT / 'var/ec-apply-test-out' if case == 'in-repo' else tmp_path / 'out'
    if case == 'refused':
        grid = tmp_path / 'missing.tif'  # refused before any read of the grid
    if case == 'existing-output':
        out.mkdir()
        (out / 'provenance.tif').write_bytes(b'old')
    if case == 'not-json':
        detect.write_text('{')
    assert _run(grid, detect, out) == 2
    assert message in capsys.readouterr().err
    assert not out.exists() or [p.name for p in out.iterdir()] == (['provenance.tif'] if case == 'existing-output' else [])


@pytest.mark.parametrize('target, value', [((4, 5), -22.0), (PIT, -50.0)])
def test_deepening_gate_exits_3_and_leaves_the_folder_empty(tmp_path, capsys, monkeypatch, target, value):
    mod = _load()
    original = mod._fill

    def bad_fill(after, window, comp, fill):
        original(after, window, comp, fill)
        after[target] = value  # -22 into the -20 ring (untreated), or the -45 pit made deeper (treated)
    monkeypatch.setattr(mod, '_fill', bad_fill)
    grid = _tif(tmp_path / 'grid.tif', _grid())
    out = tmp_path / 'out'
    assert mod.main([str(grid), '--detect', str(_detect(grid, tmp_path)), '--out-dir', str(out)]) == 3
    assert 'apply refused: deepened 1 cells' in capsys.readouterr().err
    assert not out.exists() or list(out.iterdir()) == []


def test_sentinels_become_nodata_and_join_a_hole_only_when_the_receipt_says_so(tmp_path):
    z = _grid()
    z[H1], z[28, 3], z[28, 4] = 9999.0, 9999.0, np.nan
    grid = _tif(tmp_path / 'grid.tif', z)
    assert _run(grid, _detect(grid, tmp_path, [_hole1()], []), tmp_path / 'out') == 0
    out, _, _ = _read(tmp_path / 'out/corrected.tif')
    codes, _, _ = _read(tmp_path / 'out/provenance.tif')
    assert (out[H1], codes[H1]) == (-20.0, 20) and (out[28, 3], codes[28, 3]) == (-9999.0, 50)
    assert np.isnan(out[28, 4]) and codes[28, 4] == 0 and (codes[12:14, 12:14] == 0).all()
    unchanged = codes == 10
    assert np.array_equal(out[unchanged], z.astype('float32')[unchanged])
    receipt = json.loads((tmp_path / 'out/EC-APPLY.json').read_text())
    assert ec.check_receipt('ec-apply-v1', receipt) == []
    assert receipt['counts']['masked-sentinel'] == 1 and receipt['counts']['nodata'] == 5
