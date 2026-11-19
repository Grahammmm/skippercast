"""F27-09: synthetic native raster support, not a grade for a real outline.

Run `python -B -m tests.unit.test_f27_09_audit` with survey dependencies for
an opt-in read-only comparison against the unchanged audit (exit 1 on a gap).
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

SIZE = 50
AREA = 10_000
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CASES = (('full-edge-aligned', 0, 2500, True), ('clipped-at-east-edge', 20, 1500, False))


def _polygon(affine, left, top, right, bottom):
    from shapely.geometry import Polygon

    return Polygon([affine @ p for p in ((left, top), (right, top), (right, bottom), (left, bottom))])


def _reference(affine, footprint, depth):
    from shapely.geometry import Point
    from skippercast.platform.bottom_targets import terrain_metrics

    height, width = depth.shape
    # Enumerate only native indices (no virtual/boundless cells), using the
    # full affine on centers; separately require whole-footprint support.
    centers = [(affine @ (col + .5, row + .5), depth[row, col])
               for row in range(height) for col in range(width)]
    inside = [(xy, z) for xy, z in centers if footprint.contains(Point(xy))]
    support = _polygon(affine, 0, 0, width, height)
    if not support.covers(footprint):
        return len(inside), None
    x, y, z = zip(*[(x, y, z) for (x, y), z in inside], strict=True)
    return len(inside), terrain_metrics(x, y, z, [2.0] * len(z), hard_area_m2=footprint.area)


def _grid():
    import numpy as np
    from affine import Affine

    rows, cols = np.indices((SIZE, SIZE))
    return Affine(2, 0, 1000, 0, -2, 2000), (-20 - (rows + cols) / 10).astype('float32')


@pytest.mark.gis
@pytest.mark.parametrize('_name,offset,count,reviewed', CASES, ids=[case[0] for case in CASES])
def test_a_clipped_read_cannot_grade_the_full_outline(_name, offset, count, reviewed):
    affine, depth = _grid()
    footprint = _polygon(affine, offset, 0, offset + SIZE, SIZE)
    assert footprint.area == AREA
    actual_count, metrics = _reference(affine, footprint, depth)
    # All returned cells qualify in both cases. The clipped case still has
    # 6,000 m² of native support, not the claimed 10,000 m².
    assert actual_count == count
    if reviewed:
        assert metrics is not None
        assert metrics['analysis_samples'] == 625
        # The input is a linear ramp. In the 25×25 analysis bins the
        # 5th/95th percentile bin-depth offsets differ by 34 steps of 0.2 m.
        assert metrics['relief_90_percent_m'] == 6.8
        assert metrics['score_components']['hard_area'] == 4.167
    else:
        assert count * 4 == 6000 and metrics is None


def _write_json(root, leaf, obj):
    path = root / leaf
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding='utf-8')
    return path


def _replay():
    import numpy as np
    from rasterio.io import MemoryFile
    from shapely.geometry import mapping
    from research.scripts import audit_native_hard_terrain as terrain

    affine, depth = _grid()
    # Actual synthetic GDAL window reads; only the BAG identity and reprojection
    # prerequisite are stubbed. Inputs are already on the invented metric grid.
    parts = [SimpleNamespace(name='UTM zone 10 synthetic'), SimpleNamespace(to_epsg=lambda: 5866)]
    transformer = SimpleNamespace(transform=lambda x, y: (x, y))
    with TemporaryDirectory() as directory, MemoryFile() as memory:
        root = Path(directory)
        fake_bag = _write_json(root, 'var/noaa-native-cache/H117-synthetic.bag', {'synthetic': True})
        props = {'survey_id': 'synthetic', 'noaa_bag_sha256': sha256(fake_bag.read_bytes()).hexdigest(),
                 'native_resolution_m': [2., 2.], 'fishing_target': False, 'exportable': False}
        _write_json(root, 'regions/bodega-point-reyes/region.json',
                    {'status': 'preview', 'id': 'bodega-point-reyes', 'fishing_bounds': [900, 1800, 1200, 2100]})
        footprints = {name: _polygon(affine, offset, 0, offset + SIZE, SIZE) for name, offset, *_ in CASES}
        # The unchanged audit requires a 74-outline envelope. Repeat the two
        # synthetic geometries to reach it; no work uses any historical inputs.
        context = _write_json(root, 'dist/data/sf-native-hard-context.geojson', {'features': [
            {'geometry': mapping(footprint), 'properties': {**props, 'id': f'{name}-{i}'}}
            for name, footprint in footprints.items() for i in range(37)]})
        _write_json(root, 'research/receipts/bodega-native-enc-scope-review.json', {
            'source_context_sha256': sha256(context.read_bytes()).hexdigest(),
            'research_outlines_in_region': 74, 'outlined_footprints_covered_by_all_scopes': 74,
            'status': 'research-screen-only', 'audited_at': NOW.isoformat(),
            'outlines_near_selected_charted_dangers': [],
        })
        with memory.open(driver='GTiff', width=SIZE, height=SIZE, count=2,
                         dtype='float32', transform=affine, crs='EPSG:32610') as raster:
            raster.write(depth, 1)
            raster.write(np.full_like(depth, .5), 2)

        @contextmanager
        def open_fixture(path):
            assert path == fake_bag
            with memory.open() as raster:
                yield SimpleNamespace(driver='BAG', count=raster.count, crs=raster.crs,
                                      res=raster.res, transform=raster.transform, read=raster.read,
                                      window_transform=raster.window_transform)

        with (patch.object(terrain.rasterio, 'open', open_fixture),
              patch.object(terrain, 'CRS', SimpleNamespace(from_wkt=lambda _: SimpleNamespace(sub_crs_list=parts))),
              patch.object(terrain, 'Transformer', SimpleNamespace(from_crs=lambda *_a, **_k: transformer)),
              patch.object(terrain, 'datetime', SimpleNamespace(fromisoformat=datetime.fromisoformat,
                                                               now=lambda _: NOW))):
            rows = {row['context_id']: row for row in terrain.audit(root)['rows']}
        gap = False
        for name, _, count, reviewed in CASES:
            row = rows[f'{name}-0']
            assert row['display_area_m2'] == AREA
            assert row['native_cells_inside_display'] == row['qualified_native_cells'] == count
            expected = _reference(affine, footprints[name], depth)[1]
            actual = row['terrain']
            passed = actual == expected and (row['status'] == 'terrain-reviewed') == reviewed
            gap |= not passed
            print(f'{name}: {"PASS" if passed else "GAP"}; {count * 4}/{AREA} m² supported; '
                  f'expected {"terrain metrics" if reviewed else "hold"}; observed {row["status"]}; '
                  f'metrics present={actual is not None}')
        return int(gap)


if __name__ == '__main__':
    raise SystemExit(_replay())
