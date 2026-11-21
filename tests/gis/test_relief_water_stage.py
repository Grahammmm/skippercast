"""Drive the water stage through the real region CLI with a synthetic CUSP manifest and tiles."""

import hashlib
import json
import math
import socket

import pytest
from shapely.geometry import LineString, Point, shape

from scripts.relief import region as cli
from scripts.shoreline import import_cusp as cusp
from skippercast.platform.shoreline import feature_lines, slim_shoreline
from skippercast.relief import water
from tests.unit.test_cusp_shoreline import NOAA, tile

_REGION = 'synthetic-coast'
_BOUNDS = [-120.0, 38.0, -119.95, 38.04]  # Frame tiles: 12/682/1579 (offshore) and 12/683/1579 (coast).
_FRAME = (-120.0, 38.0, -119.95, 38.04)
_WEST, _EAST, _DECOY = '12/682/1579', '12/683/1579', '12/690/1570'
_OUTPUTS = ('water.geojson', 'water.json')


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line(name, accuracy, *lonlat):
    """One NOAA feature for tile ``name`` with positions given in degrees."""
    z, x, y = map(int, name.split('/'))
    points = []
    for lon, lat in lonlat:
        row = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z
        points.append((round(((lon + 180) / 360 * 2 ** z - x) * 4096), round((row - y) * 4096)))
    props = dict(NOAA) if accuracy is None else dict(NOAA, HOR_ACC=accuracy)
    if accuracy is None:
        del props['HOR_ACC']
    return props, points


def _coast(accuracy='18'):
    # A north-south coast with the land side at the inland east frame edge.
    return _line(_EAST, accuracy, (-119.962, 38.06), (-119.962, 37.997))


_ISLAND = _line(_EAST, '4.31', (-119.968, 38.019), (-119.966, 38.019), (-119.966, 38.021),
                (-119.968, 38.021), (-119.968, 38.019))


class Inputs:
    def __init__(self, root):
        self.root = root
        self.dir = root / 'cusp'
        self.manifest = self.dir / 'manifest.json'
        self.config = root / 'region.json'
        self.out = root / 'out'
        self.region = self.out / _REGION
        self.write_config({'id': _REGION, 'bounds': _BOUNDS})

    def write_config(self, doc):
        self.config.write_text(json.dumps(doc), encoding='utf-8')

    def tile_path(self, name):
        return self.dir / 'tiles' / f'{name}.pbf'

    def write(self, tiles, regions=None):
        """``tiles`` maps a tile id to its features, or to None for an unavailable row."""
        rows = []
        for name, features in sorted(tiles.items()):
            if features is None:
                rows.append({'status': 'unavailable', 'tile': name})
                continue
            path = self.tile_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(tile(features))
            rows.append({'bytes': path.stat().st_size, 'path': str(path), 'sha256': _sha(path),
                         'status': 'served', 'tile': name})
        doc = {'regions': {_REGION: {'bounds': _BOUNDS}} if regions is None else regions, 'tiles': rows}
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(json.dumps(doc), encoding='utf-8')
        return doc


def _default_tiles(coast='18'):
    # The decoy is a listed served tile outside the frame: an input, checked, never decoded.
    return {_WEST: None, _EAST: [_coast(coast), _ISLAND], _DECOY: [_line(_DECOY, '2', (-119.4, 38.6), (-119.39, 38.6))]}


@pytest.fixture
def held(tmp_path):
    inputs = Inputs(tmp_path)
    inputs.write(_default_tiles())
    return inputs


def _run(inputs, out=None):
    return cli.main(['water', '--out', str(out or inputs.out), '--region', _REGION,
                     '--region-config', str(inputs.config), '--shoreline-manifest', str(inputs.manifest)])


def _receipt_path(region):
    return region / 'stages' / 'water.json'


def _receipt(region):
    return json.loads(_receipt_path(region).read_bytes())


