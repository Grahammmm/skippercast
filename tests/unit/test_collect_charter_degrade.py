"""SC-FEED-DEGRADE-1: a stale charter-report source marks only that section not available.

The rest of the daily feed still publishes. A fresh charter source leaves the feed exactly as it was
(no new keys), and the "cannot infer zero trips" rule (coverage below 5 of 7 days is never read as no trips)
is unchanged: the section carries no trip records at all rather than zero catches.
"""
from datetime import datetime, timedelta, timezone
import json
from hashlib import sha256

import pytest

from skippercast.pipeline import collect
from tests._support import ROOT

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
TODAY = NOW.date()
STAMP = NOW.strftime('%Y-%m-%dT%H:%M:%SZ')


def trip(day):
    return {'id': sha256(day.encode()).hexdigest()[:16], 'date': day, 'boat': 'Fixture Boat', 'port': 'Morro Bay',
            'catches': [{'species': 'lingcod', 'label': 'Lingcod', 'count': 3, 'disposition': 'retained'}],
            'source_url': 'https://reports.example/' + day, 'coordinates': None, 'depth_ft': None}


def fake_source(ok_days):
    def source(ident, name, kind, url, max_age, loader, now, previous=None, client_factory=None):
        row = {'id': ident, 'name': name, 'kind': kind, 'url': url, 'checked_at': STAMP, 'max_age_hours': max_age,
               'status': 'ok', 'data': {'sample_at': STAMP, 'issued_at': STAMP}, 'requests': [],
               'last_success_at': STAMP, 'data_retrieved_at': STAMP}
        if kind == 'charter-reports':
            day = ident[len('catches-'):]
            if day in ok_days:
                row['data'] = {'reports': [trip(day)]}
            else:
                row.update(status='failed', data=None, issue='ValueError: no scores posted')
        return row
    return source


def build(monkeypatch, ok_days):
    # The fake source never calls its loader, and the real grid loaders import scipy (absent from the no-GIS lane).
    monkeypatch.setattr(collect, 'grid_loader', lambda kind, bounds=None, config=None: None)
    monkeypatch.setattr(collect, 'source', fake_source(ok_days))
    return collect.collect(NOW)


def days(count_ok, offset=0):
    return {(TODAY - timedelta(days=i)).isoformat() for i in range(1 + offset, 1 + offset + count_ok)}


def test_stale_charter_source_publishes_with_section_not_available(monkeypatch):
    # Last charter scores are well before the 7-day window, as on 2026-11-12.
    feed = build(monkeypatch, days(3, offset=4))
    assert feed['health']['recent_report_days_ok'] < 5
    assert feed['charter_reports'] == {'status': 'not_available', 'reason': 'source_stale',
                                       'last_source_day': max(days(3, offset=4))}
    assert feed['reports'] == [], 'no trip records and no zero-catch rows'
    assert 'zero' not in json.dumps(feed['charter_reports'])
    assert feed['health']['status'] == 'degraded'
    assert feed['health']['critical_available'] is True
    assert feed['health']['degraded_reasons'] == ['charter_reports: source_stale']
    others = [s for s in feed['sources'].values() if s['kind'] != 'charter-reports']
    assert others and all(s['status'] == 'ok' for s in others), 'every other section is present and fresh'
    collect.validate(feed)


def test_stale_charter_source_with_no_scores_at_all(monkeypatch):
    feed = build(monkeypatch, set())
    assert feed['charter_reports'] == {'status': 'not_available', 'reason': 'source_stale', 'last_source_day': None}
    assert feed['reports'] == []
    assert feed['health']['status'] == 'degraded'


def test_fresh_charter_source_output_has_no_new_keys_and_returns_reports(monkeypatch):
    feed = build(monkeypatch, days(30))
    assert 'charter_reports' not in feed
    assert 'degraded_reasons' not in feed['health']
    assert len(feed['reports']) == 30
    assert feed['health']['recent_report_days_ok'] == 7
    assert feed['health']['critical_available'] is True
    # Source failures other than the charter section keep their existing meaning.
    assert feed['health']['status'] == 'ok'


def test_recovery_is_automatic_at_five_of_seven_days(monkeypatch):
    stale = build(monkeypatch, days(4))
    assert stale['charter_reports']['status'] == 'not_available'
    back = build(monkeypatch, days(5))
    assert 'charter_reports' not in back and len(back['reports']) == 5


def test_validate_rejects_not_available_section_that_still_carries_trips(monkeypatch):
    feed = build(monkeypatch, days(30))
    feed['charter_reports'] = {'status': 'not_available', 'reason': 'source_stale', 'last_source_day': None}
    with pytest.raises(ValueError, match='no trip records'):
        collect.validate(feed)


def test_schema_describes_the_new_section_and_reason_list():
    schema = json.loads((ROOT / 'schemas' / 'daily-feed.schema.json').read_text())
    section = schema['properties']['charter_reports']
    assert section['properties']['status'] == {'const': 'not_available'}
    assert 'degraded_reasons' in schema['properties']['health']['properties']
    assert 'charter_reports' not in schema['required']


def test_freshness_check_reports_the_degraded_reason_without_failing(monkeypatch):
    from scripts import check_feed_freshness as check
    feed = build(monkeypatch, days(3, offset=4))
    feed.update(published_at=STAMP, run_id='fixture')
    status, message = check.check_feed('data', 'fixture://public', 'fixture://github', NOW, fetch=lambda *a, **k: feed)
    assert not status & check.STALE and not status & check.DEGRADED
    assert 'is degraded by design: charter_reports: source_stale.' in message
    fresh = build(monkeypatch, days(30))
    fresh.update(published_at=STAMP, run_id='fixture')
    _, quiet = check.check_feed('data', 'fixture://public', 'fixture://github', NOW, fetch=lambda *a, **k: fresh)
    assert 'degraded by design' not in quiet
