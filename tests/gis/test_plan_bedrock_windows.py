"""Offline synthetic checks for the private bedrock-window proposer."""
from affine import Affine
import numpy as np
import pytest
from shapely.geometry import box
from shapely.ops import unary_union

import research.scripts.plan_bedrock_windows as plan_module

from research.scripts.plan_bedrock_windows import (
    _window_records, nominal_depth_count, depth_window_eligibility, enforce_pixel_bound,
    MAX_DEPTH_M, MIN_DEPTH_M, validate_output_location,
)


def test_nominal_depth_includes_25_and_300_ft_endpoints_and_excludes_nodata():
    values = np.array([[MIN_DEPTH_M, MAX_DEPTH_M, MIN_DEPTH_M - .001,
                        MAX_DEPTH_M + .001, np.nan]], dtype=float)
    valid = np.array([[True, True, True, True, True]], dtype=bool)
    assert nominal_depth_count(values, valid) == 2
    valid[0, 1] = False  # masked/no-data at the upper endpoint is not usable support
    assert nominal_depth_count(values, valid) == 1


def test_tiles_are_nonoverlapping_inset_and_partial_edges_stay_in_bounds():
    affine = Affine(2, 0, 0, 0, -2, 0)
    bounds = box(0, -16, 20, 0)
    records, pixels = _window_records(10, 8, 3, affine, bounds, bounds, bounds,
                                      unary_union([]))
    windows = [r['window'] for r in records]
    assert windows == [[1, 1, 3, 3], [4, 1, 3, 3], [7, 1, 2, 3],
                       [1, 4, 3, 3], [4, 4, 3, 3], [7, 4, 2, 3]]
    assert pixels == 48
    for x, y, w, h in windows:
        assert x >= 1 and y >= 1 and x + w <= 9 and y + h <= 7


def test_whole_window_foreign_occupancy_excludes_tile_even_when_bedrock_intersects():
    affine = Affine(1, 0, 0, 0, -1, 0)
    full = box(0, -8, 10, 0)
    occupied = box(2, -2, 3, -1)
    records, _ = _window_records(10, 8, 4, affine, full, full, full, occupied)
    hit = next(r for r in records if r['window'] == [1, 1, 4, 4])
    assert 'whole_window_intersects_existing_occupied_geometry' in hit['reasons']
    clear = next(r for r in records if r['window'] == [5, 1, 4, 4])
    assert clear['reasons'] == []


def test_window_outside_reviewed_depth_scope_is_held():
    affine = Affine(1, 0, 0, 0, -1, 0)
    full = box(0, -8, 10, 0)
    scope = box(0, -8, 5, 0)
    records, _ = _window_records(10, 8, 4, affine, full, full, scope, unary_union([]))
    assert all('outside_verified_depth_scope' in r['reasons'] for r in records if r['window'][0] == 5)


def test_resource_bound_and_bad_shape_fail_closed():
    affine = Affine(1, 0, 0, 0, -1, 0)
    full = box(0, -8, 10, 0)
    records, pixels = _window_records(10, 8, 4, affine, full, full, full, unary_union([]))
    assert pixels > 1
    with pytest.raises(ValueError):
        nominal_depth_count(np.ones((2, 2)), np.ones((2, 1), dtype=bool))
    with pytest.raises(ValueError):
        _window_records(10, 8, 513, affine, full, full, full, unary_union([]))
    with pytest.raises(ValueError):
        enforce_pixel_bound(2, 1)
    with pytest.raises(ValueError):
        enforce_pixel_bound(1, 25_000_001)


def test_zero_valid_depth_pixels_are_held_and_positive_count_is_eligible():
    empty = {'reasons': []}
    assert not depth_window_eligibility(empty, 0)
    assert empty['reasons'] == ['no_valid_nominal_25_300ft_depth_pixels']
    eligible = {'reasons': []}
    assert depth_window_eligibility(eligible, 1)
    assert eligible['valid_nominal_depth_pixels'] == 1
    with pytest.raises(ValueError):
        depth_window_eligibility({'reasons': []}, -1)


