"""Gap acquisition must avoid already supported bottom and credit no new area."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from research.scripts.discover_noaa_multibeam_footprints import (
    FIELDS, discover_gaps, gap_sectors,
)

pytestmark = pytest.mark.gis


def snapshot(folder, cells):
    payload = {'reach': 'test-reach', 'cells': cells}
    raw = json.dumps(payload).encode()
    (folder/'coverage-cells.json').write_bytes(raw)
    (folder/'coverage-checkpoint.json').write_text(json.dumps({
        'cells_sha256': hashlib.sha256(raw).hexdigest(), 'physical_input_hash': 'a'*64,
    }))


def cell(x, y, valid=0, band=62500):
    return {'id': f'3310:{x}:{y}', 'reach': 'test-reach', 'tier': int(valid >= 15625),
            'band_area_m2': band, 'valid_area_m2': valid,
            'source_id': 'known' if valid else 'unknown',
            'available_source_ids': ['known'] if valid else []}


def fake_fetch(url):
    args = parse_qs(urlsplit(url).query)
    if urlsplit(url).path.endswith('/0'):
        return {'geometryType': 'esriGeometryPolygon', 'maxRecordCount': 2000,
                'fields': [{'name': name} for name in FIELDS.split(',')]}, 'b'*64
    if 'returnCountOnly' in args:
        return {'count': 1}, 'c'*64
    return {'features': [{'attributes': {'OBJECTID': 1, 'DOWNLOAD_URL': 'https://www.ncei.noaa.gov/'}}]}, 'd'*64


def current_inputs(folder, *, retained=('one',), published=('one',)):
    sources = [{'id': ident, 'sha256': 'c' * 64, 'format': 'arcgrid',
                'resolution_m': 2, 'archive_member': 'original', 'vertical_datum': 'unknown'}
               for ident in retained]
    inputs = {'sources': sources}
    physical_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    checkpoint = json.loads((folder/'coverage-checkpoint.json').read_text())
    checkpoint['physical_input_hash'] = physical_hash
    (folder/'coverage-checkpoint.json').write_text(json.dumps(checkpoint))
    (folder/'run.json').write_text(json.dumps({'inputs': inputs, 'physical_input_hash': physical_hash}))
    ledger = folder/'ledger.json'; catalog = folder/'catalog.json'
    ledger.write_text(json.dumps({'reaches': [{'id': 'test-reach', 'surveys_used': list(published)}]}))
    catalog.write_text(json.dumps({'surveys': sources + [dict(sources[0], id=ident)
                                                        for ident in published if ident not in retained]}))
    return ledger, catalog


def test_current_source_guard_rejects_stale_valid_snapshot_before_network():
    with TemporaryDirectory() as temp:
        folder = Path(temp); snapshot(folder, [cell(-270, -1420)])
        ledger, catalog = current_inputs(folder, published=('one', 'two'))
        with pytest.raises(ValueError, match='omits published contributors: two'):
            discover_gaps(folder, lambda _: pytest.fail('No request for stale gaps'),
                          current_ledger=ledger, current_catalog=catalog)


def test_rights_only_refresh_resumes_but_new_published_contributor_does_not():
    with TemporaryDirectory() as temp:
        folder = Path(temp); snapshot(folder, [cell(-270+i, -1420) for i in range(3)])
        ledger, catalog = current_inputs(folder, retained=('one', 'private-new'))
        before = discover_gaps(folder, fake_fetch, max_cells=1, max_groups=1,
                               current_ledger=ledger, current_catalog=catalog)
        resume = folder/'resume.json'; resume.write_text(json.dumps(before))
        current = json.loads(catalog.read_text()); current['surveys'][0]['license'] = 'new-review'
        catalog.write_text(json.dumps(current))
        after = discover_gaps(folder, fake_fetch, max_cells=1, max_groups=1, resume_from=resume,
                              current_ledger=ledger, current_catalog=catalog)
        assert after['start_group'] == 1 and after['next_group'] == 2
        assert after['coverage_snapshot']['published_source_guard']['binding_sha256'] == before['coverage_snapshot']['published_source_guard']['binding_sha256']
        assert after['new_measured_km2'] == 0
        current = json.loads(ledger.read_text()); current['reaches'][0]['surveys_used'] += ['private-new']
        ledger.write_text(json.dumps(current))
        with pytest.raises(ValueError, match='Resume receipt differs'):
            discover_gaps(folder, lambda _: pytest.fail('Changed contributors invalidate resume'),
                          max_cells=1, max_groups=1, resume_from=resume,
                          current_ledger=ledger, current_catalog=catalog)


def test_cli_checks_published_sources_by_default_and_marks_explicit_history(monkeypatch, tmp_path):
    from research.scripts.discover_noaa_multibeam_footprints import main
    snapshot(tmp_path, [cell(-270, -1420, 62500)])
    ledger, catalog = current_inputs(tmp_path, published=('one', 'two'))
    (tmp_path/'dist/data').mkdir(parents=True); (tmp_path/'catalog').mkdir()
    (tmp_path/'dist/data/seafloor-ledger.json').write_bytes(ledger.read_bytes())
    (tmp_path/'catalog/surveys.json').write_bytes(catalog.read_bytes())
    monkeypatch.chdir(tmp_path)
    args = ['discover', '--coverage-folder', str(tmp_path), '--output', str(tmp_path/'out.json')]
    monkeypatch.setattr('sys.argv', args)
    with pytest.raises(ValueError, match='omits published contributors'):
        main()
    assert not (tmp_path/'out.json').exists()
    monkeypatch.setattr('sys.argv', args + ['--allow-historical-snapshot'])
    main()
    guard = json.loads((tmp_path/'out.json').read_text())['coverage_snapshot']['published_source_guard']
    assert guard == {'status': 'not-checked', 'current_coverage_claim': False}


def test_queries_exact_zero_support_cells_and_excludes_partial_support():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270, -1420), cell(-269, -1420, 10), cell(-270, -1419, 62500)])
        groups, receipt = gap_sectors(folder)
        assert len(groups) == 1
        assert receipt['partial_support_cells_excluded'] == 1
        ring = groups[0]['query_geometry']['rings'][0]
        assert Polygon(ring).area == 62500
        assert Polygon(ring).contains(Point(-270*250+125, -1420*250+125))
        assert not Polygon(ring).covers(Point(-269*250+125, -1420*250+125))
        calls = []
        def fetch(url):
            calls.append(url)
            return fake_fetch(url)
        result = discover_gaps(folder, fetch)
        args = parse_qs(urlsplit(calls[1]).query)
        assert args['geometryType'] == ['esriGeometryPolygon']
        assert args['inSR'] == ['3310']
        assert result['new_measured_km2'] == 0
        assert not result['fishing_target'] and not result['exportable']


def test_owned_batch_edges_never_lose_or_duplicate_cells():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270+i, -1420) for i in range(5)])
        groups, _ = gap_sectors(folder, max_cells=2)
        ids = [ident for group in groups for ident in group['planning_cell_ids']]
        assert len(ids) == len(set(ids)) == 5
        polygons = [Polygon(group['query_geometry']['rings'][0]) for group in groups]
        assert unary_union(polygons).area == 5*62500
        result = discover_gaps(folder, fake_fetch, max_cells=2, max_groups=2)
        assert result['queried_group_count'] == 2 and result['remaining_group_count'] == 1
        resume = folder/'resume.json'; resume.write_text(json.dumps(result))
        follow = discover_gaps(folder, fake_fetch, max_cells=2, max_groups=2, resume_from=resume)
        assert follow['remaining_group_count'] == 0
        assert follow['sectors'][0]['planning_cell_ids'] == groups[2]['planning_cell_ids']
        assert not set(follow['sectors'][0]['planning_cell_ids']) & set(result['sectors'][0]['planning_cell_ids'])
        assert result['unique_footprint_object_ids'] == 1  # Duplicate surveys are not extra evidence.


def test_no_gap_has_no_network_or_area_credit():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270, -1420, 62500), cell(-269, -1420, band=0)])
        result = discover_gaps(folder, lambda url: pytest.fail('No gap needs no request'))
        assert result['queried_group_count'] == 0
        assert result['new_measured_km2'] == 0


def test_corrupt_checkpoint_fails_before_request():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270, -1420)])
        (folder/'coverage-cells.json').write_text('{}')
        with pytest.raises(ValueError, match='hash mismatch'):
            discover_gaps(folder, lambda url: pytest.fail('Invalid cache must not query'))


@pytest.mark.parametrize('change', [
    {'valid_area_m2': float('nan')}, {'valid_area_m2': -1}, {'band_area_m2': 62501},
    {'source_id': 'known'}, {'available_source_ids': ['known']}, {'reach': 'other'},
    {'id': '3310:1.5:2'}, {'id': '3310:-0270:-1420'},
])
def test_invalid_or_contradictory_cells_are_not_gap_evidence(change):
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        item = cell(-270, -1420); item.update(change); snapshot(folder, [item])
        with pytest.raises(ValueError):
            gap_sectors(folder)


def test_duplicate_cells_fail_and_holes_keep_esri_orientation():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270, -1420), cell(-270, -1420)])
        with pytest.raises(ValueError, match='duplicate'):
            gap_sectors(folder)
        cells = [cell(x, y) for x in range(-272, -269) for y in range(-1422, -1419)
                 if (x,y) != (-271,-1421)]
        snapshot(folder, cells)
        groups, _ = gap_sectors(folder)
        outer, hole = groups[0]['query_geometry']['rings']
        assert not Polygon(outer).exterior.is_ccw and Polygon(hole).exterior.is_ccw
        assert Polygon(outer, [hole]).area == 8*62500


@pytest.mark.parametrize('value', [0, 257, True, 1.5])
def test_invalid_batch_bounds(value):
    with pytest.raises(ValueError, match='1–256'):
        gap_sectors(Path('never-read'), value)


def test_resume_requires_identical_checkpoint_and_batch_size():
    with TemporaryDirectory() as temp:
        folder = Path(temp)
        snapshot(folder, [cell(-270+i, -1420) for i in range(3)])
        result = discover_gaps(folder, fake_fetch, max_cells=1, max_groups=1)
        resume = folder/'resume.json'; resume.write_text(json.dumps(result))
        with pytest.raises(ValueError, match='requires a checked'):
            discover_gaps(folder, fake_fetch, start_group=1)
        with pytest.raises(ValueError, match='differs'):
            discover_gaps(folder, fake_fetch, max_cells=2, resume_from=resume)
        snapshot(folder, [cell(-270, -1420)])
        with pytest.raises(ValueError, match='differs'):
            discover_gaps(folder, fake_fetch, max_cells=1, resume_from=resume)


def test_missing_identity_is_not_a_verified_snapshot():
    with TemporaryDirectory() as temp:
        folder = Path(temp); snapshot(folder, [cell(-270, -1420)])
        path = folder/'coverage-checkpoint.json'; data = json.loads(path.read_text())
        data.pop('physical_input_hash'); path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match='physical input identity'):
            gap_sectors(folder)


def test_large_polygon_uses_post_instead_of_exceeding_url_limits(monkeypatch):
    from research.scripts import discover_noaa_multibeam_footprints as module
    from io import BytesIO
    seen = []
    def opened(request, timeout):
        seen.append(request)
        return BytesIO(b'{}')
    monkeypatch.setattr(module, 'urlopen', opened)
    module.fetch_json(module.LAYER + '/query?geometry=' + 'x'*7000)
    assert seen[0].get_method() == 'POST'
    assert seen[0].full_url == module.LAYER + '/query'
    assert seen[0].data.startswith(b'geometry=')
    module.fetch_json(module.LAYER + '?f=json')
    assert isinstance(seen[1], str)


def native_fixture(folder):
    """Two measured masks fill four columns; the fifth is not measured shallow."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    cache = folder/'cache'; receipts, sources = [], []
    for index in range(2):
        source_hash = str(index+1)*64
        inputs = {'source_id': f'source-{index}', 'source_sha256': source_hash}
        key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        path = cache/source_hash/(key+'.tif'); path.parent.mkdir(parents=True)
        depth = np.full((5, 5), np.nan, dtype='float32')
        if index == 0:
            depth[:, :3] = 30
            depth[:, 3] = 91.4401  # Just outside the nominal ceiling; not support.
        else:
            depth[:, 3] = 91.44  # The ceiling itself is included.
            depth[:, 4] = 0      # Zero is not submerged support.
        with rasterio.open(path, 'w', driver='GTiff', width=5, height=5, count=1,
                           dtype='float32', nodata=np.nan, crs='EPSG:3310',
                           transform=from_origin(-67500, -354750, 50, 50)) as dst:
            dst.write(depth, 1); dst.set_band_description(1, 'depth_m_positive_down')
        receipt = {'inputs': inputs, 'source_id': inputs['source_id'], 'source_sha256': source_hash,
                   'cog_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'requested_bounds_wgs84': [-125, 34, -118, 38],
                   'native_resolution_m': [50,50], 'vertical_datum': 'unknown',
                   'valid_pixels_in_requested_bounds': int(np.isfinite(depth).sum()),
                   'nominal_0_300ft_pixels_in_requested_bounds': int(((depth>0)&(depth<=91.44)).sum())}
        path.with_suffix('.json').write_text(json.dumps(receipt))
        receipts.append(receipt); sources.append({'id': inputs['source_id'], 'sha256': source_hash,
                                                 'adapter_review': dict(receipt)})
    snapshot(folder, [cell(-270, -1420, 37500)])
    inputs = {'sources': sources}
    physical = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    checkpoint = folder/'coverage-checkpoint.json'; cp = json.loads(checkpoint.read_text())
    cp['physical_input_hash'] = physical; checkpoint.write_text(json.dumps(cp))
    (folder/'run.json').write_text(json.dumps({'inputs': inputs, 'physical_input_hash': physical,
                                            'source_receipts': receipts}))
    return cache


