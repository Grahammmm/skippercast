"""F05-02: area and drift GeoJSON properties use an allowlist, at both depths."""
import json

import pytest

from skippercast.atlas.export import geojson_document, validate, write_exports

DATUM = "unverified source datum"
URL = "https://example.invalid/survey"


def evidence():
    return {"missing_depth": False, "minimum_ft": 90, "maximum_ft": 110,
            "native_cells": 12, "closure_clearance_m": 900, "datum": DATUM}


@pytest.fixture
def atlas():
    return {
        "schema_version": 1, "fishing_depth_limit_ft": 200,
        "edition": "synthetic", "title": "Synthetic atlas", "coverage": "Fictional survey",
        "sources": [{"id": "synthetic", "datum": DATUM, "url": URL}],
        "targets": [{
            "id": "t1", "name": "Synthetic target", "label": "Fictional target",
            "longitude": 0, "latitude": 0, "source_id": "synthetic", "source_url": URL,
            "vertical_datum": DATUM, "research_only": True, "depth_qualified": False,
            "metrics": {"relief_210m_m": 0, "rugose_or_bedrock_fraction_210m": 0,
                        "plane_residual_rms_250m_m": 0, "rough_habitat_within_250m_ha": 0},
            "habitat_score": 0, "habitat_grade": "C", "rank": 1,
            "recorded_validation": {"native_circle_has_gap": False, "native_center_depth_ft": 100,
                                    "native_100m_circle_min_depth_ft": 90,
                                    "native_100m_circle_max_depth_ft": 110},
            "center_depth_ft": 100, "neighborhood_depth_ft": [90, 110],
            "area_ids": ["a1"], "drift_id": "d1", "terrain_interpretation": "Fictional relief",
            "ais_status": "AIS unverified", "evidence_status": "Synthetic evidence",
            "confidence": "unknown", "survey_flags": [], "special_note": "No additional note",
            "survey_year": 2000, "legacy_id": "synthetic-legacy",
        }],
        "areas": [{
            "id": "a1", "source_id": "synthetic", "source_url": URL, "area_ha": 1.5,
            "target_ids": ["t1"], "extent_note": "Fictional footprint.", "map_resolution_m": 10,
            "outline_simplification_m": 12, "research_only": True,
            "recorded_validation": evidence(),
            "geometry": {"type": "Polygon",
                         "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
        }],
        "drifts": [{
            "id": "d1", "source_id": "synthetic", "target_id": "t1", "length_m": 300,
            "bearing_true_axis_deg": 90.0, "corridor_halfwidth_m": 25,
            "rough_fraction_in_corridor": 0.5, "basis": "Fictional basis.",
            "research_only": True, "recorded_validation": evidence(),
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.003, 0]]},
        }],
    }


def properties(document, prefix):
    return next(f["properties"] for f in document["features"] if f["properties"]["id"].startswith(prefix))


def test_approved_fields_survive(atlas):
    document = geojson_document(atlas)
    area, drift = properties(document, "a"), properties(document, "d")
    for source, shown in ((atlas["areas"][0], area), (atlas["drifts"][0], drift)):
        assert shown == {k: v for k, v in source.items() if k != "geometry"}


@pytest.mark.parametrize("kind,prefix", [("areas", "a"), ("drifts", "d")])
def test_unknown_annotation_is_omitted_at_both_depths(atlas, kind, prefix):
    row = atlas[kind][0]
    row["synthetic_internal_note"] = "SYNTHETIC-TOP"
    row["recorded_validation"]["synthetic_internal_note"] = "SYNTHETIC-NESTED"
    validate(atlas)  # the annotation passes validation, so the exporter must drop it
    shown = properties(geojson_document(atlas), prefix)
    assert "synthetic_internal_note" not in shown
    assert "synthetic_internal_note" not in shown["recorded_validation"]
    assert shown["recorded_validation"] == evidence()


def test_written_geojson_has_no_annotation(atlas, tmp_path):
    atlas["areas"][0]["synthetic_internal_note"] = "SYNTHETIC-TOP"
    atlas["drifts"][0]["recorded_validation"]["synthetic_internal_note"] = "SYNTHETIC-NESTED"
    write_exports(atlas, tmp_path / "out")
    text = (tmp_path / "out" / "atlas.geojson").read_text(encoding="utf-8")
    assert "SYNTHETIC" not in text
    assert json.loads(text)["features"]


@pytest.mark.parametrize("kind", ["areas", "drifts"])
@pytest.mark.parametrize("path", [("recorded_validation", "datum"), ("recorded_validation", "native_cells"),
                                  ("source_id",), ("basis",), ("extent_note",)])
def test_allowed_field_cannot_carry_an_object(atlas, kind, path):
    row = atlas[kind][0]
    if path[-1] in ("basis", "extent_note") and path[-1] not in row:
        pytest.skip("field belongs to the other kind")
    holder = row[path[0]] if len(path) == 2 else row
    holder[path[-1]] = {"synthetic_internal_note": "SYNTHETIC-NESTED"}
    with pytest.raises(ValueError):
        geojson_document(atlas)


def test_target_ids_must_be_a_list_of_scalars(atlas):
    atlas["areas"][0]["target_ids"] = [{"synthetic_internal_note": "SYNTHETIC-NESTED"}]
    with pytest.raises(ValueError):
        geojson_document(atlas)
