"""SC-5: the pinned contained partial-support policy beside the strict one.

G option A (2026-10-20): mask-invalid native cells become unsupported/nodata
holes instead of holding the whole window, while every supported cell keeps the
strict depth (0..91.44 m) and product-uncertainty (0 < u <= 1 m) limits. The
strict all-pairs policy, its SHA and the strict grant identity must not change,
and the partial policy is only admitted with its own pinned four128 window set.
"""
import pytest

from skippercast.coastal.authenticated_v1.policy import (
    POLICY_SHA,
    policy_for_profile,
    policy_sha,
)
from skippercast.coastal.authenticated_v1.profiles import (
    CONTAINED,
    LARGER,
    PARTIAL_SUPPORT,
    grant_identity,
    profile,
    validate_grant_packet,
)
from skippercast.coastal.coordinator.ordered_trial import (
    LARGER_AFFINE,
    LARGER_BOUNDS,
    LARGER_RUNTIME,
    LARGER_SCOPE,
    LARGER_WINDOWS,
    PARTIAL_BOUNDS,
    PARTIAL_WINDOWS,
    SCOPE_REVIEW,
    scope_windows,
    validate_scope_review,
)
from skippercast.coastal.coordinator.packet_release import _grant_context
from skippercast.coastal.handoff.common import digest, ref, write
from skippercast.coastal.output_writer import COMPACT_V2_PROFILE, declaration

SIDE = 128
PAIRS = SIDE * SIDE
CONFIG = {'window_side': SIDE, 'window_count': 4}
PARTIAL = dict(CONFIG, support_policy=PARTIAL_SUPPORT)
CODE_SHA = 'c' * 64
DEPS_SHA = 'd' * 64

# Digests computed before this change (origin/main 3f30dfbbf) and after it:
# identical. A strict admission keeps its exact policy and grant identity.
STRICT_POLICY_SHA = 'bd787c80167be8c40077f3f9c6fac4d27dd9c66025bbdb4563ecfb9ba248ca41'
STRICT_CONTAINED_SHA = {
    32: '316cc60a10edebcf728b99fb171ab96dac909ce62c169a5fa8201bf52c0c20fd',
    64: 'ccb87dca6fb07751df0859e300f2c9408d9810080dbe3b91fe94bdc25360e451',
    128: 'df3303146ccbbc0b0f28278aa79edf5f453850650a1f83faecf84542a13e5526',
}
STRICT_GRANT_IDENTITY = 'b9229489140420a5dcd90d7ea10b227bf3209f33ecf2c33762b8a9b1a6734cee'


def _source():
    return {'path': 'x.bag', 'sha256': 'a' * 64, 'bytes': 1}


def _grant(windows, **extra):
    grant = {'schema': 'coastal-authenticated-policy-v1', 'source': _source(), 'source_root': '/tmp/s',
             'source_relative_path': 'x.bag', 'execution_profile': CONTAINED,
             'window_side': SIDE, 'window_count': 4, 'window_set': [list(w) for w in windows]}
    grant.update(extra)
    return grant


# ---------------------------------------------------------------- policy pins

def test_strict_policy_and_grant_identity_digests_are_unchanged():
    assert POLICY_SHA == STRICT_POLICY_SHA
    for side, expected in STRICT_CONTAINED_SHA.items():
        assert policy_sha(CONTAINED, {'window_side': side, 'window_count': 4}) == expected
    assert digest(grant_identity(_grant(LARGER_WINDOWS))) == STRICT_GRANT_IDENTITY
    assert 'support_policy' not in grant_identity(_grant(LARGER_WINDOWS))
    assert 'support_policy' not in policy_for_profile(CONTAINED, CONFIG)


def test_partial_policy_is_a_distinct_pinned_policy():
    strict = policy_for_profile(CONTAINED, CONFIG)
    partial = policy_for_profile(CONTAINED, PARTIAL)
    assert partial['schema'] == 'coastal-fixed-patch-policy-partial-v1'
    assert partial['support_policy'] == PARTIAL_SUPPORT
    assert partial['minimum_supported_pairs'] == PAIRS // 2
    assert partial['minimum_unsupported_pairs'] == 1
    assert partial['unsupported_cells'] == 'mask_invalid_only_as_nodata'
    assert partial['mask_raw_source_normalized_finite_pairs'] == 'all_mask_valid'
    assert partial['quality_pairs'] == 'all_mask_valid'
    # Every supported cell keeps the strict physical limits.
    for key in ('depth_minimum_m', 'depth_maximum_m', 'depth_minimum_inclusive', 'depth_maximum_inclusive',
                'uncertainty_minimum_m', 'uncertainty_minimum_inclusive', 'uncertainty_maximum_m',
                'uncertainty_maximum_inclusive', 'product_uncertainty_type', 'product_uncertainty_units',
                'independent_quality_review_required', 'no_relocation', 'legacy_25ft_floor', 'paired_cells'):
        assert partial[key] == strict[key], key
    assert policy_sha(CONTAINED, PARTIAL) != policy_sha(CONTAINED, CONFIG)