def test_unknown_policy_fails_closed_before_any_source_access(tmp_path):
    from research.scripts.plan_bedrock_windows import propose
    with pytest.raises(ValueError, match='exactly one reviewed local policy'):
        propose(tmp_path, 'some-reach', 'unknown-policy')


def test_output_must_be_outside_inspected_workroot(tmp_path):
    root = tmp_path / 'workroot'
    root.mkdir()
    assert validate_output_location(root, tmp_path / 'proposal.json') == (tmp_path / 'proposal.json').resolve()
    with pytest.raises(ValueError, match='outside'):
        validate_output_location(root, root / 'proposal.json')


def _cached_reviewed_depth(root):
    import hashlib
    import json
    import rasterio
    from rasterio.transform import from_origin
    from skippercast.seafloor.io import sha256
    from skippercast.seafloor.normalized import raster_identity

    bounds = [-122.0, 36.0, -121.9, 36.1]
    source_bytes = b'synthetic reviewed source bytes'
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    cache = root / 'var/seafloor/cache' / source_hash
    cache.mkdir(parents=True)
    (cache / 'source.zip').write_bytes(source_bytes)
    cog = cache / 'normalized.tif'
    with rasterio.open(cog, 'w', driver='GTiff', width=2, height=2, count=1,
                       dtype='float32', crs='EPSG:32610', transform=from_origin(500000, 4100000, 2, 2),
                       nodata=float('nan')) as dst:
        dst.write(np.array([[10, 11], [12, 13]], dtype='float32'), 1)
        dst.set_band_description(1, 'depth_m_positive_down')
        dst.update_tags(vertical_datum='unknown', depth_basis='nominal')
    review = {
        'source_sha256': source_hash,
        'requested_bounds_wgs84': bounds,
        'native_resolution_m': [2.0, 2.0],
        'vertical_datum': 'unknown',
        'valid_pixels_in_requested_bounds': 4,
        'nominal_0_300ft_pixels_in_requested_bounds': 4,
        'cog_sha256': sha256(cog),
        'raster_identity': raster_identity(cog),
    }
    receipt = dict(review, source_id='synthetic-depth')
    receipt_path = cache / 'normalized.json'
    receipt_path.write_text(json.dumps(receipt))
    row = {
        'id': 'synthetic-depth',
        'url': 'https://cmgds.marine.usgs.gov/test/source.zip',
        'sha256': source_hash,
        'bytes': len(source_bytes),
        'adapter_review': review,
    }
    return row, receipt_path, cog


def test_read_only_normalized_depth_uses_verified_cache_without_any_writer(tmp_path):
    import json
    from unittest.mock import patch
    from skippercast.seafloor import classified_habitat as ch
    from skippercast.seafloor import ingest as native_ingest
    from skippercast.seafloor import source_ingest
    from skippercast.platform import contracts

    row, receipt_path, cog = _cached_reviewed_depth(tmp_path)
    # Model a legacy receipt that verification might otherwise upgrade in place.
    receipt = json.loads(receipt_path.read_text())
    receipt.pop('raster_identity')
    receipt_path.write_text(json.dumps(receipt))
    writer = AssertionError('normalization or receipt writer must not run')
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    def exercise_source_context(root, reach, policy, *, fetch=False):
        return ch.normalized_depth(row, root, fetch=fetch)
    with (patch.object(ch, 'source_context', exercise_source_context),
          patch.object(source_ingest, 'ingest', side_effect=writer),
          patch.object(native_ingest, 'ingest', side_effect=writer),
          patch.object(native_ingest, 'atomic_json', side_effect=writer),
          patch.object(native_ingest, 'raster_copy', side_effect=writer),
          patch.object(ch, 'atomic_json', side_effect=writer),
          patch.object(contracts, 'atomic_json', side_effect=writer)):
        receipt, path = plan_module._read_only_source_context(tmp_path, 'fixture', {})
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert after == before
    assert path == cog
    assert receipt['source_id'] == 'synthetic-depth'
    assert 'raster_identity' not in json.loads(receipt_path.read_text())


