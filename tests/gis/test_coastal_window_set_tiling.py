"""Window-set geometry and run order (audit 2026-10-23 N2, N11).

Every world here is synthetic: tiny float32 GeoTIFFs written into tmp_path, no
network, no real survey data.
"""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gis
pytest.importorskip("pyproj")
pytest.importorskip("rasterio")

import numpy as np  # noqa: E402
from pyproj import Transformer  # noqa: E402

from skippercast.coastal.coordinator import bridge_run as driver, catalog_bridge
from skippercast.coastal.coordinator.stages import digest
from tests import _coastal_catalog_fixture as fx

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from tests._coastal_operations import Harness  # noqa: E402
from tests._support import FakeClock  # noqa: E402
from tests.coast_contract_factory import load_helper, materialize  # noqa: E402
from tests.unit.test_coastal_bridge_run import synthetic_dispatch  # noqa: E402,F401

refs = load_helper('coast_refs')
CLOCK = FakeClock()
PIXEL = 1e-5


@pytest.fixture(autouse=True)
def offline_and_provenance(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('window-set tests must not open a socket')
    for name in ('socket', 'create_connection', 'getaddrinfo'):
        monkeypatch.setattr(socket, name, refuse)
    for key, value in dict(AUTHOR_PROFILE='synthetic-auditor', AUTHOR_MODEL='synthetic-test-model',
                           CARD_ID='t_audit', CODE_COMMIT='1'*40, SKILL_COMMIT='2'*40).items():
        monkeypatch.setenv('COAST_' + key, value)


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o644)
    path.write_bytes(value if isinstance(value, bytes) else refs.canonical(value))


def read(path):
    return json.loads(path.read_bytes())


