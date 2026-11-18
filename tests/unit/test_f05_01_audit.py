"""F05-01: historical export depths must agree with native evidence."""
import html
import json
from xml.etree import ElementTree as ET

import pytest

from skippercast.atlas.export import GPX, validate, write_exports


@pytest.fixture
def atlas():
    datum = "unverified source datum"
    url = "https://example.invalid/survey"
    return {
        "schema_version": 1, "fishing_depth_limit_ft": 200,
        "edition": "synthetic", "title": "Synthetic atlas", "coverage": "Fictional survey",
        "sources": [{"id": "synthetic", "datum": datum, "url": url}],
        "targets": [{
            "id": "synthetic-target", "name": "Synthetic target", "label": "Fictional target",
            "longitude": 0, "latitude": 0, "source_id": "synthetic", "source_url": url,
            "vertical_datum": datum, "research_only": True, "depth_qualified": False,
            "metrics": {"relief_210m_m": 0, "rugose_or_bedrock_fraction_210m": 0,
                        "plane_residual_rms_250m_m": 0, "rough_habitat_within_250m_ha": 0},
            "habitat_score": 0, "habitat_grade": "C", "rank": 1,
            "recorded_validation": {"native_circle_has_gap": False, "native_center_depth_ft": 100,
                                    "native_100m_circle_min_depth_ft": 90,
                                    "native_100m_circle_max_depth_ft": 110},
            "center_depth_ft": 100, "neighborhood_depth_ft": [90, 110],
            "area_ids": [], "drift_id": None, "terrain_interpretation": "Fictional relief",
            "ais_status": "AIS unverified", "evidence_status": "Synthetic evidence",
            "confidence": "unknown", "survey_flags": [], "special_note": "No additional note",
            "survey_year": 2000, "legacy_id": "synthetic-legacy",
        }],
        "areas": [], "drifts": [],
    }


@pytest.mark.parametrize("changes", [
    pytest.param({"center_depth_ft": 7, "neighborhood_depth_ft": [5, 8]}, id="audit-reproduction"),
    pytest.param({"center_depth_ft": 7}, id="center-only"),
    pytest.param({"neighborhood_depth_ft": [89, 110]}, id="minimum-only"),
    pytest.param({"neighborhood_depth_ft": [90, 111]}, id="maximum-only"),
    pytest.param({"neighborhood_depth_ft": [90]}, id="missing-endpoint"),
    pytest.param({"neighborhood_depth_ft": [90, float("nan")]}, id="nonfinite-endpoint"),
])
def test_contradiction_fails_before_export(atlas, tmp_path, changes):
    atlas["targets"][0].update(changes)
    with pytest.raises(ValueError):
        validate(atlas)
    output_parent = tmp_path / "not-created"
    with pytest.raises(ValueError):
        write_exports(atlas, output_parent / "exports")
    assert not output_parent.exists()


def test_native_center_outside_its_circle_fails(atlas, tmp_path):
    row = atlas["targets"][0]
    row["recorded_validation"]["native_center_depth_ft"] = row["center_depth_ft"] = 111
    with pytest.raises(ValueError, match="outside.*neighborhood"):
        write_exports(atlas, tmp_path / "not-created" / "exports")
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("center, limits", [(100, [90, 110]), (100.4, [90.8, 109.2])],
                         ids=["whole-foot-rounding", "exact-evidence"])
def test_matching_depth_and_historical_warnings_in_all_formats(atlas, tmp_path, center, limits):
    row = atlas["targets"][0]
    row["recorded_validation"].update(native_center_depth_ft=100.4,
                                      native_100m_circle_min_depth_ft=90.8,
                                      native_100m_circle_max_depth_ft=109.2)
    row.update(center_depth_ft=center, neighborhood_depth_ft=limits)
    output = tmp_path / "exports"
    write_exports(atlas, output)

    notes = []
    for name in ("complete.gpx", "waypoints.gpx"):
        point = ET.parse(output / name).getroot().find(f"{{{GPX}}}wpt")
        assert point is not None
        comment = point.findtext(f"{{{GPX}}}cmt", "")
        assert f"source raster depth {center} ft, datum unverified" in comment
        assert "Research-only" in comment
        notes.append(point.findtext(f"{{{GPX}}}desc", ""))
    geojson = json.loads((output / "atlas.geojson").read_text(encoding="utf-8"))
    notes.append(geojson["features"][0]["properties"]["note"])
    notes.append(html.unescape((output / "spot-notes.html").read_text(encoding="utf-8")))
    for note in notes:
        assert f"Historical source raster depth: center {center} ft; 100-m neighborhood {limits[0]}–{limits[1]} ft." in note
        assert "Vertical datum unverified; this is not a chart-depth or <=200 ft qualification." in note
        assert "Confirm actual depth with an official chart and sounder." in note