def rings_geometry(group):
    # Esri exterior clockwise, holes anticlockwise, including disconnected parts.
    rings = group['query_geometry']['rings']
    outers = [Polygon(r) for r in rings if not Polygon(r).exterior.is_ccw]
    holes = [Polygon(r) for r in rings if Polygon(r).exterior.is_ccw]
    return unary_union(outers).difference(unary_union(holes))


def test_native_masks_find_partial_gap_without_querying_any_supported_bottom(monkeypatch):
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        assert gap_sectors(folder)[0] == []  # Reproduces the excluded-partial blocker.
        groups, receipt = gap_sectors(folder, cache_root=cache)
        gap = rings_geometry(groups[0])
        assert gap.area == pytest.approx(12500)
        assert gap.bounds == (-67300, -355000, -67250, -354750)
        assert not gap.contains(Point(-67325, -354875))  # Overlapping second source fills this.
        assert receipt['partial_support_cells_excluded'] == 0
        assert receipt['zero_support_cell_count'] == 0
        from skippercast.seafloor import coverage
        monkeypatch.setattr(coverage, 'footprint', lambda *a, **k: pytest.fail('Reuse checked mask'))
        assert gap_sectors(folder, cache_root=cache) == (groups, receipt)
        result = discover_gaps(folder, fake_fetch, cache_root=cache)
        assert result['new_measured_km2'] == 0 and not result['exportable']