@pytest.mark.parametrize('name,config', [
    (None, {'support_policy': PARTIAL_SUPPORT}),
    (LARGER, {'support_policy': PARTIAL_SUPPORT}),
    (CONTAINED, dict(CONFIG, support_policy='coastal-anything-goes-v1')),
    (CONTAINED, dict(CONFIG, support_policy='')),
])
def test_support_policy_is_closed(name, config):
    with pytest.raises(ValueError):
        profile(name, config)
    with pytest.raises(ValueError):
        policy_for_profile(name, config)


# ------------------------------------------------------- grant and packet

def _ordered(**extra):
    """The full ordered four128 authority a partial grant must carry."""
    fields = dict(ordered_scope_contract=LARGER_SCOPE, larger_runtime_contract=LARGER_RUNTIME,
                  geographic_review={'path': 'metadata/scope-review.json', 'sha256': 'e' * 64, 'bytes': 1,
                                     'contract': SCOPE_REVIEW},
                  output_retention=declaration(0, 32 * 1024 * 1024, profile=COMPACT_V2_PROFILE),
                  output_root='/tmp/skippercast-output')
    fields.update(extra)
    return fields


def _partial_packet(grant, window):
    packet = {key: grant[key] for key in ('execution_profile', 'window_side', 'window_count', 'source',
                                          'source_root', 'source_relative_path', 'ordered_scope_contract',
                                          'geographic_review', 'output_retention', 'output_root',
                                          'larger_runtime_contract') if key in grant}
    packet['fixed_center_plan'] = {'native_window': window}
    return packet


def test_partial_grant_identity_binds_support_policy_and_packets():
    grant = _grant(PARTIAL_WINDOWS, support_policy=PARTIAL_SUPPORT, **_ordered())
    domain = grant_identity(grant)
    assert domain['support_policy'] == PARTIAL_SUPPORT
    assert digest(domain) != digest(grant_identity(_grant(PARTIAL_WINDOWS, **_ordered())))
    packet = _partial_packet(grant, PARTIAL_WINDOWS[0])
    with pytest.raises(ValueError, match='support policy'):
        validate_grant_packet(grant, packet)
    assert validate_grant_packet(grant, dict(packet, support_policy=PARTIAL_SUPPORT)) == domain
    with pytest.raises(ValueError, match='support policy'):
        validate_grant_packet(_grant(PARTIAL_WINDOWS, **_ordered()), dict(packet, support_policy=PARTIAL_SUPPORT))


# Review round 1 (P1): the partial policy is pinned at the shared authority
# boundary, not only in the ordered-trial scope review. An unscoped, reshaped
# or relocated partial grant fails closed in grant_identity itself, so
# Store.enqueue_authenticated and every validate_grant_packet caller refuse it.

def test_partial_grant_without_ordered_authority_fails_closed():
    with pytest.raises(ValueError, match='ordered four128'):
        grant_identity(_grant(PARTIAL_WINDOWS, support_policy=PARTIAL_SUPPORT))
    for missing in ('ordered_scope_contract', 'larger_runtime_contract', 'geographic_review',
                    'output_retention', 'output_root'):
        fields = _ordered()
        fields.pop(missing)
        with pytest.raises(ValueError, match='ordered|runtime|geometry'):
            grant_identity(_grant(PARTIAL_WINDOWS, support_policy=PARTIAL_SUPPORT, **fields))
    with pytest.raises(ValueError, match='ordered four128'):
        grant_identity(_grant(PARTIAL_WINDOWS, support_policy=PARTIAL_SUPPORT, **_ordered(geographic_review=None)))


