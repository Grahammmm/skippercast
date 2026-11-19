"""F21-08: the scheduled report must not count retained or foreign evidence."""
import json

import pytest

from tests.unit.test_report_regulations import health, make_root, section
from tests.unit.test_report_regulations_decode import run_cli


@pytest.mark.parametrize(('status', 'receipt_region', 'exit_code', 'message'), [
    ('failed', 'a', 0, 'Any retained receipt was not checked.'),
    ('failed', 'b', 0, 'Any retained receipt was not checked.'),
    ('ok', 'b', 1, 'region_id does not match the index'),
    ('ok', None, 1, 'region_id does not match the index'),
    ('ok', 'a', 0, 'Required sources: 1/1 match'),
], ids=['failed-matching', 'failed-retained-foreign', 'current-foreign',
        'current-missing-id', 'current-matching'])
def test_scheduled_report_qualifies_only_current_receipts_for_the_region(
        tmp_path, status, receipt_region, exit_code, message):
    receipt = health(review_required=[], areas={}, checks={'s1': {'status': 'match', 'source_status': 'ok'}})
    if receipt_region is not None:
        receipt['region_id'] = receipt_region
    root = make_root(tmp_path, {'a': json.dumps(receipt)}, index=[{'region_id': 'a', 'status': status}])
    summary = tmp_path / 'summary.md'
    result = run_cli(root, summary)

    # A healthy-looking receipt alone used to yield a clean report in every case.
    clean = status == 'ok' and receipt_region == 'a'
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert ('::warning::' in result.stdout) == (not clean)
    assert ('::error::Regulation health unreadable for: a' in result.stdout) == bool(exit_code)
    region = section(summary.read_text(), 'a')
    assert message in region
    assert ('Required sources:' in region) == clean
