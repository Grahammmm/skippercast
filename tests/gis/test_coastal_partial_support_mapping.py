"""SC-5: the contained map stage keeps holes only under the pinned partial policy.

``contained_batch._prepare`` is the source-free gate between qualification and
terrain cores. Under the strict policy any unsupported cell refuses the window.
Under the partial-support policy mask-invalid holes pass through as nodata, but
every supported cell still has to meet the strict depth and uncertainty limits,
the support floor holds, and the qualified result must carry the partial policy
SHA. The upstream qualification readers are replaced with in-memory fixtures so
the gate is tested on its own; they are covered by their own suites.
"""
import numpy as np
import pytest

pytest.importorskip('affine')
pytest.importorskip('pyproj')
pytest.importorskip('shapely')

from affine import Affine  # noqa: E402
from pyproj import CRS  # noqa: E402

from skippercast.coastal import contained_batch  # noqa: E402
from skippercast.coastal.authenticated_v1.policy import WINDOW_QUALITY_HOLDS, evaluate, policy_sha  # noqa: E402
from skippercast.coastal.authenticated_v1.supplement import summarize  # noqa: E402
from skippercast.coastal.authenticated_v1.profiles import CONTAINED, PARTIAL_SUPPORT  # noqa: E402
from skippercast.coastal.coordinator.ordered_trial import PARTIAL_WINDOWS  # noqa: E402

pytestmark = pytest.mark.gis

SIDE = 128
STRICT = {'window_side': SIDE, 'window_count': 4}
PARTIAL = dict(STRICT, support_policy=PARTIAL_SUPPORT)
PAIRS = SIDE * SIDE
CONFIG = STRICT


def _window(index, *, holes, policy, depth=30.0, uncertainty=0.3, sha=None):
    col, row = PARTIAL_WINDOWS[index][:2]
    valid = np.ones((SIDE, SIDE), dtype=bool)
    valid.reshape(-1)[:holes] = False
    depth_array = np.where(valid, depth, np.nan)
    uncertainty_array = np.where(valid, uncertainty, np.nan)
    observation = dict(execution_profile=CONTAINED, window_side=SIDE, window_count=4)
    if policy is not None:
        observation['support_policy'] = policy
    config = PARTIAL if policy is not None else STRICT
    result = dict(source={'sha256': 'a' * 64, 'bytes': 1}, segment_id='seg', observation={'path': 'obs-%d' % index},
                  arrays={'path': 'arrays-%d' % index},
                  policy_sha256=sha if sha is not None else policy_sha(CONTAINED, config))
    item = dict(packet={'synthetic': True}, result=result, result_ref={'sha256': 'r' * 64},
                facts={'header': {'window': [col, row, SIDE, SIDE]}, 'valid_count': int(valid.sum())},
                depth=depth_array, uncertainty=uncertainty_array, valid=valid,
                transform=Affine(2, 0, 721091 + 2 * col, 0, -2, 3826155 - 2 * row),
                crs=CRS.from_epsg(26910), vertical={'datum': 'MLLW', 'lineage': {}})
    arrays = dict(elevation_mask=~valid, uncertainty_mask=np.zeros_like(valid),
                  raw_elevation_data=np.where(valid, -depth, np.nan).astype('float32'),
                  raw_uncertainty_data=np.full((SIDE, SIDE), uncertainty, dtype='float32'))
    return item, arrays, observation


def _prepare(monkeypatch, windows):
    by_packet = {id(packet): window for packet, window in windows}

    monkeypatch.setattr(contained_batch.derived, 'read_window',
                        lambda root, packet, **kw: by_packet[id(packet)][0])
    monkeypatch.setattr(contained_batch.derived, 'arrays',
                        lambda root, ref, **kw: next(w[1] for w in by_packet.values() if w[0]['result']['arrays'] is ref))
    monkeypatch.setattr(contained_batch, 'load',
                        lambda root, ref, **kw: next(w[2] for w in by_packet.values() if w[0]['result']['observation'] is ref))
    return contained_batch._prepare('/nonexistent', [packet for packet, _ in windows], SIDE, 0.0, 1.0,
                                    declared_window_count=4)


def _packets(*specs):
    return [({'schema': 'coastal-derived-window-v1', 'n': i}, _window(i, **spec)) for i, spec in enumerate(specs)]


def test_partial_policy_maps_hole_bearing_windows(monkeypatch):
    items, infos = _prepare(monkeypatch, _packets(
        dict(holes=14, policy=PARTIAL_SUPPORT), dict(holes=4, policy=PARTIAL_SUPPORT),
        dict(holes=299, policy=PARTIAL_SUPPORT), dict(holes=18, policy=PARTIAL_SUPPORT)))
    assert [int((~i['valid']).sum()) for i in items] == [14, 4, 299, 18]
    assert all(i['support_policy'] == PARTIAL_SUPPORT for i in items)
    facts = dict(items[0]['facts'], support={'limitations': [], 'support_kind': 'native_grid_node_footprints'})
    acceptance = contained_batch._acceptance(dict(items[0], facts=facts), {})
    assert contained_batch.PARTIAL_LIMITATION in acceptance['limitations']


def test_strict_policy_still_refuses_holes(monkeypatch):
    with pytest.raises(ValueError, match='strict all-pairs'):
        _prepare(monkeypatch, _packets(dict(holes=4, policy=None)))


