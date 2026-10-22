"""Exercise candidate role documents through BUILT packets, without source data.

No validator is mocked: both modes traverse scope, validate_input, and the finite
batch contract. Fixtures describe synthetic source bytes which never exist.
"""
import ast
from contextlib import contextmanager
import copy
import inspect
import os
from pathlib import Path
import sys
from unittest import mock

import pytest

from skippercast.coastal.authenticated_v1.profiles import CONTAINED, PARTIAL_SUPPORT
from skippercast.coastal.coordinator import authenticated, packet_release
from skippercast.coastal.coordinator.loop import implementation_hashes
from skippercast.coastal.coordinator.ordered_trial import (
    LARGER_SCOPE, LARGER_WINDOWS, LARGER_BOUNDS, PARTIAL_WINDOWS, PARTIAL_BOUNDS,
)
from skippercast.coastal.handoff.common import ref, write
from tests.unit.test_coastal_partial_support import _review, _scoped_grant

NOW = 100.0
HORIZON = 3700.0
RIGHTS_KEYS = {
    'independent', 'reviewer_id', 'private_use', 'decision',
    'accepted_source_rights_for_declared_private_purpose', 'holds_added',
    'source_sha256', 'source_bytes', 'source_id', 'source_url', 'product_title',
    'synthetic',
}


