"""SC32-BRIDGE-BOUNDS: malformed CRS84 boxes never plan a coast catalog bridge.

The bridge's existing CRS84 bbox contract, made explicit as ``_crs84_bbox``: four
finite non-boolean int/float coordinates ``[west, south, east, north]``,
longitude in -180..180, latitude in -90..90, ``west < east`` and
``south < north``. No wrapping and no anti-meridian interpretation.

* ``check_plan`` refuses a malformed plan segment box with ValueError before any
  candidate or cached source is inspected and before any output exists.
* The candidate gate in ``_decide`` holds a malformed catalog extent with the
  existing ``catalog_extent_does_not_overlap_segment`` reason; a valid extent is
  selected only on a positive-area overlap (edge-only adjacency is not overlap).
* ``_overlaps`` itself is byte-identical to the frozen base. It also decides which
  computed window footprints a window set must carry (``_expected_windows``), and
  a footprint may legitimately reach past the world edge, so the strict contract is
  applied to the external boxes only, never to computed footprints (operator
  refreeze, option 1, after the round-1 review).

Every case runs the complete staged ``catalog_bridge`` module through its public
``dry_run`` / ``run`` / ``check_plan`` entry points, plus the gate as ``_decide``
composes it for non-finite coordinates, which a frozen catalog cannot carry. The
producer shapes come from ``tests._coastal_catalog_fixture``; cached sources are
tiny placeholder files that the bridge only lstat-checks. Sockets are disabled.

Test-local callables used by the acceptance runner's negative suite (swapped in,
in memory; production bytes are never edited):
``legacy_bbox_gate``       no contract at all, the pre-SC32 decision path;
``round1_strict_overlaps`` the round-1 predicate that applied the contract inside
                           ``_overlaps`` and so dropped required world-edge windows.
``legacy_overlaps`` is the frozen-base predicate, verbatim.
"""
import ast
import copy
import inspect
import json
import math
from pathlib import Path
import socket
import textwrap
import tomllib

import pytest

from skippercast.coastal.coordinator import catalog_bridge as bridge
from skippercast.http import Allowlist
from tests import _coastal_catalog_fixture as fx
from tests._support import FIXTURES as SUPPORT_FIXTURES, ROOT

MODULE_PATH = ROOT / 'src/skippercast/coastal/coordinator/catalog_bridge.py'
FIXTURES = SUPPORT_FIXTURES / 'sc32_bridge_bounds'
BOXES = json.loads((FIXTURES / 'boxes.json').read_text(encoding='utf-8'))
SEGMENT = BOXES['segment']
ALLOW = Allowlist([fx.HOST])
HOLD = 'catalog_extent_does_not_overlap_segment'
SOURCE = 'sources/H11952_MB_2m_MLLW_1of1.bag'
# Failure markers the acceptance runner's mutation check looks for.
ACCEPTED = 'SC32-OVERLAP-ACCEPTED'
RAISED = 'SC32-OVERLAP-RAISED'
SELECTED = 'SC32-CANDIDATE-SELECTED'
CRASHED = 'SC32-CANDIDATE-RAISED'
SEGMENT_ACCEPTED = 'SC32-SEGMENT-ACCEPTED'
WINDOW_OMITTED = 'SC32-WINDOW-OMITTED'

# A box whose every coordinate is valid on its own; one position is then replaced.
BASE = [-120.6, 34.45, -120.5, 34.55]
POSITIONS = {0: 'west', 1: 'south', 2: 'east', 3: 'north'}
HUGE = 10 ** 400        # an exact Python int with no float representation


def _kinds(position):
    value = BASE[position]
    return {'true': True, 'false': False, 'numeric-string': str(value), 'null': None,
            'nested-list': [value], 'nested-object': {'value': value},
            'nan': math.nan, 'inf': math.inf, 'minus-inf': -math.inf, 'huge-int': HUGE}


NONFINITE = ('nan', 'inf', 'minus-inf')
COORDINATE_CASES = [(POSITIONS[p], kind) for p in POSITIONS for kind in _kinds(p)]
JSON_COORDINATE_CASES = [c for c in COORDINATE_CASES if c[1] not in NONFINITE]


def _replaced(position_name, kind):
    position = {v: k for k, v in POSITIONS.items()}[position_name]
    box = list(BASE)
    box[position] = _kinds(position)[kind]
    return box


