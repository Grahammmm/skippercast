"""Synthetic, offline endpoint observations; never uses admitted coast data."""
import json

import pytest

pytestmark = pytest.mark.gis


def write_json(path, value):
    path.write_text(json.dumps(value) + '\n')


@pytest.fixture
def pair(tmp_path):
    from pyproj import Transformer
    inverse = Transformer.from_crs(
        '+proj=aeqd +lat_0=34 +lon_0=-120 +datum=WGS84 +units=m',
        'EPSG:4326', always_xy=True).transform
    boundary = tmp_path / 'edge.geojson'
    write_json(boundary, dict(type='LineString', coordinates=[inverse(0, -500), inverse(0, 500)]))

    def make(a=None, b=None, resolution=10):
        dirs = [tmp_path / 'a', tmp_path / 'b']
        for directory, rows, sign in zip(dirs, (a, b), (-1, 1)):
            directory.mkdir(exist_ok=True)
            if rows is None:
                rows = [(10, [(sign * 200, -100), (0, -100)]),
                        (20, [(sign * 200, 100), (0, 100)])]
            features = [dict(type='Feature', properties=dict(depth_ft=depth, source_resolution_m=resolution),
                             geometry=dict(type='LineString', coordinates=[inverse(*xy) for xy in points]))
                        for depth, points in rows]
            write_json(directory / 'contours.geojson', dict(type='FeatureCollection', features=features))
            write_json(directory / 'manifest.json', dict(status='review_required',
                       value_convention='elevation_positive_up', contour_crs='EPSG:4326'))
        return *dirs, boundary
    return make


def test_continuous(pair):
    from research.scripts.coast_mvp import coast_seams as seams
    result = seams.observe(*pair())
    assert result['schema'] == 'coast-seam-observation-v1'
    assert (result['band_m'], result['match_m']) == (20, 30)
    assert result['totals'] == dict(a_endpoints=2, b_endpoints=2, matched=2,
                                    unmatched_a=0, unmatched_b=0)
    for row in result['levels']:
        assert row['matched'] == row['a_endpoints'] == row['b_endpoints'] == 1
        assert row['gap_m']['max'] < 0.01
    assert result['levels_one_side_only'] == []
    assert result['vertical_datum'] == 'undeclared'


@pytest.mark.parametrize('shift, matched', [(25, 1), (100, 0)])
def test_offset(pair, shift, matched):
    from research.scripts.coast_mvp import coast_seams as seams
    result = seams.observe(*pair(a=[(10, [(-200, 0), (0, 0)])],
                                b=[(10, [(200, shift), (0, shift)])]))
    row = result['levels'][0]
    assert row['matched'] == matched
    assert row['unmatched_a'] == row['unmatched_b'] == 1 - matched
    if matched:
        assert row['gap_m']['median'] == pytest.approx(25, abs=0.5)
    else:
        assert row['gap_m'] is None


def test_one_side_band_and_closed_ring(pair):
    from research.scripts.coast_mvp import coast_seams as seams
    result = seams.observe(*pair(a=[(30, [(-200, 0), (0, 0)]),
                                   (40, [(-200, 100), (-21, 100)]),
                                   (50, [(0, 0), (-5, 5), (-5, -5), (0, 0)])]))
    assert result['levels_one_side_only'] == [10, 20, 30, 40, 50]
    rows = {row['depth_ft']: row for row in result['levels']}
    assert rows[30]['unmatched_a'] == 1
    assert rows[40]['a_endpoints'] == rows[50]['a_endpoints'] == 0


@pytest.mark.parametrize('field,value', [('value_convention', 'depth_positive_down'),
                                        ('contour_crs', 'EPSG:3857'), ('status', 'accepted')])
def test_convention_refusal(pair, field, value):
    from research.scripts.coast_mvp import coast_seams as seams
    a, b, boundary = pair()
    manifest = json.loads((b / 'manifest.json').read_text())
    manifest[field] = value
    write_json(b / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='^convention_mismatch$'):
        seams.observe(a, b, boundary)


def test_missing_manifest_and_empty_contours(pair):
    from research.scripts.coast_mvp import coast_seams as seams
    a, b, boundary = pair()
    (a / 'manifest.json').unlink()
    with pytest.raises(ValueError, match='^manifest_missing$'):
        seams.observe(a, b, boundary)
    a, b, boundary = pair(a=[])
    with pytest.raises(ValueError, match='^empty_contours$'):
        seams.observe(a, b, boundary)
    (a / 'contours.geojson').write_bytes(b'')
    with pytest.raises(ValueError, match='^empty_contours$'):
        seams.observe(a, b, boundary)


@pytest.mark.parametrize('coordinates', [[[-120, 34]],
    [[-120, 34], [-119.9, 34.1], [-120, 34.1], [-119.9, 34]],
    [[-120, 91], [-120, 92]], [[-120, 34], [-120, 34]]])
def test_invalid_boundary(pair, coordinates):
    from research.scripts.coast_mvp import coast_seams as seams
    a, b, boundary = pair()
    write_json(boundary, dict(type='LineString', coordinates=coordinates))
    with pytest.raises(ValueError, match='^boundary_invalid$'):
        seams.observe(a, b, boundary)


