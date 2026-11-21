"""Offline GEFS Wave inventory, exact-time provenance and collection health."""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from skippercast.pipeline import intelligence, wave_ensemble
from skippercast.pipeline.collect import source

NOW = datetime(2026, 11, 9, 9, tzinfo=timezone.utc)
NEW = NOW.replace(hour=6)
OLD = NOW.replace(hour=0)
LEADS = tuple(range(0, 169, 3))
# Eight NOAA exceedance fields in both committed regional intelligence snapshots.
THRESHOLDS = (0.6, 1, 2, 3, 4, 5.5, 7, 9)
REGION = {'bounds': [0, 0, 1, 1], 'forecast_points': []}


def filename(cycle, lead):
    return f'gefs.wave.t{cycle:%H}z.prob.global.0p25.f{lead:03}.grib2'


def records(cycle, lead, thresholds=THRESHOLDS):
    return [{'cycle': int(cycle.timestamp()), 'time': int((cycle + timedelta(hours=lead)).timestamp()),
             'threshold_m': threshold, 'points': [{'percent': None}, {'percent': 0.0}]}
            for threshold in thresholds]


class InertClient:
    def __init__(self, listings, overrides=None):
        self.listings = listings
        self.overrides = overrides or {}
        self.files = []
        self.requests = []

    def get(self, url, as_binary=False):
        parsed = urlparse(url)
        if not as_binary:
            return ' '.join(self.listings.get(parsed.path.rstrip('/').split('/')[-3], ()))
        query = parse_qs(parsed.query)
        name = query['file'][0]
        self.files.append(name)
        cycle = datetime.strptime(query['dir'][0].split('/')[-3], '%H').hour
        key = (cycle, int(name.split('.')[-2][1:]))
        if key in self.overrides:
            value = self.overrides[key]
            if isinstance(value, Exception):
                raise value
            return value
        return records(NOW.replace(hour=cycle), key[1])


@pytest.fixture(autouse=True)
def stub_decoding(monkeypatch):
    monkeypatch.setattr(wave_ensemble, 'decode_probabilities', lambda body, _: body)


def collect(client):
    return source('wave-ensemble', 'GEFS Wave', 'forecast', 'https://example.invalid', 36,
                  lambda c: wave_ensemble.wave_probabilities(c, REGION, NOW), NOW,
                  client_factory=lambda _: client)


def test_lone_f168_is_partial_and_does_not_create_other_times():
    client = InertClient({'06': [filename(NEW, 168)]})
    result = collect(client)
    data = result['data']
    assert data['frames'] == records(NEW, 168)
    assert data['failed_files'] == []
    assert data['horizon_status'] == 'partial'
    assert data['missing_lead_hours'] == list(LEADS[:-1])
    assert intelligence.collection_health({'wave-ensemble': result, 'model-sea': {'status': 'ok'}}) == {
        'status': 'degraded', 'issues': ['wave-ensemble'], 'coverage_gaps': ['wave-ensemble']}


def test_earlier_complete_inventory_wins_without_mixing_cycles():
    # f003 from the wrong cycle cannot close the gap in the newest listing.
    client = InertClient({'06': [filename(NEW, lead) for lead in LEADS if lead != 3] + [filename(OLD, 3)],
                          '00': [filename(OLD, lead) for lead in (*LEADS, 171)]})
    result = collect(client)
    data = result['data']
    assert data['horizon_status'] == 'complete'
    assert data['missing_lead_hours'] == data['incomplete_threshold_lead_hours'] == []
    assert data['frames'] == [frame for lead in LEADS for frame in records(OLD, lead)]
    assert sorted(client.files) == [filename(OLD, lead) for lead in LEADS]
    assert intelligence.collection_health({'wave-ensemble': result}) == {
        'status': 'ok', 'issues': [], 'coverage_gaps': []}


def test_duplicate_threshold_does_not_replace_missing_threshold_at_present_lead():
    client = InertClient({'06': [filename(NEW, lead) for lead in LEADS]}, {
        (6, 9): records(NEW, 9, (*THRESHOLDS[:-1], 7)),
    })
    result = collect(client)
    assert result['data']['missing_lead_hours'] == []
    assert result['data']['incomplete_threshold_lead_hours'] == [9]
    assert result['data']['horizon_status'] == 'partial'
    assert intelligence.collection_health({'wave-ensemble': result})['status'] == 'degraded'


def test_complete_listing_still_requires_bound_decoded_leads_and_thresholds():
    client = InertClient({'06': [filename(NEW, lead) for lead in LEADS]}, {
        (6, 3): records(NEW, 0),  # Same cycle, repeated f000's valid time.
        (6, 6): OSError('Unusable file'),
        (6, 9): records(NEW, 9, THRESHOLDS[:-1]),
        (6, 12): records(NEW, 12) + records(OLD, 12),
    })
    data = wave_ensemble.wave_probabilities(client, REGION, NOW)
    assert data['horizon_status'] == 'partial'
    assert data['missing_lead_hours'] == [3, 6]
    assert data['incomplete_threshold_lead_hours'] == [9]
    assert [failure['file'] for failure in data['failed_files']] == [filename(NEW, lead) for lead in (3, 6, 12)]
    assert data['frames'] == [frame for lead in LEADS if lead not in (3, 6)
                              for frame in records(NEW, lead, THRESHOLDS[:-1] if lead == 9 else THRESHOLDS)]
