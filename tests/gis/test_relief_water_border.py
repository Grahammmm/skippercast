"""Exercise the optional water boundary at the real region receipt boundary."""

import json

import pytest
from shapely import orient_polygons
from shapely.geometry import Point, Polygon, box, mapping, shape

from scripts.relief import region as cli
from skippercast.relief import border, receipts, water
from tests.gis.test_relief_water_stage import (
    _BOUNDS, _DECOY, _EAST, _REGION, _WEST, _expected, _inputs, _receipt, _receipt_path, _run, _sha,
    held,  # noqa: F401 - original stage fixture
)

_SLICE = Polygon([(-120.1, 38.005), (-119.85, 38.05), (-119.85, 38.1), (-120.1, 38.1)])
_ALL = Polygon([(-120.1, 37.9), (-119.85, 37.91), (-119.85, 38.15), (-120.1, 38.15)])
_NONE = Polygon([(-120.1, 38.08), (-119.85, 38.09), (-119.85, 38.15), (-120.1, 38.15)])
_EMPTY = {'type': 'FeatureCollection', 'features': []}
_PARAMS = {'close_m': 'max stated HOR_ACC', 'connect_m': 250.0}


def _boundary(held, geometry):
    path = held.root / 'reviewed.geojson'
    path.write_text(json.dumps(mapping(geometry)), encoding='utf-8')
    return path


def _clipped(held, boundary, out=None):
    return cli.main(['water', '--out', str(out or held.out), '--region', _REGION,
                     '--region-config', str(held.config), '--shoreline-manifest', str(held.manifest),
                     '--us-boundary', str(boundary)])


def _bytes(doc):
    return receipts.canonical(doc) + b'\n'


def _outputs(region, *names):
    paths = [region / 'water' / name for name in names]
    assert sorted(p.name for p in paths[0].parent.iterdir()) == list(names)
    return [{'path': f'water/{p.name}', 'sha256': _sha(p), 'bytes': p.stat().st_size} for p in paths]


def _boundary_input(path, digest):
    return {'path': str(path), 'role': 'us-boundary', 'sha256': digest}


@pytest.mark.parametrize('boundary_shape,has_inside,has_outside', [
    pytest.param(_SLICE, True, True, id='C1: split at a sloped jurisdiction seam'),
    pytest.param(_ALL, True, False, id='C1: omit an empty outside remainder'),
    pytest.param(_NONE, False, True, id='C1: emit no inside features when all water is outside'),
])
def test_c1_receipted_split(held, boundary_shape, has_inside, has_outside):
    """C1: Ignoring the boundary, swapping the two parts or retaining a stale outside file changes the result."""
    # The full-coverage run replaces a prior split in the same output directory.
    before = None
    if not has_outside:
        assert _clipped(held, _boundary(held, _SLICE)) == 0
        before = _receipt(held.region)['generation']
    path = _boundary(held, boundary_shape)
    assert _clipped(held, path) == 0
    receipt = _receipt(held.region)
    assert (receipt['status'], receipt['rc'], receipt['held_reason'], receipt['error']) == ('ok', 0, None, None)
    assert receipt['inputs'] == [*_inputs(held), _boundary_input(path, _sha(path))]
    names = ('outside-us.geojson', 'water.geojson', 'water.json') if has_outside else ('water.geojson', 'water.json')
    assert receipt['outputs'] == _outputs(held.region, *names)

    original, _ = _expected(held)
    inside, outside = border.clip_to_us(original, boundary_shape)
    target = held.region / 'water'
    expected = water.to_geojson(inside, _REGION) if has_inside else _EMPTY
    assert (target / 'water.geojson').read_bytes() == _bytes(expected)
    if has_outside:
        assert (target / 'outside-us.geojson').read_bytes() == _bytes({
            'type': 'Feature', 'properties': {'tier': 'none', 'reason': 'outside-us-waters'},
            'geometry': mapping(orient_polygons(outside)),
        })
    if before is not None:
        assert receipt['generation'] != before
    if has_inside and has_outside:
        emitted = shape(json.loads((target / 'water.geojson').read_bytes())['features'][0]['geometry'])
        # Same latitude, different sides of the sloped seam: a latitude cut cannot pass.
        assert [emitted.contains(Point(lon, 38.026)) for lon in (-119.99, -119.97)] == [True, False]


