"""Exercise fallback and fine eligibility through local JSON and real GeoTIFFs."""
import json

import numpy as np
import pytest

from scripts.relief.fine_fallback_check import main
from skippercast.relief import fine_proof

PARENT = [15, 2, 3]
OTHER_COARSE = [14, 8, 6]
CERTIFIED = [16, 4, 7]
UNCERTIFIED = [16, 5, 7]
NO_PROOF = [17, 5, 7]


@pytest.fixture
def check(tmp_path, capsys):
    size = fine_proof.TILE
    # z16/x4 is emitted in each candidate; x5 has exactly one unproven
    # sample; x6 is certified but never emitted. x4 and x5 share PARENT.
    bands = [np.full((size, 3 * size), value) for value in (3., -10., 0.5)]
    for band in bands:
        band[-1, 2 * size - 1] = fine_proof.NODATA
    proof = tmp_path / 'proof.tif'
    fine_proof.write(proof, 16, 4, 7, 6, 7, *bands)
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps([PARENT, OTHER_COARSE, PARENT]), encoding='utf-8')
    candidate = tmp_path / 'candidate.json'

    def run(tiles):
        candidate.write_text(json.dumps(tiles), encoding='utf-8')
        status = main([str(baseline), str(candidate), str(proof)])
        return status, json.loads(capsys.readouterr().out)

    return run


def test_withheld_fine_with_retained_parent_passes(check):
    # Requiring all proof-capable tiles to be emitted, or auditing withheld
    # pixels as though they were emitted, would reject this intact fallback.
    status, report = check([PARENT, OTHER_COARSE, CERTIFIED])
    assert (status, report) == (0, {
        'passed': True, 'lost_fallback': [], 'certified': [CERTIFIED],
        'missing_proof': [], 'uncertified': [],
    })


def test_withheld_fine_with_lost_baseline_parent_fails(check):
    # A fine-only check, a coarse count check, or treating a certified child
    # as its parent's replacement would miss these exact baseline losses.
    status, report = check([[15, 3, 2], [14, 8, 7], CERTIFIED])
    assert (status, report) == (1, {
        'passed': False, 'lost_fallback': [OTHER_COARSE, PARENT],
        'certified': [CERTIFIED], 'missing_proof': [], 'uncertified': [],
    })


def test_wrongly_emitted_fine_with_intact_parent_fails(check):
    # A fallback-only check or an any-proven-pixel rule would accept x5.
    status, report = check([PARENT, OTHER_COARSE, CERTIFIED, UNCERTIFIED])
    assert (status, report) == (1, {
        'passed': False, 'lost_fallback': [], 'certified': [CERTIFIED],
        'missing_proof': [], 'uncertified': [UNCERTIFIED],
    })


def test_missing_zoom_proof_is_distinct_from_uncertified(check):
    # An operator needs to distinguish absent evidence from a failed sample;
    # flattening the fine audit to a single rejection bucket loses that.
    status, report = check([PARENT, OTHER_COARSE, CERTIFIED, UNCERTIFIED, NO_PROOF])
    assert (status, report) == (1, {
        'passed': False, 'lost_fallback': [], 'certified': [CERTIFIED],
        'missing_proof': [NO_PROOF], 'uncertified': [UNCERTIFIED],
    })