def world(destination, *, raster_shape, nw_offset_m, windows, tiling_override=None):
    """One-source window-set world, modelled on test_coastal_bridge_run_window_set.make_world.

    raster_shape: (width, height) of the synthetic GeoTIFF (EPSG:4326, PIXEL degrees).
    nw_offset_m: (dx, dy) of the raster's NW corner from the segment's SW corner in EPSG:3310 metres.
    windows: callable(tiling) -> the plan's native windows (default: the bridge's own expectation).
    tiling_override: dict merged into the declared tiling (to declare geometry that contradicts the affine).
    Returns the world, or raises from catalog_bridge if the plan itself is refused.
    """
    instances, bindings = materialize(destination/'seed', windows=4)
    admission = deepcopy(instances['admission'])
    seed = Path(bindings['queue:synthetic'])
    base = destination/'world'
    base.mkdir()
    ops = Harness(base, base, policy_value=driver._policy())
    ops.close()
    root = ops.root.rename(base/'synthetic')
    (root/driver.DATABASE).rename(root/'empty-harness.sqlite')
    p = root/'plans/plan01'
    record = read(seed/admission['segment_record']['path'])
    record['synthetic'] = True
    put(p/'segment.json', record)
    campaign = read(seed/admission['campaign']['path'])
    header = {k: admission[k] for k in ('created_utc', 'author_profile', 'author_model',
                                       'card_id', 'code_commit', 'skill_commit')}
    width, height = raster_shape
    west, north = Transformer.from_crs('EPSG:3310', 'OGC:CRS84', always_xy=True).transform(
        record['bbox'][0] + nw_offset_m[0], record['bbox'][1] + nw_offset_m[1])
    tiling = dict(tile=512, width=width, height=height, origin=[0, 0], anchor=[west, north], cell=[PIXEL, PIXEL])
    tiling.update(tiling_override or {})
    name = 'input0.tif'
    path = root/'cache'/name
    path.parent.mkdir(exist_ok=True)
    with rasterio.open(path, 'w', driver='GTiff', width=width, height=height, count=1, dtype='float32',
                       crs='EPSG:4326', nodata=-9999, transform=from_origin(west, north, PIXEL, PIXEL),
                       compress='deflate') as ds:
        ds.write(np.full((height, width), -10, dtype='float32'), 1)
    source = dict(path=path.relative_to(root).as_posix(), sha256=refs.sha256(path.read_bytes()),
                  bytes=path.stat().st_size, contract='native-raster-v1')
    row = fx.candidate(name, bbox=record['bbox_crs84'], size=source['bytes'], source_hash=source['sha256'])
    segment = dict(segment_id=record['segment_id'], bbox_crs84=record['bbox_crs84'])
    chosen = windows(tiling) if windows else catalog_bridge._expected_windows(
        512, width, height, tiling['origin'], tiling['anchor'], tiling['cell'], segment)
    selection = fx.window_set(row['source_id'], source, chosen, tiling)
    definition = dict(source_sha256=source['sha256'], raster_crs='EPSG:4326',
                      affine_transform=[PIXEL, 0, west, 0, -PIXEL, north], width=width, height=height,
                      tile_width=512, tile_height=512, tiling_version='window-set-v1', tiling=deepcopy(tiling))
    sha = digest(definition)
    grids = [dict(source_id=row['source_id'], grid_sha256=sha, definition=definition,
                  cols=len({w[0] for w in chosen}), rows=len({w[1] for w in chosen}), total=len(chosen))]
    admission_windows = []
    for index, (x, y, w, h) in enumerate(chosen):
        key = f"{row['source_id']}#{sha}#{index}"
        admission_windows.append(dict(source_id=row['source_id'], grid_sha256=sha, idx=index,
            window_key=key, window_dir=refs.sha256(key.encode()), pixel_window=[x, y, w, h],
            owner_segment_id=record['segment_id'],
            footprint=[west+x*PIXEL, north-(y+h)*PIXEL, west+(x+w)*PIXEL, north-y*PIXEL],
            overlapping_segment_ids=[record['segment_id']]))
    hot = dict(root_id='queue:synthetic', **{k: source[k] for k in ('path', 'sha256', 'bytes')})
    sources = [dict(source_id=row['source_id'], raw_provenance=[hot], retained_inputs=[], hot_cache=[hot],
                    rights='synthetic private use', datum='unknown', reader='native-raster-v1')]
    catalog = fx.frozen_catalog([row])
    catalog_sha = fx.write_catalog(root/'catalog.json', catalog)
    plan = fx.plan(catalog, catalog_sha, [selection], bbox=record['bbox_crs84'],
                   segment_id=record['segment_id'], synthetic=True)
    put(p/'plan.json', plan)
    campaign.update(bbox_crs84=record['bbox_crs84'], source_inventory=[row['source_id']],
                    intended_windows=[w['window_key'] for w in admission_windows])
    put(root/'campaign.json', campaign)
    catalog_ref = driver._ref(root, root/'catalog.json', 'queue:synthetic')
    put(root/'evidence.txt', b'Synthetic offline evidence only; no scientific acceptance.\n')
    put(root/'discovery.json', dict(schema='coast-discovery-evidence-v1', **header, catalog=catalog_ref,
                                    evidence=[driver._ref(root, root/'evidence.txt', 'queue:synthetic')]))
    catalog_bridge.dry_run(root, root/'catalog.json', plan, p/'dry', now=CLOCK.timestamp())
    catalog_bridge.run(root, root/'catalog.json', plan, p/'bridge', now=CLOCK.timestamp())
    admission.update(grids=grids, windows=admission_windows, sources=sources, plan_sha256=digest(plan),
                     selected_source_ids=[row['source_id']], would_enqueue_count=len(admission_windows),
                     **{key: driver._ref(root, path_, 'queue:synthetic') for key, path_ in dict(
                         campaign=root/'campaign.json', plan_file=p/'plan.json', segment_record=p/'segment.json',
                         catalog=root/'catalog.json', discovery=root/'discovery.json',
                         dry_run=p/'dry/bridge-dry-run-receipt.json').items()})
    put(p/'admission.json', admission)
    (p/'runs').mkdir()
    return SimpleNamespace(root=root, p=p, admission=admission, plan=plan, record=record, tiling=tiling,
                           windows=chosen, west=west, north=north)


def context(w):
    return driver._context(w.root, w.p/'admission.json', w.p/'bridge/bridge-receipt.json', w.p/'segment.json')


def test_run_executes_windows_in_admission_index_order(tmp_path, monkeypatch, synthetic_dispatch):
    """A bounded run advances windows in admission order (0, 1, 2, ...), never window_key order
    (0, 1, 10, 11, 2, ...): with 9 ticks (acquire, qualify, map) windows 0-2 finish and 10 is untouched."""
    w = world(tmp_path, raster_shape=(2048, 1536), nw_offset_m=(1500, 4000), windows=None)
    assert len(w.windows) == 12
    context(w)
    monkeypatch.setenv('COAST_EXCLUSIVE_WRITER', str(w.root))
    driver.enqueue(w.root, w.p/'bridge/bridge-receipt.json', w.p/'segment.json',
                   w.p/'admission.json', w.p/'bridge/enqueue-receipt.json', clock=CLOCK.timestamp)
    summary = driver.run(w.root, w.p/'bridge/enqueue-receipt.json', w.p/'runs/run-00.json',
                         max_ticks=9, until=CLOCK.timestamp()+3600, clock=CLOCK.timestamp)
    assert summary['stop_reason'] == 'max_ticks', summary['problems']
    states = [win['state'] for win in summary['windows']]
    assert states.count('map_done') == 3, states
    assert states[2] == 'map_done' and states[10] != 'map_done', ' '.join(f'{i}:{s}' for i, s in enumerate(states))