def legacy_overlaps(a, b):
    """The frozen-base catalog_bridge._overlaps, verbatim: float coercion, no range check."""
    try:
        w1, s1, e1, n1 = (float(v) for v in a)
        w2, s2, e2, n2 = (float(v) for v in b)
    except (TypeError, ValueError):
        return False
    if not (w1 < e1 and s1 < n1 and w2 < e2 and s2 < n2):
        return False
    return min(e1, e2) > max(w1, w2) and min(n1, n2) > max(s1, s2)


def legacy_bbox_gate(box):
    """The pre-SC32 decision path had no bbox contract: every box reached _overlaps."""
    return True


def round1_strict_overlaps(a, b):
    """The round-1 (b1d5fd98) _overlaps: the strict contract applied to every call."""
    if not (bridge._crs84_bbox(a) and bridge._crs84_bbox(b)):
        return False
    w1, s1, e1, n1 = a
    w2, s2, e2, n2 = b
    return min(e1, e2) > max(w1, w2) and min(n1, n2) > max(s1, s2)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('the catalog bridge must not open a socket')
    monkeypatch.setattr(socket, 'socket', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)
    monkeypatch.setattr(socket, 'getaddrinfo', refuse)


@pytest.fixture
def world(tmp_path):
    root = tmp_path / 'queue'
    root.mkdir()
    return dict(root=root, tmp=tmp_path, source=fx.cache_file(root, SOURCE))


def _candidate_world(world, bbox, name='c.bag'):
    """One producer-shaped candidate with ``bbox`` set verbatim (falsy boxes included)."""
    row = fx.candidate(name, size=world['source']['bytes'], source_hash=world['source']['sha256'])
    row['extent']['bbox'] = copy.deepcopy(bbox)
    catalog = fx.frozen_catalog([row])
    path = world['tmp'] / f"catalog-{len(list(world['tmp'].glob('catalog-*.json')))}.json"
    sha = fx.write_catalog(path, catalog)
    plan = fx.plan(catalog, sha, [fx.selection(row['source_id'], world['source'])])
    return path, plan, catalog, sha


def _segment_plan(world, segment_bbox):
    """The ordinary single-candidate plan with its segment box replaced verbatim."""
    path, plan, catalog, sha = _candidate_world(world, BASE)
    plan['segment']['bbox_crs84'] = copy.deepcopy(segment_bbox)
    return path, plan, catalog, sha


def _dry(world, path, plan, label='dry'):
    return bridge.dry_run(world['root'], path, plan, world['tmp'] / label, allowlist=ALLOW)


def _candidate_gate_or_marker(box, segment=SEGMENT):
    """The candidate extent gate exactly as _decide composes it (bbox contract, then overlap)."""
    try:
        return bool(bridge._crs84_bbox(box) and bridge._overlaps(box, segment))
    except Exception as error:  # noqa: BLE001 - a crash is the defect the marker names
        pytest.fail(f'{RAISED}: the candidate gate raised {type(error).__name__} for {box!r}')


def _legacy_expected_windows(geometry, segment):
    """Frozen-base window completeness: unchanged production tiling with the base predicate."""
    bbox = segment['bbox_crs84']
    origin = geometry['origin']
    return [w for w in bridge._canonical_tiles(geometry['tile'], geometry['width'], geometry['height'], origin)
            if legacy_overlaps(bridge._window_bbox(geometry['anchor'], geometry['cell'], w[0] - origin[0],
                                                   w[1] - origin[1], w[2], w[3]), bbox)]


def _edge_case(name):
    case = BOXES['world_edge_tilings'][name]
    geometry = fx.tiling(case['width'], case['height'], anchor=tuple(case['anchor']), cell=tuple(case['cell']))
    return case, geometry, dict(segment_id='synthetic-world-edge', bbox_crs84=list(case['bbox']))


# --- A1 valid and boundary behaviour ----------------------------------------------------

