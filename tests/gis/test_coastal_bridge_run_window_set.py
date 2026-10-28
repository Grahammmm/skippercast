"""PC-9b real producer admission binding, offline synthetic queue acceptance.

Scientific stage handoffs use the existing labelled synthetic dispatcher; this
qualifies ordered queue lineage, not terrain science or projected window sets.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from skippercast.coastal.coordinator import bridge_run as driver, catalog_bridge, loop
from skippercast.coastal.coordinator.stages import digest
from tests import _coastal_catalog_fixture as fx
from tests._coastal_operations import Harness
from tests._support import FakeClock
from tests.coast_contract_factory import load_helper, materialize
from tests.unit.test_coastal_bridge_run import synthetic_dispatch  # noqa: F401

pytestmark = pytest.mark.gis
refs = load_helper('coast_refs')
validator = load_helper('validate_coast_receipt')
CLOCK = FakeClock()


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o644)  # Only this test's copied synthetic fixture bytes.
    path.write_bytes(value if isinstance(value, bytes) else refs.canonical(value))


def read(path):
    return json.loads(path.read_bytes())


@pytest.fixture(autouse=True)
def offline_and_provenance(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('PC-9b must not open a socket')
    for name in ('socket', 'create_connection', 'getaddrinfo'):
        monkeypatch.setattr(socket, name, refuse)
    for key, value in dict(AUTHOR_PROFILE='synthetic-builder', AUTHOR_MODEL='synthetic-test-model',
                           CARD_ID='t_dce3e0a0', CODE_COMMIT='1'*40, SKILL_COMMIT='2'*40).items():
        monkeypatch.setenv('COAST_' + key, value)


def make_world(destination, windows=4, second=False):
    # Start from the merged real-schema factory, but do not reuse its synthetic
    # downstream receipts/intents or unreadable BAG placeholder as run evidence.
    instances, bindings = materialize(destination/'seed', windows=windows)
    admission = deepcopy(instances['admission'])
    seed = Path(bindings['queue:synthetic'])
    base = destination/'world'
    base.mkdir()
    ops = Harness(base, base, policy_value=driver._policy())
    ops.close()
    root = ops.root.rename(base/'synthetic')
    # Preserve the empty Harness Store outside the driver path. Negatives must
    # prove refusal before any driver Store, intent or output is created.
    (root/driver.DATABASE).rename(root/'empty-harness.sqlite')
    p = root/'plans/plan01'
    record = read(seed/admission['segment_record']['path'])
    record['synthetic'] = True
    put(p/'segment.json', record)
    campaign = read(seed/admission['campaign']['path'])
    header = {k: admission[k] for k in ('created_utc', 'author_profile', 'author_model',
                                       'card_id', 'code_commit', 'skill_commit')}
    cx, cy = (record['bbox'][0]+2500, record['bbox'][1]+2500)
    lon, lat = Transformer.from_crs('EPSG:3310', 'OGC:CRS84', always_xy=True).transform(cx, cy)
    pixel = 1e-5
    west, north = lon-1024*pixel, lat+1024*pixel
    native = [[x, y, 512, 512] for y in (1024, 1536) for x in (1024, 1536)] if windows == 4 else [[1024, 1024, 4, 4]]
    tiling = dict(tile=512, width=2048, height=2048, origin=[1024, 1024],
                  anchor=[west+1024*pixel, north-1024*pixel], cell=[pixel, pixel])
    rows, selections, grids, admission_windows, sources = [], [], [], [], []
    raw_root = destination/'raw'
    raw_root.mkdir()
    for number in range(2 if second else 1):
        name = f'input{number}.tif'
        path = root/'cache'/name
        path.parent.mkdir(exist_ok=True)
        data = np.full((2048, 2048), -9999, dtype='float32')
        data[1024:, 1024:] = -10-number
        with rasterio.open(path, 'w', driver='GTiff', width=2048, height=2048,
                           count=1, dtype='float32', crs='EPSG:4326', nodata=-9999,
                           transform=from_origin(west, north, pixel, pixel), compress='deflate') as ds:
            ds.write(data, 1)
        with rasterio.open(path) as ds:
            assert ds.read(1, window=rasterio.windows.Window(1024, 1024, 4, 4)).shape == (4, 4)
        source = dict(path=path.relative_to(root).as_posix(), sha256=refs.sha256(path.read_bytes()),
                      bytes=path.stat().st_size, contract='native-raster-v1')
        row = fx.candidate(name, bbox=record['bbox_crs84'], size=source['bytes'], source_hash=source['sha256'])
        rows.append(row)
        is_set = windows == 4 and number == 0
        chosen = native if number == 0 else [native[0]]
        selection = fx.window_set(row['source_id'], source, chosen, tiling) if is_set else fx.selection(row['source_id'], source, chosen[0])
        selections.append(selection)
        definition = dict(source_sha256=source['sha256'], raster_crs='EPSG:4326',
                          affine_transform=[pixel, 0, west, 0, -pixel, north], width=2048, height=2048,
                          tile_width=512 if is_set else chosen[0][2], tile_height=512 if is_set else chosen[0][3],
                          tiling_version='window-set-v1' if is_set else 'single-selected-v1')
        definition.update(tiling=deepcopy(tiling)) if is_set else definition.update(pixel_window=chosen[0])
        sha = digest(definition)
        grids.append(dict(source_id=row['source_id'], grid_sha256=sha, definition=definition,
                          cols=2 if is_set else 1, rows=2 if is_set else 1, total=len(chosen)))
        for index, (x, y, w, h) in enumerate(chosen):
            key = f"{row['source_id']}#{sha}#{index}"
            admission_windows.append(dict(source_id=row['source_id'], grid_sha256=sha, idx=index,
                window_key=key, window_dir=refs.sha256(key.encode()), pixel_window=[x, y, w, h],
                owner_segment_id=record['segment_id'], footprint=[west+x*pixel, north-(y+h)*pixel, west+(x+w)*pixel, north-y*pixel],
                overlapping_segment_ids=[record['segment_id']]))
        hot = dict(root_id='queue:synthetic', **{k: source[k] for k in ('path', 'sha256', 'bytes')})
        # raw_provenance takes a raw:campaign payload Ref (#832 edge contract); the
        # GeoTIFF stays in hot_cache, as in tests/coast_real_admission_factory.py.
        (raw_root/name).write_bytes(path.read_bytes())
        raw = dict(hot, root_id='raw:campaign', path=name)
        sources.append(dict(source_id=row['source_id'], raw_provenance=[raw], retained_inputs=[], hot_cache=[hot],
                            rights='synthetic private use', datum='unknown', reader='native-raster-v1'))
    catalog = fx.frozen_catalog(rows)
    catalog_sha = fx.write_catalog(root/'catalog.json', catalog)
    plan = fx.plan(catalog, catalog_sha, selections, bbox=record['bbox_crs84'], segment_id=record['segment_id'], synthetic=True)
    put(p/'plan.json', plan)
    campaign.update(bbox_crs84=record['bbox_crs84'], source_inventory=[s['source_id'] for s in selections],
                    intended_windows=[w['window_key'] for w in admission_windows])
    put(root/'campaign.json', campaign)
    catalog_ref = driver._ref(root, root/'catalog.json', 'queue:synthetic')
    put(root/'evidence.txt', b'Synthetic offline evidence only; no scientific acceptance.\n')
    put(root/'discovery.json', dict(schema='coast-discovery-evidence-v1', **header, catalog=catalog_ref,
                                    evidence=[driver._ref(root, root/'evidence.txt', 'queue:synthetic')]))
    catalog_bridge.dry_run(root, root/'catalog.json', plan, p/'dry', now=CLOCK.timestamp())
    catalog_bridge.run(root, root/'catalog.json', plan, p/'bridge', now=CLOCK.timestamp())
    admission.update(grids=grids, windows=admission_windows, sources=sources, plan_sha256=digest(plan),
                     selected_source_ids=[s['source_id'] for s in selections], would_enqueue_count=len(admission_windows),
                     **{key: driver._ref(root, path, 'queue:synthetic') for key, path in dict(
                         campaign=root/'campaign.json', plan_file=p/'plan.json', segment_record=p/'segment.json',
                         catalog=root/'catalog.json', discovery=root/'discovery.json', dry_run=p/'dry/bridge-dry-run-receipt.json').items()})
    put(p/'admission.json', admission)
    (p/'runs').mkdir()
    w = SimpleNamespace(root=root, p=p, admission=admission, plan=plan, record=record,
                        bindings={'queue:synthetic': str(root), 'raw:campaign': str(raw_root.absolute())}, ops=ops)
    check(w)
    return w


def context(w):
    return driver._context(w.root, w.p/'admission.json', w.p/'bridge/bridge-receipt.json', w.p/'segment.json')


def check(w):
    validator.validate_schema(w.admission)
    return validator.validate(w.admission, refs.Resolver(w.bindings, allowed_root_ids=w.bindings), root_id='queue:synthetic')


def inventory(w):
    return {p.relative_to(w.root).as_posix(): refs.sha256(p.read_bytes()) for p in w.root.rglob('*') if p.is_file()}


def clone(w, destination):
    root = destination/'synthetic'
    shutil.copytree(w.root, root)
    return SimpleNamespace(root=root, p=root/'plans/plan01', admission=deepcopy(w.admission),
                           plan=deepcopy(w.plan), record=w.record,
                           bindings=dict(w.bindings, **{'queue:synthetic': str(root)}))


def rekey(window):
    window['window_key'] = f"{window['source_id']}#{window['grid_sha256']}#{window['idx']}"
    window['window_dir'] = refs.sha256(window['window_key'].encode())


def mutate(w, case):
    before = inventory(w)
    a = w.admission
    campaign_changed = False
    bridge_path = w.p/'bridge/bridge-receipt.json'
    if case == 'N1':
        bridge = read(bridge_path)
        paths = [w.root/bridge['jobs'][i]['input_manifest']['path'] for i in (1, 2)]
        raw = [p.read_bytes() for p in paths]
        for path, value in zip(paths, reversed(raw)):
            path.chmod(0o644)
            path.write_bytes(value)
        for i in (1, 2):
            job = bridge['jobs'][i]
            job['input_manifest'].update(**{k: v for k, v in driver._ref(w.root, w.root/job['input_manifest']['path'], 'queue:synthetic').items() if k != 'root_id'})
        put(bridge_path, bridge)
    elif case == 'N7':
        bridge = read(bridge_path)
        bridge['jobs'][1], bridge['jobs'][2] = bridge['jobs'][2], bridge['jobs'][1]
        put(bridge_path, bridge)
    elif case == 'N2':
        a['windows'][1]['pixel_window'], a['windows'][2]['pixel_window'] = a['windows'][2]['pixel_window'], a['windows'][1]['pixel_window']
    elif case == 'N3':
        a['windows'][2]['idx'], a['windows'][3]['idx'] = a['windows'][3]['idx'], a['windows'][2]['idx']
        for win in a['windows']:
            rekey(win)
        campaign_changed = True
    elif case == 'N6':
        a['windows'][0], a['windows'][1] = a['windows'][1], a['windows'][0]
    elif case == 'N8a':
        a['windows'][3] = deepcopy(a['windows'][2])
    elif case == 'N8b':
        a['windows'].pop()
    elif case == 'N5':
        a['windows'][0]['source_id'] = a['windows'][-1]['source_id']
        rekey(a['windows'][0])
        campaign_changed = True
    elif case in ('N4', 'N13'):
        grid = deepcopy(a['grids'][0])
        grid['definition']['tiling']['origin'][0] += 512
        grid['grid_sha256'] = digest(grid['definition'])
        a['grids'].append(grid)
        if case == 'N4':
            a['windows'][1]['grid_sha256'] = grid['grid_sha256']
            rekey(a['windows'][1])
            campaign_changed = True
    elif case == 'N12':
        a['grids'][0]['source_id'] = 'other'
    elif case == 'N11':
        a['grids'][0]['total'] = 3
    elif case == 'N14':
        grid = a['grids'][0]
        affine = grid['definition']['affine_transform']
        affine[2] += 512 * affine[0]            # affine no longer puts the declared anchor at origin
        grid['grid_sha256'] = digest(grid['definition'])
        for win in a['windows']:
            win['grid_sha256'] = grid['grid_sha256']
            rekey(win)
        campaign_changed = True
    elif case in ('N9a', 'N9b'):
        grid = a['grids'][0]
        definition = grid['definition']
        if case == 'N9a':
            del definition['tiling']
            definition.update(tiling_version='single-selected-v1', pixel_window=a['windows'][0]['pixel_window'])
            grid.update(cols=1, rows=1, total=1)
        else:
            pixel_window = definition.pop('pixel_window')
            definition.update(tiling_version='window-set-v1', tiling=dict(tile=512, width=2048, height=2048,
                origin=pixel_window[:2], anchor=[0, 0], cell=[1e-5, 1e-5]))
        grid['grid_sha256'] = digest(definition)
        for win in a['windows']:
            win['grid_sha256'] = grid['grid_sha256']
            rekey(win)
        campaign_changed = True
    else:
        raise AssertionError(case)
    if campaign_changed:
        campaign = read(w.root/'campaign.json')
        campaign['intended_windows'] = [win['window_key'] for win in a['windows']]
        put(w.root/'campaign.json', campaign)
        a['campaign'] = driver._ref(w.root, w.root/'campaign.json', 'queue:synthetic')
    put(w.p/'admission.json', a)
    validator.validate_schema(a)
    after = inventory(w)
    allowed = {'plans/plan01/admission.json'}
    if campaign_changed:
        allowed.add('campaign.json')
    if case in ('N1', 'N7'):
        allowed.add('plans/plan01/bridge/bridge-receipt.json')
    if case == 'N1':
        allowed.update(path.relative_to(w.root).as_posix() for path in paths)
    assert before.keys() == after.keys()
    assert {key for key in before if before[key] != after[key]} <= allowed


MATRIX = [
    ('N1', 'native: native manifest differs from pinned plan/catalog', None),
    ('N7', 'job', None),
    ('N2', 'pixel_window', 'plan window population mismatch'),
    ('N3', 'idx: window/grid/owner binding mismatch', 'plan window population mismatch'),
    ('N6', 'idx: window/grid/owner binding mismatch', 'plan window population mismatch'),
    ('N8a', 'duplicate', 'duplicate admission window_key'),
    ('N8b', None, 'plan window population mismatch'),
    ('N5', 'source', 'plan window population mismatch'),
    ('N4', 'grid', 'selection windows bind to more than one grid'),
    ('N12', 'grid_source', 'grid/window source binding mismatch'),
    ('N11', 'grid_shape', 'window-set grid/window binding mismatch'),
    ('N9a', 'tiling_version: window-set grid requires reviewed PC-6 support', 'window-set grid/window binding mismatch'),
    ('N9b', 'tiling_version: window-set grid requires reviewed PC-6 support', 'single-selected grid/window binding mismatch'),
    ('N13', 'population', 'admission grid population mismatch'),
    ('N14', 'grid_geometry: window-set tiling anchor disagrees with the grid affine',
     'window-set tiling anchor disagrees with the grid affine'),
]


@pytest.fixture(scope='module')
def worlds(tmp_path_factory):
    return {name: make_world(tmp_path_factory.mktemp(name), windows=count, second=second)
            for name, count, second in [('W1', 1, False), ('W4', 4, False), ('W2', 4, True)]}


@pytest.mark.parametrize('name', ['W1', 'W4'])
def test_validator_driver_positive(worlds, name):
    w = worlds[name]
    check(w)
    context(w)


def test_four_window_same_source_context_accepts(worlds):
    """run1051/result.json b08bc72f91a9cbb8c8c81a4b5a0831581b56ceb6b02b379cd7308be47e9ae4d6 regression."""
    assert len(context(worlds['W4'])[0]['windows']) == 4


@pytest.mark.parametrize('case,code,message', MATRIX, ids=[r[0] for r in MATRIX])
def test_validator_driver_matrix_and_value_errors(worlds, tmp_path, case, code, message):
    w = clone(worlds['W1' if case == 'N9b' else 'W2' if case == 'N5' else 'W4'], tmp_path)
    mutate(w, case)
    expected = ('admission window population mismatch' if case == 'N8b' else
                'admission grid population mismatch' if case == 'N13' else 'window binding mismatch: ' + code)
    with pytest.raises(ValueError, match='^' + re.escape(expected) + '$'):
        context(w)
    if message is None:
        check(w)
    else:
        with pytest.raises(ValueError, match='^' + re.escape(message) + '$'):
            check(w)
    assert not (w.root/driver.DATABASE).exists()
    assert not (w.root/'var/coastal/enqueue-intents').exists()
    assert not (w.p/'bridge/enqueue-receipt.json').exists()


@pytest.mark.parametrize('case', ['N2', 'N3', 'N7'])
def test_bind_window_is_the_deciding_gate(worlds, tmp_path, monkeypatch, case):
    w = clone(worlds['W4'], tmp_path)
    mutate(w, case)
    with monkeypatch.context() as patch:
        patch.setattr(driver, '_bind_window', lambda *args: None)
        context(w)
    code = next(code for row, code, _ in MATRIX if row == case)
    with pytest.raises(ValueError, match='^' + re.escape('window binding mismatch: ' + code) + '$'):
        context(w)
    context(worlds['W4'])


def enqueue(w):
    return driver.enqueue(w.root, w.p/'bridge/bridge-receipt.json', w.p/'segment.json',
                          w.p/'admission.json', w.p/'bridge/enqueue-receipt.json', clock=CLOCK.timestamp)


def run(w, ticks, continuation=False):
    return driver.run(w.root, w.p/'bridge/enqueue-receipt.json', w.p/f"runs/run-{int(continuation):02}.json",
                      max_ticks=ticks, until=CLOCK.timestamp()+3600, clock=CLOCK.timestamp,
                      continuation_of=w.p/'runs/run-00.json' if continuation else None)


@pytest.mark.parametrize('name', ['W1', 'W4'])
def test_context_enqueue_run_projection_and_map_lineage(worlds, tmp_path, monkeypatch, synthetic_dispatch, name):
    w = clone(worlds[name], tmp_path)
    monkeypatch.setenv('COAST_EXCLUSIVE_WRITER', str(w.root))
    context(w)
    receipt = enqueue(w)
    binding = loop.implementation_hashes(w.root)
    assert (receipt['code_sha'], receipt['deps_sha']) == binding
    datetime.fromisoformat(receipt['created_utc'].replace('Z', '+00:00'))
    bridge = read(w.p/'bridge/bridge-receipt.json')
    dry = read(w.root/w.admission['dry_run']['path'])
    expected = []
    observed = []
    for index, (window, job, enqueued) in enumerate(zip(w.admission['windows'], bridge['jobs'], receipt['jobs'], strict=True)):
        raw = (w.root/job['input_manifest']['path']).read_bytes()
        native = json.loads(raw)
        assert dry['would_enqueue'][index]['native_job_sha256'] == digest(native)
        assert job['input_manifest']['sha256'] == refs.sha256(raw)
        assert job['input_manifest']['bytes'] == len(raw)
        assert enqueued['input_manifest'] == dict(root_id='queue:synthetic', **job['input_manifest'])
        selection = w.plan['selections'][0]
        assert native['window'] == window['pixel_window'] == catalog_bridge._selection_windows(selection)[index]
        assert window['grid_sha256'] == digest(w.admission['grids'][0]['definition'])
        if name == 'W4':
            assert job['window_index'] == dry['would_enqueue'][index]['window_index'] == window['idx'] == index
            assert job['window'] == dry['would_enqueue'][index]['window'] == window['pixel_window']
        expected.append((selection['source_id'], window['window_key'], window['grid_sha256'], window['idx'],
                         window['pixel_window'], refs.sha256(raw)))
        observed.append((enqueued['source_id'], enqueued['window_key'], window['grid_sha256'], window['idx'],
                         native['window'], enqueued['input_manifest']['sha256']))
    assert observed == expected
    assert len(receipt['jobs']) == len(w.admission['windows'])
    with driver._snapshot(w.root) as db:
        for job in receipt['jobs']:
            row = dict(db.execute('SELECT * FROM jobs WHERE job_id=?', (job['root_job_id'],)).fetchone())
            stored = json.loads(row['record_json'])
            assert (stored['code_sha'], stored['deps_sha']) == binding
            assert job['root_job_id'] == 'job:' + driver._identity(stored)[:24]
    first = run(w, 2 if name == 'W4' else 24)
    if name == 'W4':
        assert first['stop_reason'] == 'max_ticks' and first['ticks_used'] == 2
        first_bytes = (w.p/'runs/run-00.json').read_bytes()
        summary = run(w, 24, continuation=True)
        assert summary['continuation_of']['sha256'] == refs.sha256(first_bytes)
        assert (w.p/'runs/run-00.json').read_bytes() == first_bytes
    else:
        summary = first
    assert summary['stop_reason'] == 'terminal', summary['problems']
    assert summary['counts']['map_done'] == summary['counts']['windows'] == len(receipt['jobs'])
    assert sum(summary['counts'][key] for key in driver.PARTITION) == len(receipt['jobs'])
    assert summary['usage']['requests'] == 0
    assert summary['untouched']['render_jobs_left_queued'] == len(receipt['jobs'])
    assert summary['enqueued_job_ids'] == [job['root_job_id'] for job in receipt['jobs']]
    assert [win['window_key'] for win in summary['windows']] == [win['window_key'] for win in w.admission['windows']]
    assert all(win['stages']['render']['state'] == 'queued' for win in summary['windows'])
    assert (summary['code_sha'], summary['deps_sha']) == binding
    assert summary['wall_s'] >= 0
    for key in ('created_utc', 'started_utc', 'finished_utc'):
        datetime.fromisoformat(summary[key].replace('Z', '+00:00'))
    with pytest.raises(ValueError, match='output exists'):
        enqueue(w)
    with pytest.raises(ValueError, match='output exists'):
        run(w, 24)