def test_partial_grant_shape_count_and_windows_are_pinned():
    # The round-1 reproduction: a 32x32/count=1 partial grant on [0,0,32,32].
    small = _grant([[0, 0, 32, 32]], window_side=32, window_count=1, support_policy=PARTIAL_SUPPORT, **_ordered())
    with pytest.raises(ValueError, match='pinned to the ordered four128 scope'):
        grant_identity(small)
    small_config = {'window_side': 32, 'window_count': 1, 'support_policy': PARTIAL_SUPPORT}
    for call in (lambda: profile(CONTAINED, small_config), lambda: policy_for_profile(CONTAINED, small_config),
                 lambda: policy_sha(CONTAINED, small_config)):
        with pytest.raises(ValueError, match='pinned to the ordered four128 scope'):
            call()
    with pytest.raises(ValueError, match='pinned to the ordered four128 scope'):
        profile(CONTAINED, dict(PARTIAL, window_count=2))
    shifted = [list(w) for w in PARTIAL_WINDOWS]
    shifted[0][0] += 1
    with pytest.raises(ValueError, match='window set'):
        grant_identity(_grant(shifted, support_policy=PARTIAL_SUPPORT, **_ordered()))
    with pytest.raises(ValueError, match='window set'):
        grant_identity(_grant(LARGER_WINDOWS, support_policy=PARTIAL_SUPPORT, **_ordered()))
    # A packet window outside the pinned set is refused against a valid grant.
    grant = _grant(PARTIAL_WINDOWS, support_policy=PARTIAL_SUPPORT, **_ordered())
    packet = dict(_partial_packet(grant, [4403, 3872, 128, 128]), support_policy=PARTIAL_SUPPORT)
    with pytest.raises(ValueError, match='window outside'):
        validate_grant_packet(grant, packet)
    # ...and a packet stripped of the ordered contract is refused against it.
    for missing in ('ordered_scope_contract', 'geographic_review', 'output_retention', 'output_root',
                    'larger_runtime_contract'):
        stripped = dict(_partial_packet(grant, PARTIAL_WINDOWS[0]), support_policy=PARTIAL_SUPPORT)
        stripped.pop(missing)
        with pytest.raises(ValueError, match='differs from immutable grant'):
            validate_grant_packet(grant, stripped)


def test_partial_policy_refuses_reuse_and_continuation_contracts():
    for extra in ({'source_reuse_contract': 'coastal-source-reuse-v1'},
                  {'saved_area_continuation_contract': 'coastal-saved-area-continuation-v1'}):
        with pytest.raises(ValueError):
            grant_identity(_grant(PARTIAL_WINDOWS, support_policy=PARTIAL_SUPPORT, **_ordered(**extra)))


def test_support_policy_rejected_outside_contained_profile():
    larger = {'schema': 'coastal-authenticated-policy-v1', 'source': _source(), 'source_root': '/tmp/s',
              'source_relative_path': 'x.bag', 'execution_profile': LARGER, 'window_set': LARGER_WINDOWS,
              'support_policy': PARTIAL_SUPPORT}
    with pytest.raises(ValueError, match='support policy'):
        grant_identity(larger)


# ------------------------------------------------------------ scope

def test_partial_window_set_is_pinned_separately():
    assert scope_windows(_grant(LARGER_WINDOWS)) == (LARGER_WINDOWS, LARGER_BOUNDS)
    assert scope_windows(_grant(PARTIAL_WINDOWS, support_policy=PARTIAL_SUPPORT)) == (PARTIAL_WINDOWS, PARTIAL_BOUNDS)
    assert PARTIAL_WINDOWS == sorted(PARTIAL_WINDOWS, key=lambda w: (-w[1], w[0]))
    assert all(w[2:] == [SIDE, SIDE] for w in PARTIAL_WINDOWS)
    assert not set(map(tuple, PARTIAL_WINDOWS)) & set(map(tuple, LARGER_WINDOWS))
    x0, _, _, top = LARGER_AFFINE[2], None, None, LARGER_AFFINE[5]
    cols = [w[0] for w in PARTIAL_WINDOWS]
    rows = [w[1] for w in PARTIAL_WINDOWS]
    assert PARTIAL_BOUNDS == [x0 + 2 * min(cols), top - 2 * (max(rows) + SIDE),
                              x0 + 2 * (max(cols) + SIDE), top - 2 * min(rows)]
    # grant_identity accepts the non-contiguous contained set (non-overlapping).
    assert grant_identity(_grant(PARTIAL_WINDOWS, support_policy=PARTIAL_SUPPORT, **_ordered()))['window_set'] == PARTIAL_WINDOWS


def _write_metadata(root, name, document, contract):
    path = root / 'metadata' / name
    write(path, document)
    return ref(root, path, contract)