@pytest.mark.parametrize('spec,message', [
    (dict(holes=4, policy=PARTIAL_SUPPORT, depth=91.5), 'partial-support'),
    (dict(holes=4, policy=PARTIAL_SUPPORT, uncertainty=1.5), 'partial-support'),
    (dict(holes=4, policy=PARTIAL_SUPPORT, uncertainty=0.0), 'partial-support'),
    (dict(holes=0, policy=PARTIAL_SUPPORT), 'partial-support'),
    (dict(holes=SIDE * SIDE // 2 + 1, policy=PARTIAL_SUPPORT), 'partial-support'),
    (dict(holes=4, policy=PARTIAL_SUPPORT, sha=policy_sha(CONTAINED, STRICT)), 'partial-support'),
    (dict(holes=4, policy='coastal-anything-goes-v1'), 'support policy'),
])
def test_partial_policy_keeps_strict_limits(monkeypatch, spec, message):
    with pytest.raises(ValueError, match=message):
        _prepare(monkeypatch, _packets(spec))


def test_partial_policy_refuses_unmasked_nonfinite_holes(monkeypatch):
    """Review round 1 hardening: holes must be exactly the native mask-invalid cells.

    Raw-NaN cells that the BAG masks do not mark invalid are not admissible
    holes; the map gate enforces its mask-invalid-only contract on its own.
    """
    windows = _packets(dict(holes=4, policy=PARTIAL_SUPPORT))
    windows[0][1][1]['elevation_mask'][:] = False
    with pytest.raises(ValueError, match='partial-support'):
        _prepare(monkeypatch, windows)


def test_one_support_policy_per_batch(monkeypatch):
    with pytest.raises(ValueError, match='support policy'):
        _prepare(monkeypatch, _packets(dict(holes=0, policy=None), dict(holes=4, policy=PARTIAL_SUPPORT)))


# ------------------------------------------------------------ evaluation

FACTS = {'header': {'driver': 'BAG', 'scales': [1.0, 1.0], 'offsets': [0.0, 0.0], 'units': ['m', 'm']}}


def _diagnostics(*, holes=0, depth_fault=None, uncertainty_fault=None, sentinel=0):
    """Same-return diagnostics from synthetic arrays with `holes` mask-invalid cells."""
    shape = (SIDE, SIDE)
    raw = np.full(shape, -30.0, dtype=np.float32)
    unc = np.full(shape, 0.3, dtype=np.float32)
    elevation_mask = np.zeros(shape, dtype=bool)
    flat = elevation_mask.reshape(-1)
    flat[:holes] = True
    valid = ~elevation_mask
    if sentinel:
        # Mask-valid, finite, but rejected by the source sentinel gate.
        source_flat = valid.reshape(-1)
        source_flat[holes:holes + sentinel] = False
    depth = np.where(valid, -raw.astype('float64'), np.nan)
    if depth_fault is not None:
        depth[-1, -1] = depth_fault
    if uncertainty_fault is not None:
        unc[-1, -1] = uncertainty_fault
    arrays = dict(raw_elevation_data=raw, raw_uncertainty_data=unc, elevation_mask=elevation_mask,
                  uncertainty_mask=np.zeros(shape, dtype=bool), source_pair_valid=valid, depth=depth,
                  legacy_25_300ft_uncertainty_0_1m=np.zeros(shape, dtype=bool))
    return summarize(arrays, 'f' * 64)


def _holds(diagnostics, config):
    return evaluate(diagnostics, FACTS, execution_profile=CONTAINED, configuration=config)['holds']


def test_strict_policy_still_holds_any_hole():
    assert _holds(_diagnostics(), CONFIG) == []
    assert _holds(_diagnostics(holes=4), CONFIG) == [
        'bounded_patch_nominal_depth_out_of_range', 'bounded_patch_nominal_support_incomplete',
        'bounded_patch_uncertainty_quality_failed']


@pytest.mark.parametrize('holes', [1, 4, 299, PAIRS // 2])
def test_partial_policy_passes_mask_invalid_holes(holes):
    evaluation = evaluate(_diagnostics(holes=holes), FACTS, execution_profile=CONTAINED, configuration=PARTIAL)
    assert evaluation['holds'] == []
    assert evaluation['paired_eligibility_quality_pass'] is True
    assert evaluation['accepted'] is False
    assert evaluation['policy_sha256'] == policy_sha(CONTAINED, PARTIAL)


@pytest.mark.parametrize('kwargs,hold', [
    (dict(holes=0), 'bounded_patch_partial_support_without_unsupported_cells'),
    (dict(holes=PAIRS // 2 + 1), 'bounded_patch_partial_support_below_floor'),
    (dict(holes=4, depth_fault=91.5), 'bounded_patch_nominal_depth_out_of_range'),
    (dict(holes=4, depth_fault=-0.01), 'bounded_patch_nominal_depth_out_of_range'),
    (dict(holes=4, uncertainty_fault=1.01), 'bounded_patch_uncertainty_quality_failed'),
    (dict(holes=4, uncertainty_fault=0.0), 'bounded_patch_uncertainty_quality_failed'),
    (dict(holes=4, sentinel=3), 'bounded_patch_partial_support_not_mask_only'),
])
def test_partial_policy_keeps_strict_limits_on_supported_cells(kwargs, hold):
    holds = _holds(_diagnostics(**kwargs), PARTIAL)
    assert hold in holds
    assert set(holds) <= WINDOW_QUALITY_HOLDS


def test_partial_policy_holds_unresolved_depth():
    diagnostics = _diagnostics(holes=4)
    diagnostics['counts']['eligible'] = None
    holds = _holds(diagnostics, PARTIAL)
    assert 'bounded_patch_nominal_support_incomplete' in holds
    assert set(holds) <= WINDOW_QUALITY_HOLDS
