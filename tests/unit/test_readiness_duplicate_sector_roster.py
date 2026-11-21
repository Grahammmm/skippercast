"""The statewide queue must contain exactly one row per roster sector."""
import hashlib
import json

import pytest

from skippercast.platform.readiness import compile_readiness
from tests._support import FIXTURES

DATA = 'dist/data/'
ROSTER = DATA + 'coastal-sectors.json'
OUTPUT = DATA + 'california-atlas-readiness.json'
AUDITS = (
    'noaa-native-sector-review.json',
    'noaa-vr-native-depth-expanded-review.json',
    'noaa-regular-native-depth-review.json',
    'noaa-survey-discovery.json',
    'noaa-seabed-samples-sector-review.json',
)
RECEIPT_LINKS = {
    DATA + 'nbs-hard-footprint-depth-audit.json': {
        'inventory_sha256': DATA + 'nbs-hard-footprint-tile-inventory.json',
    },
    DATA + 'nbs-hard-footprint-original-class-overlap.json': {
        'depth_audit_sha256': DATA + 'nbs-hard-footprint-depth-audit.json',
    },
    DATA + 'usgs-ds781-character-semantics.json': {
        'source_native_audit_sha256': DATA + 'usgs-ds781-native-character-review.json',
        'source_metadata_inventory_sha256': 'catalog/usgs-ds781-metadata-review.json',
    },
}


@pytest.fixture
def readiness_root(tmp_path):
    bundle = FIXTURES / 'sp1701_readiness_spacing/root-inputs.json'
    for relative, packet in json.loads(bundle.read_text()).items():
        for key, source in RECEIPT_LINKS.get(relative, {}).items():
            packet[key] = hashlib.sha256((tmp_path / source).read_bytes()).hexdigest()
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(packet))
    return tmp_path


def test_unique_roster_compiles_one_row_per_sector(readiness_root):
    roster = json.loads((readiness_root / ROSTER).read_text())['sectors']
    compile_readiness(readiness_root)
    report = json.loads((readiness_root / OUTPUT).read_text())
    ids = [row['sector_id'] for row in report['sectors']]
    assert len(ids) == len(set(ids)) == 19
    assert set(ids) == {row['id'] for row in roster}


def test_duplicate_roster_refused_even_when_audits_agree(readiness_root):
    roster_path = readiness_root / ROSTER
    roster = json.loads(roster_path.read_text())
    sectors = roster['sectors']
    omitted = sectors[-1]['id']
    sectors[-1]['id'] = sectors[0]['id']
    roster_path.write_text(json.dumps(roster))
    expected = {row['id'] for row in sectors}
    assert len(sectors) == 19 and len(expected) == 18

    # All five audits still match the reduced set; checking only set equality
    # would accept this roster and emit the repeated sector twice.
    for name in AUDITS:
        path = readiness_root / DATA / name
        audit = json.loads(path.read_text())
        audit['sectors'] = [row for row in audit['sectors'] if row['sector_id'] != omitted]
        assert len(audit['sectors']) == len(expected)
        assert {row['sector_id'] for row in audit['sectors']} == expected
        path.write_text(json.dumps(audit))

    output = readiness_root / OUTPUT
    previous = b'{"previous": true}\n'
    output.write_bytes(previous)
    with pytest.raises(ValueError, match='Duplicate sector IDs in statewide readiness roster'):
        compile_readiness(readiness_root)
    assert output.read_bytes() == previous