def _review(windows, bounds, **extra):
    review = {
        'schema': SCOPE_REVIEW, 'status': 'accepted_scope_only', 'independent': True,
        'reviewer_id': 'independent-synthetic-scope-reviewer', 'holds': [], 'source': _source(),
        'ordered_scope_contract': LARGER_SCOPE, 'execution_profile': CONTAINED, 'window_side': SIDE,
        'window_count': 4, 'window_set': windows, 'grid_shape': [10495, 10034], 'global_affine': LARGER_AFFINE,
        'native_crs': 'EPSG:26910', 'native_bounds': bounds, 'scope_basis': 'new_native_grid_target',
        'historical_support_qualified': False, 'native_quality_accepted': False, 'publication_prohibited': True,
        'habitat': 'unassessed', 'segment_contained': True, 'product_region_contained': True,
        'safety_bbox_native': [bounds[0] - 100, bounds[1] - 100, bounds[2] + 100, bounds[3] + 100],
        'segment': {'schema': 'coastal-segment-v1', 'segment_id': 'synthetic-scope-segment'},
        'product_region': 'point-arguello-conception', 'checked_at': 50.0, 'valid_until': 5000.0}
    review.update(extra)
    return review


def _scoped_grant(tmp_path, windows, review, **extra):
    grant = _grant(windows, ordered_scope_contract=LARGER_SCOPE,
                   output_retention=declaration(0, 32 * 1024 * 1024, profile=COMPACT_V2_PROFILE),
                   output_root='/tmp/skippercast-output', larger_runtime_contract=LARGER_RUNTIME,
                   code_sha=CODE_SHA, deps_sha=DEPS_SHA, **extra)
    grant['geographic_review'] = _write_metadata(tmp_path, 'scope-review.json', review, SCOPE_REVIEW)
    return grant


def test_partial_scope_review_accepts_only_the_partial_set(tmp_path):
    review = _review(PARTIAL_WINDOWS, PARTIAL_BOUNDS, support_policy=PARTIAL_SUPPORT)
    grant = _scoped_grant(tmp_path, PARTIAL_WINDOWS, review, support_policy=PARTIAL_SUPPORT)
    assert validate_scope_review(tmp_path, grant, now=100.0, horizon=200.0)['window_set'] == PARTIAL_WINDOWS
    assert _grant_context(grant, CODE_SHA, DEPS_SHA)['side'] == SIDE


@pytest.mark.parametrize('case', ['strict_set_partial_grant', 'partial_set_strict_grant',
                                  'review_without_policy', 'strict_review_bounds'])
def test_partial_scope_mismatches_are_refused(tmp_path, case):
    if case == 'strict_set_partial_grant':
        review = _review(LARGER_WINDOWS, LARGER_BOUNDS, support_policy=PARTIAL_SUPPORT)
        grant = _scoped_grant(tmp_path, LARGER_WINDOWS, review, support_policy=PARTIAL_SUPPORT)
    elif case == 'partial_set_strict_grant':
        review = _review(PARTIAL_WINDOWS, PARTIAL_BOUNDS)
        grant = _scoped_grant(tmp_path, PARTIAL_WINDOWS, review)
    elif case == 'review_without_policy':
        review = _review(PARTIAL_WINDOWS, PARTIAL_BOUNDS)
        grant = _scoped_grant(tmp_path, PARTIAL_WINDOWS, review, support_policy=PARTIAL_SUPPORT)
    else:
        review = _review(PARTIAL_WINDOWS, LARGER_BOUNDS, support_policy=PARTIAL_SUPPORT)
        grant = _scoped_grant(tmp_path, PARTIAL_WINDOWS, review, support_policy=PARTIAL_SUPPORT)
    with pytest.raises(ValueError):
        validate_scope_review(tmp_path, grant, now=100.0, horizon=200.0)
    if case in ('strict_set_partial_grant', 'partial_set_strict_grant'):
        with pytest.raises(ValueError, match='ordered four128'):
            _grant_context(grant, CODE_SHA, DEPS_SHA)


def test_partial_support_is_refused_for_legacy_sides():
    windows = [[0, 64, 32, 32], [32, 64, 32, 32], [0, 32, 32, 32], [32, 32, 32, 32]]
    grant = _grant(windows, window_side=32, support_policy=PARTIAL_SUPPORT)
    with pytest.raises(ValueError, match='pinned to the ordered four128 scope'):
        validate_scope_review('/nonexistent', grant, now=100.0, horizon=200.0)