@pytest.mark.parametrize('corruption', ['raster', 'run', 'missing-source', 'geometry'])
def test_native_mask_corruption_never_queries(corruption):
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        gap_sectors(folder, cache_root=cache)
        if corruption == 'raster':
            next(cache.glob('*/*.tif')).write_bytes(b'corrupt')
        elif corruption == 'geometry':
            p = next((folder/'acquisition-support').glob('*.json'))
            d = json.loads(p.read_text()); d['geometry']['coordinates'] = []
            p.write_text(json.dumps(d))
        else:
            p = folder/'run.json'; d = json.loads(p.read_text())
            if corruption == 'run': d['inputs']['sources'].pop()
            else: d['source_receipts'].pop()
            p.write_text(json.dumps(d))
        with pytest.raises(ValueError, match='verification|checkpoint|complete'):
            discover_gaps(folder, lambda u: pytest.fail('Corrupt support must not query'), cache_root=cache)


def test_resume_cannot_switch_from_whole_cells_to_native_masks():
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        result = discover_gaps(folder, fake_fetch)
        p = folder/'resume.json'; p.write_text(json.dumps(result))
        with pytest.raises(ValueError, match='differs'):
            discover_gaps(folder, fake_fetch, cache_root=cache, resume_from=p)


def update_native_fixture_source(folder, cache, index, *, fill=False, hole=False):
    import rasterio
    import numpy as np
    p = next((cache/(str(index+1)*64)).glob('*.tif'))
    with rasterio.open(p, 'r+') as ds:
        if fill:
            values = ds.read(1); values[:, 4] = 30; ds.write(values, 1)
        if hole:
            mask = np.full((5,5), 255, dtype='uint8'); mask[2,1] = 0; ds.write_mask(mask)
    receipt = json.loads(p.with_suffix('.json').read_text())
    receipt['cog_sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
    p.with_suffix('.json').write_text(json.dumps(receipt))
    run_path = folder/'run.json'; run = json.loads(run_path.read_text())
    run['source_receipts'][index] = receipt
    run['inputs']['sources'][index]['adapter_review'] = dict(receipt)
    run['physical_input_hash'] = hashlib.sha256(json.dumps(run['inputs'], sort_keys=True).encode()).hexdigest()
    run_path.write_text(json.dumps(run))
    cp_path = folder/'coverage-checkpoint.json'; cp = json.loads(cp_path.read_text())
    cp['physical_input_hash'] = run['physical_input_hash']; cp_path.write_text(json.dumps(cp))


def test_union_can_fully_cover_a_cell_with_only_partially_selected_support():
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        update_native_fixture_source(folder, cache, 1, fill=True)
        result = discover_gaps(folder, lambda u: pytest.fail('Fully covered union needs no request'), cache_root=cache)
        assert result['queried_group_count'] == 0


def test_native_nodata_hole_and_owned_edges_survive_geometry_batching():
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        update_native_fixture_source(folder, cache, 0, hole=True)
        snapshot(folder, [cell(-270,-1420,35000), cell(-269,-1420)])
        cp_path = folder/'coverage-checkpoint.json'; cp = json.loads(cp_path.read_text())
        cp['physical_input_hash'] = json.loads((folder/'run.json').read_text())['physical_input_hash']
        cp_path.write_text(json.dumps(cp))
        groups, _ = gap_sectors(folder, max_cells=1, cache_root=cache)
        geometries = [rings_geometry(g) for g in groups]
        assert len(groups) == 2
        assert geometries[0].area == pytest.approx(15000)
        assert geometries[0].contains(Point(-67425,-354875))  # Native mask hole.
        assert geometries[1].area == pytest.approx(62500)
        assert geometries[0].intersection(geometries[1]).area == 0
        assert unary_union(geometries).area == pytest.approx(77500)


def test_legal_only_run_change_reuses_physical_support(monkeypatch):
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        groups, before = gap_sectors(folder, cache_root=cache)
        p = folder/'run.json'; run = json.loads(p.read_text())
        run['inputs']['screen'] = {'version': 'new-legal-screen'}
        run['inputs']['screen_implementation_sha256'] = 'b'*64
        p.write_text(json.dumps(run))
        from skippercast.seafloor import coverage
        monkeypatch.setattr(coverage, 'footprint', lambda *a, **k: pytest.fail('Legal change must not reread masks'))
        after_groups, after = gap_sectors(folder, cache_root=cache)
        assert after_groups == groups
        assert after['native_support_sha256'] == before['native_support_sha256']
        assert after['retained_run_sha256'] != before['retained_run_sha256']


def deep_fixture_source(folder, cache, value=95, masked=False):
    """Replace the unsurveyed column with an explicitly checked native sample."""
    import numpy as np
    import rasterio
    path = next((cache/('2'*64)).glob('*.tif'))
    with rasterio.open(path, 'r+') as ds:
        depth = ds.read(1); depth[:, 4] = value; ds.write(depth, 1)
        if masked:
            mask = np.full((5, 5), 255, dtype='uint8'); mask[2, 4] = 0; ds.write_mask(mask)
    update_native_fixture_source(folder, cache, 1)


def test_measured_95m_is_not_a_missing_shallow_survey_or_new_habitat():
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        deep_fixture_source(folder, cache)
        default, _ = gap_sectors(folder, cache_root=cache)
        assert rings_geometry(default[0]).area == pytest.approx(12500)  # Reproducible false search.
        result = discover_gaps(folder, lambda u: pytest.fail('Measured deeper water needs no acquisition'),
                               cache_root=cache, exclude_measured_deep=True)
        assert result['group_count'] == result['queried_group_count'] == 0
        assert result['coverage_snapshot']['excluded_non_target_query_m2'] == pytest.approx(12500)
        assert result['new_measured_km2'] == 0 and not result['exportable'] and not result['fishing_target']
        assert json.loads((folder/'coverage-cells.json').read_text())['cells'][0]['valid_area_m2'] == 37500


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 0, -1])
def test_nonfinite_and_nonpositive_depth_remains_unknown(value):
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder); deep_fixture_source(folder, cache, value)
        groups, receipt = gap_sectors(folder, cache_root=cache, exclude_measured_deep=True)
        assert rings_geometry(groups[0]).area == pytest.approx(12500)
        assert receipt['excluded_non_target_query_m2'] == 0


