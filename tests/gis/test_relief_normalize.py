"""R2 output is directly consumable, but only admitted evidence can certify a cell."""
import json
from pathlib import Path
import sys
from types import ModuleType

import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from research.scripts.coast_mvp.coast_mosaic import load_sources
from scripts.build_bathy_tiles import load_native_manifest
from scripts.relief.region import main as region_main
from skippercast.relief import normalize as norm, receipts
from tests.gis.test_coastal_vr_refinements import make_vr_bag


pytestmark = pytest.mark.gis


def tif(path, values, transform, crs, *, hole=None, nodata=None, external_mask=False, **tags):
    bands = values if values.ndim == 3 else values[np.newaxis]
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=not external_mask):
        with rasterio.open(path, 'w', driver='GTiff', width=bands.shape[2], height=bands.shape[1],
                           count=len(bands), dtype=bands.dtype, transform=transform, crs=crs, nodata=nodata) as dst:
            dst.write(bands)
            dst.update_tags(**tags)
            if hole:
                mask = np.full(bands.shape[1:], 255, dtype='uint8')
                mask[hole] = 0
                dst.write_mask(mask)
    return path


def result_files(result):
    assert result.state in {'ok', 'done'}, result.line()
    doc = receipts.read_receipt(result.receipt)
    assert doc is not None
    target = Path(doc['target'])
    pin = {Path(row['path']).name: row['sha256'] for row in doc['outputs']}
    assert set(pin) == {'grid.tif', 'support.tif', 'sidecar.json'}
    assert all(receipts.sha256_file(target / name) == sha for name, sha in pin.items())
    return target, json.loads((target / 'sidecar.json').read_text())


def values(path):
    with rasterio.open(path) as ds:
        return ds.read(1, masked=True)


def consumers(tmp_path, target, sidecar, *, native=True):
    row = dict(id='fixture', path=str(target / 'grid.tif'), sha256=sidecar['outputs']['grid.tif'],
               resolution_m=sidecar['resolution_m'], units=sidecar['units'],
               vertical_datum=sidecar['vertical_datum'], vertical_offset_m=0,
               value_convention=sidecar['value_convention'], citation='synthetic', rights='synthetic',
               attribution='synthetic', offset_note='no datum conversion')
    sources = tmp_path / 'sources.json'
    sources.write_text(json.dumps(dict(schema_version=1, sources=[row])))
    assert load_sources(sources)[0]['sha256'] == row['sha256']
    native_manifest = tmp_path / 'native.json'
    native_manifest.write_text(json.dumps([row]))
    if native:
        assert load_native_manifest(native_manifest)[0]['resolution_m'] == row['resolution_m']
    else:
        with pytest.raises(ValueError, match='<=2 m or 5 m'):
            load_native_manifest(native_manifest)


@pytest.mark.parametrize('family,crs,cell,bands', [
    ('ncmp_topobathy_2009', 'EPSG:5498', 0.000009, 1),
    ('nbs_bluetopo', 'EPSG:26910', 2, 3),
    ('nbs_bluetopo', 'EPSG:26910', 4, 3),  # actual 4 m BlueTopo is mosaic-only
])
def test_consumer_admission_and_holes(tmp_path, family, crs, cell, bands):
    data = np.full((32, 32), -10, dtype='float32')
    data[18:21, 18:21] = -9999
    if bands == 3:
        data = np.stack([data, np.full_like(data, 8), np.full_like(data, 12)])
    origin = (-121, 35.5) if bands == 1 else (685000, 3930000)
    hole = np.s_[4:10, 7:13]
    src = tif(tmp_path / 'source.tif', data, from_origin(*origin, cell, cell), crs,
              hole=hole, nodata=-9999)
    target, sidecar = result_files(norm.normalize(src, tmp_path / 'cache', family=family))
    assert sidecar['original_sha256'] == receipts.sha256_file(src)
    assert sidecar['vertical_datum'] == ('NAVD88' if bands == 1 else 'unstated')
    assert [(v['band'], v['role']) for v in sidecar['ignored_bands']] == (
        [] if bands == 1 else [(2, 'uncertainty'), (3, 'contributor')])
    with rasterio.open(target / 'grid.tif') as dem, rasterio.open(target / 'support.tif') as support:
        assert dem.tags(ns='IMAGE_STRUCTURE')['LAYOUT'] == 'COG'
        assert dem.dtypes == ('float32',) and support.dtypes == ('uint8',)
        assert dem.crs.to_epsg() == 26910
        assert (dem.crs, dem.transform, dem.shape) == (support.crs, support.transform, support.shape)
        elevation = dem.read(1, masked=True)
        classes = support.read(1)
        for row, col in [(6, 9), (19, 19)]:
            x, y = from_origin(*origin, cell, cell) * (col + 0.5, row + 0.5)
            r, c = dem.index(*[a[0] for a in transform(crs, dem.crs, [x], [y])])
            assert elevation.mask[r, c] and classes[r, c] == 0
        assert np.all(classes[~elevation.mask] == 2)
        assert np.all(elevation.compressed() == -10)
    consumers(tmp_path, target, sidecar, native=cell != 4)


