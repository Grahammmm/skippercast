"""stamp(to_utc=False) always writes a four-digit year."""
from datetime import datetime, timedelta, timezone

import pytest

from skippercast.util.time import stamp


@pytest.mark.parametrize('year, text', [(1, '0001'), (9, '0009'), (99, '0099'), (999, '0999')])
def test_wall_field_year_is_four_digits(year, text):
    moment = datetime(year, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
    assert stamp(moment, to_utc=False) == f'{text}-02-03T04:05:06Z'


@pytest.mark.parametrize('year', [1000, 2026, 9999])
def test_wall_field_year_boundaries_and_modern_control(year):
    moment = datetime(year, 12, 31, 23, 59, 58, tzinfo=timezone.utc)
    assert stamp(moment, to_utc=False) == f'{year}-12-31T23:59:58Z'


def test_wall_fields_do_not_convert_offset():
    zone = timezone(timedelta(hours=5, minutes=30))
    assert stamp(datetime(7, 2, 3, 4, 5, 6, tzinfo=zone), to_utc=False) == '0007-02-03T04:05:06Z'
    assert stamp(datetime(2026, 2, 3, 4, 5, 6, tzinfo=zone), to_utc=False) == '2026-02-03T04:05:06Z'
    assert stamp(datetime(2026, 2, 3, 4, 5, 6, tzinfo=zone)) == '2026-02-02T22:35:06Z'


def test_naive_wall_fields_and_microseconds():
    assert stamp(datetime(42, 2, 3, 4, 5, 6, 987654), to_utc=False) == '0042-02-03T04:05:06Z'


def test_default_utc_format_is_unchanged():
    assert stamp(datetime(5, 2, 3, 4, 5, 6, tzinfo=timezone.utc)) == '0005-02-03T04:05:06Z'
    assert stamp(datetime(2026, 2, 3, 4, 5, 6, tzinfo=timezone.utc)) == '2026-02-03T04:05:06Z'