def test_depth_mask_holes_and_owned_edges_survive_deep_exclusion():
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder); deep_fixture_source(folder, cache, masked=True)
        snapshot(folder, [cell(-270,-1420,37500), cell(-269,-1420)])
        cp_path = folder/'coverage-checkpoint.json'; cp = json.loads(cp_path.read_text())
        cp['physical_input_hash'] = json.loads((folder/'run.json').read_text())['physical_input_hash']
        cp_path.write_text(json.dumps(cp))
        groups, receipt = gap_sectors(folder, max_cells=1, cache_root=cache, exclude_measured_deep=True)
        geometries = [rings_geometry(g) for g in groups]
        assert len(groups) == 2 and geometries[0].area == pytest.approx(2500)
        assert geometries[0].contains(Point(-67275,-354875))  # Masked 95 m is still missing data.
        assert geometries[1].area == pytest.approx(62500)
        assert geometries[0].intersection(geometries[1]).area == 0
        assert receipt['excluded_non_target_query_m2'] == pytest.approx(10000)


def test_deep_exclusion_requires_verified_masks_and_mode_bound_resume():
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        with pytest.raises(ValueError, match='requires checked native masks'):
            discover_gaps(folder, lambda u: pytest.fail('Missing masks cannot query'), exclude_measured_deep=True)
        first = discover_gaps(folder, fake_fetch, cache_root=cache)
        resume = folder/'resume.json'; resume.write_text(json.dumps(first))
        with pytest.raises(ValueError, match='differs'):
            discover_gaps(folder, fake_fetch, cache_root=cache, exclude_measured_deep=True, resume_from=resume)


