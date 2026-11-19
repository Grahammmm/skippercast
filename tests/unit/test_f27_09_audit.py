"""F27-09: synthetic native raster support, not a grade for a real outline.

Run `python -B -m tests.unit.test_f27_09_audit` with survey dependencies for
the original north-up comparison (exit 1 on a gap).
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
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CASES = (
    ('full-edge-aligned', (0, 0, SIZE, SIZE), 2500, True),
    ('clipped-at-east-edge', (20, 0, 70, SIZE), 1500, False),
    ('fractional-window', (2.75, 2.75, 49.75, 49.75), 2209, True),
    ('touching-west-edge-from-outside', (-SIZE, 0, 0, SIZE), 0, False),
)


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


def _grid(swapped_axes):
    import numpy as np
    from affine import Affine

    rows, cols = np.indices((SIZE, SIZE))
    affine = Affine(0, 2, 1000, 2, 0, 2000) if swapped_axes else Affine(2, 0, 1000, 0, -2, 2000)
    return affine, (-20 - (rows + cols) / 10).astype('float32')


@pytest.mark.gis
@pytest.mark.parametrize('swapped_axes', [False, True], ids=['north-up', 'swapped-axes'])
def test_a_clipped_read_cannot_grade_the_full_outline(swapped_axes):
    # A clipped read can contain only qualified cells and still support just
    # 6,000 of the claimed 10,000 m². A window that rounds lengths also loses
    # the final centers of the fractional footprint, and dropping the affine
    # cross terms maps the swapped-axis grid's centers to the same point.
    assert _replay(CASES, swapped_axes) == 0


def _write_json(root, leaf, obj):
    path = root / leaf
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding='utf-8')
    return path


def _replay(cases, swapped_axes=False):
    import numpy as np
    from rasterio.io import MemoryFile
    from shapely.geometry import mapping
    from research.scripts import audit_native_hard_terrain as terrain

    affine, depth = _grid(swapped_axes)
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
                    {'status': 'preview', 'id': 'bodega-point-reyes', 'fishing_bounds': [850, 1800, 1200, 2200]})
        footprints = {name: _polygon(affine, *bounds) for name, bounds, *_ in cases}
        # Pad the 74-outline envelope with synthetic repeats, not historical inputs.
        features = list(footprints.items())
        features += [features[0]] * (74 - len(features))
        context = _write_json(root, 'dist/data/sf-native-hard-context.geojson', {'features': [
            {'geometry': mapping(footprint), 'properties': {**props, 'id': f'{name}-{i}'}}
            for i, (name, footprint) in enumerate(features)]})
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
                                      width=raster.width, height=raster.height,
                                      window_transform=raster.window_transform)

        with (patch.object(terrain.rasterio, 'open', open_fixture),
              patch.object(terrain, 'CRS', SimpleNamespace(from_wkt=lambda _: SimpleNamespace(sub_crs_list=parts))),
              patch.object(terrain, 'Transformer', SimpleNamespace(from_crs=lambda *_a, **_k: transformer)),
              patch.object(terrain, 'datetime', SimpleNamespace(fromisoformat=datetime.fromisoformat,
                                                               now=lambda _: NOW))):
            rows = {row['context_id']: row for row in terrain.audit(root)['rows']}
        gap = False
        for i, (name, _, count, reviewed) in enumerate(cases):
            row = rows[f'{name}-{i}']
            area = footprints[name].area
            assert row['display_area_m2'] == area
            assert row['native_cells_inside_display'] == row['qualified_native_cells'] == count
            reference_count, expected = _reference(affine, footprints[name], depth)
            assert reference_count == count
            if name == 'full-edge-aligned':
                assert expected is not None
                assert expected['analysis_samples'] == 625
                assert expected['relief_90_percent_m'] == 6.8
                assert expected['score_components']['hard_area'] == 4.167
            actual = row['terrain']
            status = 'terrain-reviewed' if reviewed else 'held-native-cell-gap'
            passed = (actual == expected and row['status'] == status
                      and (row['sampled_original_depth_ft'] is not None) == reviewed)
            gap |= not passed
            print(f'{name}: {"PASS" if passed else "GAP"}; {count} native centers; {area:g} m² claimed; '
                  f'expected {"terrain metrics" if reviewed else "hold"}; observed {row["status"]}; '
                  f'metrics present={actual is not None}')
        return int(gap)


if __name__ == '__main__':
    raise SystemExit(_replay(CASES[:2]))
