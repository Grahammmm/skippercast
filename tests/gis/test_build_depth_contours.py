"""scripts/build_depth_contours.py on tiny synthetic GeoTIFFs; nothing is written outside tmp_path."""
import importlib.util
import sys

import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis


def _load_builder():
    spec = importlib.util.spec_from_file_location('build_depth_contours', ROOT / 'scripts/build_depth_contours.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tif(path, values, x0, y0, cell=2.0, crs='EPSG:32610', dtype='float32', nodata=-9999.0):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[1], height=values.shape[0], count=1, dtype=dtype,
                       crs=crs, transform=from_origin(x0, y0, cell, cell), nodata=nodata) as ds:
        ds.write(np.asarray(values, dtype=dtype), 1)
    return path


def _sources(*ids, native=2):
    return {i: {'id': i, 'review_status': 'approved', 'needs': ['bathymetry'], 'name': f'Synthetic {i}',
                'documentation_url': 'https://example.invalid/doc', 'rights': {'attribution': 'Synthetic'},
                'survey_year': 2008, 'vertical_datum': None, 'native_resolution_m': native,
                'reviewed_at': '2026-10-01'} for i in ids}


def _run_builder(monkeypatch, grids, sources):
    pytest.importorskip('rasterio')
    bs = _load_builder()
    region = {'id': 'synthetic-bay', 'bounds': [-121.5, 35.0, -120.0, 36.0],
              'source_bindings': {'bathymetry': list(sources)}}
    captured = {}
    monkeypatch.setattr(bs, 'load_region', lambda ident: region)
    monkeypatch.setattr(bs, 'load_catalogs', lambda: (None, sources))
    monkeypatch.setattr(bs, 'atomic_json', lambda path, value: captured.setdefault('doc', value) and {'sha256': '0' * 64, 'bytes': 1})
    argv = ['build_depth_contours.py', '--region', 'synthetic-bay']
    for ident, path in grids.items():
        argv += ['--grid', f'{ident}={path}']
    monkeypatch.setattr(sys, 'argv', argv)
    bs.main()
    return captured['doc']


def _slope(shape, shallow=-10.0, deep=-60.0):
    import numpy as np
    h, w = shape
    return np.tile(np.linspace(shallow, deep, w), (h, 1))


X0, Y0 = 690_000.0, 3_915_000.0


def test_guard_feet_levels_and_lonlat(tmp_path, monkeypatch):
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    doc = _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a'))
    depths = sorted(f['properties']['depth_ft'] for f in doc['features'] if f['properties']['kind'] == 'contour')
    assert depths and all(d % 30 == 0 and 30 <= d <= 196 for d in depths)
    lon, lat = doc['features'][0]['geometry']['coordinates'][0][0]
    assert -121.5 < lon < -120.0 and 35.0 < lat < 36.0 and doc['provenance']['units'] == 'ft'


def test_grid_contributing_no_water_block_is_refused(tmp_path, monkeypatch):
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    b = _tif(tmp_path / 'b.tif', -_slope((64, 64)), X0 + 128, Y0)          # positive-down: no water by this method
    with pytest.raises(SystemExit, match=r"no valid water block: \['usgs-b'\]"):
        _run_builder(monkeypatch, {'usgs-a': a, 'usgs-b': b}, _sources('usgs-a', 'usgs-b'))


def test_same_file_under_two_sources_is_refused(tmp_path, monkeypatch):
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    with pytest.raises(SystemExit, match='same file'):
        _run_builder(monkeypatch, {'usgs-a': a, 'usgs-b': a}, _sources('usgs-a', 'usgs-b'))


@pytest.mark.parametrize('cell,native', [(4.0, 2), (2.0, None)])
def test_grid_cell_must_match_reviewed_native_resolution(tmp_path, monkeypatch, cell, native):
    a = _tif(tmp_path / 'a.tif', _slope((32, 32)), X0, Y0, cell=cell)
    with pytest.raises(SystemExit, match='differs from reviewed native_resolution_m'):
        _run_builder(monkeypatch, {'usgs-a': a}, _sources('usgs-a', native=native))


def test_omitted_binding_is_recorded_and_an_unapproved_grid_is_refused_before_any_read(tmp_path, monkeypatch):
    import hashlib
    import numpy as np
    import rasterio
    sources = _sources('usgs-a', 'noaa-x')
    sources['noaa-x']['review_status'] = 'candidate'
    a = _tif(tmp_path / 'a.tif', _slope((64, 64)), X0, Y0)
    doc = _run_builder(monkeypatch, {'usgs-a': a}, sources)
    assert doc['provenance']['sources_omitted'] == [{'source_id': 'noaa-x', 'review_status': 'candidate'}]
    x = _tif(tmp_path / 'x.tif', np.full((8, 8), -20.0), X0, Y0)
    # The builder's sha256 is hashlib.file_digest; both spies are on the modules the builder imports.
    calls = []
    monkeypatch.setattr(rasterio, 'open', lambda *a, **k: calls.append(('open', a)))
    monkeypatch.setattr(hashlib, 'file_digest', lambda *a, **k: calls.append(('sha256', a)))
    with pytest.raises(SystemExit, match='not an approved bathymetry source'):
        _run_builder(monkeypatch, {'usgs-a': a, 'noaa-x': x}, sources)
    assert calls == []