def test_deep_cache_reuses_masks_but_rejects_corrupt_geometry(monkeypatch):
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder); deep_fixture_source(folder, cache)
        before = gap_sectors(folder, cache_root=cache, exclude_measured_deep=True)
        import rasterio
        monkeypatch.setattr(rasterio, 'open', lambda *a, **kw: pytest.fail('Checked deep geometry must be reused'))
        assert gap_sectors(folder, cache_root=cache, exclude_measured_deep=True) == before
        p = next((folder/'acquisition-support').glob('deep-*.json'))
        data = json.loads(p.read_text()); data['geometry']['coordinates'] = []; p.write_text(json.dumps(data))
        with pytest.raises(ValueError, match='deep geometry failed verification'):
            discover_gaps(folder, lambda u: pytest.fail('Corrupt deep cache cannot query'), cache_root=cache,
                          exclude_measured_deep=True)


def test_self_consistent_substituted_cog_cannot_override_pinned_source_review():
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        original_run = json.loads((folder/'run.json').read_text())
        update_native_fixture_source(folder, cache, 1, fill=True)
        substituted = json.loads((folder/'run.json').read_text())
        # Preserve the pinned source rows/physics; substitute only the external receipt/cache.
        substituted['inputs'] = original_run['inputs']
        substituted['physical_input_hash'] = original_run['physical_input_hash']
        (folder/'run.json').write_text(json.dumps(substituted))
        cp = json.loads((folder/'coverage-checkpoint.json').read_text())
        cp['physical_input_hash'] = original_run['physical_input_hash']
        (folder/'coverage-checkpoint.json').write_text(json.dumps(cp))
        with pytest.raises(ValueError, match='reviewed manifest'):
            discover_gaps(folder, lambda u: pytest.fail('Substituted raster must not query'), cache_root=cache)


