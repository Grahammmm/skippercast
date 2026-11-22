"""Check the inert Central Coast roster against the coverage and packet readers."""
import json
import subprocess
import sys

import pytest

from scripts.relief import coast_coverage
from skippercast.relief import receipts
from tests._support import ROOT


ROSTER = ROOT / 'docs/operations/fixtures/relief-central-r8-batches.json'
EXPECTED = {
    'central-r8-1': {'big-sur-coast', 'cambria-san-simeon', 'south-big-sur-san-simeon'},
    'central-r8-2': {'monterey-point-sur', 'point-arguello-conception', 'santa-cruz-monterey-bay'},
}
PACKET = 'scripts/relief/r8_packet.py'


@pytest.fixture
def batches():
    return json.loads(ROSTER.read_text(encoding='utf-8'))['batches']


def test_batches_partition_the_exact_six_coverage_members(batches):
    """Catch a duplicate, wrong-batch swap, or roster member dropped from the release index."""
    assert len(batches) == 2
    assert {row['id'] for row in batches} == EXPECTED.keys()
    members = [region for row in batches for region in row['regions']]
    assert len(members) == len(set(members)) == 6
    assert set(members) <= coast_coverage.load_regions(ROOT)['release'].keys()
    for row in batches:
        assert set(row['regions']) == EXPECTED[row['id']]


def test_evidence_slots_are_separate_and_unfilled(batches):
    """Catch a missing or duplicated slot, or example evidence turning into a receipt."""
    for row in batches:
        slots = row['evidence_slots']
        assert len(slots) == len(row['regions'])
        assert {slot['region'] for slot in slots} == set(row['regions'])
        assert all(slot == {'region': slot['region'], 'evidence': None} for slot in slots)


@pytest.fixture(params=EXPECTED, ids=str)
def batch(request, batches):
    return next(row for row in batches if row['id'] == request.param)


@pytest.fixture
def packet_argv(batch, tmp_path):
    template = batch['packet_argv']
    # Only fill OUT; validate the exact template before executing any of it.
    assert template == ['python', PACKET, '--out', None, *batch['regions']]
    return [sys.executable, str(ROOT / template[1]), template[2], str(tmp_path / 'out'), *template[4:]]


def test_packet_reports_every_member_and_none_ready(batch, packet_argv, tmp_path):
    """Catch truncated batch output or a member shown as ready with no envelope."""
    expected = []
    for i, member in enumerate(batch['regions'], start=1):
        generation = f'{i:064x}'
        path = receipts.Region(tmp_path / 'out', member).receipt_path('package')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            'schema': receipts.SCHEMA, 'region': member, 'stage': 'package', 'scope': None,
            'status': 'ok', 'generation': generation, 'outputs': [], 'upstream': [], 'attempt': 1,
        }), encoding='utf-8')
        # Only the current-package selector exists; no envelope or approval is written.
        expected.append(f"NOT READY {member}: artifact is missing or not a file: "
                        f"'review/{generation}/envelope.json'")

    result = subprocess.run(packet_argv, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert (result.returncode, result.stdout.splitlines(), result.stderr) == (1, expected, '')


def test_packet_refuses_a_fourth_member(packet_argv, tmp_path):
    """Catch a fourth member being processed or silently truncated to a three-member batch."""
    result = subprocess.run([*packet_argv, 'fixture-fourth'], cwd=tmp_path,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert result.stdout == ''
    assert 'expected at most 3 regions' in result.stderr
    assert not (tmp_path / 'out').exists()
