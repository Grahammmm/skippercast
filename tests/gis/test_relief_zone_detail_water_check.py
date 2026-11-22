"""Exercise the offline check from saved producer-format GeoJSON through JSON output."""

import json

import pytest
from shapely.geometry import Polygon, box, mapping

from scripts.relief.zone_detail_water_check import main

REGION = "fixture-region"
WATER = box(-120.004, 36.996, -119.996, 37.004)


def _save(path, geometries, *, region=REGION, tier=None):
    # Deliberately omit source metadata: this is a geometry check, not source validation.
    value = dict(type="FeatureCollection", region=region, navigation="NOT FOR NAVIGATION",
                 features=[dict(type="Feature", geometry=mapping(geom),
                                properties={} if tier is None else {"tier": tier}) for geom in geometries])
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _check(zone, detail, capsys, *flags):
    code = main(["--region", REGION, "--zone", str(zone), "--detail", str(detail), *flags])
    return code, json.loads(capsys.readouterr().out)


def test_contained_by_union_not_by_any_single_feature(tmp_path, capsys):
    # Invariant: the union is the reference. Using just one feature (or requiring
    # individual containment) would flag this footprint that bridges two zones.
    zone = _save(tmp_path / "zone.geojson", [box(-120.004, 36.996, -120, 37.004),
                                             box(-120, 36.996, -119.996, 37.004)])
    detail = _save(tmp_path / "detail.geojson", [box(-120.001, 36.999, -119.999, 37.001)], tier="estimated")
    before = (zone.read_bytes(), detail.read_bytes())
    assert _check(zone, detail, capsys) == (0, dict(region=REGION, area_crs="EPSG:3310",
                                                   area_tolerance_m2=0.01, status="within_tolerance",
                                                   outside_area_m2=0.0))
    assert (zone.read_bytes(), detail.read_bytes()) == before
    assert set(tmp_path.iterdir()) == {zone, detail}


def test_exact_edge_contact_with_different_vertex_spacing(tmp_path, capsys):
    # Invariant: an exact shared GeoJSON edge contributes no outside area. If
    # inputs are projected separately, the extra vertex bends the shared edge.
    zone = _save(tmp_path / "zone.geojson", [WATER])
    detail = _save(tmp_path / "detail.geojson", [Polygon([
        (-120.003, 37.001), (-119.997, 37.001), (-119.997, 36.996),
        (-120.000, 36.996), (-120.003, 36.996),
    ])], tier="1m-measured")
    code, report = _check(zone, detail, capsys, "--area-tolerance-m2", "0")
    assert (code, report["outside_area_m2"], report["status"]) == (0, 0.0, "within_tolerance")


def test_detail_crossing_land_hole_reports_unique_outside_area_and_applies_tolerance(tmp_path, capsys):
    # Invariant: holes remain outside water and overlapping footprints count
    # once. Using an envelope, omitting the existing 'none' tier, summing both
    # polygons, or measuring degrees instead of m² changes this result.
    hole = box(-120.001, 36.999, -119.999, 37.001)
    zone = _save(tmp_path / "zone.geojson", [Polygon(WATER.exterior.coords, [hole.exterior.coords])])
    detail = _save(tmp_path / "detail.geojson", [box(-120.002, 36.998, -120, 37.002),
                                                 box(-120.0015, 36.9985, -120, 37.0015)], tier="none")
    code, report = _check(zone, detail, capsys)
    assert (code, report["status"], report["area_crs"]) == (1, "outside", "EPSG:3310")
    # Half the hole is 0.001° × 0.002° at 37° N: roughly 89 m × 222 m.
    assert report["outside_area_m2"] == pytest.approx(19_800, rel=0.01)
    # The tolerance is inclusive and changes the verdict, not the measured area.
    area = report["outside_area_m2"]
    code, report = _check(zone, detail, capsys, "--area-tolerance-m2", str(area))
    assert (code, report["status"], report["outside_area_m2"], report["area_tolerance_m2"]) == (
        0, "within_tolerance", area, area,
    )


@pytest.mark.parametrize("save_empty", [False, True], ids=["missing-zone", "empty-zone"])
def test_zone_without_geometry_is_unknown_not_zero_or_a_survey_gap(tmp_path, capsys, save_empty):
    # Invariant: no usable zone is unknown. Substituting an empty geometry for
    # the zone would label all detail outside; substituting an empty result
    # would instead report zero and pass the check.
    zone = tmp_path / "zone.geojson"
    if save_empty:
        _save(zone, [])
    detail = _save(tmp_path / "detail.geojson", [WATER], tier="estimated")
    assert _check(zone, detail, capsys) == (2, dict(region=REGION, area_crs="EPSG:3310",
                                                   area_tolerance_m2=0.01, status="unknown",
                                                   outside_area_m2=None,
                                                   reason="empty_zone" if save_empty else "missing_zone"))


@pytest.mark.parametrize("bad_role", ["zone", "detail"])
def test_declared_region_binds_each_input_even_when_geometries_match(tmp_path, capsys, bad_role):
    # Invariant: reject cross-region comparisons. Checking just one declaration
    # (or just their geometry) would allow the other input to come from elsewhere.
    zone = _save(tmp_path / "zone.geojson", [WATER], region="other" if bad_role == "zone" else REGION)
    detail = _save(tmp_path / "detail.geojson", [WATER], region="other" if bad_role == "detail" else REGION,
                   tier="estimated")
    with pytest.raises(SystemExit) as error:
        _check(zone, detail, capsys)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert f"{bad_role}: region does not match" in output.err


def test_invalid_zone_is_not_repaired_or_silently_dropped(tmp_path, capsys):
    # Invariant: do not report against an incomplete or invented zone. Keeping
    # the valid sibling while dropping the self-intersecting polygon would pass.
    bow_tie = Polygon([(-120.002, 36.998), (-119.998, 37.002), (-119.998, 36.998), (-120.002, 37.002)])
    zone = _save(tmp_path / "zone.geojson", [WATER, bow_tie])
    detail = _save(tmp_path / "detail.geojson", [WATER], tier="5m")
    with pytest.raises(SystemExit) as error:
        _check(zone, detail, capsys)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert "zone feature 1: expected valid" in output.err


def test_unknown_detail_tier_does_not_create_a_class(tmp_path, capsys):
    # Invariant: only existing tiers may contribute. Treating every tier as
    # classified (or silently dropping unrecognized tiers) would give a verdict.
    zone = _save(tmp_path / "zone.geojson", [WATER])
    detail = _save(tmp_path / "detail.geojson", [WATER], tier="invented")
    with pytest.raises(SystemExit) as error:
        _check(zone, detail, capsys)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert "detail feature 0: unknown survey detail tier" in output.err
