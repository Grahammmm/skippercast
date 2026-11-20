"""Receipt clocks treat aware datetimes as instants, not times of day."""
from datetime import datetime, timedelta, timezone, tzinfo
from types import SimpleNamespace

import pytest

from skippercast.coastal.receipts import epoch, monotonic, utc


def test_direct_datetime_agrees_with_callable_and_epoch_clock():
    instant = datetime(1970, 1, 1, 2, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    clock = SimpleNamespace(time=lambda: 30.0)
    assert epoch(lambda: instant) == epoch(clock) == epoch(instant) == 30.0
    assert utc(instant) == "1970-01-01T00:00:30Z"
    assert monotonic(instant) == 30.0


class NoOffset(tzinfo):
    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize("zone", [None, NoOffset()], ids=["no-zone", "no-offset"])
def test_naive_datetimes_are_not_interpreted_as_local_time(zone):
    instant = datetime(2026, 1, 1, tzinfo=zone)
    for clock in (instant, lambda: instant):
        with pytest.raises(ValueError, match="naive datetime"):
            epoch(clock)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_clock_readings_are_refused(value):
    clock = SimpleNamespace(time=lambda: value, monotonic=lambda: value)
    with pytest.raises(ValueError, match="finite instant"):
        epoch(clock)
    with pytest.raises(ValueError, match="monotonic clock must be finite"):
        monotonic(clock)
