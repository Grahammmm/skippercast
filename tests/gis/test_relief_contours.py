"""Offline checks for the contour producer's normalised-input boundary."""
import hashlib
import importlib.util
import json
import sys

import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis
SOURCE = 'usgs-point-estero'


@pytest.fixture
def builder(monkeypatch):
    pytest.importorskip('rasterio')
    spec = importlib.util.spec_from_file_location('build_depth_contours', ROOT / 'scripts/build_depth_contours.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = {'name': 'Synthetic CSUMB survey', 'review_status': 'approved', 'needs': ['bathymetry'],
              'documentation_url': 'https://example.org/survey', 'survey_year': 2008,
              'native_resolution_m': 2, 'vertical_datum': 'MLLW',
              'rights': {'public_display': 'allowed', 'attribution': 'USGS; CSUMB',
                         'owner_public_display': {'decision': 'allowed',
                                                  'basis': 'G decision 2026-11-18 (owner-accepted risk; revisit when paid)'}}}
    region = {'id': 'morro-bay', 'bounds': [-122, 34, -120, 36], 'source_bindings': {'bathymetry': [SOURCE]}}
    monkeypatch.setattr(module, 'load_catalogs', lambda: ({}, {SOURCE: source}))
    monkeypatch.setattr(module, 'load_region', lambda _: region)

    def run(grid, out, *, sidecar=None):
        argv = ['build_depth_contours.py', '--region', region['id'], '--set', 'v2',
                '--grid', f'{SOURCE}={grid}', '--output', str(out)]
        if sidecar is not None:
            argv.extend(('--normalized-sidecar', f'{SOURCE}={sidecar}'))
        monkeypatch.setattr(sys, 'argv', argv)
        module.main()
        return json.loads(out.read_bytes())

    return run, source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_grid(path, values, crs, transform):
    import rasterio

    with rasterio.open(path, 'w', driver='GTiff', count=1, dtype='float32', nodata=-9999,
                       height=values.shape[0], width=values.shape[1], crs=crs, transform=transform) as ds:
        ds.write(values, 1)
    return path


@pytest.fixture
def geographic_twin(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import reproject

    crs, transform = 'EPSG:32610', from_origin(690000, 3915000, 2, 2)
    values = np.tile(np.linspace(-1, -120, 100, dtype='float32'), (80, 1))
    projected = write_grid(tmp_path / 'projected.tif', values, crs, transform)
    with rasterio.open(projected) as ds:
        geographic, geo_transform = reproject(ds.read(1), src_transform=ds.transform, src_crs=crs,
                                               src_nodata=-9999, dst_crs='EPSG:4326', dst_nodata=-9999,
                                               dst_resolution=0.000004)
    raw = write_grid(tmp_path / 'original-geographic.tif', geographic[0], 'EPSG:4326', geo_transform)
    twin, _ = reproject(geographic[0], destination=np.empty_like(values), src_transform=geo_transform,
                        src_crs='EPSG:4326', src_nodata=-9999, dst_crs=crs, dst_transform=transform,
                        dst_nodata=-9999)
    normalized = write_grid(tmp_path / 'grid.tif', twin, crs, transform)
    sidecar = tmp_path / 'sidecar.json'
    sidecar.write_text(json.dumps({'schema': 'sc-relief-normalized/1', 'original_sha256': digest(raw),
                                   'original_path': str(raw), 'outputs': {'grid.tif': digest(normalized)},
                                   'units': 'm', 'value_convention': 'elevation_positive_up', 'vertical_datum': 'MLLW',
                                   'crs': crs, 'shape': list(values.shape), 'transform': list(transform)[:6],
                                   'resolution_m': 2}))
    return projected, raw, normalized, sidecar


def test_normalized_twin_retains_original_identity_and_shelf_lines(builder, geographic_twin, tmp_path):
    # A derivative may not replace the original digest, leak its path or move lines in this planar control.
    from pyproj import Transformer
    from shapely import transform
    from shapely.geometry import shape

    run, _ = builder
    projected, raw, normalized, sidecar = geographic_twin
    expected = run(projected, tmp_path / 'control.geojson')
    output = tmp_path / 'twin.geojson'
    actual = run(normalized, output, sidecar=sidecar)
    assert actual['provenance']['sources'][0]['sha256'] == digest(raw)
    assert str(tmp_path) not in output.read_text()
    assert actual['provenance']['set'] == 'ft-v2'
    xy = Transformer.from_crs('EPSG:4326', 'EPSG:32610', always_xy=True).transform

    def lines(doc):
        return {f['id']: transform(shape(f['geometry']), xy, interleaved=False)
                for f in doc['features'] if f['properties']['kind'] == 'contour'}

    ref, got = lines(expected), lines(actual)
    assert ref and ref.keys() == got.keys()
    assert max(geom.hausdorff_distance(got[ident]) for ident, geom in ref.items()) <= 0.5
    contours = [f['properties'] for f in actual['features'] if f['properties']['kind'] == 'contour']
    assert max(p['depth_ft'] for p in contours) == 300
    assert all(p['source_id'] == SOURCE and p['estimated'] is True and 'name' not in p for p in contours)


@pytest.mark.parametrize('failure', ['registry-excluded', 'different-normalized-bytes'])
def test_derivative_fails_closed(builder, geographic_twin, tmp_path, failure):
    # Neither an owner-basis declaration nor a correct-looking sidecar may override an explicit denial or pin.
    run, source = builder
    _, _, grid, sidecar = geographic_twin
    if failure == 'registry-excluded':
        source['rights']['public_display'] = 'excluded'
        grid = tmp_path / 'must-not-open.tif'
        reason = 'not cleared for public display'
    else:
        doc = json.loads(sidecar.read_bytes())
        doc['outputs']['grid.tif'] = 'b' * 64
        sidecar.write_text(json.dumps(doc))
        reason = 'normalised grid hash mismatch'
    out = tmp_path / 'refused.geojson'
    with pytest.raises(SystemExit, match=reason):
        run(grid, out, sidecar=sidecar)
    assert not out.exists()
