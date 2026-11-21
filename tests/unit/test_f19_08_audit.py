"""F19-08: station predictions must cover the requested UTC dates."""
import datetime as dt
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import build_tide_layer as tide


def test_build_distinguishes_station_coverage(tmp_path):
    # Four alternating extremes used to pass even when all were six years old.
    # Boundary-day timing varies by station; no extreme is required at midnight.
    begin = dt.datetime(2026, 5, 31, 6, tzinfo=dt.timezone.utc)
    full = [begin + dt.timedelta(hours=12 * i) for i in range(10)]
    tables = {
        'complete': full[::-1],
        'old': [dt.datetime(2020, 1, 1, h, tzinfo=dt.timezone.utc) for h in (0, 6, 12, 18)],
        'late-start': full[2:],
        'early-end': full[:-2],
        'missing-day': full[:4] + full[6:],
        'spill': full + [dt.datetime(2026, 6, 5, tzinfo=dt.timezone.utc)],
    }
    sectors = tmp_path / 'sectors.json'
    sectors.write_text(json.dumps({'sectors': [{'id': 'synthetic', 'latitude': [-1, 1]}]}))

    def build(ids):
        def fetch(url):
            if url == tide.STATIONS_URL:
                return {'stations': [dict(id=i, name=i, lat=0, lng=0) for i in ids]}
            query = parse_qs(urlsplit(url).query)
            assert query['begin_date'] == ['20260531']
            assert query['end_date'] == ['20260604']
            assert query['time_zone'] == ['gmt']
            return {'predictions': [
                {'t': t.strftime('%Y-%m-%d %H:%M'), 'type': 'LH'[i % 2], 'v': '1'}
                for i, t in enumerate(tables[query['station'][0]])
            ]}

        return tide.build(sectors, ['synthetic'], 'audit', begin + dt.timedelta(days=1),
                          3, fetch=fetch, lon_range=(-1, 1), pause=0)

    doc = build(tables)
    assert doc['window'] == {'begin': '2026-05-31', 'end': '2026-06-04', 'time_zone': 'UTC'}
    assert [station['id'] for station in doc['stations']] == ['complete']
    assert doc['stations'][0]['coverage'] == {
        'status': 'complete', 'first': '2026-05-31T06:00Z', 'last': '2026-06-04T18:00Z',
    }
    failed = {station['id']: station['coverage'] for station in doc['failed']}
    assert failed == {
        'old': {'status': 'out_of_window', 'first': '2020-01-01T00:00Z', 'last': '2020-01-01T18:00Z'},
        'late-start': {'status': 'partial', 'first': '2026-06-01T06:00Z', 'last': '2026-06-04T18:00Z'},
        'early-end': {'status': 'partial', 'first': '2026-05-31T06:00Z', 'last': '2026-06-03T18:00Z'},
        'missing-day': {'status': 'partial', 'first': '2026-05-31T06:00Z', 'last': '2026-06-04T18:00Z'},
        'spill': {'status': 'out_of_window', 'first': '2026-05-31T06:00Z', 'last': '2026-06-05T00:00Z'},
    }
    with pytest.raises(SystemExit, match='partial UTC date coverage'):
        build(['early-end'])
