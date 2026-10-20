"""Full-path contract for candidate coastal-rights-evidence documents (SC-5b).

The first SC-5b issuance failed at dispatch because the Sol-authored rights
document omitted ``product_title``; nothing executed
``authenticated.validate_input`` against a BUILT packet before issuance. This
module builds the four held packets from a synthetic candidate rights document
and grant/templates via ``packet_release.canonical_packet`` and runs
``validate_acquisition_package`` in both held and released mode, so the exact
predicates the dispatcher runs are exercised on a scratch root with no real
project data. It is the committed form of the dry full-path regression.
"""
import json

import pytest

from skippercast.coastal.authenticated_v1.profiles import CONTAINED
from skippercast.coastal.coordinator.authenticated import EXECUTION_CONTRACT, INPUT_CONTRACT
from skippercast.coastal.coordinator.loop import implementation_hashes
from skippercast.coastal.coordinator.ordered_trial import (
    LARGER_AFFINE,
    LARGER_BOUNDS,
    LARGER_RUNTIME,
    LARGER_SCOPE,
    LARGER_WINDOWS,
    SCOPE_REVIEW,
)
from skippercast.coastal.coordinator.packet_release import canonical_packet, validate_acquisition_package
from skippercast.coastal.handoff.common import ref, write
from skippercast.coastal.output_writer import COMPACT_V2_PROFILE, declaration

GRANT_CONTRACT = 'coastal-authenticated-policy-v1'
SOURCE_ROOT = '/tmp/skippercast-source'
SIDE = 128

# The exact keys ``authenticated.validate_input`` reads from a
# ``coastal-rights-evidence-v1`` document in its rights-binding predicate.
RIGHTS_BINDING_KEYS = (
    'independent', 'reviewer_id', 'private_use', 'decision',
    'accepted_source_rights_for_declared_private_purpose', 'holds_added',
    'source_sha256', 'source_bytes', 'source_id', 'source_url',
    'product_title', 'synthetic',
)


def _source():
    return {'path': 'var/coastal/source/H11879.bag', 'sha256': 'a' * 64, 'bytes': 12345}


def _write(root, name, document, contract):
    path = root / 'metadata' / name
    write(path, document)
    return ref(root, path, contract)


def _segment():
    return {'schema': 'coastal-segment-v1', 'segment_id': 'synthetic-scope-segment',
            'crs': 'EPSG:26910', 'bbox': list(LARGER_BOUNDS), 'region': 'synthetic', 'synthetic': True}


def _trial(source):
    return {
        'schema': 'coastal-bounded-patch-quality-policy-v3',
        'execution_profile': CONTAINED,
        'window_side': SIDE,
        'window_count': 4,
        'independent': True,
        'source': {'sha256': source['sha256'], 'bytes': source['bytes']},
        'window_shape': [SIDE, SIDE],
        'halo': 0,
        'total_pairs': SIDE * SIDE,
        'required_nominally_eligible_pairs': SIDE * SIDE,
        'legacy_25ft_minimum_applied': False,
        'nominal_depth': {'minimum_m': 0, 'maximum_m': 91.44,
                          'minimum_inclusive': True, 'maximum_inclusive': True},
        'product_uncertainty': {'units': 'm', 'type': 'productUncert',
                                'required_quality_pairs': SIDE * SIDE,
                                'minimum_m': 0, 'minimum_inclusive': False,
                                'maximum_m': 1, 'maximum_inclusive': True},
    }


def _row(source):
    return {
        'id': 'synthetic-bag',
        'title': 'H11879_MB_2m_MLLW_1of5.bag',
        'kind': 'bathymetry',
        'format': 'bag',
        'url': 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/H11879_MB_2m_MLLW_1of5.bag',
        'sha256': source['sha256'],
    }