@pytest.mark.parametrize('name', sorted(BOXES['candidate_overlapping']))
def test_a1_valid_candidate_extent_is_selected(world, name):
    path, plan, catalog, sha = _candidate_world(world, BOXES['candidate_overlapping'][name])
    receipt = _dry(world, path, plan)
    decision = receipt['decisions'][0]
    assert decision['state'] == 'selected' and decision['holds'] == [], decision
    assert receipt['selected_source_ids'] == [decision['source_id']] and receipt['held_source_ids'] == []
    assert receipt['network_requests'] == receipt['source_opens'] == receipt['source_bytes_read'] == 0
    assert receipt['review_required'] is True and receipt['mapping_accepted'] is False
    assert receipt['execution_authorized'] is False
    assert receipt['caps'] == dict(max_jobs=bridge.LEGACY_MAX_JOBS, max_total_bytes=bridge.MAX_TOTAL_BYTES,
                                   plan_max_total_bytes=plan['max_total_bytes'],
                                   selected_bytes=world['source']['bytes'], acquire_budget=fx.BUDGET)
    assert [entry['stage'] for entry in receipt['would_enqueue']] == ['acquire']
    assert sorted(p.name for p in (world['tmp'] / 'dry').iterdir()) == ['bridge-dry-run-receipt.json']


@pytest.mark.parametrize('name', sorted(BOXES['candidate_not_overlapping']))
def test_a1_edge_adjacent_and_disjoint_candidates_are_held(world, name):
    path, plan, catalog, sha = _candidate_world(world, BOXES['candidate_not_overlapping'][name])
    receipt = _dry(world, path, plan)
    assert receipt['selected_source_ids'] == []
    assert receipt['decisions'][0]['holds'] == [HOLD]


@pytest.mark.parametrize('name', sorted(BOXES['segment_valid_geographic_edges']))
def test_a1_segment_boxes_on_exact_geographic_edges_plan_normally(world, name):
    segment_bbox = BOXES['segment_valid_geographic_edges'][name]
    path, plan, catalog, sha = _candidate_world(world, [-180, -90, 180, 90])
    plan['segment']['bbox_crs84'] = list(segment_bbox)
    before = copy.deepcopy(plan)
    receipt = _dry(world, path, plan)
    assert receipt['selected_source_ids'] == [receipt['decisions'][0]['source_id']]
    assert plan == before, 'check_plan must not rewrite the submitted plan'
    assert [type(v) for v in plan['segment']['bbox_crs84']] == [type(v) for v in segment_bbox]


def test_a1_overlap_predicate_is_positive_area_only_and_symmetric():
    for name, box in BOXES['candidate_overlapping'].items():
        assert bridge._crs84_bbox(box) is True, name
        assert bridge._overlaps(box, SEGMENT) is True, name
        assert bridge._overlaps(SEGMENT, box) is True, name
    for name, box in BOXES['candidate_not_overlapping'].items():
        assert bridge._crs84_bbox(box) is True, name
        assert bridge._overlaps(box, SEGMENT) is False, name
        assert bridge._overlaps(SEGMENT, box) is False, name
    for name, box in BOXES['segment_valid_geographic_edges'].items():
        assert bridge._crs84_bbox(box) is True, name
        assert bridge._overlaps(box, box) is True, name


def test_a1_ordinary_dry_run_keeps_its_receipt_shape(world):
    """The producer-default world selects exactly as before: same caps, flags and decisions."""
    path, plan, catalog, sha = _candidate_world(world, BASE)
    plan['segment']['bbox_crs84'] = list(fx.SEGMENT_BBOX)
    receipt = _dry(world, path, plan)
    assert receipt['schema'] == bridge.DRY_RUN
    assert receipt['decisions'][0]['catalog_hash_binding'] == 'matched'
    assert receipt['decisions'][0]['state'] == 'selected'
    assert receipt['segment_id'] == plan['segment']['segment_id']
    assert receipt['caps']['max_jobs'] == bridge.LEGACY_MAX_JOBS == 4
    assert bridge.MAX_TOTAL_BYTES == 2 * 1024 ** 3 and bridge.MAX_WINDOWS == 64 and bridge.MAX_SOURCES == 4
    assert receipt['network_requests'] == receipt['source_opens'] == 0