def test_cli_sets_elevation_units_and_reuses_cross_region_cache(tmp_path, capsys):
    src = tif(tmp_path / 'depth.tif', np.full((8, 8), 10, dtype='float32'),
              from_origin(680000, 3930000, 1, 1), 'EPSG:26910', units='ft', positive='down', vertical_datum='MLLW')
    cache, out = tmp_path / 'cache', tmp_path / 'out'
    args = ['normalize', '--source', str(src), '--cache', str(cache), '--out', str(out)]
    assert region_main([*args, '--region', 'first']) == 0
    receipt = receipts.check(receipts.Region(out, 'first'), 'normalize').receipt
    assert receipt and receipt['status'] == 'ok'
    assert receipt['generation'] == receipts.generation(receipt['inputs'], receipt['upstream'],
                                                       receipt['code']['stage_digest'], receipt['params'])
    assert receipt['inputs'][0]['sha256'] == receipts.sha256_file(src)
    target = Path(receipt['target'])
    assert np.allclose(values(target / 'grid.tif').compressed(), -3.048)
    assert json.loads((target / 'sidecar.json').read_text())['vertical_datum'] == 'MLLW'
    original_inode = (target / 'grid.tif').stat().st_ino
    assert region_main([*args, '--region', 'second']) == 0
    assert 'no work' in capsys.readouterr().out
    second = receipts.check(receipts.Region(out, 'second'), 'normalize')
    assert second.done and second.receipt['generation'] == receipt['generation']
    assert (target / 'grid.tif').stat().st_ino == original_inode
    (target / 'support.tif').write_bytes(b'corrupted')
    assert not receipts.check(receipts.Region(out, 'second'), 'normalize').done
    rebuilt = norm.normalize(src, cache)
    assert rebuilt.state == 'ok'
    result_files(rebuilt)


def mock_registry(tmp_path, monkeypatch):
    registry = ModuleType('skippercast.relief.support_adapters')
    code = tmp_path / 'adapter-policy.txt'
    code.write_text('reviewed policy A')
    registry.__file__ = str(code)
    monkeypatch.setitem(sys.modules, registry.__name__, registry)
    registry.ADAPTERS = {'test': norm.SupportAdapter('fixture', evidence_adapter)}
    return registry, code


def evidence_adapter(dataset, grid, evidence):
    assert dataset.shape == grid.elevation.shape
    return np.load(evidence[0], allow_pickle=False)


