"""iso_utc keeps four-digit years so every supported UTC year round-trips through from_iso."""
from __future__ import annotations

import pytest

from skippercast.fleet.ais.events import from_iso, id32, iso_utc, trip_id

@pytest.mark.parametrize("year", ["0001", "0009", "0099", "0999"])
def test_iso_utc_pads_supported_low_years(year):
    text = f"{year}-03-04T05:06:07.089Z"
    ms = from_iso(text)
    assert iso_utc(ms) == text
    assert from_iso(iso_utc(ms)) == ms


def test_iso_utc_year_width_boundary():
    low = from_iso("0999-12-31T23:59:59.001Z")
    high = from_iso("1000-01-01T00:00:00.002Z")
    assert iso_utc(low) == "0999-12-31T23:59:59.001Z"
    assert iso_utc(high) == "1000-01-01T00:00:00.002Z"
    assert high - low == 1001


@pytest.mark.parametrize(
    "ms,expected",
    [
        (-1, "1969-12-31T23:59:59.999Z"),
        (0, "1970-01-01T00:00:00.000Z"),
        (1, "1970-01-01T00:00:00.001Z"),
        (1767225599999, "2025-12-31T23:59:59.999Z"),
        (1767225600000, "2026-01-01T00:00:00.000Z"),
    ],
)
def test_iso_utc_modern_control(ms, expected):
    assert iso_utc(ms) == expected
    assert from_iso(expected) == ms


def test_modern_trip_id_is_stable_from_literal_iso():
    ms = 1767225600001
    assert trip_id(366123456, ms, "synthetic") == id32("366123456", "2026-01-01T00:00:00.001Z", "synthetic")
