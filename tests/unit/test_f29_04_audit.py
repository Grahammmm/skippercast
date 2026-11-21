"""F29-04 / F32-08: a tile boundary must not truncate the research closure screen."""
from datetime import datetime

import pytest

from tests._support import NOW


@pytest.mark.gis  # The reserved unit path exercises the GIS tier only.
@pytest.mark.parametrize('producer', ['source-review', 'research-context'])
@pytest.mark.parametrize(('offset_m', 'source'), [(-2, 'mpa'), (10, 'mpa'), (10, 'gea'), (50, 'gea'), (110, 'gea')])
def test_closure_buffer_survives_tile_split(tmp_path, monkeypatch, producer, offset_m, source):
    from affine import Affine
    import numpy as np
    from pyproj import Transformer
    import rasterio
    from rasterio.features import geometry_mask
    from shapely import transform
    from shapely.geometry import box, mapping, shape

    from research.scripts import audit_nbs_coast_camera_tiles as cameras
    from research.scripts import build_nbs_hard_research_context as context
    from research.scripts import review_nbs_hard_overlap as overlap

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    crs = 'EPSG:32631+5866'  # Synthetic UTM grid with a separate vertical axis, like NBS.
    to_geo = Transformer.from_crs(crs, 4326, always_xy=True).transform
    to_native = Transformer.from_crs(4326, crs, always_xy=True).transform
    grid = Affine(4, 0, 500000, 0, -4, 40)
    layouts = {'whole': (0, 120), 'west': (0, 60), 'east': (60, 120)}
    receipt = tmp_path / 'synthetic-receipt'
    receipt.write_text('synthetic input')
    checked = dict(raster_sha256='synthetic raster', rat_sha256='synthetic RAT',
                   raster_url='https://example.invalid/synthetic.tiff')
    rat = {1: dict(coverage='1', bathy_coverage='1', source_survey_id='synthetic-survey',
                   survey_date_end='2000-01-01')}
    original = dict(release_id='synthetic', kind='seafloor_character', status='ok',
                    archive_sha256='synthetic archive', metadata_sha256='synthetic metadata',
                    metadata_url='https://example.invalid/source', raster_bounds_wgs84=(2, -1, 4, 1))
    for module in (cameras, overlap, context):
        monkeypatch.setattr(module, 'datetime', FrozenDatetime)
    for module in (overlap, context):
        monkeypatch.setattr(module, 'audit', lambda *args: checked)
        monkeypatch.setattr(module, 'contributors', lambda *args: rat)
        monkeypatch.setattr(module, 'original_usgs_class', lambda _, raster, *args: (
            np.ones(raster.shape, dtype=bool), [original]))

    def feature(polygon, **properties):
        return dict(type='Feature', geometry=mapping(transform(polygon, to_geo, interleaved=False)),
                    properties=properties)

    # The straight portion spans every row; the 100 m buffer begins and ends
    # strictly inside columns, not on ambiguous rasterization ties.
    start = 240 + offset_m
    closure = feature(box(500000 + start, -120, 500000 + start + 40, 160),
                      groundfish_candidate_exclusion=True)
    distant = feature(box(501000, -120, 501040, 160), groundfish_candidate_exclusion=True)
    mpa_features = [distant] * 100 + ([closure] if source == 'mpa' else [])
    mpas = {'sources': {'mpas': dict(status='ok', data_retrieved_at=NOW.isoformat(),
                                   data=dict(geojson={'features': mpa_features}, feature_count=len(mpa_features)))}}
    federal = dict(scope='noaa-west-coast-groundfish-conservation-areas', status='ok',
                   retrieved_at=NOW.isoformat(), features=[distant] * 10 + ([closure] if source == 'gea' else []))
    hard = dict(type='FeatureCollection', features=[feature(box(499900, -120, 500600, 160), release_id='synthetic')])
    usgs = dict(scope='usgs-state-waters-doi-native-grid-audit', products=[original])
    allowed = np.array([4 * (col + 1) <= start - 100 or 4 * col >= start + 140 for col in range(120)])
    for tile, (left, right) in layouts.items():
        with rasterio.open(tmp_path / f'{tile}.tiff', 'w', driver='GTiff', crs=crs,
                           width=right - left, height=10, count=3, dtype='float32',
                           transform=grid @ Affine.translation(left, 0)) as dst:
            for band, value in enumerate((-20, 0.5, 1), 1):
                dst.write(np.full(dst.shape, value, dtype='float32'), band)

    def run(tiles):
        windows = [layouts[tile] for tile in tiles]
        expected_counts = [10 * int(allowed[left:right].sum()) for left, right in windows]
        review: dict[str, object] = dict(scheme_sha256=overlap.digest(receipt))
        if producer == 'source-review':
            review.update(scope='coast-nbs-hard-footprint-depth-source-audit', sectors=[dict(
                sector_id='synthetic', reviewed_tiles=[dict(tile=tile, source_audit=checked) for tile in tiles])])
            result = overlap.build(review, receipt, tmp_path, hard, receipt, usgs, receipt, tmp_path, mpas, federal)
            rows = result['sectors'][0]['tiles']
            for key in ('strict_1m_original_class3_unique_pixels', 'sensitivity_2m_original_class3_unique_pixels'):
                assert [row[key] for row in rows] == expected_counts
            assert [row['closure_polygons_intersecting_tile'] for row in rows] == [
                int(start < 4 * right and start + 40 > 4 * left) for left, right in windows]
            return sum(row['sensitivity_2m_original_class3_unique_pixels'] for row in rows)

        # Supply independent counts so a stale upstream review cannot hide the same bug here.
        review.update(scope='central-nbs-usgs-hard-source-review', status='research-leads-only', sectors=[dict(
            sector_id='synthetic', tiles=[dict(tile=tile, source_raster_sha256=checked['raster_sha256'],
                                              source_rat_sha256=checked['rat_sha256'],
                                              sensitivity_2m_original_class3_unique_pixels=pixels)
                                        for tile, pixels in zip(tiles, expected_counts)])])
        result = context.compile_context(review, receipt, tmp_path, hard, usgs, tmp_path, mpas, federal,
                                         sector_ids=('synthetic',), minimum_area_m2=400)
        footprints = [transform(shape(row['geometry']), to_native, interleaved=False) for row in result['features']]
        assert footprints
        return geometry_mask(footprints, out_shape=(10, 120), transform=grid, invert=True)

    whole, tiled = run(['whole']), run(['west', 'east'])
    np.testing.assert_array_equal(tiled, whole)
    if producer == 'research-context':
        display = np.repeat(allowed.reshape(-1, 5).all(axis=1), 5)
        np.testing.assert_array_equal(tiled, np.broadcast_to(display, (10, 120)))
