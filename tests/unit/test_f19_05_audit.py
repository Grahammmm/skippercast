from datetime import datetime, timedelta
import json

import pytest

from scripts import audit_noaa_survey_products as products
from scripts.discover_noaa_surveys import scan
from tests._support import NOW


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.mark.parametrize('failed, had_survey', [
    pytest.param(True, True, id='failed-discovery-retains-omitted-survey'),
    pytest.param(False, True, id='healthy-empty-confirms-withdrawal'),
    pytest.param(True, False, id='failed-discovery-cannot-reuse-complete-empty-inventory'),
])
def test_product_inventory_respects_discovery_completeness(tmp_path, monkeypatch, failed, had_survey):
    # Identical empty lead lists must not hide either an outage or a real withdrawal.
    def fetch_discovery(_url):
        if failed:
            raise OSError('synthetic discovery unavailable')
        return b'{"features": []}'

    def unexpected_transport(*args, **kwargs):
        pytest.fail('An empty discovery must not fetch catalog pages')

    discovery = scan([{'id': 'synthetic', 'bounds': [0, 0, 1, 1]}], now=NOW, fetcher=fetch_discovery)
    then = NOW - timedelta(days=1)
    prior_row = products.inspect(
        {'id': 'H00000', 'catalog_url': 'https://www.ngdc.noaa.gov/H00000.html'},
        now=then, fetcher=lambda _url: b'<a href="/H00000/BAG/synthetic.bag">BAG</a>',
    )
    discovery_path, previous_path, output_path = (tmp_path / name for name in ('discovery', 'previous', 'output'))
    discovery_path.write_text(json.dumps(discovery))
    previous_path.write_text(json.dumps({
        'last_complete_scan_at': then.isoformat(),
        'health': {'status': 'ok', 'issues': []},
        'surveys': [prior_row] if had_survey else [],
    }))
    monkeypatch.setattr(products, 'datetime', FixedDatetime)
    monkeypatch.setattr(products, 'urlopen', unexpected_transport)

    assert products.main(['--discovery', str(discovery_path), '--previous', str(previous_path),
                          '--output', str(output_path)]) is None
    result = json.loads(output_path.read_text())
    if failed:
        assert result['health']['status'] == 'degraded'
        assert result['health']['issues']
        assert result['last_complete_scan_at'] == then.isoformat()
    else:
        assert result['health'] == {'status': 'ok', 'issues': []}
        assert result['last_complete_scan_at'] == NOW.isoformat()
    assert result['collected_at'] == NOW.isoformat()
    if failed and had_survey:
        assert result['survey_count'] == result['bag_link_count'] == 1
        row, = result['surveys']
        assert row['issue']
        assert row == {**prior_row, 'status': 'retained', 'issue': row['issue']}
    else:
        assert result['survey_count'] == result['bag_link_count'] == 0
        assert result['surveys'] == []
