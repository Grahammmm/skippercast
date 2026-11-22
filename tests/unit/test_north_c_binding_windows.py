"""Bind the offline North Coast C review frames to the tracked region inputs."""

import pytest

from skippercast.platform.contracts import bbox, read_json
from tests._support import ROOT

REGION_IDS = ("trinidad-klamath", "crescent-city")
FIXTURE = ROOT / "docs/operations/fixtures/north-c-binding-windows.json"


def _check_window(region_id, window):
    region = read_json(ROOT / "regions" / region_id / "region.json")
    assert region["id"] == region_id and window["name"] == region["name"]
    assert bbox(window["fishing_bounds"]) == bbox(region["fishing_bounds"]), (
        f"{region_id}: fishing bounds differ from the tracked input"
    )
    endpoint = None
    if region_id == "crescent-city":
        endpoint = {
            "context_name": region["contexts"]["north-of-st-george"]["name"],
            "regional_north_latitude": bbox(region["bounds"])[3],
        }
    assert window.get("oregon_endpoint") == endpoint, (
        f"{region_id}: Oregon endpoint differs from the tracked input"
    )


def test_two_named_wgs84_fishing_windows_match_tracked_inputs():
    # A single combined window, swapped region names, or using discovery bounds
    # instead of fishing bounds must not silently change the review geometry.
    fixture = read_json(FIXTURE)
    assert fixture["crs"] == "WGS84"
    assert fixture["coordinate_order"] == ["west", "south", "east", "north"]
    assert set(fixture["windows"]) == set(REGION_IDS)
    for region_id in REGION_IDS:
        _check_window(region_id, fixture["windows"][region_id])


def test_reject_latitude_first_transposition():
    # A map-center convention (latitude first) must not be used for a bbox.
    window = read_json(FIXTURE)["windows"]["trinidad-klamath"]
    west, south, east, north = window["fishing_bounds"]
    window["fishing_bounds"] = [south, west, north, east]
    with pytest.raises(ValueError, match="Invalid WGS84 bounding box"):
        _check_window("trinidad-klamath", window)


def test_reject_fishing_window_extended_to_oregon_line():
    # Substituting the regional endpoint makes a valid bbox but expands the
    # fishing window north of its recorded 41.99-degree limit.
    window = read_json(FIXTURE)["windows"]["crescent-city"]
    window["fishing_bounds"][3] = window["oregon_endpoint"]["regional_north_latitude"]
    with pytest.raises(AssertionError, match="fishing bounds differ"):
        _check_window("crescent-city", window)


def test_reject_oregon_endpoint_extended_past_region():
    # A plausible latitude is not enough to identify the configured endpoint.
    window = read_json(FIXTURE)["windows"]["crescent-city"]
    window["oregon_endpoint"]["regional_north_latitude"] = 42.01
    with pytest.raises(AssertionError, match="Oregon endpoint differs"):
        _check_window("crescent-city", window)
