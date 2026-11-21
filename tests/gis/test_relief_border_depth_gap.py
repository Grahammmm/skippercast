"""Exercise the offline border depth gap CLI from polygon bytes to stdout JSON."""

from hashlib import sha256
import json
import subprocess
import sys

from pyproj import Transformer
import pytest
import shapely
from shapely.geometry import Polygon, box, mapping

from tests._support import ROOT

_CLI = ROOT / "scripts/relief/border_depth_gap.py"
_TO_DEGREES = Transformer.from_crs(3310, 4326, always_xy=True)


def _write(path, polygon):
    geometry = shapely.transform(polygon, _TO_DEGREES.transform, interleaved=False)
    path.write_text(json.dumps(mapping(geometry), indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def inputs(tmp_path):
    # In metric coordinates the reviewed edge is y = x/4 + 100; US is above it.
    return {
        "water": _write(tmp_path / "water.json", box(-1500, -1000, 1500, 650)),
        "window": _write(tmp_path / "window.json", box(-1000, -750, 1000, 750)),
        "boundary": _write(tmp_path / "boundary.json", Polygon([
            (-4000, -900), (4000, 1100), (4000, 5000), (-4000, 5000),
        ])),
    }


def _run(inputs):
    args = [arg for label, path in inputs.items() for arg in (f"--{label}", str(path))]
    return subprocess.run([sys.executable, str(_CLI), *args], capture_output=True, text=True, timeout=30)


def _report(inputs):
    result = _run(inputs)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["sha256"] == {
        label: sha256(inputs[label].read_bytes()).hexdigest() if label in inputs else None
        for label in ("water", "support", "window", "boundary")
    }
    return report


def test_oblique_boundary_counts_only_support_in_windowed_us_water(tmp_path, inputs):
    """Exclude support beyond the sloped border, window and water; bind raw bytes, not normalized JSON."""
    inputs["support"] = _write(tmp_path / "support.json", box(-1250, -500, 0, 1250))
    report = _report(inputs)
    # 2000 m × (650 - 100) average height for water; 1000 m × (650 - (-25)) for support.
    # A horizontal split can match the whole symmetric water area but not the western support area.
    assert report["us_water_m2"] == pytest.approx(1_100_000, rel=1e-7)
    assert report["support_m2"] == pytest.approx(675_000, rel=1e-7)
    assert report["remainder_m2"] == pytest.approx(425_000, rel=1e-7)


def test_omitted_support_is_unknown_not_zero(inputs):
    """Missing evidence must not claim zero support or classify all water as the remainder."""
    report = _report(inputs)
    assert report["us_water_m2"] == pytest.approx(1_100_000, rel=1e-7)
    assert report["support_m2"] is None
    assert report["remainder_m2"] is None


@pytest.mark.parametrize("support", [
    pytest.param(box(-500, -700, 500, -300), id="outside-reviewed-boundary"),
    pytest.param(box(-1400, -750, -1000, 750), id="touching-window-edge-only"),
])
def test_supplied_support_without_positive_overlap_is_zero(tmp_path, inputs, support):
    """A supplied footprint is neither missing evidence nor proof of positive-area overlap."""
    inputs["support"] = _write(tmp_path / "support.json", support)
    report = _report(inputs)
    assert report["us_water_m2"] == pytest.approx(1_100_000, rel=1e-7)
    assert report["support_m2"] == 0
    assert report["remainder_m2"] == report["us_water_m2"]


@pytest.mark.parametrize("data", [None, b"{"], ids=["unreadable", "malformed"])
def test_explicit_bad_support_is_not_treated_as_missing(tmp_path, inputs, data):
    """A bad path or broken support file must fail, not emit a successful unknown report."""
    support = tmp_path / "support.json"
    if data is not None:
        support.write_bytes(data)
    result = _run(dict(inputs, support=support))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "support" in result.stderr


def test_rejects_axis_aligned_boundary_proxy(inputs):
    """Use the reviewed boundary reader, not an arbitrary rectangle in place of the border."""
    inputs["boundary"].write_text(json.dumps(mapping(box(-121, 36, -119, 38))), encoding="utf-8")
    result = _run(inputs)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "axis-aligned" in result.stderr