@pytest.mark.parametrize('name', sorted(BOXES['world_edge_tilings']))
def test_a1_world_edge_window_set_keeps_baseline_completeness(world, name):
    """A valid world-edge segment keeps every frozen-base window, whose footprint may cross the edge.

    The complete window set is selected with one acquire job per window; the same
    plan omitting the edge-crossing tile is refused, exactly as on the frozen base.
    """
    case, geometry, segment = _edge_case(name)
    baseline = _legacy_expected_windows(geometry, segment)
    assert len(baseline) == case['required_windows'], baseline
    last = baseline[-1]
    footprint = bridge._window_bbox(geometry['anchor'], geometry['cell'], last[0] - geometry['origin'][0],
                                    last[1] - geometry['origin'][1], last[2], last[3])
    west, south, east, north = footprint
    assert not (-180 <= west and east <= 180 and -90 <= south and north <= 90), \
        'the fixture must exercise an edge-crossing footprint'
    produced = bridge._expected_windows(geometry['tile'], geometry['width'], geometry['height'],
                                        geometry['origin'], geometry['anchor'], geometry['cell'], segment)
    if produced != baseline:
        pytest.fail(f'{WINDOW_OMITTED}: _expected_windows gave {produced!r}, frozen base {baseline!r}')

    source = world['source']
    row = fx.candidate('edge.bag', bbox=list(case['bbox']), size=source['bytes'], source_hash=source['sha256'])
    catalog = fx.frozen_catalog([row])
    path = world['tmp'] / 'catalog-edge.json'
    sha = fx.write_catalog(path, catalog)

    complete = fx.plan(catalog, sha, [fx.window_set(row['source_id'], source, baseline, tiling=geometry)],
                       bbox=list(case['bbox']), segment_id=segment['segment_id'])
    receipt = _dry(world, path, complete, label='complete')
    assert receipt['selected_source_ids'] == [row['source_id']], receipt['decisions']
    assert [entry['stage'] for entry in receipt['would_enqueue']] == ['acquire'] * len(baseline)
    assert receipt['network_requests'] == receipt['source_opens'] == 0

    omitted = fx.plan(catalog, sha, [fx.window_set(row['source_id'], source, baseline[:-1], tiling=geometry)],
                      bbox=list(case['bbox']), segment_id=segment['segment_id'])
    try:
        _dry(world, path, omitted, label='omitted')
    except ValueError as error:
        assert 'deterministic tiling' in str(error), error
    else:
        pytest.fail(f'{WINDOW_OMITTED}: a plan omitting required window {last!r} was accepted')
    assert not (world['tmp'] / 'omitted').exists()


# --- A2 malformed input and preservation -------------------------------------------------

@pytest.mark.parametrize('position, kind', COORDINATE_CASES)
def test_a2_bbox_contract_rejects_a_malformed_coordinate(position, kind):
    box = _replaced(position, kind)
    result = _candidate_gate_or_marker(box)
    assert result is False, f'{ACCEPTED}: the candidate gate accepted {box!r}'
    assert bridge._crs84_bbox(box) is False, f'{ACCEPTED}: _crs84_bbox accepted {box!r}'


@pytest.mark.parametrize('name', sorted(BOXES['malformed_shapes']))
def test_a2_bbox_contract_rejects_a_malformed_shape(name):
    box = BOXES['malformed_shapes'][name]
    result = _candidate_gate_or_marker(box)
    assert result is False, f'{ACCEPTED}: the candidate gate accepted {box!r}'
    assert bridge._crs84_bbox(box) is False, f'{ACCEPTED}: _crs84_bbox accepted {box!r}'


def test_a2_bbox_contract_rejects_tuples_and_numeric_string_boxes():
    assert bridge._crs84_bbox(tuple(BASE)) is False
    assert bridge._crs84_bbox([str(v) for v in BASE]) is False
    assert _candidate_gate_or_marker(tuple(BASE)) is False
    assert _candidate_gate_or_marker([str(v) for v in BASE]) is False


def _expect_segment_refusal(call):
    try:
        call()
    except ValueError as error:
        if 'bbox_crs84' not in str(error):
            pytest.fail(f'{SEGMENT_ACCEPTED}: refused for another reason: {error}')
        return
    except Exception as error:  # noqa: BLE001 - reaching a later stage is the defect the marker names
        pytest.fail(f'{SEGMENT_ACCEPTED}: the malformed segment reached {type(error).__name__}: {error}')
    pytest.fail(f'{SEGMENT_ACCEPTED}: the malformed segment plan was accepted')