def _rights(source, row):
    return {
        'schema': 'coastal-rights-evidence-v1',
        'independent': True,
        'reviewer_id': 'synthetic-rights-reviewer',
        'private_use': True,
        'decision': 'accepted_private_processing_conditional_on_exact_expected_source_identity',
        'accepted_source_rights_for_declared_private_purpose': True,
        'holds_added': [],
        'source_sha256': source['sha256'],
        'source_bytes': source['bytes'],
        'source_id': row['id'],
        'source_url': row['url'],
        'product_title': row['title'],
        'synthetic': True,
        'checked_at': 0.0,
        'valid_until': 7200.0,
    }


def _review(source, segment):
    return {
        'schema': SCOPE_REVIEW,
        'status': 'accepted_scope_only',
        'independent': True,
        'reviewer_id': 'independent-synthetic-scope-reviewer',
        'holds': [],
        'source': source,
        'ordered_scope_contract': LARGER_SCOPE,
        'execution_profile': CONTAINED,
        'window_side': SIDE,
        'window_count': 4,
        'window_set': LARGER_WINDOWS,
        'grid_shape': [10495, 10034],
        'global_affine': LARGER_AFFINE,
        'native_crs': 'EPSG:26910',
        'native_bounds': LARGER_BOUNDS,
        'scope_basis': 'new_native_grid_target',
        'historical_support_qualified': False,
        'native_quality_accepted': False,
        'publication_prohibited': True,
        'habitat': 'unassessed',
        'segment_contained': True,
        'product_region_contained': True,
        'safety_bbox_native': [728000, 3818000, 730000, 3820000],
        'segment': segment,
        'product_region': 'point-arguello-conception',
        'checked_at': 0.0,
        'valid_until': 7200.0,
    }


def _spec(window, source, review, segment):
    col, row, side, _ = window
    center = [721091 + 2 * (col + side / 2), 3826155 - 2 * (row + side / 2)]
    return {
        'schema': 'coastal-contained-native-window-spec-v3',
        'execution_profile': CONTAINED,
        'window_side': SIDE,
        'window_count': 4,
        'source_sha256': source['sha256'],
        'window_shape': [SIDE, SIDE],
        'halo': 0,
        'minimum_margin_m': 0.1,
        'native_window': window,
        'center_native': center,
        'safety_bbox_native': review['safety_bbox_native'],
        'segment': segment,
        'ordered_scope_contract': LARGER_SCOPE,
        'scope_basis': 'new_native_grid_target',
        'historical_support_qualified': False,
        'native_interest': {'crs': 'EPSG:26910', 'bbox': review['safety_bbox_native']},
    }


def _template(source, row, window, review, segment):
    return {
        'schema': INPUT_CONTRACT,
        'execution_contract': EXECUTION_CONTRACT,
        'stage': 'acquire',
        'segment_id': segment['segment_id'],
        'synthetic': True,
        'source_row': row,
        'metadata_sha256': None,
        'fixed_center_plan': _spec(window, source, review, segment),
    }


def _grant(source, root, code_sha, deps_sha, review_ref, execution_authorized=False):
    return {
        'schema': GRANT_CONTRACT,
        'source': source,
        'source_root': SOURCE_ROOT,
        'source_relative_path': 'H11879.bag',
        'execution_profile': CONTAINED,
        'window_side': SIDE,
        'window_count': 4,
        'window_set': LARGER_WINDOWS,
        'code_sha': code_sha,
        'deps_sha': deps_sha,
        'execution_authorized': execution_authorized,
        'ordered_scope_contract': LARGER_SCOPE,
        'geographic_review': review_ref,
        'output_retention': declaration(0, 32 * 1024 * 1024, profile=COMPACT_V2_PROFILE),
        'output_root': str(root),
        'larger_runtime_contract': LARGER_RUNTIME,
    }


