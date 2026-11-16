"""RF2325-2: the two offline measurement scripts refuse bad arguments / unreadable exports with one named error before any work."""
import gzip
import importlib.util
import json
import sys

import pytest

from tests._support import ROOT

pytest.importorskip('numpy')
BOUNDS = [-1, -1, 1, 1]
SQUARE = {'type': 'Polygon', 'coordinates': [[[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5], [-0.5, -0.5]]]}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod     # the process pool pickles _chunk by module name
    spec.loader.exec_module(mod)
    return mod


def _feature(rid):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [0.9, 0.9]},
            'properties': {'id': rid, 'waypoint': {'longitude': 0.9, 'latitude': 0.9}}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path/'repo'
    (root/'dist/regions/bay').mkdir(parents=True)
    (root/'dist/data').mkdir()
    (root/'dist/regions/bay/region.json').write_text(json.dumps({'mpa': {'bounds': BOUNDS}, 'assets': {'protected_areas': 'data/pa.geojson', 'closures': None}}))
    (root/'dist/data/pa.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': SQUARE, 'properties': {'NAME': 'Box'}}]}))
    export = tmp_path/'export.geojson'
    export.write_text(json.dumps({'features': [_feature('a'), _feature('b')], 'expires_at': '2030-01-01T00:00:00+00:00'}))
    oracle = tmp_path/'oracle.json'
    oracle.write_text(json.dumps({'verdicts': {}, 'ms': 0, 'fingerprint': 'x'}))
    parity, slim = _load('protected_screen_parity'), _load('reef_slim_build')
    for mod in (parity, slim):
        monkeypatch.setattr(mod, 'REPO', root)
    calls = []
    monkeypatch.setattr(parity.subprocess, 'run', lambda *a, **k: calls.append(a))
    return {'tmp': tmp_path, 'export': str(export), 'oracle': str(oracle), 'parity': parity, 'slim': slim, 'calls': calls}


BAD = [['--workers', '0'], ['--workers', '-2'], ['--limit', '0'], ['--limit', '-1'], ['--limit', 'x']]


@pytest.mark.parametrize('bad', BAD)
def test_bad_workers_or_limit_exit_2_with_no_work(env, bad, capsys):
    with pytest.raises(SystemExit) as e:
        env['parity'].main([env['export'], '--region', 'bay', *bad])
    assert e.value.code == 2 and 'must be a whole number of 1 or more' in capsys.readouterr().err and not env['calls']
    if bad[0] == '--limit':
        out = env['tmp']/'out'
        with pytest.raises(SystemExit) as e:
            env['slim'].main([env['export'], str(out), '--region', 'bay', *bad])
        assert e.value.code == 2 and not out.exists()


def test_unknown_region_is_one_named_error_before_node(env):
    with pytest.raises(SystemExit) as e:
        env['parity'].main([env['export'], '--region', 'nowhere'])
    assert e.value.code == 'protected-screen-parity: no protected screen for region nowhere' and not env['calls']


def _bad_exports(tmp):
    (tmp/'trunc.geojson.gz').write_bytes(gzip.compress(b'{"features": []}')[:-8])
    (tmp/'list.geojson').write_text('[]')
    return [str(tmp/'missing.geojson'), str(tmp/'trunc.geojson.gz'), str(tmp/'list.geojson')]


@pytest.mark.parametrize('which', ['parity', 'slim'])
def test_unreadable_export_is_one_stderr_line(env, which):
    for path in _bad_exports(env['tmp']):
        args = [path, '--region', 'bay'] if which == 'parity' else [path, str(env['tmp']/'o'), '--region', 'bay']
        with pytest.raises(SystemExit) as e:
            env[which].main(args)
        msg = str(e.value.code)
        assert '\n' not in msg and f'cannot read export {path}:' in msg
        assert msg.startswith('protected-screen-parity:' if which == 'parity' else 'reef_slim_build:')
    assert not env['calls'] and not (env['tmp']/'o').exists()


def test_valid_parity_run_prints_the_same_shape(env, capsys):
    assert env['parity'].main([env['export'], '--oracle', env['oracle'], '--region', 'bay', '--workers', '1']) == 1   # empty oracle: verdicts differ
    out = capsys.readouterr().out.splitlines()
    assert out[0] == 'reefs compared: 2  (oracle has 0)' and out[3].startswith('fingerprint python=') and out[4] == 'differences: 2' and not env['calls']


def test_valid_slim_run_writes_three_files(env):
    new = env['tmp']/'new'
    env['slim'].main([env['export'], str(new), '--region', 'bay'])
    names = sorted(p.name for p in new.iterdir())
    assert len(names) == 3 and 'habitat-export.geojson.gz' in names and 'manifest.json' in names
    assert [f['properties']['id'] for f in json.loads(gzip.decompress((new/'habitat-export.geojson.gz').read_bytes()))['features']] == ['a', 'b']


def test_limit_1_keeps_exactly_the_first_reef(env):
    out = env['tmp']/'one'
    env['slim'].main([env['export'], str(out), '--region', 'bay', '--limit', '1'])
    feats = json.loads(gzip.decompress((out/'habitat-export.geojson.gz').read_bytes()))['features']
    assert [f['properties']['id'] for f in feats] == ['a']
    assert env['parity'].main([env['export'], '--oracle', env['oracle'], '--region', 'bay', '--limit', '1', '--workers', '1']) == 1
    assert not env['calls']