def test_read_only_resolver_fails_without_creating_missing_or_stale_cache(tmp_path):
    row = {'id':'missing', 'url':'https://cmgds.marine.usgs.gov/test/source.zip',
           'sha256':'a' * 64, 'bytes':1,
           'adapter_review':{'requested_bounds_wgs84':[-122,36,-121,37], 'cog_sha256':'b' * 64}}
    with pytest.raises(FileNotFoundError):
        plan_module._read_only_normalized_ingest(row, row['adapter_review']['requested_bounds_wgs84'],
                                                 root=tmp_path, fetch=False)
    assert not (tmp_path / 'var/seafloor/cache').exists()

    row, _, cog = _cached_reviewed_depth(tmp_path)
    cog.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='COG hash mismatch'):
        plan_module._read_only_normalized_ingest(
            row, row['adapter_review']['requested_bounds_wgs84'], root=tmp_path, fetch=False)


@pytest.mark.parametrize('cached_directory', [False, True])
def test_read_only_source_context_never_extracts_arcgrid_or_removes_part(
        tmp_path, monkeypatch, cached_directory):
    import hashlib
    import json
    import shutil
    from pathlib import Path
    from skippercast.seafloor import classified_habitat as ch
    from skippercast.seafloor.adapters import arcgrid

    cache = tmp_path / 'cache'
    cache.mkdir()
    archive = cache / 'source.tar.gz'
    archive.write_bytes(b'original archive bytes')
    row = {'archive_member': 'reviewed/grid'}
    member = arcgrid.safe_name(row['archive_member'])
    identity = hashlib.sha256(member.encode()).hexdigest()[:16]
    destination = cache / ('grid-' + identity)
    receipt_path = destination.with_suffix('.json')
    if cached_directory:
        destination.mkdir()
    part = destination.with_name(destination.name + '.part')
    part.mkdir()
    marker = part / 'preserve'
    marker.write_text('untouched')

    def source_context(_root, _reach, _policy, *, fetch=False):
        assert fetch is False
        return arcgrid.source_path(archive, row)

    failure = AssertionError('read-only cache miss attempted a filesystem write/removal')
    with (monkeypatch.context() as m):
        m.setattr(ch, 'source_context', source_context)
        for name in ('mkdir', 'unlink', 'rename', 'replace', 'write_text', 'write_bytes'):
            m.setattr(Path, name, lambda *args, _failure=failure, **kwargs: (_ for _ in ()).throw(_failure))
        m.setattr(shutil, 'rmtree', lambda *args, **kwargs: (_ for _ in ()).throw(failure))
        with pytest.raises(FileNotFoundError, match='must already be cached'):
            plan_module._read_only_source_context(tmp_path, 'fixture', {})
    assert marker.read_text() == 'untouched'
    assert not receipt_path.exists()


