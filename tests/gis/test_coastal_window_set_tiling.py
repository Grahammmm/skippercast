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
    raw_root = destination/'raw'
    raw_root.mkdir()
    (raw_root/name).write_bytes(path.read_bytes())
    raw = dict(hot, root_id='raw:campaign', path=name)
    sources = [dict(source_id=row['source_id'], raw_provenance=[raw], retained_inputs=[], hot_cache=[hot],
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
                           windows=chosen, west=west, north=north,
                           bindings={'queue:synthetic': str(root), 'raw:campaign': str(raw_root.absolute())})


def context(w):
    return driver._context(w.root, w.p/'admission.json', w.p/'bridge/bridge-receipt.json', w.p/'segment.json')


def true_tiles(w, width, height):
    """Tiles that really intersect the segment, using the raster's real affine (anchor/cell = truth)."""
    segment = dict(bbox_crs84=w.record['bbox_crs84'])
    return catalog_bridge._expected_windows(512, width, height, [0, 0], [w.west, w.north], [PIXEL, PIXEL], segment)


# --- Finding 1 -------------------------------------------------------------------------------

def test_window_set_tiling_geometry_not_bound_to_affine(tmp_path):
    """A wrong declared cell (1 degree, not 1e-5) makes the bridge want 1 tile of 4; it is refused."""
    w = world(tmp_path, raster_shape=(1024, 1024), nw_offset_m=(2000, 3000), windows=None,
              tiling_override=dict(cell=[1.0, 1.0]))
    assert w.windows == [[0, 0, 512, 512]]                      # bridge's "complete" tiling
    assert len(true_tiles(w, 1024, 1024)) == 4                  # what really intersects the segment
    with pytest.raises(ValueError, match='grid_geometry: window-set tiling cell disagrees'):
        context(w)


def test_window_set_tiling_anchor_must_match_affine(tmp_path):
    shifted = lambda tiling: dict(anchor=[tiling['anchor'][0] + 512*PIXEL, tiling['anchor'][1]])  # noqa: E731
    w = world(tmp_path/'probe', raster_shape=(1024, 1024), nw_offset_m=(2000, 3000), windows=None)
    w = world(tmp_path/'shifted', raster_shape=(1024, 1024), nw_offset_m=(2000, 3000), windows=None,
              tiling_override=shifted(w.tiling))
    with pytest.raises(ValueError, match='grid_geometry: window-set tiling anchor disagrees'):
        context(w)


def test_interior_window_set_with_matching_geometry_admitted(tmp_path):
    w = world(tmp_path, raster_shape=(1024, 1024), nw_offset_m=(2000, 3000), windows=None)
    assert len(w.windows) == 4
    assert len(context(w)[0]['windows']) == 4


def _equivalent_crs(name):
    from pyproj import CRS
    return CRS('EPSG:4326').to_wkt() if name == 'wkt' else name


def _rebind_crs(w, crs):
    """Change representation only; keep all dependent admission identities valid."""
    grid = w.admission['grids'][0]
    grid['definition']['raster_crs'] = crs
    grid['grid_sha256'] = digest(grid['definition'])
    for win in w.admission['windows']:
        win['grid_sha256'] = grid['grid_sha256']
        win['window_key'] = f"{win['source_id']}#{grid['grid_sha256']}#{win['idx']}"
        win['window_dir'] = refs.sha256(win['window_key'].encode())
    campaign = read(w.root/'campaign.json')
    campaign['intended_windows'] = [win['window_key'] for win in w.admission['windows']]
    put(w.root/'campaign.json', campaign)
    w.admission['campaign'] = driver._ref(w.root, w.root/'campaign.json', 'queue:synthetic')
    put(w.p/'admission.json', w.admission)


def _affine_intersecting_tiles(w):
    """Independent oracle: affine corner polygons, not the declared tiling helper."""
    from shapely.geometry import Polygon, box
    a, b, c, d, e, f = w.admission['grids'][0]['definition']['affine_transform']
    transform = Transformer.from_crs(w.admission['grids'][0]['definition']['raster_crs'],
                                     'OGC:CRS84', always_xy=True)
    segment = box(*w.record['bbox_crs84'])
    return [[x, y, 512, 512] for y in (0, 512) for x in (0, 512)
            if Polygon([transform.transform(a*col+b*row+c, d*col+e*row+f)
                        for col, row in ((x, y), (x+512, y), (x+512, y+512), (x, y+512))]
                       ).intersection(segment).area > 0]


@pytest.mark.parametrize('crs', ['EPSG:4326', 'OGC:CRS84', 'epsg:4326',
                                'urn:ogc:def:crs:EPSG::4326', 'wkt',
                                'urn:ogc:def:crs:OGC:1.3:CRS84'])
@pytest.mark.parametrize('problem', [None, 'cell', 'anchor'])
@pytest.mark.parametrize('consumer', ['driver', 'validator'])
def test_crs_equivalence_geometry_gate(tmp_path, monkeypatch, crs, problem, consumer):
    from tests.gis.test_coastal_bridge_run_window_set import validator
    override = {'cell': [1.0, 1.0]} if problem == 'cell' else None
    if problem == 'anchor':
        probe = world(tmp_path/'probe', raster_shape=(1024, 1024),
                      nw_offset_m=(2000, 3000), windows=None)
        override = {'anchor': [probe.west + 512*PIXEL, probe.north]}
    w = world(tmp_path/'case', raster_shape=(1024, 1024), nw_offset_m=(2000, 3000),
              windows=None, tiling_override=override)
    _rebind_crs(w, _equivalent_crs(crs))
    assert _affine_intersecting_tiles(w) == [[x, y, 512, 512] for y in (0, 512) for x in (0, 512)]
    assert len(w.windows) == (1 if problem == 'cell' else 4)
    validator.validate_schema(w.admission)

    def admit():
        if consumer == 'driver':
            return context(w)
        return validator.validate(w.admission, refs.Resolver(w.bindings,
                                  allowed_root_ids=w.bindings), root_id='queue:synthetic')

    before = {p.relative_to(w.root): p.read_bytes() for p in w.root.rglob('*') if p.is_file()}
    if problem is None:
        admit()
    else:
        # The exact same fixture admits with ONLY this gate disabled. Schema,
        # hash, cardinality, campaign and ownership checks therefore cannot mask it.
        with monkeypatch.context() as control:
            control.setattr(catalog_bridge, 'tiling_affine_problem', lambda *_: None)
            admit()
        prefix = 'window binding mismatch: grid_geometry: ' if consumer == 'driver' else ''
        with pytest.raises(ValueError) as error:
            admit()
        assert str(error.value) == prefix + f'window-set tiling {problem} disagrees with the grid affine'
    assert {p.relative_to(w.root): p.read_bytes() for p in w.root.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('crs', ['EPSG:3310', 'EPSG:4269'])
def test_crs_equivalence_does_not_reclassify_other_grids(crs):
    # Projected metres and a genuinely different geographic datum are not
    # CRS84-degree affines. Preserve the helper's existing unchecked contract.
    definition = dict(raster_crs=crs, affine_transform=[2, 0, 100, 0, -2, 200])
    tiling = dict(origin=[0, 0], anchor=[0, 0], cell=[1, 1])
    assert catalog_bridge.tiling_affine_problem(tiling, definition) is None
    definition['affine_transform'][1] = 1
    assert catalog_bridge.tiling_affine_problem(tiling, definition) == 'window-set grid affine must not be rotated'


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