def _inputs(inputs, tiles=(_EAST, _DECOY)):
    return [{'path': str(inputs.manifest), 'role': 'shoreline-manifest', 'sha256': _sha(inputs.manifest)},
            {'path': str(inputs.config), 'role': 'region', 'sha256': _sha(inputs.config)},
            *[{'path': str(inputs.tile_path(name)), 'role': 'shoreline-tile', 'sha256': _sha(inputs.tile_path(name))}
              for name in tiles]]


def _output_paths(region):
    return [region / 'water' / name for name in _OUTPUTS]


def _no_output(region):
    assert not (region / 'water').exists()


def _expected(inputs):
    """The same decode the reviewed builder does, scored by the public RMSC-09 function."""
    doc = json.loads(inputs.manifest.read_bytes())
    data = {row['tile']: inputs.tile_path(row['tile']).read_bytes() for row in doc['tiles'] if row['status'] == 'served'}
    collection = cusp.extract(_REGION, _BOUNDS, get=lambda t: data.get('/'.join(map(str, t))))
    published = slim_shoreline(collection)
    lines = [(LineString(c), float(f['properties']['HOR_ACC']))
             for f in published['features'] for c in feature_lines(f['geometry'])]
    close_m = max(a for _, a in lines)
    return water.ocean_polygon(lines, _FRAME, close_m=close_m, connect_m=250.0)


@pytest.mark.parametrize('coast,close_m,accuracies', [
    pytest.param('18', 18.0, [4.31, 18.0], id='C1: north-B parity, maximum HOR_ACC 18 gives the reviewed CLOSE_M'),
    pytest.param('12', 12.0, [4.31, 12.0], id='C1: close_m is the decoded maximum HOR_ACC, not a fixed 18'),
])
def test_C1_receipt_and_outputs(held, monkeypatch, capsys, coast, close_m, accuracies):
    """C1: Dropping a listed tile, re-typing the radii or decoding unlisted bytes changes this receipt or report."""
    def offline(*args, **kwargs):
        raise AssertionError('the water stage must not open a network connection')

    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket, 'getaddrinfo', offline)
    held.write(_default_tiles(coast))
    # The reviewed builder's constants (build_water.py:67): the rule's north-B instance and the connectivity radius.
    assert (water.CLOSE_M, water.CONNECT_M) == (18.0, 250.0)
    assert _run(held) == 0
    receipt = _receipt(held.region)
    assert capsys.readouterr() == (f'[water] OK generation {receipt["generation"][:12]}: 2 outputs, attempt 1\n', '')
    assert (receipt['status'], receipt['rc'], receipt['held_reason'], receipt['error']) == ('ok', 0, None, None)
    assert receipt['inputs'] == _inputs(held)
    assert receipt['params'] == {'close_m': 'max stated HOR_ACC', 'connect_m': 250.0}
    assert receipt['metrics'] == {'close_m': close_m, 'connect_m': 250.0}
    assert (receipt['upstream'], receipt['target']) == ([], 'water')
    geojson, report_path = _output_paths(held.region)
    assert receipt['outputs'] == [{'path': f'water/{p.name}', 'sha256': _sha(p), 'bytes': p.stat().st_size}
                                  for p in (geojson, report_path)]

    expected_water, expected_report = _expected(held)
    assert json.loads(geojson.read_bytes()) == json.loads(json.dumps(water.to_geojson(expected_water, _REGION)))
    assert json.loads(report_path.read_bytes()) == {
        'region': _REGION, 'region_bounds_wgs84': _BOUNDS, 'frame_wgs84': _BOUNDS,
        'params': {'close_m': close_m, 'connect_m': 250.0}, 'hor_acc_values_m': accuracies,
        'unavailable_tiles': [_WEST], 'report': expected_report,
        'inputs': {'manifest_sha256': _sha(held.manifest),
                   'tiles': [{'tile': name, 'sha256': _sha(held.tile_path(name))} for name in (_EAST, _DECOY)]},
    }
    assert expected_report['displacement_bound_m'] == 2 * close_m
    ocean = shape(json.loads(geojson.read_bytes())['features'][0]['geometry'])
    # Offshore (in the unavailable west tile), island interior, inland.
    assert [ocean.contains(Point(lon, 38.02)) for lon in (-119.99, -119.967, -119.955)] == [True, False, False]


