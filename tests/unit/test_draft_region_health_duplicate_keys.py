"""Receipt parsing must refuse ambiguous evidence before evaluating health."""
import subprocess
import sys

import pytest

from tests._support import ROOT
from tests.unit.test_draft_region_health_report import REGION, write


# A last-value-wins loader sees only healthy data. The array case also catches
# validators that check duplicates only on objects in the known receipt schema.
@pytest.mark.parametrize('name,member,replacement', [
    ('regulations-health.json', '"review_required": []',
     '"review_required": ["fixture-review"], "review_required": []'),
    ('latest.json', '"status": "ok"', '"status": "failed", "status": "ok"'),
    ('latest.json', '"status": "ok"',
     '"status": "ok", "notes": [{"fixture-key": "first", "fixture-key": "second"}]'),
], ids=['legal-review', 'source-status', 'object-in-array'])
def test_duplicate_keys_refused_without_echoing_receipt_content(tmp_path, name, member, replacement):
    write(tmp_path, {'harbor': 'ok'})
    rehearsal = tmp_path / 'rehearsal'
    receipt = rehearsal / REGION / 'regions' / REGION / name
    receipt.write_text(receipt.read_text().replace(member, replacement, 1))
    summary = tmp_path / 'summary.md'

    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/draft_region_health_report.py'),
         '--region', REGION, '--root', str(rehearsal), '--summary', str(summary)],
        text=True, capture_output=True, timeout=10,
    )

    message = f'Draft evidence unreadable: {name}: unreadable JSON\n'
    assert result.returncode == 1
    assert result.stdout == ''
    assert result.stderr == message
    assert summary.read_text() == f'## {REGION} draft rehearsal\n{message}'