def test_foreign_occupancy_reports_unprocessed_incomplete_and_verified(tmp_path):
    import json
    from skippercast.seafloor.io import sha256

    catalog = tmp_path / 'catalog'
    catalog.mkdir()
    (catalog / 'reaches.json').write_text(json.dumps({'reaches':[
        {'id':'target-r02','region':'test'}, {'id':'neighbor-r01','region':'test'}]}))
    empty, ids, receipts, statuses = plan_module._native_occupancy(
        tmp_path, 'target-r02', 'test', 'EPSG:32610')
    assert statuses[0]['status'] == 'unprocessed'
    assert statuses[0]['complete'] is False
    assert receipts == []

    folder = tmp_path / 'var/seafloor/reaches/neighbor-r01'
    folder.mkdir(parents=True)
    def empty_collection(name):
        if name == 'classified-native.geojson':
            return {'version':'native-classified-geometry-v1','crs':'EPSG:3310','features':[]}
        return {'type':'FeatureCollection','features':[]}
    partial = folder / 'classified-native.geojson'
    partial.write_text(json.dumps({'version':'native-classified-geometry-v1','crs':'EPSG:3310','features':[
        {'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}}]}))
    occupied, _, receipts, statuses = plan_module._native_occupancy(
        tmp_path, 'target-r02', 'test', 'EPSG:32610')
    assert statuses[0]['status'] == 'incomplete' and statuses[0]['complete'] is False
    assert not occupied.is_empty and receipts[0]['receipt_status'] == 'unverified'
    partial.unlink()

    outputs = {}
    for name in ('classified-native.geojson', 'classified-held.geojson',
                 'classified-candidates.geojson'):
        path = folder / name
        path.write_text(json.dumps(empty_collection(name)))
        outputs[name] = sha256(path)
    audit_path = folder / 'classified-bedrock-audit.json'
    audit_path.write_text(json.dumps({'version':'interpreted-bedrock-private-audit-v1','quarantine':[]}))
    outputs[audit_path.name] = sha256(audit_path)
    (folder / 'classified-run.json').write_text(json.dumps({'reach':'neighbor-r01','outputs':outputs}))
    _, _, receipts, statuses = plan_module._native_occupancy(
        tmp_path, 'target-r02', 'test', 'EPSG:32610')
    assert statuses[0]['status'] == 'verified'
    assert statuses[0]['complete'] is True
    assert len(receipts) == 5  # receipt, 3 feature collections, zero-quarantine audit

    audit_path.write_text(json.dumps({'version':'interpreted-bedrock-private-audit-v1',
                                      'quarantine':[{'held':'not imported'}]}))
    outputs[audit_path.name] = sha256(audit_path)
    (folder / 'classified-run.json').write_text(json.dumps({'reach':'neighbor-r01','outputs':outputs}))
    _, _, _, statuses = plan_module._native_occupancy(
        tmp_path, 'target-r02', 'test', 'EPSG:32610')
    assert statuses[0]['complete'] is False
    assert any('nonzero private bedrock quarantine' in x for x in statuses[0]['reasons'])


def test_legacy_no_quarantine_compatibility_is_exact_and_fail_closed(tmp_path):
    import copy
    import json
    from skippercast.seafloor import bedrock_habitat as bh, classified_habitat as ch
    from skippercast.seafloor.io import sha256

    folder = tmp_path / 'cambria-san-simeon-r01'
    folder.mkdir()
    names = ('classified-candidates.geojson', 'classified-native.geojson',
             'classified-habitat.geojson', 'classified-held.geojson')
    native = {'version':'native-classified-geometry-v1','crs':'EPSG:3310','features':[
        {'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[
            [[0,0],[10,0],[10,10],[0,10],[0,0]]]}}]}
    geographic = {'type':'FeatureCollection','features':[]}
    for name in names:
        (folder / name).write_text(json.dumps(
            native if name == 'classified-native.geojson' else geographic))
    policy = {
        'id':'usgs-sim3327-sansimeon-bedrock-v1',
        'interpretation_method':'original-interpreted-bedrock-v1',
        'profile':'original-interpreted-bedrock-area-v1',
        'reach_ids':['cambria-san-simeon-r01'], 'reviewed_on':'2026-10-06',
        'depth_source_id':'csumb-scc-block03-2m-native',
        'classification_source_id':'geology-sansimeon-zip-9387f22e02',
        'depth_source_sha256':'a'*64, 'classification_source_sha256':'b'*64,
        'metadata_sha256':'c'*64, 'metadata_url':'https://pubs.usgs.gov/sim/3327/',
        'release_license':'public-domain-us-gov', 'rugose_raw_codes':None,
        'credit':'USGS', 'notice':'Limitations retained.', 'review_basis':'Synthetic test fixture.',
        'vector_review':{
            'original_crs':'EPSG:32610', 'expected_polygon_count':625,
            'invalid_original_records':[123], 'unit_field':'MapUnitAbb',
            'member_stem':'Geology_SanSimeon',
            'metadata_member':'Geology_SanSimeon_metadata.txt',
            'bedrock_units':['Tus','Tm','KJug','KJug?','KJf','Ksl','Jo','Jo?'],
            'excluded_units':['Qms/Tus','Qms/KJf','Qms/KJug','Qms/KJug?'],
            'native_windows':[[1,1,2,2]],
        },
    }
    inputs = {'physical':{'sources':[{
        'reach':'cambria-san-simeon-r01',
        'profile':'original-interpreted-bedrock-area-v1', 'policy':policy,
    }]}, 'screen':{}, 'screen_implementation_sha256':'d'*64}
    run = {
        'reach':'cambria-san-simeon-r01', 'inputs':inputs,
        'input_hash':ch.digest(inputs), 'physical_input_hash':ch.digest(inputs['physical']),
        'representation':{'version':'native-classified-geometry-v1','feature_count':1},
        'outputs':{name:sha256(folder / name) for name in names},
    }
    run_path = folder / 'classified-run.json'
    def save_run():
        run_path.write_text(json.dumps(run, sort_keys=True))
    def refresh_output_hashes():
        run['outputs'] = {name:sha256(folder / name) for name in names}
    save_run()
    contract = {
        'reach':'cambria-san-simeon-r01',
        'physical_input_hash':run['physical_input_hash'],
        'source_policy':'usgs-sim3327-sansimeon-bedrock-v1',
        'source_profile':'original-interpreted-bedrock-area-v1',
        'interpretation_method':'original-interpreted-bedrock-v1',
        'depth_source_id':'csumb-scc-block03-2m-native',
        'classification_source_id':'geology-sansimeon-zip-9387f22e02',
        'implementation':{
            'bedrock_habitat.py':sha256(bh.__file__),
            'classified_habitat.py':sha256(ch.__file__),
        },
        'native_sha256':sha256(folder / 'classified-native.geojson'), 'feature_count':1,
    }
    args = (folder, 'cambria-san-simeon-r01', run, run['outputs'])
    assert plan_module._authenticated_legacy_no_quarantine(*args, contract=contract)

    # A current screen-only receipt/output refresh remains eligible for
    # occupancy accounting when the physical identity and native geometry stay
    # pinned. The current output hashes are read from this refreshed receipt.
    initial_output_hashes = dict(run['outputs'])
    original_screen = inputs['screen']
    run['inputs'] = copy.deepcopy(inputs)
    run['inputs']['screen'] = {'snapshot_sha256':'e'*64, 'status':'refreshed'}
    run['inputs']['screen_implementation_sha256'] = 'f'*64
    run['input_hash'] = ch.digest(run['inputs'])
    run['physical_input_hash'] = ch.digest(run['inputs']['physical'])
    refreshed_feature = {'type':'Feature','properties':{},'geometry':{
        'type':'Polygon','coordinates':[[[1,1],[2,1],[2,2],[1,2],[1,1]]]}}
    refreshed = {'type':'FeatureCollection','features':[refreshed_feature]}
    (folder / 'classified-habitat.geojson').write_text(json.dumps(refreshed))
    (folder / 'classified-held.geojson').write_text(json.dumps(refreshed))
    refresh_output_hashes()
    save_run()
    assert plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', run, run['outputs'], contract=contract)
    assert original_screen != run['inputs']['screen']
    assert run['outputs']['classified-habitat.geojson'] != initial_output_hashes['classified-habitat.geojson']
    assert run['outputs']['classified-held.geojson'] != initial_output_hashes['classified-held.geojson']
    assert run['outputs']['classified-native.geojson'] == contract['native_sha256']

    # Changed physical identity, audited profile, mixed profile, receipt
    # identity, implementation, or native geometry must fail closed.
    physical_changed = copy.deepcopy(run)
    physical_changed['inputs']['physical']['sources'][0]['policy']['depth_source_sha256'] = 'f'*64
    physical_changed['input_hash'] = ch.digest(physical_changed['inputs'])
    physical_changed['physical_input_hash'] = ch.digest(physical_changed['inputs']['physical'])
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', physical_changed, physical_changed['outputs'], contract=contract)

    audited = copy.deepcopy(run)
    audited['inputs']['physical']['sources'][0]['policy']['vector_review']['source_profile'] = bh.MONTEREY
    audited['input_hash'] = ch.digest(audited['inputs'])
    audited['physical_input_hash'] = ch.digest(audited['inputs']['physical'])
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', audited, audited['outputs'], contract=contract)
    mixed = copy.deepcopy(run)
    mixed['inputs']['physical']['sources'][0]['profile'] = 'mixed-profile'
    mixed['input_hash'] = ch.digest(mixed['inputs'])
    mixed['physical_input_hash'] = ch.digest(mixed['inputs']['physical'])
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', mixed, mixed['outputs'], contract=contract)

    stale_input = copy.deepcopy(run)
    stale_input['input_hash'] = '0'*64
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', stale_input, stale_input['outputs'], contract=contract)
    stale = copy.deepcopy(contract)
    stale['implementation'] = dict(stale['implementation'], **{'bedrock_habitat.py':'0'*64})
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', run, run['outputs'], contract=stale)
    stale_output = dict(run['outputs'], **{'classified-held.geojson':'0'*64})
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', run, stale_output, contract=contract)
    missing = dict(run['outputs'])
    del missing['classified-held.geojson']
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', run, missing, contract=contract)

    (folder / 'classified-held.geojson').unlink()
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', run, run['outputs'], contract=contract)
    (folder / 'classified-held.geojson').write_text(json.dumps(refreshed))

    # Even if the current receipt hash is updated, the fixed native identity
    # and schema cannot be replaced by malformed or different native geometry.
    (folder / 'classified-native.geojson').write_text(json.dumps({'type':'FeatureCollection'}))
    run['outputs']['classified-native.geojson'] = sha256(folder / 'classified-native.geojson')
    save_run()
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', run, run['outputs'], contract=contract)
    (folder / 'classified-bedrock-audit.json').write_text('{}')
    assert not plan_module._authenticated_legacy_no_quarantine(
        folder, 'cambria-san-simeon-r01', run, run['outputs'], contract=contract)


def test_foreign_feature_schema_and_invalid_geometry_fail_closed(tmp_path):
    import json
    from skippercast.seafloor.io import sha256

    (tmp_path / 'catalog').mkdir()
    (tmp_path / 'catalog/reaches.json').write_text(json.dumps({'reaches':[
        {'id':'target-r02','region':'test'}, {'id':'neighbor-r01','region':'test'}]}))
    folder = tmp_path / 'var/seafloor/reaches/neighbor-r01'
    folder.mkdir(parents=True)
    bad = folder / 'classified-native.geojson'
    bad.write_text(json.dumps({'type':'FeatureCollection'}))
    (folder / 'classified-run.json').write_text(json.dumps({'reach':'neighbor-r01','outputs':{bad.name:sha256(bad)}}))
    with pytest.raises(ValueError, match='Invalid FeatureCollection schema'):
        plan_module._native_occupancy(tmp_path,'target-r02','test','EPSG:32610')

    with pytest.raises(ValueError, match='nonempty polygon or multipolygon'):
        plan_module._project_occupied({'type':'Point','coordinates':[1,2]},4326,'EPSG:32610',label='test')
    with pytest.raises(ValueError, match='finite'):
        plan_module._project_occupied({'type':'Polygon','coordinates':[[[0,0],[1,0],[float('nan'),1],[0,0]]]},
                                      4326,'EPSG:32610',label='test')
    with pytest.raises(ValueError, match='Projected test coordinates must all be finite'):
        plan_module._project_occupied(
            {'type':'Polygon','coordinates':[[[-122,95],[-121,95],[-121,95.1],[-122,95.1],[-122,95]]]},
            4326,'EPSG:32610',label='test')
    # Invalid source polygons fail closed; enveloping before nonlinear projection
    # could omit part of the transformed geometry.
    with pytest.raises(ValueError, match='source polygon is invalid'):
        plan_module._project_occupied(
            {'type':'Polygon','coordinates':[[[0,0],[1,1],[0,1],[1,0],[0,0]]]},
            4326,'EPSG:32610',label='test')


def test_exclusive_output_create_preserves_file_created_during_planning(tmp_path, monkeypatch):
    output = tmp_path / 'proposal.json'
    root = tmp_path / 'workroot'
    root.mkdir()
    def late_file(*args, **kwargs):
        output.write_text('preserve-me')
        return {'eligible_windows': [], 'resource_limits': {'candidate_window_count':0,
                'eligible_window_count':0, 'eligible_pixels':0}, 'held_windows':[],
                'source_context_sha256':'test'}
    monkeypatch.setattr(plan_module, 'propose', late_file)
    with pytest.raises(SystemExit):
        plan_module.main(['--root',str(root),'--reach','r','--policy-id','p','--output',str(output)])
    assert output.read_text() == 'preserve-me'