def _assert_failed(inputs, error):
    receipt = _receipt(inputs.region)
    assert (receipt['status'], receipt['rc'], receipt['error'], receipt['outputs']) == ('failed', 1, error, [])
    _no_output(inputs.region)


@pytest.mark.parametrize('case,error', [
    pytest.param('region', 'ReceiptError: region config id differs from the requested region',
                 id='C1: refuse another region config'),
    pytest.param('manifest', 'ValueError: unreadable shoreline manifest: JSONDecodeError: '
                             'Expecting value: line 1 column 1 (char 0)', id='C1: refuse an unreadable manifest'),
    pytest.param('empty', 'ValueError: no shoreline lines in the frame of region synthetic-coast',
                 id='C1: refuse a frame without shoreline'),
])
def test_C1_refusals(held, case, error):
    """C1: A wrong region, unreadable custody or empty shoreline must not produce an ocean."""
    if case == 'region':
        held.write_config({'id': 'other-region', 'bounds': _BOUNDS})
    elif case == 'manifest':
        held.manifest.write_bytes(b'not json')
    else:
        held.write({_WEST: None, _EAST: []})
    assert _run(held) == 1
    _assert_failed(held, error)


def _assert_held(inputs, reason, capsys, tiles=(_EAST, _DECOY)):
    receipt = _receipt(inputs.region)
    assert capsys.readouterr() == (f'[water] HELD generation {receipt["generation"][:12]}: {reason}\n', '')
    assert (receipt['status'], receipt['held_reason'], receipt['error'], receipt['outputs']) == ('held', reason, None, [])
    assert receipt['inputs'] == _inputs(inputs, tiles)
    _no_output(inputs.region)
    return receipt


@pytest.mark.parametrize('regions,shown', [
    pytest.param({_REGION: {'bounds': [-120.0, 38.0, -119.96, 38.04]}}, [-120.0, 38.0, -119.96, 38.04],
                 id='C2: manifest bounds stop short of the region'),
    pytest.param({'other-region': {'bounds': _BOUNDS}}, None, id='C2: manifest has no bounds for the region'),
])
def test_C2_manifest_does_not_cover_region(held, capsys, regions, shown):
    """C2: Tiles that happen to exist do not stand in for a manifest that never covered the region."""
    held.write(_default_tiles(), regions)
    assert _run(held) == 4
    _assert_held(held, f'shoreline manifest does not cover region synthetic-coast: manifest bounds {shown}, '
                       f'region bounds {_BOUNDS}', capsys)


def test_C2_runner_blocks_missing_served_tile(held, capsys, monkeypatch):
    """C2: A listed served tile that is gone never reaches build and cannot shrink the shoreline."""
    path = held.tile_path(_EAST)
    path.rename(path.with_suffix('.absent'))

    def unexpected_build(*args):
        pytest.fail('blocked inputs must not invoke build')

    monkeypatch.setattr(water, 'build', unexpected_build)
    assert _run(held) == 3
    assert capsys.readouterr() == (f'[water] BLOCKED generation -: input missing: {path}\n', '')
    assert not _receipt_path(held.region).exists()
    _no_output(held.region)


def test_C2_mismatched_tile(held, capsys):
    """C2: A changed tile is held at its manifest pin, not re-pinned to the local bytes."""
    doc = json.loads(held.manifest.read_bytes())
    pinned = next(row['sha256'] for row in doc['tiles'] if row['tile'] == _EAST)
    held.tile_path(_EAST).write_bytes(tile([_coast()]))
    assert _run(held) == 4
    _assert_held(held, f'SHA-256 mismatch for shoreline tile {_EAST}: expected {pinned}, '
                       f'observed {_sha(held.tile_path(_EAST))}', capsys)


