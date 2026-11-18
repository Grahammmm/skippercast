"""R7 accepts only the hash-pinned bytes that pass its independent checks."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import array_bounds
from rasterio.warp import transform_bounds
from shapely.geometry import box, mapping

from scripts import build_bathy_tiles as tiles
from scripts.relief import region as cli
from skippercast.relief import envelope, package, qa, receipts
from tests._support import ROOT

REGION = 'morro-bay'
ARCHIVE = 'layers/public/relief.pmtiles'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(receipts.canonical(value))


def raster(path, grid, values, nodata):
    with rasterio.open(path, 'w', driver='GTiff', crs='EPSG:3857', transform=grid, width=256, height=256,
                       count=len(values), dtype=values.dtype, nodata=nodata) as ds:
        ds.write(values)


def setup_case(tmp, monkeypatch, fault):
    region = receipts.Region(tmp, REGION)
    z, x, y = 17, 21522, 51712
    grid = qa._tile_grid(z, x, y)
    w, s, e, n = array_bounds(256, 256, grid)
    bounds = [round(v, 7) for v in transform_bounds('EPSG:3857', 'EPSG:4326', w, s, e, n)]
    rights = {'public_display': 'allowed', 'license': 'public-domain'}
    contract = tmp / 'config'
    write_json(contract / 'regions' / REGION / 'region.json', {'bounds': [bounds[0] - .001, bounds[1] - .001,
                                                                         bounds[2] + .001, bounds[3] + .001]})
    write_json(contract / 'catalog/sources.json', {'sources': [{'id': 'synthetic', 'review_status': 'approved', 'rights': rights}]})
    write_json(contract / 'catalog/relief/pointer.schema.json', package.decode_document(
        (ROOT / 'catalog/relief/pointer.schema.json').read_bytes()))
    for module in (package, qa, envelope):
        monkeypatch.setattr(module, 'repo_root', lambda: contract)

    def evidence(out):
        depth = np.full((1, 256, 256), -8, dtype='float32')
        depth[0, 24, 24] = 4
        raster(out / 'elevation.tif', grid, depth, -9999)
        raster(out / 'contributor.tif', grid, np.ones(depth.shape, dtype='uint16'), 0)
        support = np.full(depth.shape, 3, dtype='uint8')
        if fault == 'measured_label_uncertified_cells':
            support[0, 42, 42] = 1
        raster(out / 'support_class.tif', grid, support, 0)
        proof = np.concatenate((np.full_like(depth, 3), depth, np.full_like(depth, .5)))
        if fault == 'z16plus_uncertified_pixels':
            proof[0, 42, 42] = 2
        elif fault == 'z16plus_depth':
            proof[1, 42, 42] = -20.01
        elif fault == 'z16plus_spacing':
            proof[2, 42, 42] = 1.01
        raster(out / 'z17.tif', grid, proof, -9999)

    assert receipts.run_stage(receipts.StageRun(region, 'evidence', evidence, 'a' * 64,
                                                scope='public')).state == 'ok'
    evidence_dir = region.dir / 'evidence/public'

    def archive(out):
        rgba = np.full((256, 256, 4), 128, dtype='uint8')
        rgba[:, :, 3] = 255
        rgba[24, 24, 3] = 1 if fault == 'land_leak_pct' else 0
        desc = 'Synthetic NOT FOR NAVIGATION.' if fault != 'not_for_navigation' else 'Synthetic relief.'
        tiles.write_pmtiles(out / 'relief.pmtiles', {(z, x, y): tiles.encode_png(rgba)},
                            metadata={'description': desc}, bounds=bounds, minzoom=z, maxzoom=z,
                            center=(z, (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2))
        px, py = grid @ (42, 42)
        geometry = mapping(box(*transform_bounds('EPSG:3857', 'EPSG:4326', px, py + grid.e, px + grid.a, py)))
        write_json(out / 'detail.geojson', {'type': 'FeatureCollection', 'region': REGION,
            'features': [{'type': 'Feature', 'geometry': geometry, 'properties': {'tier': '1m-measured'}}]})
        line = {'type': 'LineString', 'coordinates': [[bounds[0], bounds[1]], [bounds[2], bounds[3]]]}
        # Producer-format native replacement and an ancillary survey edge:
        # one counts in the 60-ft tier, the other is not a contour.
        write_json(out / 'contours.geojson', {'type': 'FeatureCollection',
            'provenance': {'region_id': REGION, 'set': 'ft-v2', 'units': 'ft'}, 'features': [
                {'type': 'Feature', 'properties': {'kind': 'contour', 'minzoom': 14, 'depth_ft': 60}, 'geometry': line},
                {'type': 'Feature', 'properties': {'kind': 'survey-edge', 'minzoom': 8}, 'geometry': line}]})

    assert receipts.run_stage(receipts.StageRun(region, 'tiles', archive, 'b' * 64, scope='public',
                                                target='layers/public')).state == 'ok'
    sources = [{'id': 'synthetic', 'attribution': 'Synthetic survey', 'rights_class': 'public', 'label': 'measured',
                'vertical_datum': 'NAVD88', 'survey_dates': ['2020'], 'rights': rights}]
    assembly = tmp / 'assembly.json'
    write_json(assembly, {'region': REGION, 'bounds': bounds, 'minzoom': z, 'maxzoom': z, 'sources': sources,
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': 'synthetic', 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': .5, 'support_class': 3}]},
        'native_support_by_zoom': {'17': {'tiles': 1, 'limit_m': 20, 'support_class': 3,
                                           'sources': [{'id': 'synthetic', 'tiles': 1, 'resolution_m': .5}]}},
        'layer_paths': ['layers/public/contours.geojson', 'layers/public/detail.geojson', ARCHIVE]})

    def run(stage, *argv):
        return cli.main([stage, '--out', str(tmp), '--region', REGION, *map(str, argv)])

    assert run('digests') == 0
    digest_receipt = receipts.read_receipt(region.receipt_path('digests'))
    assert digest_receipt is not None
    doc = package.decode_document(assembly.read_bytes())
    doc['layer_paths'].extend(r['path'] for r in digest_receipt['outputs'])
    write_json(assembly, doc)
    if fault == 'sources_all_public':
        # Package itself already refuses this. Simulate a different writer that
        # emitted a hash-current package anyway to verify QA's separate gate.
        def bad_package(out):
            pending = receipts.read_receipt(region.receipt_path('package'))
            assert pending is not None
            write_json(out / 'release.json', dict(doc,
                private=True, sources=[dict(sources[0], rights_class='private')], schema=package.RELEASE_SCHEMA,
                generation=pending['generation'], digest_root_sha256=receipts.sha256_file(region.dir / package.DIGEST_ROOT),
                layers=[package.layer_record(region.dir, p) for p in sorted(doc['layer_paths'])]))
        assert receipts.run_stage(receipts.StageRun(region, 'package', bad_package, 'c' * 64,
                                                    target='release/{generation}')).state == 'ok'
    else:
        assert run('package', '--manifest', assembly, '--upstream', 'tiles:public', '--upstream', 'digests') == 0
    gen = receipts.read_receipt(region.receipt_path('package'))['generation']
    release = region.dir / 'release' / gen / 'release.json'
    digest = receipts.sha256_file(release)
    shot_manifest = tmp / 'capture' / 'shots.json'
    shots = []
    for device, (width, height) in (('desktop', (1200, 800)), ('phone', (390, 844))):
        # Synthetic PNGs exercise pack binding; no browser or web is needed in CI.
        png = tiles.encode_png(np.zeros((height, width, 4), dtype='uint8'))
        for theme in ('dark', 'light'):
            path = f'shots/{theme}-{device}-z17.png'
            local = shot_manifest.parent / path
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(png)
            shots.append(dict(path=path, zoom=z, theme=theme, device=device, viewport=[width, height],
                              sha256=receipts.sha256_bytes(png), navigation_visible=True))
    write_json(shot_manifest, {'renderer': 'mb08-chart', 'release_sha256': digest, 'cameras': [z], 'shots': shots,
        'center': [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]})
    if fault == 'shots':
        (shot_manifest.parent / shots[0]['path']).write_bytes(b'changed')
    expected = '0' * 64 if fault == 'release_sha256' else digest
    args = ['--generation', gen, '--release-sha256', expected, '--upstream', 'evidence:public',
            '--elevation', evidence_dir / 'elevation.tif', '--contributor', evidence_dir / 'contributor.tif',
            '--support', evidence_dir / 'support_class.tif', '--shots', shot_manifest]
    if fault != 'missing_fine_proof':
        args += ['--fine-proof', z, evidence_dir / 'z17.tif']
    return region, gen, digest, run, args


@pytest.mark.parametrize(('fault', 'metric'), [
    ('land_leak_pct', 'land_leak_pct'), ('sources_all_public', 'sources_all_public'),
    ('z16plus_uncertified_pixels', 'z16plus_uncertified_pixels'), ('z16plus_depth', 'z16plus_uncertified_pixels'),
    ('z16plus_spacing', 'z16plus_uncertified_pixels'), ('missing_fine_proof', 'z16plus_uncertified_pixels'),
    ('measured_label_uncertified_cells', 'measured_label_uncertified_cells'),
    ('release_sha256', 'release_sha256'), ('not_for_navigation', 'not_for_navigation'), ('shots', 'shots'),
])
def test_bad_release_fails_by_metric(tmp_path, monkeypatch, fault, metric):
    region, gen, _, run, args = setup_case(tmp_path, monkeypatch, fault)
    assert run('qa', *args) == 1
    status = receipts.check(region, 'qa')
    assert status.state == 'failed' and metric in status.reason
    assert not (region.dir / 'qa' / gen / 'qa.json').exists()
    assert run('envelope', '--generation', gen) == 3


def test_good_release_is_idempotent_and_envelope_binds_exact_qa(tmp_path, monkeypatch):
    region, gen, digest, run, args = setup_case(tmp_path, monkeypatch, None)
    assert run('qa', *args) == 0
    pack = region.dir / 'qa' / gen
    summary = package.decode_document((pack / 'qa.json').read_bytes())
    assert summary['status'] == 'PASS' and summary['release_sha256'] == digest
    assert summary['metrics']['z16plus_uncertified_pixels'] == 0
    assert summary['metrics']['measured_label_uncertified_cells'] == 0
    assert summary['metrics']['transparent_share'] == 1 / 256 ** 2
    assert summary['metrics']['contour_count_by_interval_ft'] == {'60': 1}
    assert summary['metrics']['tile_bytes_by_zoom']['17']['count'] == 1
    assert len(summary['shots']['entries']) == 4
    row_id, board, title, prompt = (pack / 'localfeed.tsv').read_text().splitlines()[0].split('\t')
    assert board == 'skippercast' and row_id.endswith(digest) and 'review required' in title and 'non-blocking' in prompt
    assert run('qa', *args) == 0
    assert receipts.check(region, 'qa').receipt['attempt'] == 1
    assert run('envelope', '--generation', gen) == 0
    review = package.decode_document((region.dir / 'review' / gen / 'envelope.json').read_bytes())
    assert review['qa']['sha256'] == receipts.sha256_file(pack / 'qa.json')
    assert review['release']['sha256'] == digest
    (pack / summary['shots']['entries'][0]['path']).write_bytes(b'tampered')
    assert not receipts.check(region, 'envelope').done


def test_source_edge_across_tile_boundary_uses_actual_paint(tmp_path):
    z, x, y = 13, 1345, 3232
    grid = qa._tile_grid(z, x, y)
    extent = array_bounds(256, 512, grid)
    bounds = transform_bounds('EPSG:3857', 'EPSG:4326', *extent)
    archive = tmp_path / 'relief.pmtiles'
    rgb = np.full((256, 256, 4), 255, dtype='uint8')
    rgb[:, :, :3] = 100
    a = tiles.encode_png(rgb)
    rgb[:, :, :3] = 160
    b = tiles.encode_png(rgb)
    tiles.write_pmtiles(archive, {(z, x, y): a, (z, x + 1, y): b}, metadata={}, bounds=bounds,
                        minzoom=z, maxzoom=z, center=(z, bounds[0], bounds[1]))
    elevation = tmp_path / 'elev.tif'
    contributor = tmp_path / 'contributor.tif'
    with rasterio.open(elevation, 'w', driver='GTiff', crs='EPSG:3857', transform=grid, width=512, height=256,
                       count=1, dtype='float32') as ds:
        ds.write(np.full((256, 512), -8, dtype='float32'), 1)
    with rasterio.open(contributor, 'w', driver='GTiff', crs='EPSG:3857', transform=grid, width=512, height=256,
                       count=1, dtype='uint16') as ds:
        ds.write(np.tile(np.repeat([1, 2], 256), (256, 1)).astype('uint16'), 1)
    with rasterio.open(elevation) as depth, rasterio.open(contributor) as owner:
        metrics, failures = qa._raster_metrics(archive, dict(bounds=bounds, minzoom=z, maxzoom=z), bounds, depth, owner, {})
    assert failures == ['seam_delta_lstar']
    assert metrics['seam_delta_lstar']['edge_pairs'] == 256
    assert metrics['seam_delta_lstar']['max'] > 20
