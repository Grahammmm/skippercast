"""Audit repro: terrain-pending coverage is republished without implementation identity.

publish.region_layers() reuses var/seafloor/reaches/<id>/coverage-cells.json for a
'terrain-pending' reach after checking only catalog, habitat-rules and reference
hashes. The checkpoint records `physical_input_hash` (which covers coverage.py,
run.py, requirements and source rows) but publication never recomputes or compares
it, so cells classified by an older/buggy coverage implementation are published
indefinitely without the rerun that the habitat branch forces.
"""
import hashlib
import json

import pytest

from skippercast.seafloor import publish


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pending_coverage_with_stale_physical_identity_is_refused(tmp_path):
    root = tmp_path
    for folder in ('dist/data', 'catalog', 'var/seafloor/reference', 'var/seafloor/reaches/cc-r01'):
        (root / folder).mkdir(parents=True)
    (root / 'catalog/surveys.json').write_text(json.dumps({'surveys': []}))
    (root / 'catalog/habitat-rules.json').write_text(json.dumps({'rule_version': 'x'}))
    reference = root / 'var/seafloor/reference/cells.json'
    reference.write_text(json.dumps({'cells': []}))
    (root / 'dist/data/seafloor-ledger.json').write_text(json.dumps({
        'reference_cells_sha256': _sha(reference), 'reference': {},
        'reaches': [{'id': 'cc-r01', 'region': 'cc', 'status': 'terrain-pending'}]}))
    folder = root / 'var/seafloor/reaches/cc-r01'
    (folder / 'coverage-cells.json').write_text(json.dumps({'reach': 'cc-r01', 'cells': []}))
    (folder / 'coverage-checkpoint.json').write_text(json.dumps({
        # Produced by a different (older) coverage implementation / source set.
        'physical_input_hash': '0' * 64,
        'ledger_summary': {'coverage_rule_version': 'obsolete-coverage-rule'},
        'catalog_sha256': _sha(root / 'catalog/surveys.json'),
        'rules_sha256': _sha(root / 'catalog/habitat-rules.json'),
        'reference_sha256': _sha(reference),
        'cells_sha256': _sha(folder / 'coverage-cells.json'),
        'source_hashes': []}))
    # Correct behaviour: a checkpoint whose physical/implementation identity is not
    # the current one must force a rerun, like the habitat branch does.
    with pytest.raises(ValueError):
        publish.region_layers(root, 'cc', rerun=False)


import os as _audit_os  # noqa: E402

import pytest as _audit_pytest  # noqa: E402

pytestmark = _audit_pytest.mark.skipif(
    _audit_os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1",
    reason="audit repro (fails on purpose): set SKIPPERCAST_AUDIT_CLOUD=1",
)
