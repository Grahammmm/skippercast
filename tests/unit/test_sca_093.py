from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest

from research.scripts import triage_noaa_bag_files as bag


SCAN = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)
URL = 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/SYNTHETIC/BAG/test_MLLW.bag'


@pytest.fixture
def documents():
    return (
        {'scope': 'noaa-bag-survey-discovery', 'sector_count': 2, 'distinct_survey_leads': 1,
         'sectors': [{'sector_id': 'first', 'surveys': [{'id': 'SYNTHETIC'}]},
                     {'sector_id': 'second', 'surveys': []}]},
        {'scope': 'noaa-survey-product-links', 'survey_count': 1, 'bag_link_count': 1, 'report_link_count': 1,
         'surveys': [{'id': 'SYNTHETIC', 'products': {'bag': [URL], 'report': ['synthetic-report']}}]},
    )


def run_cli(tmp_path, monkeypatch, documents, previous, fetcher):
    clock = Mock(wraps=datetime)
    clock.now.return_value = NOW
    monkeypatch.setattr(bag, 'datetime', clock)
    args = []
    for name, value in zip(('discovery', 'products', 'previous'), (*documents, previous)):
        if value is not None:
            path = tmp_path / f'{name}.json'
            path.write_text(json.dumps(value), encoding='utf-8')
            args.extend((f'--{name}', str(path)))
    output = tmp_path / 'output.json'
    bag.main([*args, '--output', str(output)], fetcher=fetcher)
    return json.loads(output.read_text(encoding='utf-8'))


@pytest.mark.parametrize('report_available', [False, True])
def test_warm_scan_rebuilds_membership_and_hints(tmp_path, monkeypatch, documents, report_available):
    discovery, products = documents
    links = products['surveys'][0]['products']
    report = links['report']
    links['report'] = [] if report_available else report
    products['report_link_count'] = int(not report_available)
    previous = bag.inventory(*documents, now=SCAN, fetcher=lambda _: (1234, 'synthetic-last-modified'))
    first, second = discovery['sectors']
    second['surveys'] = first['surveys'].copy()
    first['surveys'].clear()
    second['sector_id'] = 'renamed'
    links['report'] = report if report_available else []
    products['report_link_count'] = int(report_available)
    no_head = Mock(side_effect=AssertionError('unexpected HEAD'))

    result = run_cli(tmp_path, monkeypatch, documents, previous, no_head)

    no_head.assert_not_called()
    assert result['collected_at'] == NOW.isoformat()
    assert result['last_complete_scan_at'] == SCAN.isoformat()
    assert result['native_review_hint_count'] == int(report_available)
    assert result['sectors'] == [
        {'sector_id': 'first', 'survey_count': 0, 'file_count': 0, 'accessible_files': 0, 'native_review_hints': 0},
        {'sector_id': 'renamed', 'survey_count': 1, 'file_count': 1, 'accessible_files': 1,
         'native_review_hints': int(report_available)},
    ]
    row = result['files'][0]
    assert (row['checked_at'], row['bytes'], row['last_modified_http'], row['status']) == (
        SCAN.isoformat(), 1234, 'synthetic-last-modified', 'ok',
    )
    assert row['native_review_hint'].startswith('filename-MLLW') == report_available


def test_warm_empty_file_set_still_updates_survey_leads(tmp_path, monkeypatch, documents):
    discovery, products = documents
    products['surveys'][0]['products']['bag'].clear()
    products['bag_link_count'] = 0
    no_head = Mock(side_effect=AssertionError('unexpected HEAD'))
    previous = bag.inventory(*documents, now=SCAN, fetcher=no_head)
    discovery['sectors'][0]['surveys'][0]['id'] = 'NEW-SYNTHETIC'
    products['surveys'][0]['id'] = 'NEW-SYNTHETIC'
    discovery['sectors'].append({'sector_id': 'new', 'surveys': [{'id': 'NEW-SYNTHETIC'}]})
    discovery['sector_count'] = 3
    result = run_cli(tmp_path, monkeypatch, documents, previous, no_head)
    no_head.assert_not_called()
    assert result['files'] == []
    assert result['last_complete_scan_at'] == SCAN.isoformat()
    assert [sector['sector_id'] for sector in result['sectors']] == ['first', 'second', 'new']
    assert [sector['survey_count'] for sector in result['sectors']] == [1, 0, 1]


@pytest.mark.parametrize('warm', [False, True])
@pytest.mark.parametrize(('doc', 'key', 'value'), [
    (0, 'scope', 'wrong'), (1, 'scope', 'wrong'),
    (0, 'sector_count', 3), (1, 'survey_count', 2), (1, 'survey_count', True),
    (0, 'distinct_survey_leads', 2), (1, 'bag_link_count', 0), (1, 'report_link_count', 0),
])
def test_rejects_invalid_scope_or_counts_before_head(tmp_path, monkeypatch, documents, warm, doc, key, value):
    previous = bag.inventory(*documents, now=SCAN, fetcher=lambda _: (1234, None)) if warm else None
    documents[doc][key] = value
    no_head = Mock(side_effect=AssertionError('unexpected HEAD'))
    with pytest.raises(ValueError, match='NOAA'):
        run_cli(tmp_path, monkeypatch, documents, previous, no_head)
    no_head.assert_not_called()
    assert not (tmp_path / 'output.json').exists()


def test_matching_url_with_wrong_cached_survey_is_not_reused(tmp_path, monkeypatch, documents):
    previous = bag.inventory(*documents, now=SCAN, fetcher=lambda _: (1234, None))
    previous['files'][0]['survey_id'] = 'OTHER'
    failed_head = Mock(side_effect=OSError('synthetic HEAD failure'))
    result = run_cli(tmp_path, monkeypatch, documents, previous, failed_head)
    failed_head.assert_called_once_with(URL)
    assert result['health']['status'] == 'degraded'
    assert result['files'][0]['survey_id'] == 'SYNTHETIC'
    assert result['files'][0]['status'] == 'failed'
