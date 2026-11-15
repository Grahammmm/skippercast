"""latest_cycle checks both existing ECMWF mirrors per cycle, newest cycle first; GFS is unchanged."""
from datetime import datetime, timezone

import pytest

from skippercast.forecast import fetch
from skippercast.forecast.models import ECMWF_AWS, ECMWF_PORTAL, MODELS

NOW = datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)
NEWEST = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
PREVIOUS = datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
ECMWF = MODELS['ecmwf_ifs025']
GFS = next(model for model in MODELS.values() if model.family == 'gfs')


def probe(monkeypatch, answers):
    """Replace `exists`; `answers` maps URL -> bool or exception. Unlisted URLs are missing. Returns the call log."""
    calls = []

    def exists(url):
        calls.append(url)
        answer = answers.get(url, False)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(fetch, 'exists', exists)
    return calls


def url(model, cycle, base):
    return fetch.index_url(model, cycle, model.steps[-1], base)


def test_portal_serves_newest_cycle_when_aws_lacks_it(monkeypatch):
    probe(monkeypatch, {url(ECMWF, NEWEST, ECMWF_PORTAL): True, url(ECMWF, PREVIOUS, ECMWF_AWS): True})
    assert fetch.latest_cycle(ECMWF, NOW) == NEWEST


def test_aws_transport_error_still_checks_portal(monkeypatch):
    calls = probe(monkeypatch, {url(ECMWF, NEWEST, ECMWF_AWS): OSError('mirror down'),
                                url(ECMWF, NEWEST, ECMWF_PORTAL): True})
    assert fetch.latest_cycle(ECMWF, NOW) == NEWEST
    assert calls == [url(ECMWF, NEWEST, ECMWF_AWS), url(ECMWF, NEWEST, ECMWF_PORTAL)]


def test_both_mirrors_missing_falls_to_next_cycle_then_none(monkeypatch):
    probe(monkeypatch, {url(ECMWF, NEWEST, ECMWF_AWS): OSError('down'), url(ECMWF, PREVIOUS, ECMWF_PORTAL): True})
    assert fetch.latest_cycle(ECMWF, NOW) == PREVIOUS
    calls = probe(monkeypatch, {url(ECMWF, NEWEST, ECMWF_AWS): OSError('down')})
    assert fetch.latest_cycle(ECMWF, NOW, lookback_hours=12) is None
    assert url(ECMWF, NEWEST, ECMWF_PORTAL) in calls and url(ECMWF, PREVIOUS, ECMWF_PORTAL) not in calls


def test_aws_success_does_not_probe_portal(monkeypatch):
    calls = probe(monkeypatch, {url(ECMWF, NEWEST, ECMWF_AWS): True})
    assert fetch.latest_cycle(ECMWF, NOW) == NEWEST
    assert calls == [url(ECMWF, NEWEST, ECMWF_AWS)]


def test_gfs_checks_only_its_own_index_and_misses_stay_misses(monkeypatch):
    cycle = datetime(2026, 11, 1, 18, tzinfo=timezone.utc)
    calls = probe(monkeypatch, {fetch.index_url(GFS, cycle, GFS.steps[-1]): True})
    assert fetch.latest_cycle(GFS, NOW) == cycle
    assert calls == [fetch.index_url(GFS, cycle, GFS.steps[-1])]
    probe(monkeypatch, {})
    assert fetch.latest_cycle(GFS, NOW, lookback_hours=6) is None


def test_gfs_transport_error_still_propagates(monkeypatch):
    probe(monkeypatch, {fetch.index_url(GFS, datetime(2026, 11, 1, 18, tzinfo=timezone.utc), GFS.steps[-1]): OSError('x')})
    with pytest.raises(OSError):
        fetch.latest_cycle(GFS, NOW)
