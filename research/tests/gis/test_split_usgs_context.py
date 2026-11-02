import json
import math
import subprocess
import sys

import pytest

from research.scripts import split_usgs_context as splitter
from tests._support import ROOT

SCRIPT = ROOT / 'research/scripts/split_usgs_context.py'
SCOPE = 'generalized-statewide-usgs-hard-bottom-context'


def square(ident, lat):
    ring = [[-123, lat - 0.05], [-122.9, lat - 0.05], [-122.9, lat + 0.05], [-123, lat + 0.05], [-123, lat - 0.05]]
    return {'type': 'Feature', 'properties': {'id': ident}, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}}


def context(*features):
    return {'type': 'FeatureCollection', 'scope': SCOPE, 'source': 'usgs', 'features': list(features)}


def coasts(*regions):
    return {'regions': [{'id': ident, 'latitude': band} for ident, band in regions]}


TWO = coasts(('northern', [40, 42]), ('central', [34, 40]))


def error(data, coast_file):
    with pytest.raises(ValueError) as caught:
        splitter.split(data, coast_file)
    return str(caught.value)


def run(tmp_path, data, coast_file):
    (tmp_path / 'in.json').write_text(json.dumps(data))
    (tmp_path / 'coasts.json').write_text(json.dumps(coast_file))
    return subprocess.run([sys.executable, str(SCRIPT), '--input', 'in.json', '--coasts', 'coasts.json',
                           '--output-dir', 'out'], cwd=tmp_path, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize('ident', ['../x', 'a/b', 'Central', '', 'a--b', 7])
def test_coast_id_that_is_not_plain_is_refused(ident):
    assert error(context(square('p-1', 41)), coasts((ident, [40, 42]))) == 'Coast 0 id is not a plain id'


@pytest.mark.parametrize('region', ['central', None, ['central']])
def test_coast_that_is_not_an_object_is_refused(region):
    assert error(context(), {'regions': [region]}) == 'Coast 0 id is not a plain id'


def test_traversal_coast_id_writes_nothing_in_output_dir_or_parent(tmp_path):
    done = run(tmp_path, context(square('p-1', 41)), coasts(('northern', [40, 42]), ('../x', [34, 40])))
    assert done.returncode != 0
    assert 'Coast 1 id is not a plain id' in done.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ['coasts.json', 'in.json']


def test_coast_listed_twice_is_refused():
    message = error(context(square('p-1', 41)), coasts(('central', [34, 40]), ('central', [40, 42])))
    assert message == 'Coast id listed twice: central'


@pytest.mark.parametrize('band', [[36, 35], [36, 36], [math.nan, 40], [34, math.inf], [34], [34, 40, 42],
                                  None, '34,40', [True, 40], ['34', 40]])
def test_invalid_latitude_band_is_refused(band):
    assert error(context(), coasts(('central', band))) == 'Coast central latitude band invalid'


def test_feature_outside_every_band_is_named():
    message = error(context(square('p-1', 41), square('p-7', 50)), TWO)
    assert message == 'USGS polygon p-7 falls outside one California coast'


def test_feature_inside_two_overlapping_bands_is_named():
    message = error(context(square('p-3', 39)), coasts(('northern', [38, 42]), ('central', [34, 40])))
    assert message == 'USGS polygon p-3 falls outside one California coast'


def test_feature_without_plain_id_is_named_by_index():
    feature = square('../../etc/passwd', 50)
    assert error(context(square('p-1', 41), feature), TWO) == 'USGS polygon #1 falls outside one California coast'
    del feature['properties']
    assert error(context(feature), TWO) == 'USGS polygon #0 falls outside one California coast'


@pytest.mark.parametrize('geometry', [None, {}, {'type': 'Polygon'}, {'type': 'Polygon', 'coordinates': []},
                                      {'type': 'Nonsense', 'coordinates': [1, 2]}])
def test_feature_without_usable_geometry_is_named(geometry):
    feature = square('p-5', 41) | {'geometry': geometry}
    assert error(context(feature), TWO) == 'USGS feature p-5 has no usable geometry'


def test_feature_missing_geometry_key_or_not_object_is_named_by_index():
    assert error(context({'type': 'Feature', 'properties': {'id': 'p-9'}}), TWO) == 'USGS feature p-9 has no usable geometry'
    assert error(context(square('p-1', 41), 'p-2'), TWO) == 'USGS feature #1 has no usable geometry'


def test_valid_input_writes_two_shards_and_no_temp_files(tmp_path):
    data = context(square('p-1', 41), square('p-2', 35), square('p-3', 36))
    done = run(tmp_path, data, TWO)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ['northern 1', 'central 2']
    out = tmp_path / 'out'
    assert sorted(p.name for p in out.iterdir()) == ['usgs-hard-context-central.geojson',
                                                     'usgs-hard-context-northern.geojson']
    for ident, ids in (('northern', ['p-1']), ('central', ['p-2', 'p-3'])):
        text = (out / f'usgs-hard-context-{ident}.geojson').read_text()
        shard = json.loads(text)
        assert text.endswith('}\n') and ', ' not in text
        assert shard['coast_id'] == ident and shard['scope'] == SCOPE and shard['source'] == 'usgs'
        assert [f['properties']['id'] for f in shard['features']] == ids


def test_rerun_replaces_old_shard_atomically(tmp_path):
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out/usgs-hard-context-central.geojson').write_text('{"truncated')
    done = run(tmp_path, context(square('p-2', 35)), TWO)
    assert done.returncode == 0, done.stderr
    assert json.loads((tmp_path / 'out/usgs-hard-context-central.geojson').read_text())['coast_id'] == 'central'
    assert not list((tmp_path / 'out').glob('*.tmp'))