def _assert_refused_before_inspection(world, monkeypatch, segment_bbox):
    path, plan, catalog, sha = _segment_plan(world, segment_bbox)
    submitted = copy.deepcopy(plan)
    touched = []

    def spy(name):
        def refused(*args, **kwargs):
            touched.append(name)
            raise AssertionError(f'{name} reached for a malformed plan segment')
        return refused

    monkeypatch.setattr(bridge, 'cached_source', spy('cached_source'))
    monkeypatch.setattr(bridge, '_decide', spy('_decide'))
    monkeypatch.setattr(bridge, '_overlaps', spy('_overlaps'))
    _expect_segment_refusal(lambda: bridge.dry_run(world['root'], path, plan, world['tmp'] / 'dry',
                                                   allowlist=ALLOW))
    _expect_segment_refusal(lambda: bridge.run(world['root'], path, plan, world['root'] / 'bridge',
                                               allowlist=ALLOW))
    _expect_segment_refusal(lambda: bridge.check_plan(plan, path.read_bytes(), catalog))
    assert touched == []
    assert not (world['tmp'] / 'dry').exists() and not (world['root'] / 'bridge').exists()
    assert sorted(p.relative_to(world['root']).as_posix() for p in world['root'].rglob('*')) == [
        'sources', SOURCE]
    # deepcopy keeps the same float objects, so a NaN compares equal by identity here.
    assert plan == submitted, 'the malformed box must be refused as submitted, not replaced'


@pytest.mark.parametrize('position, kind', COORDINATE_CASES)
def test_a2_malformed_segment_coordinate_is_refused_before_any_source_or_output(
        world, monkeypatch, position, kind):
    _assert_refused_before_inspection(world, monkeypatch, _replaced(position, kind))


@pytest.mark.parametrize('name', sorted(BOXES['malformed_shapes']))
def test_a2_malformed_segment_shape_is_refused_before_any_source_or_output(world, monkeypatch, name):
    _assert_refused_before_inspection(world, monkeypatch, BOXES['malformed_shapes'][name])


def _held(world, bbox):
    path, plan, catalog, sha = _candidate_world(world, bbox)
    submitted = path.read_bytes()
    try:
        receipt = _dry(world, path, plan)
    except Exception as error:  # noqa: BLE001 - a crash is the defect the marker names
        pytest.fail(f'{CRASHED}: dry_run raised {type(error).__name__} for candidate bbox {bbox!r}')
    decision = receipt['decisions'][0]
    assert decision['state'] == 'held', f'{SELECTED}: candidate bbox {bbox!r} was selected'
    assert decision['holds'] == [HOLD], decision['holds']
    assert receipt['selected_source_ids'] == [] and receipt['would_enqueue'] == []
    assert receipt['source_opens'] == receipt['network_requests'] == 0
    assert path.read_bytes() == submitted
    assert json.loads(path.read_text())['candidates'][0]['extent']['bbox'] == bbox


@pytest.mark.parametrize('position, kind', JSON_COORDINATE_CASES)
def test_a2_malformed_candidate_coordinate_is_held(world, position, kind):
    _held(world, _replaced(position, kind))


@pytest.mark.parametrize('name', sorted(BOXES['malformed_shapes']))
def test_a2_malformed_candidate_shape_is_held(world, name):
    _held(world, BOXES['malformed_shapes'][name])


@pytest.mark.parametrize('position, kind', [c for c in COORDINATE_CASES if c[1] in NONFINITE])
def test_a2_nonfinite_candidate_extent_cannot_enter_a_frozen_catalog(position, kind):
    """A frozen catalog's canonical digest refuses NaN/infinity, so the gate covers them directly."""
    row = fx.candidate('c.bag')
    row['extent']['bbox'] = _replaced(position, kind)
    with pytest.raises(ValueError, match='JSON compliant'):
        fx.frozen_catalog([row])


def test_a2_candidate_failures_keep_the_existing_hold_vocabulary(world):
    rows = [fx.candidate('ok.bag', size=world['source']['bytes'], source_hash=world['source']['sha256']),
            fx.candidate('str.bag'), fx.candidate('range.bag'), fx.candidate('crs.bag')]
    rows[1]['extent']['bbox'] = [str(v) for v in BASE]
    rows[2]['extent']['bbox'] = [-120.6, 34.45, 181, 34.55]
    rows[3]['extent']['bbox_crs'] = 'EPSG:3310'
    catalog = fx.frozen_catalog(rows)
    path = world['tmp'] / 'catalog-mixed.json'
    sha = fx.write_catalog(path, catalog)
    plan = fx.plan(catalog, sha, [fx.selection(r['source_id'], world['source']) for r in rows])
    receipt = _dry(world, path, plan)
    holds = {d['source_id']: d['holds'] for d in receipt['decisions']}
    assert receipt['selected_source_ids'] == ['ncei:ok.bag']
    assert holds['ncei:str.bag'] == holds['ncei:range.bag'] == holds['ncei:crs.bag'] == [HOLD]


