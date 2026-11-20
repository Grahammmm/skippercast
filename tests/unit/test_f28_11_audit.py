"""F28-11: a clipped read cannot support grading the full outline.

Run `python -B -m tests.unit.test_f28_11_audit` with survey dependencies
for the read-only baseline comparison (exit 1 on a contract mismatch).
Required pytest checks exercise the valid control; the known-gap comparison
is opt-in until both graders enforce complete support.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
REGION = 'synthetic'
STAMP = NOW.isoformat()
BOUNDS = [-10, -10, 80, 80]


def _regular(audit, root, features):
    rows = [{'context_id': f['properties']['id'], 'survey_id': 'H000',
             'charted_danger_within_review_buffer': False} for f in features]
    queue = {'scope': 'original-habitat-site-review-queue', 'fishing_target': False,
             'enc_checked_at': STAMP, 'profile_id': REGION,
             'research_shortlist_count': len(rows), 'research_shortlist': rows}
    closures = {'scope': 'original-habitat-shortlist-fresh-closure-audit',
                'fishing_target': False, 'shortlist_count': len(rows), 'held_count': 0,
                'cdfw_retrieved_at': STAMP, 'noaa_retrieved_at': STAMP, 'outlines': rows}
    return audit(queue, {'features': features}, closures, root / 'var/noaa-native-cache', now=NOW)


def _regional(audit, root, features):
    from shapely.geometry import box, mapping

    def write(leaf, data):
        path = root / leaf
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    # Synthetic padding for the snapshot completeness gates; these exclusion
    # geometries are distant from both footprints and cannot cause the hold.
    remote = {'geometry': mapping(box(500, 500, 510, 510)), 'properties': {'area_type': 'GEA'}}
    scope = {'id': REGION, 'region_id': REGION, 'bounds': BOUNDS}
    write('regions/synthetic/region.json', {
        'id': REGION, 'status': 'preview', 'fishing_bounds': BOUNDS,
        'assets': {'protected_areas': 'synthetic-mpa.json'}, 'mpa': {'minimum_features': 1},
    })
    write('dist/data/sf-native-hard-context.geojson', {
        'scope': 'sf-native-noaa-usgs-hard-bottom-context', 'features': features,
    })
    write('dist/synthetic-mpa.json', {'region_id': REGION, 'checked_at': STAMP, 'features': [remote]})
    write('research/catalog/noaa-enc-hazard-scopes.json', {'scopes': [scope]})
    enc = write('enc.json', {'scope_id': REGION, 'region_id': REGION, 'bounds': BOUNDS,
                            'checked_at': STAMP, 'features': [remote],
                            'query_receipts': [{'count': 1}] + [{'count': 0}] * 17})
    federal = write('federal.json', {'scope': 'noaa-west-coast-groundfish-conservation-areas',
                                    'status': 'ok', 'retrieved_at': STAMP, 'features': [remote] * 25})
    return audit(REGION, enc, federal, root=root, now=NOW)


def _replay(grader, root, *, include_edge=False):
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from shapely.geometry import box, mapping

    from research.scripts import audit_regular_shortlist_terrain as regular
    from research.scripts import audit_regional_native_hard_terrain as regional
    from skippercast.platform.bottom_targets import cells_qualified, terrain_metrics

    module, run = {'regular': (regular, _regular), 'regional': (regional, _regional)}[grader]
    bag = root / 'var/noaa-native-cache/H000-synthetic.bag'
    bag.parent.mkdir(parents=True)
    bag.write_bytes(b'synthetic BAG identity only\n')
    props = {'survey_id': 'H000', 'noaa_bag_sha256': sha256(bag.read_bytes()).hexdigest(),
             'native_resolution_m': [2., 2.], 'fishing_target': False, 'exportable': False}
    footprints = {'interior': box(4, 4, 56, 56), 'edge': box(12, 4, 64, 56)}
    assert box(0, 0, 60, 60).covers(footprints['interior'])
    assert not box(0, 0, 60, 60).covers(footprints['edge'])
    assert all(p.area == 2704 for p in footprints.values())  # Above regional 2500 m² floor.
    features = [{'geometry': mapping(poly), 'properties': {**props, 'id': name}}
                for name, poly in footprints.items() if include_edge or name == 'interior']
    yy, xx = np.indices((30, 30))
    depth = (-20 - (xx + yy) / 10).astype('float32')
    uncertainty = np.full_like(depth, .5)
    assert cells_qualified(depth, uncertainty, 2).all()
    # Independently count support in pixel coordinates, not with the grader's
    # requested window. The edge needs 26 columns but has only 24 in the raster.
    inside = np.s_[2:28, 2:28]
    assert depth[inside].size == 676 and depth[2:28, 6:30].size == 624
    expected = terrain_metrics((2 * xx + 1)[inside].ravel(), (59 - 2 * yy)[inside].ravel(),
                               depth[inside].ravel(), [2.] * 676, hard_area_m2=2704)

    # Stub only BAG metadata and reprojection: geometry is already in an
    # invented metric plane. Real GDAL window reads, masks and scoring run.
    parts = [SimpleNamespace(name='UTM zone 10 synthetic'), SimpleNamespace(to_epsg=lambda: 5866)]
    identity = SimpleNamespace(transform=lambda x, y: (x, y))
    with MemoryFile() as memory:
        with memory.open(driver='GTiff', width=30, height=30, count=2, dtype='float32',
                         transform=from_origin(0, 60, 2, 2), crs='EPSG:32610') as raster:
            raster.write(depth, 1)
            raster.write(uncertainty, 2)

        @contextmanager
        def open_fixture(path):
            assert path == bag
            with memory.open() as raster:
                yield SimpleNamespace(driver='BAG', count=raster.count, crs=raster.crs,
                                      res=raster.res, transform=raster.transform, read=raster.read,
                                      width=raster.width, height=raster.height, bounds=raster.bounds,
                                      window_transform=raster.window_transform)

        with (patch.object(module.rasterio, 'open', open_fixture),
              patch.object(module, 'CRS', SimpleNamespace(from_wkt=lambda _: SimpleNamespace(sub_crs_list=parts))),
              patch.object(module, 'Transformer', SimpleNamespace(from_crs=lambda *_a, **_k: identity))):
            rows = {row['context_id']: row for row in run(module.audit, root, features)['rows']}
    return rows, expected


def _check_interior(row, expected):
    assert row['status'] == 'terrain-reviewed'
    assert row['display_area_m2'] == 2704
    assert row['qualified_native_cells'] == 676
    assert row['terrain'] == expected
    stats = row['sampled_original_depth_ft']
    assert (stats['minimum'], stats['median'], stats['maximum']) == (66.9, 75.1, 83.3)


@pytest.mark.gis
@pytest.mark.parametrize('grader', ['regular', 'regional'])
def test_fully_measured_outline_retains_terrain_metrics(grader, tmp_path):
    # Catch an over-broad hold or a change to the complete-support inputs.
    rows, expected = _replay(grader, tmp_path)
    _check_interior(rows['interior'], expected)


def _baseline():
    gap = False
    for grader in ('regular', 'regional'):
        with TemporaryDirectory() as directory:
            rows, expected = _replay(grader, Path(directory), include_edge=True)
        _check_interior(rows['interior'], expected)
        print(f'{grader} interior: PASS; 676/676 centers; 2704 m²; terrain and depth metrics retained')
        edge = rows['edge']
        held = (edge['status'] == 'held-native-cell-gap' and edge['terrain'] is None
                and edge.get('sampled_original_depth_ft') is None)
        gap |= not held
        print(f'{grader} edge: {"PASS" if held else "GAP"}; 624/676 qualified centers available; '
              f'2704 m² outline; expected hold/no metrics; observed {edge["status"]}; '
              f'reported area={edge.get("display_area_m2")}; terrain present={edge["terrain"] is not None}; '
              f'depth present={edge.get("sampled_original_depth_ft") is not None}')
    return int(gap)


if __name__ == '__main__':
    raise SystemExit(_baseline())
