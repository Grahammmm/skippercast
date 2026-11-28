"""R3 integration contract: selection and claims at the actual manifest boundary."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
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


def registry_row(source_id, display: str | None = 'allowed', owner=False, **status):
    rights = dict(attribution='Synthetic source fixture', commercial_use='allowed',
                  **({'owner_public_display': dict(decision='allowed', basis=BASIS)} if owner else {}))
    if display is not None:
        rights['public_display'] = display
    return dict(id=source_id, documentation_url='https://example.org/survey', rights=rights, **status)


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
        if ident == 'usgs-morro-bay':
            # Display is allowed even though the source cannot be redistributed
            # and its terms have not been approved in the registry.
            registry.append(registry_row(ident, owner=True, review_status='restricted', publication_allowed=False))
        else:
            registry.append(registry_row(ident))
    geographic = raster(tmp_path / 'geographic.tif', grid, crs='EPSG:4326')
    rows.append(dict(row_for(geographic, 'geographic'), admissible_now=False,
                     hold_reason='requires_projected_metre_grid'))
    registry.append(registry_row('geographic'))
    # Would raise on open if rights filtering were moved behind file access.
    absent = tmp_path / 'does-not-exist.tif'
    rows.append(row_for(absent, 'mbari-seafloor-mapping', rights_class='public'))
    registry.append(registry_row('mbari-seafloor-mapping', 'excluded', owner=True))
    # Neither an owner note nor approved raw redistribution replaces the
    # operative display field. These must be skipped before file access.
    rows.append(row_for(tmp_path / 'owner-note-only.tif', 'owner-note-only'))
    registry.append(registry_row('owner-note-only', 'private', owner=True))
    rows.append(row_for(tmp_path / 'no-display-decision.tif', 'no-display-decision'))
    registry.append(registry_row('no-display-decision', display=None, review_status='approved', publication_allowed=True))
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
    for ident in ('owner-note-only', 'no-display-decision'):
        assert (report[ident]['decision'], report[ident]['reason']) == (
            'skipped', 'registry_public_display_not_allowed')
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


def test_exclude_source_skips_only_that_registry_source_and_rebuilds(tmp_path):
    # Contract: --exclude-source drops every census row bound to that registry id, says so in the
    # selection report, and is pinned in the receipt. Bug caught: an exclusion silently ignored on a
    # rerun, or one that also drops another source, or an unknown id accepted.
    region, cache, argv = fixture(tmp_path)
    values = np.full((2, 2), -5, dtype='float32')
    rows, registry = [], []
    for ident, shift in (('keep', 0), ('drop', 1)):
        raw = raster(tmp_path / f'{ident}.tif', values - np.float32(shift))
        normalized(cache, raw, values, np.full(values.shape, 3, dtype='uint8'))
        rows.append(row_for(raw, ident))
        registry.append(registry_row(ident))
    put(region / 'census.json', dict(summary={'region': region.name}, files=rows))
    put(tmp_path / 'registry.json', {'sources': registry})
    check = receipts.Region(region.parent, region.name)

    assert main(argv) == 0
    assert {s['source_id'] for s in read(region / 'select/sources.json')['sources']} == {'keep', 'drop'}
    plain = read(check.receipt_path('select'))['generation']

    assert main([*argv, '--exclude-source', 'drop']) == 0
    assert {s['source_id'] for s in read(region / 'select/sources.json')['sources']} == {'keep'}
    report = {Path(s['path']).stem: s for s in read(region / 'select/selection.json')['files']}
    assert (report['drop']['decision'], report['drop']['reason']) == ('skipped', 'excluded_by_region_run_option')
    assert (report['keep']['decision'], report['keep']['source_id']) == ('included', 'keep')
    excluded = read(check.receipt_path('select'))['generation']
    assert excluded != plain
    assert main([*argv, '--exclude-source', 'drop']) == 0  # same option: no new work
    assert read(check.receipt_path('select'))['generation'] == excluded

    assert main(argv) == 0  # dropping the option restores the source
    assert {s['source_id'] for s in read(region / 'select/sources.json')['sources']} == {'keep', 'drop'}
    with pytest.raises(SystemExit) as refused:
        main([*argv, '--exclude-source', 'not-in-registry'])
    assert refused.value.code == 1


def test_exclude_source_cannot_widen_selection_or_use_aliases(tmp_path):
    # Contract: an excluded row still claims its census path, so a duplicate-path row bound to another
    # source stays skipped; aliases (acquisition id, URL) are refused, only real registry ids count.
    # Bug caught: excluding the first duplicate let the second one in; an alias that excluded nothing.
    region, cache, argv = fixture(tmp_path)
    values = np.full((2, 2), -5, dtype='float32')
    raw = raster(tmp_path / 'shared.tif', values)
    normalized(cache, raw, values, np.full(values.shape, 3, dtype='uint8'))
    rows = [row_for(raw, 'dup-a'), row_for(raw, 'dup-b')]
    put(region / 'census.json', dict(summary={'region': region.name}, files=rows))
    put(tmp_path / 'registry.json', {'sources': [registry_row('dup-a', acquisition_id='acq-a', data_url='https://example.org/a.tif'),
                                                 registry_row('dup-b')]})

    assert main(argv) == 0
    assert {s['source_id'] for s in read(region / 'select/sources.json')['sources']} == {'dup-a'}

    assert main([*argv, '--exclude-source', 'dup-a']) == 0
    assert read(region / 'select/sources.json')['sources'] == []
    reasons = sorted((s['source_id'], s['reason']) for s in read(region / 'select/selection.json')['files'])
    assert reasons == [('dup-a', 'excluded_by_region_run_option'), ('dup-b', 'duplicate_census_path')]

    for alias in ('acq-a', 'https://example.org/a.tif'):
        with pytest.raises(SystemExit) as refused:
            main([*argv, '--exclude-source', alias])
        assert refused.value.code == 1


def test_config_files_from_another_checkout_reuse_select(tmp_path):
    # Contract: the region config, registry and labels are pinned by content, not by where the checkout
    # sits; the same files at another path give the same generation and no new work. Bug caught: every
    # run from a new worktree made a new select generation, so identical data paid a multi-hour mosaic
    # and tiles rebuild (the dry-run plan said reuse). Control: an edited registry is still new work.
    region, cache, argv = fixture(tmp_path)
    values = np.full((2, 2), -5, dtype='float32')
    raw = raster(tmp_path / 'survey.tif', values)
    normalized(cache, raw, values, np.full(values.shape, 3, dtype='uint8'))
    put(region / 'census.json', dict(summary={'region': region.name}, files=[row_for(raw, 'survey')]))
    put(tmp_path / 'registry.json', {'sources': [registry_row('survey')]})
    check = receipts.Region(region.parent, region.name)
    assert main(argv) == 0
    first = read(check.receipt_path('select'))
    outputs = {p.name: p.read_bytes() for p in (region / 'select').iterdir()}

    other = tmp_path / 'other-checkout'
    other.mkdir()
    moved = list(argv)
    for flag in ('--registry', '--provenance', '--region-config'):
        at = moved.index(flag) + 1
        source = Path(moved[at])
        (other / source.name).write_bytes(source.read_bytes())
        moved[at] = str(other / source.name)
    assert main(moved) == 0
    again = read(check.receipt_path('select'))
    assert (again['generation'], again['attempt'], again['ended']) == (
        first['generation'], first['attempt'], first['ended'])
    assert {p.name: p.read_bytes() for p in (region / 'select').iterdir()} == outputs

    put(other / 'registry.json', {'sources': [registry_row('survey', notes='edited')]})
    assert main(moved) == 0
    assert read(check.receipt_path('select'))['generation'] != first['generation']
