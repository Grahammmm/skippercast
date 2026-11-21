"""Region status must report malformed upstream names without losing healthy stages."""
import json
import subprocess
import sys

import pytest

from skippercast.relief import receipts
from tests._support import ROOT


@pytest.mark.parametrize(('bad_ref', 'reason'), [
    ({'stage': 'mosaic.public'}, 'invalid stage name'),
    ({'stage': 'mosaic', 'scope': 'Public'}, 'invalid scope'),
])
def test_status_reports_invalid_upstream_name(tmp_path, bad_ref, reason):
    region = receipts.Region(tmp_path, 'tiny')
    base = {
        'schema': receipts.SCHEMA, 'region': region.id, 'status': 'ok',
        'generation': 'a' * 64, 'attempt': 1, 'outputs': [],
    }
    receipts.write_json_atomic(region.receipt_path('mosaic', 'public'), {
        **base, 'stage': 'mosaic', 'scope': 'public', 'upstream': [],
    })
    # Both refs pass a type-only check, but cannot name a receipt file.
    receipts.write_json_atomic(region.receipt_path('tiles'), {
        **base, 'stage': 'tiles', 'scope': None, 'generation': 'b' * 64,
        'upstream': [{**bad_ref, 'generation': base['generation']}],
    })

    result = subprocess.run([
        sys.executable, str(ROOT / 'scripts' / 'relief' / 'region.py'),
        'status', '--region', region.id, '--out', str(tmp_path), '--json',
    ], check=True, capture_output=True, text=True, timeout=10)
    rows = {row['key']: row for row in json.loads(result.stdout)['stages']}
    assert rows['tiles']['state'] == 'invalid'
    assert reason in rows['tiles']['reason']
    assert rows['mosaic.public']['state'] == 'done'
