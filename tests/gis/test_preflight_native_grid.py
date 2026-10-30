"""scripts/preflight_native_grid.py on tiny synthetic GeoTIFFs; nothing is written outside tmp_path."""
import hashlib
import importlib.util
import json
import re

import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis
SCRIPT = ROOT / 'scripts/preflight_native_grid.py'
OK = ['--vertical-datum', 'undeclared', '--vertical-unit', 'metre', '--vertical-sign', 'elevation-up']


def _load():
    spec = importlib.util.spec_from_file_location('preflight_native_grid', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tif(path, crs='EPSG:32610', w=8, h=6, cell=2.0):
    np = pytest.importorskip('numpy')
    rasterio = pytest.importorskip('rasterio')
    from rasterio.transform import from_origin
    with rasterio.open(path, 'w', driver='GTiff', width=w, height=h, count=1, dtype='float32', crs=crs,
                       transform=from_origin(690_000.0, 3_915_000.0, cell, cell)) as ds:
        ds.write(np.full((h, w), -10.0, dtype='float32'), 1)
    return str(path)


@pytest.mark.parametrize('window', ['nan,0,4,4', 'inf,0,4,4', '-1,0,4,4', '0,0,1.5,4'])
def test_bad_windows_refused(tmp_path, capsys, window):
    assert _load().main([_tif(tmp_path / 'a.tif'), *OK, f'--window={window}']) == 2
    assert 'preflight refused: window:' in capsys.readouterr().err


def test_geographic_crs_and_empty_sign_refused(tmp_path, capsys):
    mod = _load()
    assert mod.main([_tif(tmp_path / 'g.tif', crs='EPSG:4326'), *OK]) == 2
    assert 'preflight refused: crs:' in capsys.readouterr().err
    assert mod.main([_tif(tmp_path / 'p.tif'), *OK[:4], '--vertical-sign', '']) == 2
    assert 'preflight refused: vertical_sign:' in capsys.readouterr().err


def test_valid_grid_prints_identity_and_pixel_cap_refuses(tmp_path, capsys):
    mod = _load()
    path = _tif(tmp_path / 'a.tif')
    assert mod.main([path, *OK]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc['sha256'] == hashlib.sha256((tmp_path / 'a.tif').read_bytes()).hexdigest()
    assert doc['vertical_datum'] == 'undeclared' and doc['window'] == [0, 0, 8, 6] and doc['cell_m'] == 2.0
    meta = mod.raster_meta(path)
    meta.update(width=6000, height=5000)
    with pytest.raises(mod.Refused) as err:
        mod.check_grid(meta, window=['0', '0', '6000', '5000'], vertical_datum='undeclared', vertical_unit='metre',
                       vertical_sign='elevation-up', max_pixels=25_000_000, strip_rows=512)
    assert err.value.field == 'pixels'


def test_script_does_not_import_seafloor():
    imports = [ln for ln in SCRIPT.read_text().splitlines() if re.match(r'\s*(import|from)\s', ln)]
    assert imports and not any('skippercast' in ln for ln in imports)
