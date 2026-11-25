"""Exercise the crop CLI with synthetic fine_proof_report.py --json output."""
import json
import subprocess
import sys

import pytest

from tests._support import ROOT

SCRIPT = ROOT / 'scripts' / 'relief' / 'fine_proof_crop_scope.py'
TOTALS = {'certified': 4, 'uncertified': 1, 'unproven': 1}
PROOF = {'x0': 9, 'y0': 24, 'x1': 11, 'y1': 25}


@pytest.fixture
def report(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text(json.dumps([{
        'zoom': 16, 'raster_sha256': '0' * 64, 'tile_range': PROOF, **TOTALS,
        'certified_tiles': ['16/9/25', '16/10/24', '16/10/25', '16/11/24'],
    }]), encoding='utf-8')
    return path


@pytest.mark.parametrize('crop, relation, overlap, geometry_count, certified', [
    # Catches testing containment in the wrong direction or counting the wider crop.
    pytest.param((8, 23, 11, 26), 'contains_proof', PROOF, 6, 4, id='entire-proof-contained'),
    # Shared Y range but adjacent X tiles: touching physical edges do not share XYZ IDs.
    pytest.param((12, 24, 13, 25), 'disjoint', None, 0, 0, id='disjoint-adjacent-crop'),
    # One column overlaps: neither scaling four certified tiles nor reading the IDs
    # belongs in a totals-only report. A single-column intersection is not empty.
    pytest.param((11, 23, 12, 25), 'partial_overlap',
                 {'x0': 11, 'y0': 24, 'x1': 11, 'y1': 25}, 2, None, id='partial-count-withheld'),
])
def test_scope(report, crop, relation, overlap, geometry_count, certified):
    result = subprocess.run(
        [sys.executable, SCRIPT, report, '--crop', '16', *map(str, crop)],
        cwd=report.parent, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    scope = json.loads(result.stdout)
    assert scope['relation'] == relation
    assert scope['intersection_tile_range'] == overlap
    assert scope['intersection_tile_count'] == geometry_count
    assert scope['whole_proof_totals'] == TOTALS
    assert scope['crop_certified_by_this_proof'] == certified


def test_missing_crop_zoom_is_not_disjoint(report):
    # Identical indices at another zoom are not proof for the requested tile grid.
    result = subprocess.run(
        [sys.executable, SCRIPT, report, '--crop', '17', '9', '24', '11', '25'],
        cwd=report.parent, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert not result.stdout
    assert 'expected exactly one proof summary at z17' in result.stderr
