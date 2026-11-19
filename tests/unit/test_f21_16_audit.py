"""F21-16: synthetic NAIS coverage controls; no archive or registry access.

Run `python -B -m tests.unit.test_f21_16_audit` for a count-only comparison
(exit 1 on a gap). Pytest replays the same cases against the report.
"""
from datetime import date, datetime
from io import StringIO
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.fleet import nais_presence as nais


LOCAL = tuple(date(2026, 1, d) for d in (12, 13, 14))
UTC = (*LOCAL, date(2026, 1, 15))
ZONE = 'America/Los_Angeles'
HEARD = datetime.fromisoformat('2026-01-12T20:00:00+00:00')
CASES = (
    ('complete', None, (3, 3, 0, 1)),
    ('missing-shared-file', nais.DayNotPublished, (3, 1, 2, 1)),
    ('failed-shared-file', nais.CorruptDay, (3, 1, 2, 1)),
)


@pytest.mark.parametrize('_name,unavailable,expected', CASES, ids=[case[0] for case in CASES])
def test_shared_utc_archive_controls_local_day_denominator(_name, unavailable, expected):
    # A lost UTC archive straddles two Pacific days; presence in the part that
    # was read still counts as positive, but cannot make either day complete.
    assert _reported_counts(unavailable) == expected


def _reported_counts(unavailable):
    calls = []
    mmsi = 999000001

    def history(day, _bbox, wanted):
        calls.append(day)
        assert wanted == {mmsi}
        if day == UTC[1] and unavailable:
            raise unavailable('synthetic')
        if day == HEARD.date():
            yield SimpleNamespace(mmsi=mmsi, ts=int(HEARD.timestamp() * 1000))

    out = StringIO()
    region = SimpleNamespace(timezone=ZONE, ais=SimpleNamespace(south=0, west=0, north=1, east=1),
                             port=lambda _: None)
    argv = ['--region', 'synthetic', '--from', str(LOCAL[0]), '--to', str(LOCAL[-1]),
            '--targets', 'synthetic', '--workdir', '.']
    with (patch.object(nais, '_targets', return_value={'A': mmsi}),
          patch.object(nais, 'load_region', return_value=region),
          patch.object(nais, '_free_gb', return_value=100)):
        code = nais.main(argv, source=SimpleNamespace(history=history), out=out)
    text = out.getvalue()
    assert code == 0 and calls == list(UTC)
    assert f'UTC day files read: {4 - bool(unavailable)} of 4.' in text
    coverage = re.search(r'Local days requested: (\d+)\. Partial/unknown local days: (\d+)\.', text)
    assert coverage is not None
    requested, incomplete = map(int, coverage.groups())
    if unavailable is nais.DayNotPublished:
        assert f'Missing (not published): {UTC[1]}' in text
    if unavailable is nais.CorruptDay:
        assert f'Failed: {UTC[1]} (CorruptDay)' in text
    header = next(line for line in text.splitlines() if line.startswith('| Label |'))
    row = next(line for line in text.splitlines() if line.startswith('| A |'))
    cells = dict(zip((c.strip() for c in header.strip('|').split('|')),
                     (c.strip() for c in row.strip('|').split('|')), strict=True))
    return (requested, int(cells['Days fully checked']), incomplete, int(cells['Days heard anywhere in region']))


def _replay():
    gap = False
    print('Counts: requested, fully checked, partial/unknown, positive')
    for name, unavailable, expected in CASES:
        actual = _reported_counts(unavailable)
        gap |= actual != expected
        print(f'{name}: {"PASS" if actual == expected else "GAP"}; expected {expected}, observed {actual}')
    return int(gap)


if __name__ == '__main__':
    raise SystemExit(_replay())