def test_both_wrong_crs(pair):
    from research.scripts.coast_mvp import coast_seams as seams
    a, b, boundary = pair()
    for directory in (a, b):
        path = directory / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['contour_crs'] = 'EPSG:3857'
        write_json(path, manifest)
    with pytest.raises(ValueError, match='^crs_not_4326$'):
        seams.observe(a, b, boundary)


def test_shared_edge():
    from research.scripts.coast_mvp import coast_seams as seams
    a = [-120.1, 33.9, -120, 34.1]
    b = [-120, 34, -119.9, 34.2]
    edge = seams.shared_edge(a, b)
    assert edge == dict(type='LineString', coordinates=[[-120, 34], [-120, 34.1]])
    assert seams.shared_edge(b, a) == edge
    assert seams.shared_edge([-120, 33, -119, 34], [-120, 34, -119, 35]) == dict(
        type='LineString', coordinates=[[-120, 34], [-119, 34]])
    for other in ([-119, 34, -118, 35], [-120, 34.1, -119, 35], a):
        with pytest.raises(ValueError, match='^segments_not_adjacent$'):
            seams.shared_edge(a, other)
    almost = [-120.00001, 34, -119.9, 34.2]
    assert seams.shared_edge(a, almost, match_m=2)['type'] == 'LineString'
    with pytest.raises(ValueError, match='^segments_not_adjacent$'):
        seams.shared_edge(a, almost, match_m=0.1)


def test_cli_repeat_and_no_modification(pair, tmp_path):
    import hashlib
    import os
    import stat
    import subprocess
    import sys
    from research.scripts.coast_mvp import coast_seams as seams
    a, b, boundary = pair()
    data = json.loads(boundary.read_text())
    write_json(boundary, dict(type='Feature', properties={}, geometry=data))
    files = [boundary, *a.iterdir(), *b.iterdir()]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}
    report = seams.observe(a, b, boundary)
    assert not report['stitched'] and not report['inputs_modified'] and report['review_required']
    assert report['navigation'] == 'NOT FOR NAVIGATION'
    assert report['boundary_sha256'] == hashlib.sha256(boundary.read_bytes()).hexdigest()
    for directory, row in zip((a, b), report['inputs']):
        for name in ('manifest', 'contours'):
            path = directory / ('manifest.json' if name == 'manifest' else 'contours.geojson')
            assert row[name + '_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    command = [sys.executable, '-m', 'research.scripts.coast_mvp.coast_seams',
               '--a', str(a), '--b', str(b), '--boundary', str(boundary), '--output']
    outputs = [tmp_path / 'first.json', tmp_path / 'second.json']
    for output in outputs:
        assert subprocess.run(command + [str(output)], capture_output=True).returncode == 0
        assert stat.S_IMODE(os.stat(output).st_mode) == 0o600
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    assert json.loads(outputs[0].read_bytes()) == report
    assert subprocess.run(command + [str(outputs[0])], capture_output=True).returncode != 0
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files} == before


def test_greedy_matching_and_order_independence(pair):
    from research.scripts.coast_mvp import coast_seams as seams
    a_rows = [(10, [(-200, y), (0, y)]) for y in (0, 4)]
    b_rows = [(10, [(200, y), (0, y)]) for y in (3, 6)]
    paths = pair(a=a_rows, b=b_rows)
    first = seams.observe(*paths, match_m=3.1)
    # Global nearest pair (4,3) wins, not A-order pairing (0,3), (4,6).
    assert first['totals']['matched'] == 1
    assert first['levels'][0]['gap_m']['median'] == pytest.approx(1, abs=0.01)
    second = seams.observe(*pair(a=a_rows[::-1], b=b_rows[::-1]), match_m=3.1)
    assert first['levels'] == second['levels']


def test_resolution_defaults_overrides_and_invalid_distances(pair):
    from research.scripts.coast_mvp import coast_seams as seams
    a, b, boundary = pair()
    path = b / 'contours.geojson'
    data = json.loads(path.read_text())
    data['features'][0]['properties']['source_resolution_m'] = 20
    write_json(path, data)
    result = seams.observe(a, b, boundary)
    assert (result['band_m'], result['match_m']) == (40, 60)
    result = seams.observe(a, b, boundary, band_m=1, match_m=2)
    assert (result['band_m'], result['match_m']) == (1, 2)
    for kwargs in (dict(band_m=-1), dict(match_m=float('nan'))):
        with pytest.raises(ValueError, match='distance_invalid'):
            seams.observe(a, b, boundary, **kwargs)


@pytest.mark.parametrize('bad', [None, [], {'type': 'Point', 'coordinates': [-120, 34]},
                               {'type': 'LineString', 'coordinates': [[-120, 34]] * 1001}])
def test_malformed_boundary(pair, bad):
    from research.scripts.coast_mvp import coast_seams as seams
    a, b, boundary = pair()
    write_json(boundary, bad)
    with pytest.raises(ValueError, match='^boundary_invalid$'):
        seams.observe(a, b, boundary)


def test_explicit_geojson_crs_refusal(pair):
    from research.scripts.coast_mvp import coast_seams as seams
    a, b, boundary = pair()
    path = a / 'contours.geojson'
    data = json.loads(path.read_text())
    data['crs'] = dict(type='name', properties=dict(name='EPSG:3857'))
    write_json(path, data)
    with pytest.raises(ValueError, match='^crs_not_4326$'):
        seams.observe(a, b, boundary)