def test_c1_changed_boundary_after_receipt_hash(held, monkeypatch):
    """C1: A valid replacement loaded after hashing must not pass under the old SHA-256."""
    path = _boundary(held, _SLICE)
    expected = _sha(path)
    real_build = water.build

    def replace_before_loading(ctx, out_dir):
        _boundary(held, _ALL)
        return real_build(ctx, out_dir)

    monkeypatch.setattr(water, 'build', replace_before_loading)
    assert _clipped(held, path) == 4
    receipt = _receipt(held.region)
    assert receipt['inputs'] == [*_inputs(held), _boundary_input(path, expected)]
    assert (receipt['status'], receipt['held_reason'], receipt['error'], receipt['outputs']) == (
        'held', f'SHA-256 mismatch for US-waters boundary: expected {expected}, observed {_sha(path)}', None, [],
    )
    assert not (held.region / 'water').exists()


def test_c1_missing_boundary(held, capsys):
    """C1: A missing explicit input cannot silently select the no-boundary path."""
    path = held.root / 'missing.geojson'
    assert _clipped(held, path) == 3
    assert capsys.readouterr() == (f'[water] BLOCKED generation -: input missing: {path}\n', '')
    assert not _receipt_path(held.region).exists()
    assert not (held.region / 'water').exists()


def test_c2_no_boundary_bytes(held):
    """C2: An opt-in default or added receipt param must not alter the original build bytes."""
    assert _run(held) == 0
    receipt = _receipt(held.region)
    assert receipt['inputs'] == _inputs(held)
    assert receipts.canonical(receipt['params']) == b'{"close_m":"max stated HOR_ACC","connect_m":250.0}'
    assert receipt['outputs'] == _outputs(held.region, 'water.geojson', 'water.json')
    ocean, report = _expected(held)
    target = held.region / 'water'
    assert (target / 'water.geojson').read_bytes() == _bytes(water.to_geojson(ocean, _REGION))
    assert (target / 'water.json').read_bytes() == _bytes({
        'region': _REGION, 'region_bounds_wgs84': _BOUNDS, 'frame_wgs84': _BOUNDS,
        'close_m': 18.0, 'connect_m': 250.0, 'hor_acc_values_m': [2.0, 4.31, 18.0],
        'unavailable_tiles': [_WEST], 'report': report,
        'inputs': {'manifest_sha256': _sha(held.manifest),
                   'tiles': [{'tile': name, 'sha256': _sha(held.tile_path(name))} for name in (_EAST, _DECOY)]},
    })


def test_c2_refused_boundary(held, capsys):
    """C2: A loader refusal must not become a generic failure or an unclipped success."""
    west, south, east, north = _BOUNDS
    path = _boundary(held, box(west, south, east, north))
    reason = 'US-waters boundary cannot consist only of axis-aligned edges'
    assert _clipped(held, path) == 4
    receipt = _receipt(held.region)
    assert capsys.readouterr() == (f'[water] HELD generation {receipt["generation"][:12]}: {reason}\n', '')
    assert receipt['inputs'] == [*_inputs(held), _boundary_input(path, _sha(path))]
    assert receipt['params'] == _PARAMS
    assert (receipt['status'], receipt['rc'], receipt['held_reason'], receipt['error'], receipt['outputs']) == (
        'held', None, reason, None, [],
    )
    assert not (held.region / 'water').exists()


def test_c3_identical_boundary_outputs(held, capsys):
    """C3: A second fresh build must not encode output-path or timing differences."""
    path = _boundary(held, _SLICE)
    other = held.root / 'fresh-out'
    assert _clipped(held, path) == _clipped(held, path, other) == 0
    capsys.readouterr()
    receipt = _receipt(held.region)
    fresh = _receipt(other / _REGION)
    assert (fresh['generation'], fresh['inputs'], fresh['outputs']) == (
        receipt['generation'], receipt['inputs'], receipt['outputs'],
    )
    receipt_bytes = _receipt_path(held.region).read_bytes()
    assert _clipped(held, path) == 0
    assert capsys.readouterr() == (
        f'[water] DONE generation {receipt["generation"][:12]}: no work: receipt ok, outputs re-hash, upstream current\n',
        '',
    )
    assert _receipt_path(held.region).read_bytes() == receipt_bytes
    for row in receipt['outputs']:
        assert (held.region / row['path']).read_bytes() == (other / _REGION / row['path']).read_bytes()