@contextmanager
def read_only_metadata():
    """Audit only the dry call; deactivate the hook when leaving this context."""
    active = True
    violations = []

    def guard(event, args):
        if not active:
            return
        denied = event in ('subprocess.Popen', 'os.system', 'socket.connect', 'socket.connect_ex')
        if event == 'open':
            filename, mode, flags = args
            name = os.fsdecode(filename) if isinstance(filename, (str, bytes, os.PathLike)) else ''
            denied = (name.lower().endswith('.bag') or '/seafloor/cache/' in name.lower()
                      or isinstance(mode, str) and any(c in mode for c in 'wax+')
                      or isinstance(flags, int) and bool(flags & (
                          os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        if event in ('os.remove', 'os.rename', 'os.mkdir', 'os.rmdir', 'os.link', 'os.symlink'):
            denied = True
        if denied:
            violations.append(event)
            raise AssertionError('dry metadata validation attempted forbidden I/O: ' + event)

    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.addaudithook(guard)
    try:
        yield
    finally:
        active = False
        sys.dont_write_bytecode = old
    assert violations == []


def candidate_documents(root, partial):
    windows, bounds = (PARTIAL_WINDOWS, PARTIAL_BOUNDS) if partial else (LARGER_WINDOWS, LARGER_BOUNDS)
    policy = {'support_policy': PARTIAL_SUPPORT} if partial else {}
    scope = _review(copy.deepcopy(windows), bounds, **policy)
    scope['segment'].update(synthetic=True, crs='EPSG:26910',
                            bbox=scope['safety_bbox_native'], region='point-arguello-conception')
    grant = _scoped_grant(root, copy.deepcopy(windows), scope, **policy)
    code, deps = implementation_hashes(root)
    grant.update(execution_authorized=False, code_sha=code, deps_sha=deps,
                 source_root=str(root / 'never-created-source'), output_root=str(root / 'never-created-mission'))
    row = dict(id='TEST_ONLY_SYNTHETIC_SOURCE', title='TEST_ONLY_SYNTHETIC.bag',
               url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/TEST/BAG/TEST_ONLY_SYNTHETIC.bag',
               kind='bathymetry', format='bag', sha256=grant['source']['sha256'])
    rights = dict(schema='coastal-rights-evidence-v1', independent=True,
                  reviewer_id='independent-synthetic-rights-reviewer', private_use=True,
                  decision='accepted_private_processing_conditional_on_exact_expected_source_identity',
                  accepted_source_rights_for_declared_private_purpose=True, holds_added=[],
                  source_sha256=grant['source']['sha256'], source_bytes=grant['source']['bytes'],
                  source_id=row['id'], source_url=row['url'], product_title=row['title'], synthetic=True,
                  checked_at=50.0, valid_until=5000.0, **policy)
    required = 'all_mask_valid' if partial else 16384
    trial = dict(schema='coastal-bounded-patch-quality-policy-v3', independent=True,
                 execution_profile=CONTAINED, source=grant['source'], window_side=128, window_count=4,
                 window_shape=[128, 128], halo=0, total_pairs=16384,
                 required_nominally_eligible_pairs=required, legacy_25ft_minimum_applied=False,
                 nominal_depth=dict(minimum_m=0, maximum_m=91.44, minimum_inclusive=True, maximum_inclusive=True),
                 product_uncertainty=dict(units='m', type='productUncert', required_quality_pairs=required,
                                          minimum_m=0, minimum_inclusive=False, maximum_m=1, maximum_inclusive=True),
                 **policy)
    if partial:
        trial.update(minimum_supported_pairs=8192, minimum_unsupported_pairs=1,
                     unsupported_cells='mask_invalid_only_as_nodata')
    science = dict(schema='coastal-ordered-independent-scientific-preflight-v1', independent=True,
                   status='PASS_EXPECTED_SOURCE_METADATA_GEOMETRY_' + ('PARTIAL' if partial else 'STRICT') + '_POLICY',
                   source=grant['source'], native_window_set=windows, window_side=128, window_count=4,
                   scientific_acceptance=False, current_source_identity_verified=False, holds_added=[],
                   checked_at=50.0, valid_until=5000.0, **policy)
    templates = []
    for c, r, w, h in windows:
        spec = dict(schema='coastal-contained-native-window-spec-v3', execution_profile=CONTAINED,
                    window_side=128, window_count=4, window_shape=[128, 128], halo=0, minimum_margin_m=0.1,
                    source_sha256=grant['source']['sha256'], native_window=[c, r, w, h],
                    center_native=[721091 + 2 * (c + w / 2), 3826155 - 2 * (r + h / 2)],
                    safety_bbox_native=scope['safety_bbox_native'], segment=scope['segment'],
                    ordered_scope_contract=LARGER_SCOPE, scope_basis='new_native_grid_target',
                    historical_support_qualified=False,
                    native_interest=dict(crs='EPSG:26910', bbox=scope['safety_bbox_native']), **policy)
        templates.append(dict(schema=authenticated.INPUT_CONTRACT, stage='acquire',
                              execution_contract=authenticated.EXECUTION_CONTRACT, synthetic=True,
                              segment_id=scope['segment']['segment_id'], source_row=row,
                              metadata_sha256='e' * 64, fixed_center_plan=spec))
    return grant, templates, dict(rights=rights, trial=trial, segment=scope['segment'], science=science)


def build_candidates(root, grant, templates, documents, mode):
    def put(name, doc):
        path = root / 'metadata' / (name + '.json')
        write(path, doc)
        return ref(root, path, doc['schema'])

    roles = {name: put(name, doc) for name, doc in documents.items()}
    packets = [packet_release.canonical_packet(
        template, grant, rights=[roles['rights']], trial=roles['trial'], segment=roles['segment'],
        code_sha=grant['code_sha'], deps_sha=grant['deps_sha']) for template in templates]
    # Exactly prepare's prospective-release transition: same content, authority
    # flags true in copies only. No issuance, runtime, Budget or Store is created.
    released = mode == 'released'
    actual_grant = dict(grant, execution_authorized=released)
    requests = [put(f'candidate-{i}', dict(packet, execution_authorized=released))
                for i, packet in enumerate(packets)]
    return put('grant', actual_grant), requests


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('mode', ['held', 'released'])
def test_candidate_documents_full_metadata_path(tmp_path, partial, mode):
    # The historical runtime module installs its operator paths on import; do
    # not let those paths contaminate this fixture's dependency identities.
    with mock.patch.object(sys, 'path', list(sys.path)):
        from research.scripts import coastal_four128_runtime as runtime
    grant, templates, documents = candidate_documents(tmp_path, partial)
    grant_ref, requests = build_candidates(tmp_path, grant, templates, documents, mode)
    with read_only_metadata():
        runtime.validate_science(documents['science'], grant, now=NOW, horizon=HORIZON)
        result = packet_release.validate_acquisition_package(
            tmp_path, grant_ref, requests, now=NOW, horizon=HORIZON, validation_mode=mode)
    assert result['status'] == 'PASS_METADATA_ONLY', result
    assert [row['status'] for row in result['packets']] == ['PASS_METADATA_ONLY'] * 4
    assert result['validation_mode'] == mode
    assert result['validated_execution_state'] is (mode == 'released')
    assert result['larger_execution_ready'] is True
    for key in ('execution_authorized', 'native_operations', 'source_bytes_reserved',
                'Store_created', 'Budget_created', 'unit_clock_created'):
        assert not result[key]
    assert not Path(grant['source_root']).exists()
    assert not Path(grant['output_root']).exists()


def test_rights_fixture_covers_all_validate_input_reads(tmp_path):
    _, _, documents = candidate_documents(tmp_path, partial=True)
    # Track the implementation's reads too, so a newly required key cannot be
    # silently omitted from the maintained explicit fixture contract.
    tree = ast.parse(inspect.getsource(authenticated.validate_input))
    reads = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'evidence'
                and node.func.attr == 'get'):
            reads.add(ast.literal_eval(node.args[0]))
        elif (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
              and node.value.id == 'evidence'):
            reads.add(ast.literal_eval(node.slice))
    assert RIGHTS_KEYS <= reads
    assert reads <= documents['rights'].keys()


@pytest.mark.parametrize('mode', ['held', 'released'])
def test_missing_product_title_is_exact_rights_hold(tmp_path, mode):
    grant, templates, documents = candidate_documents(tmp_path, partial=True)
    del documents['rights']['product_title']
    grant_ref, requests = build_candidates(tmp_path, grant, templates, documents, mode)
    with read_only_metadata():
        result = packet_release.validate_acquisition_package(
            tmp_path, grant_ref, requests, now=NOW, horizon=HORIZON, validation_mode=mode)
    assert result['status'] == 'HOLD'
    assert [row['status'] for row in result['packets']] == ['HOLD'] * 4
    assert [row['reason'] for row in result['packets']] == [
        'independent source-specific rights binding invalid'] * 4