def _candidate(tmp_path):
    """Write grant, scope review, trial, segment and four templates to a scratch root."""
    root = tmp_path / 'root'
    root.mkdir()
    source = _source()
    code_sha, deps_sha = implementation_hashes(str(root))
    segment = _segment()
    review = _review(source, segment)
    review_ref = _write(root, 'scope-review.json', review, SCOPE_REVIEW)
    grant = _grant(source, root, code_sha, deps_sha, review_ref)
    grant_ref = _write(root, 'grant.json', grant, GRANT_CONTRACT)
    trial_ref = _write(root, 'trial.json', _trial(source), 'coastal-bounded-patch-quality-policy-v3')
    segment_ref = _write(root, 'segment.json', segment, 'coastal-segment-v1')
    row = _row(source)
    templates = [_template(source, row, window, review, segment) for window in LARGER_WINDOWS]
    return dict(root=root, source=source, code_sha=code_sha, deps_sha=deps_sha, grant=grant,
                grant_ref=grant_ref, trial_ref=trial_ref, segment_ref=segment_ref, row=row,
                templates=templates)


def _build_packets(ctx, rights_ref):
    return [canonical_packet(template, ctx['grant'], rights=[rights_ref], trial=ctx['trial_ref'],
                             segment=ctx['segment_ref'], code_sha=ctx['code_sha'],
                             deps_sha=ctx['deps_sha']) for template in ctx['templates']]


@pytest.mark.gis
def test_candidate_rights_packets_pass_full_validation_held_and_released(tmp_path):
    ctx = _candidate(tmp_path)
    root = ctx['root']
    rights_ref = _write(root, 'rights.json', _rights(ctx['source'], ctx['row']), 'coastal-rights-evidence-v1')
    held_refs = [_write(root, 'packet-%d.json' % i, packet, INPUT_CONTRACT)
                 for i, packet in enumerate(_build_packets(ctx, rights_ref))]
    held = validate_acquisition_package(root, ctx['grant_ref'], held_refs, now=0.0, horizon=3600.0,
                                        validation_mode='held')
    assert held['status'] == 'PASS_METADATA_ONLY'
    assert [entry['status'] for entry in held['packets']] == ['PASS_METADATA_ONLY'] * 4
    assert held['execution_authorized'] is False

    released_grant = dict(ctx['grant'], execution_authorized=True)
    released_grant_ref = _write(root, 'grant-released.json', released_grant, GRANT_CONTRACT)
    released_refs = []
    for i, packet in enumerate(_build_packets(ctx, rights_ref)):
        packet['execution_authorized'] = True
        released_refs.append(_write(root, 'acquire-%d.json' % i, packet, INPUT_CONTRACT))
    released = validate_acquisition_package(root, released_grant_ref, released_refs, now=0.0,
                                            horizon=3600.0, validation_mode='released')
    assert released['status'] == 'PASS_METADATA_ONLY'
    assert [entry['status'] for entry in released['packets']] == ['PASS_METADATA_ONLY'] * 4


@pytest.mark.gis
def test_rights_evidence_key_set_covers_validate_input_and_missing_title_holds(tmp_path):
    ctx = _candidate(tmp_path)
    root = ctx['root']
    rights = _rights(ctx['source'], ctx['row'])
    assert [key for key in RIGHTS_BINDING_KEYS if key not in rights] == []

    # A rights document without product_title must fail exactly the rights
    # binding predicate validate_input enforces immediately before dispatch.
    rights.pop('product_title')
    bad_ref = _write(root, 'rights-missing-title.json', rights, 'coastal-rights-evidence-v1')
    bad_refs = [_write(root, 'packet-%d.json' % i, packet, INPUT_CONTRACT)
                for i, packet in enumerate(_build_packets(ctx, bad_ref))]
    validation = validate_acquisition_package(root, ctx['grant_ref'], bad_refs, now=0.0, horizon=3600.0,
                                              validation_mode='held')
    assert validation['status'] == 'HOLD'
    assert [entry['reason'] for entry in validation['packets']] == \
        ['independent source-specific rights binding invalid'] * 4