def test_C2_frame_tile_not_listed(held, capsys):
    """C2: A frame tile with no manifest row is missing, not certified empty like an unavailable row."""
    tiles = _default_tiles()
    del tiles[_WEST]
    held.write(tiles)
    assert _run(held) == 4
    _assert_held(held, f"shoreline manifest lists no served or unavailable row for frame tiles ['{_WEST}']", capsys)


@pytest.mark.parametrize('accuracy,reason', [
    pytest.param(None, 'shoreline feature cusp-12-683-1579-0 states no positive HOR_ACC: None',
                 id='C1: hold a feature without HOR_ACC'),
    pytest.param('0', "shoreline feature cusp-12-683-1579-0 states no positive HOR_ACC: '0'",
                 id='C1: hold a zero HOR_ACC'),
    pytest.param('300', 'maximum stated HOR_ACC 300.0 m exceeds connect_m 250.0 m',
                 id='C1: hold a maximum HOR_ACC above connect_m'),
])
def test_C1_unusable_accuracy(held, capsys, accuracy, reason):
    """C1: The opening radius is never guessed when the stated accuracy cannot set it."""
    held.write(dict(_default_tiles(), **{_EAST: [_coast(accuracy), _ISLAND]}))
    assert _run(held) == 4
    _assert_held(held, reason, capsys)


def test_C2_no_west_connected_ocean(held, capsys):
    """C2: A shoreline 8 m inside the west frame edge leaves no seaward component to keep."""
    held.write(dict(_default_tiles(), **{_WEST: [_line(_WEST, '18', (-119.9999, 38.06), (-119.9999, 37.997))]}))
    assert _run(held) == 4
    _assert_held(held, 'opening at 18.0 m leaves no west-connected ocean in region synthetic-coast', capsys,
                 (_WEST, _EAST, _DECOY))


def test_C2_unlisted_displacement(held, capsys, monkeypatch):
    """C2: An over-bound boundary sample away from a listed cut holds, and its report is kept unchanged."""
    real = water.ocean_polygon
    outlier = [-119.96, 38.02]

    def displaced(*args, **kwargs):
        geometry, report = real(*args, **kwargs)
        return geometry, dict(report, unlisted_beyond_bound=[outlier])

    monkeypatch.setattr(water, 'ocean_polygon', displaced)
    assert _run(held) == 4
    receipt = _assert_held(held, '1 boundary samples lie beyond 36.0 m of the shoreline and are not at a listed cut',
                           capsys)
    kept = json.loads((held.region / receipt['failed_dir'] / 'water.json').read_bytes())
    assert kept['report'] == dict(_expected(held)[1], unlisted_beyond_bound=[outlier])


def test_C3_receipt_no_op_and_clean_output_bytes(held, tmp_path, capsys, monkeypatch):
    """C3: Rebuilding a done generation or embedding output-root/time data in outputs breaks reuse."""
    second = tmp_path / 'fresh-out'
    assert _run(held) == _run(held, second) == 0
    capsys.readouterr()
    receipt = _receipt(held.region)
    assert _receipt(second / _REGION)['generation'] == receipt['generation']
    receipt_bytes = _receipt_path(held.region).read_bytes()
    expected = [path.read_bytes() for path in _output_paths(held.region)]
    assert [path.read_bytes() for path in _output_paths(second / _REGION)] == expected

    def unexpected_build(*args):
        pytest.fail('a done generation must not invoke build')

    monkeypatch.setattr(water, 'build', unexpected_build)
    assert _run(held) == 0
    assert capsys.readouterr() == (
        f'[water] DONE generation {receipt["generation"][:12]}: no work: receipt ok, outputs re-hash, upstream current\n',
        '',
    )
    assert _receipt_path(held.region).read_bytes() == receipt_bytes
    assert [path.read_bytes() for path in _output_paths(held.region)] == expected