def test_lossless_cog_encoding_can_use_reviewed_scientific_identity():
    import rasterio.shutil
    from skippercast.seafloor.normalized import raster_identity
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder)
        p = next((cache/('1'*64)).glob('*.tif'))
        run_path = folder/'run.json'; run = json.loads(run_path.read_text())
        review = run['inputs']['sources'][0]['adapter_review']
        review['raster_identity'] = raster_identity(p)
        physical = hashlib.sha256(json.dumps(run['inputs'], sort_keys=True).encode()).hexdigest()
        run['physical_input_hash'] = physical
        temp_path = p.with_suffix('.reencoded.tif'); rasterio.shutil.copy(p, temp_path, driver='GTiff', compress='DEFLATE')
        temp_path.replace(p)
        receipt = run['source_receipts'][0]
        receipt['cog_sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
        assert receipt['cog_sha256'] != review['cog_sha256']
        p.with_suffix('.json').write_text(json.dumps(receipt)); run_path.write_text(json.dumps(run))
        cp_path = folder/'coverage-checkpoint.json'; cp = json.loads(cp_path.read_text())
        cp['physical_input_hash'] = physical; cp_path.write_text(json.dumps(cp))
        groups, _ = gap_sectors(folder, cache_root=cache)
        assert rings_geometry(groups[0]).area == pytest.approx(12500)


@pytest.mark.parametrize('value, excluded', [(91.44, 0), (91.4401, 12500)])
def test_deep_exclusion_respects_nominal_ceiling_and_shallow_overlap(value, excluded):
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder); deep_fixture_source(folder, cache, value)
        groups, receipt = gap_sectors(folder, cache_root=cache, exclude_measured_deep=True)
        assert groups == []
        assert receipt['excluded_non_target_query_m2'] == pytest.approx(excluded)
        # Source 0 is deeper in column 3; source 1 still supplies shallow support.
        assert receipt['native_support_sha256']
        assert json.loads((folder/'coverage-cells.json').read_text())['cells'][0]['valid_area_m2'] == 37500


