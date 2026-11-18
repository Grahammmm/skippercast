"""R3 integration contract: selection and claims at the actual manifest boundary."""

import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from research.scripts.coast_mvp.coast_mosaic import load_sources
from scripts.build_bathy_tiles import load_native_manifest
from scripts.relief.region import main
from skippercast.relief import receipts

CRS = 'EPSG:32610'
BASIS = 'G decision 2026-11-18 (owner-accepted risk; revisit when paid)'


def put(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return path


def raster(path, data, cell=1, crs=CRS):
    path.parent.mkdir(parents=True, exist_ok=True)
    t = (from_origin(680000, 3910000, cell, cell) if crs == CRS
         else from_origin(-121, 35.5, .00001, .00001))
    with rasterio.open(path, 'w', driver='GTiff', count=1, width=data.shape[1], height=data.shape[0],
                       dtype=data.dtype, crs=crs, transform=t, nodata=0 if data.dtype == 'uint8' else -9999) as ds:
        ds.write(data, 1)
        ds.set_band_unit(1, 'm')
    return path


def fixture(tmp):
    out = tmp / 'out'
    region = out / 'morro-bay'
    cache = tmp / 'norm'
    # Through x=680003, excluding the last column of both the 1 m and 2 m fixtures.
    lon, lat = transform(CRS, 'EPSG:4326', [679999, 680003], [3909985, 3910003])
    config = put(tmp / 'region.json', {'bounds': [lon[0], lat[0], lon[1], lat[1]]})
    labels = put(tmp / 'labels.json', {'source_rows': [
        {'source_id': '8657-void-fill', 'dem_product_id': '8657',
         'source_name': 'Coastal California Topobathy Void Fill', 'cell_label': 'interpolated'},
    ]})
    return region, cache, ['select', '--region', 'morro-bay', '--out', str(out), '--cache', str(cache),
                           '--registry', str(tmp / 'registry.json'), '--provenance', str(labels),
                           '--region-config', str(config)]


def row_for(raw, source_id, **kwargs):
    return dict(path=str(raw), id=source_id, kind='elevation', admissible_now=True, **kwargs)


def registry_row(source_id, display='allowed', owner=False):
    rights = dict(attribution='Synthetic source fixture', public_display=display,
                  **({'owner_public_display': dict(decision='allowed', basis=BASIS)} if owner else {}))
    return dict(id=source_id, documentation_url='https://example.org/survey', rights=rights)


def normalized(cache, raw, values, classes=None, cell=1):
    """R2 on-disk contract, not a fake selector result."""
    original = receipts.sha256_file(raw)
    folder = cache / original / ('a' * 64)
    grid = raster(folder / 'grid.tif', values, cell)
    outputs = {grid.name: receipts.sha256_file(grid)}
    if classes is not None:
        support = raster(folder / 'support.tif', classes, cell)
        outputs[support.name] = receipts.sha256_file(support)
    with rasterio.open(grid) as ds:
        put(folder / 'sidecar.json', dict(schema='sc-relief-normalized/1', original_sha256=original,
            units='m', value_convention='elevation_positive_up', vertical_datum='NAVD88', outputs=outputs,
            resolution_m=cell, shape=list(values.shape), crs=CRS, transform=list(ds.transform)[:6]))
    return folder


def read(path):
    return json.loads(path.read_bytes())


def test_region_manifests_select_rights_priority_and_certified_area(tmp_path):
    # A rights snapshot must beat census rights; producer provenance can lower,
    # not grant a native tier. In-region finite class-3 cells alone count.
    region, cache, argv = fixture(tmp_path)
    grid = np.array([[-20, -21, -9999, -1], [-8, 2, -91.44, -10]], dtype='float32')
    supports = np.array([[3, 3, 3, 3], [2, 3, 3, 3]], dtype='uint8')
    not_shallow = np.array([[2, 3, 3, 3], [2, 3, 3, 3]], dtype='uint8')
    cases = [
        ('certified', 1, supports), ('coarser-certified', 2, supports),
        ('deep-only', 1, not_shallow), ('nominal-1m', 1, np.full(grid.shape, 2, dtype='uint8')),
        ('usgs-coned-ca-8657', 1, supports), ('usgs-morro-bay', 1, None),
        ('five-metre', 5, None), ('four-metre', 4, None),
    ]
    rows, registry = [], []
    for i, (ident, cell, classes) in enumerate(cases):
        raw = raster(tmp_path / f'{ident}.tif', grid - np.float32(i / 1000), cell)
        if ident != 'five-metre':
            normalized(cache, raw, grid, classes, cell)
        rows.append(row_for(raw, ident, sha256_receipt=receipts.sha256_file(raw),
                            provenance_id='8657-void-fill' if ident == 'usgs-coned-ca-8657' else None,
                            provenance_class='measured' if ident == 'nominal-1m' else 'unknown',
                            rights_class='private'))
        registry.append(registry_row(ident, 'private' if ident == 'usgs-morro-bay' else 'allowed',
                                     owner=ident == 'usgs-morro-bay'))
    geographic = raster(tmp_path / 'geographic.tif', grid, crs='EPSG:4326')
    rows.append(dict(row_for(geographic, 'geographic'), admissible_now=False,
                     hold_reason='requires_projected_metre_grid'))
    registry.append(registry_row('geographic'))
    # Would raise on open if rights filtering were moved behind file access.
    absent = tmp_path / 'does-not-exist.tif'
    rows.append(row_for(absent, 'mbari-seafloor-mapping', rights_class='public'))
    registry.append(registry_row('mbari-seafloor-mapping', 'excluded', owner=True))
    census = put(region / 'census.json', dict(summary={'region': 'morro-bay'}, files=rows[::-1]))
    put(tmp_path / 'registry.json', {'sources': registry})

    assert main(argv) == 0
    selected = region / 'select'
    sources = read(selected / 'sources.json')['sources']
    assert [s['source_id'] for s in sources[:3]] == ['certified', 'deep-only', 'coarser-certified']
    assert sources[-1]['source_id'] == 'usgs-coned-ca-8657'
    assert {s['id'] for s in load_sources(selected / 'sources.json')} == {s['id'] for s in sources}
    native = {s['source_id']: s for s in load_native_manifest(selected / 'native.json')}
    assert {k: s['max_zoom'] for k, s in native.items()} == {
        'certified': 17, 'deep-only': 15, 'coarser-certified': 15, 'nominal-1m': 15,
        'usgs-coned-ca-8657': 15, 'usgs-morro-bay': 15, 'five-metre': 15,
    }
    assert native['usgs-morro-bay']['rights_basis'] == BASIS
    assert native['usgs-morro-bay']['support_path'] is None
    assert native['usgs-morro-bay']['support_class_cap'] == 2
    assert native['five-metre']['path'] == str(tmp_path / 'five-metre.tif')
    coned = native['usgs-coned-ca-8657']
    assert (coned['support_class_cap'], coned['label']) == (1, 'estimated')
    assert coned['support_sha256'] == receipts.sha256_file(coned['support_path'])
    report = {Path(s['path']).stem: s for s in read(selected / 'selection.json')['files']}
    assert len(report) == len(rows)
    assert report['does-not-exist']['reason'] == 'registry_excluded'
    assert report['geographic']['reason'] == 'no_admissible_normalized_twin'
    assert report['certified']['certified_area_m2_by_depth_band'] == {'0-20m': 1, '20-91.44m': 2}
    assert report['deep-only']['certified_area_m2_by_depth_band'] == {'0-20m': 0, '20-91.44m': 2}
    for ident in ('nominal-1m', 'usgs-coned-ca-8657', 'usgs-morro-bay'):
        assert report[ident]['certified_area_m2_by_depth_band'] == {'0-20m': 0, '20-91.44m': 0}

    def hashes():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in selected.glob('*.json')}
    first = hashes()
    check = receipts.Region(region.parent, region.name)
    assert receipts.check(check, 'select').done
    assert main(argv) == 0  # same receipt, no work
    assert read(check.receipt_path('select'))['attempt'] == 1
    put(census, dict(summary={'region': 'morro-bay'}, files=rows))  # force rebuild with reordered inputs
    assert main(argv) == 0
    assert hashes() == first


def test_changed_support_revokes_previous_selection(tmp_path):
    # A pinned support raster edit must invalidate R3, not reuse a now-unsafe
    # max_zoom or use the altered support as certification evidence.
    region, cache, argv = fixture(tmp_path)
    values = np.full((2, 2), -5, dtype='float32')
    raw = raster(tmp_path / 'survey.tif', values)
    folder = normalized(cache, raw, values, np.full(values.shape, 3, dtype='uint8'))
    put(region / 'census.json', dict(summary={'region': region.name}, files=[row_for(raw, 'survey')]))
    put(tmp_path / 'registry.json', {'sources': [registry_row('survey')]})
    assert main(argv) == 0
    assert read(region / 'select/native.json')[0]['max_zoom'] == 17
    check = receipts.Region(region.parent, region.name)
    original = read(check.receipt_path('select'))['generation']
    raster(folder / 'support.tif', np.full(values.shape, 2, dtype='uint8'))
    assert main(argv) == 0
    assert read(check.receipt_path('select'))['generation'] != original
    assert read(region / 'select/native.json') == []
    report = read(region / 'select/selection.json')['files'][0]
    assert report['decision'] == 'skipped' and 'normalized pin mismatch' in report['reason']