def test_minimum_bilinear_support_and_cache_revocation(tmp_path, monkeypatch):
    t = from_origin(-121, 35.5, 0.000009, 0.000009)
    src = tif(tmp_path / 'geographic.tif', np.full((40, 40), -12, dtype='float32'),
              t, 'EPSG:4269', hole=np.s_[10:11, 15:16], external_mask=True)
    evidence = tmp_path / 'evidence.npy'
    classes = np.full((40, 40), 2, dtype='uint8')
    classes[7:24, 8:19] = 3
    np.save(evidence, classes)
    corners = [t * p for p in [(24.1, 5.1), (35.9, 5.1), (35.9, 20.9), (24.1, 20.9), (24.1, 5.1)]]
    footprints = tmp_path / 'footprints.json'
    footprints.write_text(json.dumps(dict(type='FeatureCollection', features=[dict(type='Feature',
        properties={'label': 'interpolated'}, geometry=dict(type='Polygon', coordinates=[corners]))])))
    registry, code = mock_registry(tmp_path, monkeypatch)
    cache = tmp_path / 'cache'
    region = receipts.Region(tmp_path / 'out', 'fixture')
    opts = dict(family='test', evidence=[evidence], footprints=footprints, region=region)
    first = norm.normalize(src, cache, **opts)
    target, sidecar = result_files(first)
    assert sidecar['params']['adapter']['id'] == 'fixture'
    with rasterio.open(target / 'support.tif') as ds:
        support = ds.read(1)
        assert set(np.unique(support)) == {0, 1, 2, 3}
        rows, cols = np.indices(ds.shape)
        x, y = ds.transform * (cols + 0.5, rows + 0.5)
        sx, sy = transform(ds.crs, 'EPSG:4269', x.ravel(), y.ravel())
        col, row = ~t * (np.array(sx), np.array(sy))
        # Independently identify the immediately bracketing centers for these
        # targets. A broader downsampling kernel may conservatively shrink more.
        r0, c0 = np.floor(row - 0.5).astype(int), np.floor(col - 0.5).astype(int)
        inside = (r0 >= 7) & (r0 + 1 < 24) & (c0 >= 8) & (c0 + 1 < 19)
        touches_hole = ((r0 == 9) | (r0 == 10)) & ((c0 == 14) | (c0 == 15))
        cert = support.ravel() == 3
        assert np.any(cert) and np.all(inside[cert])
        assert not np.any(cert & touches_hole)
        assert np.any((support.ravel() == 2) & touches_hole)
    assert norm.normalize(src, cache, **opts).state == 'done'
    downgraded, _ = result_files(norm.normalize(src, cache, label='interpolated', **opts))
    assert set(values(downgraded / 'support.tif').compressed()) == {1}
    code.write_text('reviewed policy B')
    changed = norm.normalize(src, cache, **opts)
    _, new_sidecar = result_files(changed)
    assert changed.generation != first.generation
    assert new_sidecar['params']['adapter']['digest'] != sidecar['params']['adapter']['digest']
    classes[:] = 2
    np.save(evidence, classes)
    revoked = norm.normalize(src, cache, **opts)
    after, _ = result_files(revoked)
    assert revoked.state == 'ok' and revoked.generation != changed.generation
    assert set(values(after / 'support.tif').compressed()) == {1, 2}
    assert receipts.check(region, 'normalize').receipt['generation'] == revoked.generation
    evidence.unlink()
    missing = norm.normalize(src, cache, **opts)
    assert missing.state == receipts.check(region, 'normalize').state == 'held'
    # Remove the adapter without removing embedded or external evidence.
    classes[:] = 3
    np.save(evidence, classes)
    registry.ADAPTERS.clear()
    empty, sidecar = result_files(norm.normalize(src, cache, family='test', evidence=[evidence]))
    assert sidecar['params']['adapter'] is None
    assert set(values(empty / 'support.tif').compressed()) == {2}


def test_zone_boundary_falls_back_to_california_albers(tmp_path):
    src = tif(tmp_path / 'seam.tif', np.zeros((16, 16), dtype='float32'),
              from_origin(-120.00005, 35.5, 0.000009, 0.000009), 'EPSG:4269')
    _, sidecar = result_files(norm.normalize(src, tmp_path / 'cache'))
    assert sidecar['crs'] == 'EPSG:3310'


def test_regular_bag_uses_elevation_not_uncertainty(tmp_path):
    from tests.gis.test_regular_bag_native_window import OriginalBagWindowTests

    src = tmp_path / 'regular.bag'
    OriginalBagWindowTests._make_original_bag(src, spacing=2)
    target, sidecar = result_files(norm.normalize(src, tmp_path / 'cache', family='noaa_bag'))
    assert not sidecar['variable_resolution_bag']
    with rasterio.open(src) as ds:
        np.testing.assert_allclose(values(target / 'grid.tif').compressed(), ds.read(1, masked=True).compressed())
    consumers(tmp_path, target, sidecar)


def test_vr_bag_finest_valid_refinement_no_fill_or_overview(tmp_path):
    src = tmp_path / 'variable.bag'
    make_vr_bag(src, supergrids={(0, 0): (4, 4, 2.0, 1.0, 1.0),
                                 (0, 1): (3, 3, 3.0, 1.5, 1.5),
                                 (0, 2): (3, 3, 1.0, 0.5, 0.5)})
    with h5py.File(src, 'r+') as ds:
        records = ds['BAG_root/varres_refinements']
        start = int(ds['BAG_root/varres_metadata'][0, 2]['index'])
        null = records[0, start:start + 9]
        null['depth'] = 1_000_000
        records[0, start:start + 9] = null
    target, sidecar = result_files(norm.normalize(src, tmp_path / 'cache', family='noaa_bag'))
    assert sidecar['variable_resolution_bag'] and sidecar['resolution_m'] == 2
    with rasterio.open(target / 'grid.tif') as ds:
        data = ds.read(1, masked=True)
        assert np.all(data.compressed() <= -100)  # no coarse overview elevation
        assert data[ds.index(432001, 3701941)] == -100
        assert data.mask[ds.index(432003, 3701941)]  # stored fine node was null
        assert data.mask[ds.index(432009, 3701941)]  # gap between supergrids
        assert data[ds.index(432015, 3701943)] == pytest.approx(-116.6666667)
    support = values(target / 'support.tif')
    np.testing.assert_array_equal(data.mask, support.mask)
    assert set(support.compressed()) == {2}
    consumers(tmp_path, target, sidecar)
