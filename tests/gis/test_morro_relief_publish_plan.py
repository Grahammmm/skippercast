"""Offline release rehearsal with the shape of Morro's public receipts, not its data."""
from pathlib import Path
import shutil

import numpy as np
import pytest
import rasterio
from rasterio.transform import array_bounds, from_origin
from rasterio.warp import transform_bounds
from shapely.geometry import box, mapping

from scripts import build_bathy_tiles
from scripts.relief import region as cli
from skippercast.relief import contours, envelope, package, publish, qa, receipts, shots
from tests._support import FIXTURES, ROOT
from tests.gis.test_relief_qa import write_json
from tests.gis.test_run_region_e2e import stub_node_capture

REGION = 'morro-bay'
FAMILIES = {'fixture-regional': 5, 'fixture-compiled': 16, 'fixture-coarse': 30}
ZOOMS = (14, 15)


def read_json(path):
    return package.decode_document(path.read_bytes())


def write_grid(path, values, grid, nodata):
    with rasterio.open(path, 'w', driver='GTiff', width=values.shape[1], height=values.shape[0],
                       count=1, dtype=values.dtype, crs='EPSG:3857', transform=grid, nodata=nodata) as ds:
        ds.write(values, 1)


def seed_upstream(region, config, bounds, tile_ids, registry):
    """Small upstream artifacts, hashed by the real receipt writer; no real survey/cache reads."""
    mosaic_dir = region.dir / 'mosaic/public'
    west, south, east, north = transform_bounds('EPSG:4326', 'EPSG:3857', *bounds)
    cols, rows = (int(span / 10) + 2 for span in (east - west, north - south))
    grid = from_origin(west, north, 10, 10)
    elevation = np.broadcast_to(np.linspace(-4, -40, rows, dtype='float32')[:, None], (rows, cols))
    codes = np.broadcast_to(1 + np.arange(cols, dtype='uint16') * len(FAMILIES) // cols, elevation.shape)
    selected = []
    region.dir.mkdir(parents=True)
    for code, source in enumerate(registry, 1):
        sid = source['id']
        path = region.dir / f'{sid}.tif'
        cell = FAMILIES[sid]
        # Give each family its own native spacing, with a common depth gradient.
        x = np.arange((cols * 10 + cell - 1) // cell) * cell
        y = np.arange((rows * 10 + cell - 1) // cell) * cell
        source_codes = 1 + x * len(FAMILIES) // (cols * 10)
        depths = (-4 - 36 * y / (rows * 10)).astype('float32')
        values = np.where(source_codes == code, depths[:, None], np.float32(-9999))
        write_grid(path, values, from_origin(west, north, cell, cell), -9999)
        selected.append(dict(id=f'{sid}-tile', source_id=sid, path=f'../{path.name}',
                             sha256=receipts.sha256_file(path), label='estimated', rights_class='public',
                             vertical_datum=source['vertical_datum'], vertical_offset_m=0,
                             value_convention='elevation_positive_up', units='m', survey_dates=['2020'],
                             resolution_m=cell, support_class_cap=2, max_zoom=15 if cell == 5 else None))

    native = selected[:1]  # 5 m estimated native support at z14–15; no class-3 certification.

    def select_fixture(out):
        write_json(out / 'sources.json', dict(schema_version=1, scope='public', sources=selected))
        write_json(out / 'native.json', native)

    def mosaic_fixture(out):
        for name, data, nodata in (('elevation', elevation, -9999), ('contributor', codes, 0),
                                   ('support_count', np.ones(elevation.shape, dtype='uint16'), 0),
                                   ('support_class', np.full(elevation.shape, 2, dtype='uint8'), 0)):
            write_grid(out / f'{name}.tif', data, grid, nodata)
        write_json(out / 'manifest.json', dict(
            schema_version=1, segment=REGION, status='review_required', units='m', resolution_m=10,
            value_convention='elevation_positive_up', seam_feather={'feather_m': 0},
            region_sha256=receipts.sha256_file(config),
            source_table_sha256=receipts.sha256_file(region.dir / 'select/sources.json'),
            sources=[dict(id=row['id'], code=code, sha256=row['sha256'], vertical_offset_m=0)
                     for code, row in enumerate(selected, 1)],
            outputs={p.stem: {'sha256': receipts.sha256_file(p)} for p in out.glob('*.tif')}))

    def tiles_fixture(out):
        rgba = np.full((256, 256, 4), (50, 90, 130, 255), dtype='uint8')
        w, s, e, n = bounds
        build_bathy_tiles.write_pmtiles(
            out / 'relief.pmtiles', {xyz: build_bathy_tiles.encode_png(rgba) for xyz in tile_ids},
            metadata=dict(description=f'Synthetic relief. {package.DISCLAIMER}', bounds=bounds,
                          minzoom=ZOOMS[0], maxzoom=ZOOMS[-1], native_support_by_zoom={
                              str(z): dict(tiles=int(z in ZOOMS), limit_m=20 if z >= 16 else 91.44,
                                           sources=[dict(id=native[0]['id'], resolution_m=5, tiles=1)]
                                           if z in ZOOMS else [])
                              for z in range(8, 18)}),
            bounds=bounds, minzoom=ZOOMS[0], maxzoom=ZOOMS[-1], center=(ZOOMS[0], (w + e) / 2, (s + n) / 2))

    def zone_fixture(out):
        west, south, east, north = bounds
        edges = np.linspace(west, east, len(selected) + 1)
        write_json(out / 'detail.geojson', dict(type='FeatureCollection', region=REGION, features=[
            dict(type='Feature', geometry=mapping(box(edges[i], south, edges[i + 1], north)),
                 properties=dict(tier='estimated', source_id=row['source_id'])) for i, row in enumerate(selected)]))

    select_ref, mosaic_ref = receipts.Ref('select'), receipts.Ref('mosaic', 'public')
    stages = (
        receipts.StageRun(region, 'select', select_fixture, 'a' * 64,
                          plan=receipts.Plan([receipts.Input(config, 'region'), *(
                              receipts.Input(region.dir / Path(row['path']).name, f"grid:{row['id']}")
                              for row in selected)])),
        receipts.StageRun(region, 'mosaic', mosaic_fixture, 'b' * 64, scope='public', upstream=[select_ref]),
        receipts.StageRun(region, 'tiles', tiles_fixture, 'c' * 64, scope='public', target='layers/public/tiles',
                          upstream=[select_ref, mosaic_ref],
                          plan=receipts.Plan([receipts.Input(mosaic_dir / 'elevation.tif', 'elevation')])),
        receipts.StageRun(region, 'zone', zone_fixture, 'd' * 64, scope='public', target='layers/public/zone',
                          upstream=[select_ref, mosaic_ref]),
    )
    for stage in stages:
        verdict = receipts.run_stage(stage)
        assert verdict.state == 'ok', verdict.line()
    assert read_json(mosaic_dir / 'manifest.json')['status'] == 'review_required'
    return mosaic_dir


@pytest.fixture
def reviewed_release(tmp_path, monkeypatch):
    region = receipts.Region(tmp_path.resolve() / 'out', REGION)
    tile_ids = [(14, 2690, 6464), (15, 5380, 12928)]
    bounds = [round(v, 7) for v in transform_bounds('EPSG:3857', 'EPSG:4326',
              *array_bounds(256, 256, qa._tile_grid(*tile_ids[0])))]
    root = tmp_path / 'config'
    config = root / 'regions' / REGION / 'region.json'
    point = dict(longitude=(bounds[0] + bounds[2]) / 2, latitude=(bounds[1] + bounds[3]) / 2)
    write_json(config, dict(
        id=REGION, schema_version=1, name='Synthetic coast', status='draft', timezone='Etc/UTC',
        bounds=bounds, fishing_bounds=bounds, jurisdiction='Fixture', jurisdiction_id='fixture',
        boat=dict(name='Fixture boat', bottom_depth_limit_ft=300, cruise_knots=10),
        harbor=dict(**point, name='Fixture harbor', information_url='https://example.org/', watch_keywords=[]),
        stations=dict(tide='0000001', airport='TEST', nearshore_buoy='TEST1', offshore_buoy='TEST2',
                      nearshore_buoy_name='Nearshore fixture', offshore_buoy_name='Offshore fixture'),
        marine_zones=dict(coastal='TST001', offshore='TST002'),
        forecast_points=[dict(**point, id='fixture', name='Fixture point')], species=['fixture-target'],
        source_bindings={'bathymetry': list(FAMILIES)}, pipeline_sources={},
        assets=dict(atlas=None, habitats=None, bottom_index=None, regulations='fixture.json'),
        landing_names=[], mpa=dict(bounds=bounds, minimum_features=0), map={}, coverage={}, coverage_note='Fixture'))
    write_json(root / 'dist/fixture.json', {'area_notices': []})
    write_json(root / 'catalog/data-needs.json', {'schema_version': 1, 'needs': [{'id': 'bathymetry'}]})
    write_json(root / 'catalog/targets.json', {'targets': {'fixture-target': dict(
        name='Fixture target', kind='reef', control_mode='bottom', source_species=['fixture'], habitat_kinds=[])}})
    registry = [dict(id=sid, name=f'Synthetic {sid}', needs=['bathymetry'], review_status='approved',
                     vertical_datum='MLLW', survey_year=2020, native_resolution_m=cell_m,
                     documentation_url=f'https://example.org/{sid}',
                     rights=dict(public_display='allowed', license='public-domain', attribution=f'Synthetic {sid}',
                                 commercial_use='allowed', attribution_required=False, terms_url='https://example.org/'))
                for sid, cell_m in FAMILIES.items()]
    write_json(root / 'catalog/sources.json', {'schema_version': 1, 'sources': registry})
    schema = root / 'catalog/relief/pointer.schema.json'
    schema.parent.mkdir()
    shutil.copyfile(ROOT / 'catalog/relief/pointer.schema.json', schema)
    # Load the real contour tool before pointing its adapter at the synthetic region/catalog.
    tool = contours.producer()
    monkeypatch.setattr(contours, 'producer', lambda: tool)
    for module in (package, qa, envelope, contours):
        monkeypatch.setattr(module, 'repo_root', lambda: root)
    mosaic_dir = seed_upstream(region, config, bounds, tile_ids, registry)

    def run(stage, *args):
        assert cli.main([stage, '--out', str(region.out_root), '--region', REGION, *map(str, args)]) == 0
        verdict = receipts.check(region, stage)
        assert verdict.done and verdict.receipt is not None, verdict.reason
        return verdict.receipt['generation']

    run('digests')
    run('inventory')
    generation = run('package', '--manifest', region.dir / 'inventory/manifest.json', '--upstream', 'tiles:public',
                     '--upstream', 'digests', '--upstream', 'zone:public', '--upstream', 'inventory')
    release_dir = region.dir / 'release' / generation
    release = release_dir / 'release.json'
    release_sha = receipts.sha256_file(release)
    run('contours')
    monkeypatch.setattr(shots, 'capture', lambda cmd, **kw: stub_node_capture(cmd, blank_chart=False, **kw))
    shot_gen = run('shots', '--basemap', FIXTURES / 'basemap/tiny.pmtiles')
    run('qa', '--generation', generation, '--release-sha256', release_sha,
        '--upstream', 'mosaic:public', '--elevation', mosaic_dir / 'elevation.tif',
        '--contributor', mosaic_dir / 'contributor.tif', '--support', mosaic_dir / 'support_class.tif',
        '--shots', region.dir / 'shots' / shot_gen / 'shots.json')
    run('envelope', '--generation', generation)
    return release_dir, region.dir / 'qa' / generation / 'qa.json', region.dir / 'review' / generation / 'envelope.json'


@pytest.mark.parametrize('wrong_digest', [False, True], ids=['matching-approval', 'wrong-envelope-digest'])
def test_morro_publish_plan(reviewed_release, tmp_path, wrong_digest):
    # An estimated-only release must not need fine proof, but must still be approved for its exact bytes.
    release_dir, qa_path, envelope_path = reviewed_release
    release = read_json(release_dir / 'release.json')
    assert {s['id']: s['label'] for s in release['sources']} == dict.fromkeys(FAMILIES, 'estimated')
    assert (release['minzoom'], release['maxzoom']) == ZOOMS
    support = release['native_support_by_zoom']
    assert {int(z) for z, row in support.items() if row['tiles']} == set(ZOOMS)
    assert all(not support[str(z)]['sources'] for z in (16, 17))
    assert all(band['support_class'] == 2 for band in release['detail_summary']['depth_bands'])
    summary = read_json(qa_path)
    assert summary['status'] == 'PASS'
    metrics = summary['metrics']
    assert metrics['measured_label_uncertified_cells'] == metrics['z16plus_uncertified_pixels'] == 0
    assert {int(z): row['count'] for z, row in metrics['tile_bytes_by_zoom'].items()} == dict.fromkeys(ZOOMS, 1)
    assert metrics['contour_count_by_interval_ft']
    assert summary['shots']['cameras'] == list(ZOOMS)

    scope = tmp_path / 'RELIEF-PUBLISH-SCOPE'
    scope.write_text(f'{REGION}\n', encoding='utf-8')
    approval = tmp_path / 'approval.json'
    digest = receipts.sha256_file(envelope_path)
    claimed = '0' * 64 if wrong_digest else digest
    write_json(approval, dict(envelope_sha256=claimed, verdict=f'APPROVED release {REGION} envelope={claimed}'))
    if wrong_digest:
        with pytest.raises(package.ReleaseError, match='^envelope sha256 does not match approval$'):
            publish.plan(release_dir, approval, envelope_path, scope_path=scope)
        return

    plan = publish.plan(release_dir, approval, envelope_path, scope_path=scope)
    assert plan.envelope_sha256 == digest
    root = read_json(plan.region_dir / package.DIGEST_ROOT)
    assert {int(chunk.split('/')[0]) for chunk in root['chunks']} == set(ZOOMS)
    archive = plan.region_dir / package.ARCHIVE
    sha = receipts.sha256_file(archive)
    stem = f'tiles/relief/{REGION}/{sha}'
    index = f'{stem}.digests/{release["digest_root_sha256"]}'
    assert {obj.key: obj.sha256 for obj in plan.objects} == {
        f'{stem}.pmtiles': sha, f'{index}/root.json': release['digest_root_sha256'],
        **{f'{index}/{chunk}': pin for chunk, pin in root['chunks'].items()},
    }
    assert not plan.receipt_path.exists()