def test_deep_mask_window_seams_preserve_identical_query_geometry(monkeypatch):
    from skippercast.seafloor import raster
    with TemporaryDirectory() as one, TemporaryDirectory() as two:
        first = Path(one); a = native_fixture(first); deep_fixture_source(first, a, masked=True)
        expected, identity = gap_sectors(first, cache_root=a, exclude_measured_deep=True)
        original = raster.chunks
        monkeypatch.setattr(raster, 'chunks', lambda window: original(window, size=2))
        second = Path(two); b = native_fixture(second); deep_fixture_source(second, b, masked=True)
        actual, changed = gap_sectors(second, cache_root=b, exclude_measured_deep=True)
        assert rings_geometry(actual[0]).symmetric_difference(rings_geometry(expected[0])).area == 0
        assert changed['excluded_non_target_query_m2'] == identity['excluded_non_target_query_m2']


def test_deep_mask_uses_the_verified_run_snapshot_even_if_run_is_replaced(monkeypatch):
    from research.scripts import discover_noaa_multibeam_footprints as module
    with TemporaryDirectory() as temp:
        folder = Path(temp); cache = native_fixture(folder); deep_fixture_source(folder, cache)
        original_bytes = (folder/'run.json').read_bytes()
        checked = module.native_support
        def replaced(*args, **kwargs):
            result = checked(*args, **kwargs)
            changed = json.loads(original_bytes); changed['source_receipts'] = []
            (folder/'run.json').write_text(json.dumps(changed))
            return result
        monkeypatch.setattr(module, 'native_support', replaced)
        groups, identity = gap_sectors(folder, cache_root=cache, exclude_measured_deep=True)
        assert groups == []  # The verified 95 m pixels still exclude the original false query.
        assert identity['retained_run_sha256'] == hashlib.sha256(original_bytes).hexdigest()
        assert identity['retained_run_sha256'] != hashlib.sha256((folder/'run.json').read_bytes()).hexdigest()
