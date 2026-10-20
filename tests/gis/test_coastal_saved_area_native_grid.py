"""Saved-area A native grid is a named, pinned constant and refusals name the field (SC-8d, item 69).

Synthetic facts only; no native source, receipt or grant is opened.
"""
import importlib.util
import sys

import pytest

from skippercast.coastal.coordinator import saved_area
from skippercast.coastal.coordinator.saved_area import (
    SAVED_AREA_A_NATIVE_GRID as GRID,
    require_saved_area_a_native_grid,
)
from tests._support import ROOT

SCRIPT = ROOT / "research" / "scripts" / "coastal_four128_window_scan.py"
WINDOW = [3890, 3488, 128, 128]
# tests/gis/test_coastal_four128_window_scan.py::test_every_lattice_footprint_has_its_segment_margin
WINDOW_SCAN_A_NATIVE_BOUNDS = [728871, 3818923, 729127, 3819179]


@pytest.fixture
def scan():
    spec = importlib.util.spec_from_file_location("coastal_four128_window_scan_grid", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def facts(**header_overrides):
    header = dict(shape=[10495, 10034], window=list(WINDOW),
                  transform=[2.0, 0.0, 728871.0, 0.0, -2.0, 3819179.0],
                  resolution_m=[2.0, 2.0], horizontal_crs="EPSG:26910")
    header.update(header_overrides)
    return dict(header=header, valid_count=16384, valid_fraction=1)


def constant_bounds(side=128):
    a, _, x0, _, e, y0 = GRID["transform"]
    return [x0, y0 + side * e, x0 + side * a, y0]


def test_constant_origin_agrees_with_window_scan_fixture(scan):
    a, b, x0, d, e, y0 = GRID["transform"]
    assert (x0, y0) == (728871, 3819179)
    assert (a, b, d, e) == (2.0, 0.0, 0.0, -2.0) and GRID["resolution_m"] == (2.0, 2.0)
    assert constant_bounds() == WINDOW_SCAN_A_NATIVE_BOUNDS
    # The same window computed independently by the pre-scan from its own full-grid affine.
    assert scan.FIXED["A"] == (3890, 3488) and tuple(GRID["shape"]) == scan.GRID_SHAPE
    assert scan.NATIVE_CRS == "EPSG:%d" % GRID["epsg"]
    assert scan.footprint(*scan.FIXED["A"], scan.transformers())["native_bounds"] == constant_bounds()


def test_constant_is_read_only():
    with pytest.raises(TypeError):
        saved_area.SAVED_AREA_A_NATIVE_GRID["valid_count"] = 1


def test_exact_saved_area_a_grid_is_accepted():
    assert require_saved_area_a_native_grid(facts(), list(WINDOW)) is None
    # Equal-valued ints were accepted by the old literal check and still are.
    require_saved_area_a_native_grid(facts(transform=[2, 0, 728871, 0, -2, 3819179], resolution_m=[2, 2]),
                                     list(WINDOW))


@pytest.mark.parametrize("shift", [(2.0, 0.0), (0.0, -2.0), (0.5, 0.0)])
def test_shifted_origin_is_refused_naming_the_transform(shift):
    dx, dy = shift
    moved = [2.0, 0.0, 728871.0 + dx, 0.0, -2.0, 3819179.0 + dy]
    with pytest.raises(ValueError, match=r"scope differs: transform does not match pinned saved-area A grid"):
        require_saved_area_a_native_grid(facts(transform=moved), list(WINDOW))


@pytest.mark.parametrize("field,value", [
    ("shape", [10495, 10035]),
    ("shape", (10495, 10034)),  # a tuple never equalled the literal list; still refused
    ("window", [3890, 3360, 128, 128]),
    ("transform", [2.0, 0.0, 728871.0, 0.0, 2.0, 3819179.0]),
    ("resolution_m", [1.0, 1.0]),
    ("horizontal_crs", "EPSG:26911"),
])
def test_each_header_field_is_named(field, value):
    with pytest.raises(ValueError, match=r"scope differs: %s does not match" % field):
        require_saved_area_a_native_grid(facts(**{field: value}), list(WINDOW))


@pytest.mark.parametrize("field,value", [("valid_count", 16383), ("valid_fraction", 0.999)])
def test_full_support_fields_are_named(field, value):
    doc = dict(facts(), **{field: value})
    with pytest.raises(ValueError, match=r"scope differs: %s does not match" % field):
        require_saved_area_a_native_grid(doc, list(WINDOW))


def test_first_differing_field_is_reported_in_original_order():
    doc = dict(facts(transform=[2.0, 0.0, 0.0, 0.0, -2.0, 0.0]), valid_count=0)
    with pytest.raises(ValueError, match=r": transform does not match"):
        require_saved_area_a_native_grid(doc, list(WINDOW))


def old_inline_check(facts, window):
    """The pre-SC-8d condition from validate_adoption, verbatim apart from the window argument."""
    from pyproj import CRS
    h = facts['header']; c = CRS.from_user_input(h['horizontal_crs']); c = c.source_crs if c.is_bound else c
    if (h['shape'] != [10495, 10034] or h['window'] != window
        or h['transform'] != [2.0, 0.0, 728871.0, 0.0, -2.0, 3819179.0]
        or h['resolution_m'] != [2.0, 2.0] or not c.equals(CRS.from_epsg(26910))
        or facts['valid_count'] != 16384 or facts['valid_fraction'] != 1):
        raise ValueError('original native grid CRS/affine/full-support scope differs')


VARIANTS = [facts(), facts(transform=[2, 0, 728871, 0, -2, 3819179]), facts(resolution_m=(2.0, 2.0)),
            facts(horizontal_crs="+proj=utm +zone=10 +datum=NAD83 +units=m +no_defs +type=crs"),
            facts(horizontal_crs="+proj=utm +zone=10 +ellps=GRS80 +towgs84=0,0,0 +units=m +no_defs +type=crs"),
            facts(horizontal_crs="EPSG:32610"), facts(shape=[10034, 10495]),
            facts(window=[3890, 3488, 128, 129]), facts(transform=[2.0, 0.0, 728871.0, 0.0, -2.0, 3819179.0, 0.0]),
            dict(facts(), valid_count=16384.0), dict(facts(), valid_fraction=1.0), dict(facts(), valid_fraction=True),
            dict(facts(), valid_count=None)]


@pytest.mark.parametrize("doc", VARIANTS)
def test_same_inputs_accepted_and_refused_as_the_old_literal_check(doc):
    def outcome(check):
        try:
            check(doc, list(WINDOW))
            return "accepted"
        except ValueError:
            return "refused"
    assert outcome(require_saved_area_a_native_grid) == outcome(old_inline_check)


def test_validate_adoption_delegates_to_the_pinned_check():
    import inspect
    source = inspect.getsource(saved_area.validate_adoption)
    assert "require_saved_area_a_native_grid(facts,new_grant['window_set'][0])" in source
    for literal in ("10495", "728871", "3819179", "16384", "26910"):
        assert literal not in source
