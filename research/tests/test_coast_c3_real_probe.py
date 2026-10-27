"""C3 adapts metadata without silently promoting rights or another C1 run."""
from copy import deepcopy
import pytest
from research.scripts.coast_mvp.probe_c3_real import c1_sources, verify_c2_binding
from research.tests.test_coast_c1_preview_rights import manifest_fixture


def test_native_c1_to_c3_preserves_rights_and_datum_holds():
    manifest = manifest_fixture()
    manifest['sources'][0]['resolution_m'] = 10
    before = deepcopy(manifest)
    rows = c1_sources(manifest)
    assert manifest == before
    assert len(rows) == 1
    assert rows[0]['permissionRequired'] is True
    assert rows[0]['license'] == before['sources'][0]['rights']
    assert rows[0]['datum'] == 'unstated; Zero offset is not a datum conversion'
    assert rows[0]['url'] == before['sources'][0]['citation']
    assert '/private/' not in str(rows)


def test_c2_binding_requires_the_actual_c1_hashes_and_completed_receipt():
    c1 = {'outputs': {'elevation': {'sha256': 'a' * 64}, 'contributor': {'sha256': 'b' * 64}}}
    receipt = {'status': 'machine_success_review_required', 'returncode': 0,
               'input_sha256': {'manifest.json': 'c' * 64, 'elevation.tif': 'a' * 64, 'contributor.tif': 'b' * 64}}
    verify_c2_binding(c1, 'c' * 64, receipt)
    for key in receipt['input_sha256']:
        bad = deepcopy(receipt)
        bad['input_sha256'][key] = 'd' * 64
        with pytest.raises(ValueError, match='bind'):
            verify_c2_binding(c1, 'c' * 64, bad)
    for field, value in [('status', 'running'), ('returncode', 1)]:
        bad = deepcopy(receipt)
        bad[field] = value
        with pytest.raises(ValueError, match='completed'):
            verify_c2_binding(c1, 'c' * 64, bad)