# --- A3 decisive synthetic mutation -----------------------------------------------------

def test_mutation_controls_unguarded_gate_accepts_what_production_refuses():
    string_box = [str(v) for v in BASE]
    wide_east = [-120.6, 34.45, 200.0, 34.55]
    open_west = [-math.inf, 34.45, -120.5, 34.55]
    huge_east = [-120.6, 34.45, HUGE, 34.55]
    for box in (string_box, wide_east, open_west):
        assert (legacy_bbox_gate(box) and legacy_overlaps(box, SEGMENT)) is True
    with pytest.raises(OverflowError):
        legacy_bbox_gate(huge_east) and legacy_overlaps(huge_east, SEGMENT)
    for box in (string_box, wide_east, open_west, huge_east):
        assert bridge._crs84_bbox(box) is False
        assert _candidate_gate_or_marker(box) is False


def test_mutation_controls_legacy_and_production_agree_on_valid_boxes():
    for box in BOXES['candidate_overlapping'].values():
        assert legacy_overlaps(box, SEGMENT) is bridge._overlaps(box, SEGMENT) is True
        assert _candidate_gate_or_marker(box) is True
    for box in BOXES['candidate_not_overlapping'].values():
        assert legacy_overlaps(box, SEGMENT) is bridge._overlaps(box, SEGMENT) is False
        assert _candidate_gate_or_marker(box) is False


def _function_ast(function):
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    node = tree.body[0]
    node.name = '_overlaps'
    if ast.get_docstring(node) is not None:
        node.body = node.body[1:]
    return ast.dump(node)


def test_mutation_controls_overlaps_matches_the_frozen_base_predicate():
    """Computed window footprints keep the frozen-base predicate: _overlaps is unchanged."""
    assert _function_ast(bridge._overlaps) == _function_ast(legacy_overlaps)
    assert _function_ast(bridge._overlaps) != _function_ast(round1_strict_overlaps)


@pytest.mark.parametrize('name', sorted(BOXES['world_edge_tilings']))
def test_mutation_controls_round1_strict_predicate_drops_a_required_world_edge_window(name):
    case, geometry, segment = _edge_case(name)
    baseline = _legacy_expected_windows(geometry, segment)
    original = bridge._overlaps
    try:
        bridge._overlaps = round1_strict_overlaps
        strict = bridge._expected_windows(geometry['tile'], geometry['width'], geometry['height'],
                                          geometry['origin'], geometry['anchor'], geometry['cell'], segment)
    finally:
        bridge._overlaps = original
    assert len(baseline) == case['required_windows'] and strict == baseline[:-1]


def test_mutation_controls_production_predicate_is_not_the_legacy_callable():
    for double in (legacy_overlaps, legacy_bbox_gate, round1_strict_overlaps):
        assert bridge._overlaps is not double and bridge._crs84_bbox is not double
    assert bridge._overlaps.__module__ == bridge._crs84_bbox.__module__ == bridge.__name__
    assert Path(bridge.__file__).resolve() == MODULE_PATH.resolve()


# --- A4 module identity and discovery ---------------------------------------------------

def test_a4_tests_import_the_complete_staged_production_module():
    assert Path(bridge.__file__).resolve() == MODULE_PATH.resolve()
    for name in ('check_plan', 'evaluate', 'dry_run', 'run', 'enqueue', '_overlaps', '_crs84_bbox', '_decide',
                 '_expected_windows'):
        assert callable(getattr(bridge, name))


def test_a4_new_test_module_is_discovered_by_configured_patterns():
    config = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    options = config['tool']['pytest']['ini_options']
    relative = Path(*__name__.split('.')).with_suffix('.py')
    assert (ROOT / relative).is_file()
    assert relative.parts[0] in options['testpaths']
    assert any(Path(relative.name).match(pattern) for pattern in options['python_files'])
