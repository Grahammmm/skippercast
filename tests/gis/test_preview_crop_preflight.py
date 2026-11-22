"""Synthetic evidence, evaluated with the tracked Big Sur camera recipe."""
import json

from scripts.relief import preview_crop_preflight

REGION = 'big-sur-coast'
HARBOR = f'{REGION}/monterey-harbor-distant-planning-origin-z13'
BIG_SUR = f'{REGION}/big-sur-north-z15'
HARBOR_RING = [(-121.92, 36.58), (-121.86, 36.58), (-121.86, 36.63),
               (-121.92, 36.63), (-121.92, 36.58)]
BIG_SUR_RING = [(-121.998, 36.263), (-121.982, 36.263), (-121.982, 36.277),
                (-121.998, 36.277), (-121.998, 36.263)]


def _run(tmp_path, capsys, big_sur_rings):
    footprint = tmp_path / 'package.geojson'
    footprint.write_text(json.dumps({
        'type': 'Feature', 'properties': {},
        'geometry': {'type': 'MultiPolygon', 'coordinates': [[HARBOR_RING], big_sur_rings]},
    }), encoding='utf-8')
    status = preview_crop_preflight.main(['--region', REGION, '--footprint', str(footprint)])
    return status, capsys.readouterr().out.splitlines()


def test_fully_contained_squares(tmp_path, capsys):
    # Treating size_m as a radius instead of the full side rejects the tight
    # Big Sur ring; checking only the first loaded camera omits its result.
    status, lines = _run(tmp_path, capsys, [BIG_SUR_RING])
    assert status == 0
    assert lines == [f'CONTAINED {camera} uncovered_m2=0; edge_shortfall_m=0'
                     for camera in (HARBOR, BIG_SUR)]


def test_center_inside_but_corner_outside(tmp_path, capsys):
    # The center and footprint bbox still pass, but a diagonal removes the
    # SW corner and part of two edges. Require the actual metric shortfall.
    clipped_ring = [(-121.992, 36.263), *BIG_SUR_RING[1:4],
                    (-121.998, 36.269), (-121.992, 36.263)]
    status, (_, result) = _run(tmp_path, capsys, [clipped_ring])
    assert status == 1
    prefix = f'SHORTFALL {BIG_SUR} uncovered_m2='
    assert result.startswith(prefix)
    area, edges = result.removeprefix(prefix).split('; edge_shortfall_m=')
    lengths = dict(edge.split(':') for edge in edges.split(','))
    assert float(area) > 0
    assert 0 < float(lengths['west']) < 600
    assert 0 < float(lengths['south']) < 600
    assert float(lengths['east']) == float(lengths['north']) == 0


def test_footprint_hole_inside_crop(tmp_path, capsys):
    # A four-corner or perimeter-only test misses this off-center hole.
    hole = [(-121.988, 36.271), (-121.987, 36.271), (-121.987, 36.272),
            (-121.988, 36.272), (-121.988, 36.271)]
    status, (_, result) = _run(tmp_path, capsys, [BIG_SUR_RING, hole])
    assert status == 1
    prefix = f'SHORTFALL {BIG_SUR} uncovered_m2='
    assert result.startswith(prefix)
    area, edges = result.removeprefix(prefix).split('; edge_shortfall_m=')
    assert 9_000 < float(area) < 11_000
    assert edges == 'west:0,south:0,east:0,north:0'


def test_missing_footprint_is_unknown(tmp_path, capsys):
    # Missing evidence must not silently pass using the config bounds instead.
    missing = tmp_path / 'not-supplied.geojson'
    assert preview_crop_preflight.main(['--region', REGION, '--footprint', str(missing)]) == 2
    assert capsys.readouterr().out.splitlines() == [
        f'UNKNOWN {camera} footprint missing; uncovered_m2=unknown; edge_shortfall_m=unknown'
        for camera in (HARBOR, BIG_SUR)
    ]
