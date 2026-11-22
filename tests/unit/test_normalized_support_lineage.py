import json
import subprocess
import sys

import pytest

from tests._support import ROOT

_SCRIPT = ROOT / 'scripts/relief/normalized_support_lineage.py'
_ORIGINAL = '1' * 64
_DIGEST = '2' * 64
_RAT = '3' * 64
_BLUE = {'id': 'nbs-contributor-bathy-coverage/1', 'digest': _DIGEST}
_BAG = {'id': 'bag-georef-metadata-bathy-coverage/1', 'digest': _DIGEST}


def _report(tmp_path, **params):
    fixture = tmp_path / 'fixture.json'
    fixture.write_text(json.dumps({
        'schema': 'sc-relief-normalized/1', 'original_sha256': _ORIGINAL,
        'normalizer_digest': '4' * 64, 'params': params,
    }), encoding='utf-8')
    # No raster, RAT, GIS stack or cache is required to read this saved claim.
    result = subprocess.run([sys.executable, str(_SCRIPT), str(fixture)],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_bluetopo_reports_saved_adapter_and_rat_pin(tmp_path):
    # A reader must not recompute the current adapter digest, use normalizer_digest,
    # or copy a source mask into the external support-evidence pins.
    rat = {'role': 'support-evidence', 'sha256': _RAT}
    assert _report(tmp_path, family='nbs_bluetopo', adapter=_BLUE, dependencies=[
        {'role': 'source-mask', 'sha256': '5' * 64}, rat,
    ]) == {
        'original_sha256': _ORIGINAL,
        'original_sha256_role': 'source',
        'params': {'adapter': _BLUE, 'dependencies': [rat]},
        'evidence_status': 'external_pin_recorded',
    }


@pytest.mark.parametrize('extra', [
    {}, {'dependencies': []}, {'dependencies': [{'role': 'support-evidence', 'sha256': None}]},
], ids=['omitted-dependencies', 'no-rat', 'rat-without-pin'])
def test_bluetopo_adapter_without_rat_hash_is_not_evidence(tmp_path, extra):
    # An adapter selection or a dependency role alone must not count as a hash pin.
    report = _report(tmp_path, family='bluetopo', adapter=_BLUE, **extra)
    assert report['params'] == {'adapter': _BLUE, 'dependencies': extra.get('dependencies', [])}
    assert report['evidence_status'] == 'missing_or_unrecorded'


def test_bag_original_hash_identifies_only_the_container(tmp_path):
    # A BAG hash is not an external RAT pin or a claim that its metadata exists.
    assert _report(tmp_path, family='NOAA NOS BAG survey', adapter=_BAG, dependencies=[]) == {
        'original_sha256': _ORIGINAL,
        'original_sha256_role': 'bag_container',
        'params': {'adapter': _BAG, 'dependencies': []},
        'evidence_status': 'missing_or_unrecorded',
    }


def test_unsupported_family_reports_explicit_no_adapter(tmp_path):
    # A saved null adapter must not be collapsed into unknown/missing lineage.
    report = _report(tmp_path, family='dem', adapter=None, dependencies=[])
    assert report['params'] == {'adapter': None, 'dependencies': []}
    assert report['evidence_status'] == 'no_adapter'


def test_missing_adapter_field_is_not_inferred_from_family(tmp_path):
    # A historical sidecar need not have used whichever adapter is registered now.
    report = _report(tmp_path, family='bluetopo', dependencies=[])
    assert report['params'] == {'dependencies': []}
    assert report['evidence_status'] == 'missing_or_unrecorded'
