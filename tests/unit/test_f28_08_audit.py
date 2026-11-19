"""Offline controls for a Point Conception searched-zero camera receipt."""
import hashlib
from io import BytesIO
import json
import zipfile

import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis


@pytest.fixture
def camera_inputs(tmp_path, monkeypatch):
    import shapefile
    from shapely.geometry import box
    from research.scripts import audit_point_conception_4m_camera_gap as camera

    manifest = {
        "schema_version": 1,
        "catalog_url": "https://example.invalid/catalog.html",
        "base_url": "https://example.invalid/archives/",
        "archives": {},
    }
    shp, shx, dbf = BytesIO(), BytesIO(), BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POINT) as writer:
        writer.field("MAJOR_GEO", "C")
        writer.point(-123, 0)  # Synthetic point, far from both test rectangles.
        writer.record("rock")
    for cruise in ("fixture-one", "fixture-two"):
        path = tmp_path / f"{cruise}_video_observations.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for suffix, stream in (("shp", shp), ("shx", shx), ("dbf", dbf)):
                archive.writestr(f"{cruise}.{suffix}", stream.getvalue())
            archive.writestr(f"{cruise}.prj", "WGS 84")
            archive.writestr(f"{cruise}_metadata.txt",
                             "Horizontal_Positional_Accuracy_Report: highly variable, about 10 meters")
        manifest["archives"][cruise] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    monkeypatch.setattr(camera, "REVIEWED_INVENTORY_SHA256", digest, raising=False)
    candidates = [("H11952", 296, box(0, 0, 16, 296)), ("H11953", 226, box(16, 0, 32, 226))]
    return camera, manifest, candidates


@pytest.mark.parametrize("missing", ["all-cruises", "one-cruise", "one-component", "duplicate-component"])
def test_camera_does_not_emit_a_zero_for_incomplete_inputs(tmp_path, camera_inputs, missing):
    # F28-08: a partial loop used to emit a zero and claim full catalog coverage.
    camera, manifest, candidates = camera_inputs
    if missing == "all-cruises":
        manifest["archives"].clear()
    elif missing == "one-cruise":
        manifest["archives"].pop("fixture-two")
    elif missing == "one-component":
        candidates.pop()
    else:
        candidates[1] = candidates[0]
    with pytest.raises(ValueError, match="incomplete or changed"):
        camera.audit(manifest, tmp_path, candidates)


@pytest.mark.parametrize("change", [None, "no-sources", "one-source", "same-size-wrong-hash",
                                    "no-components", "one-component", "missing-count", "detection"])
def test_lineage_only_accepts_a_complete_searched_zero(tmp_path, monkeypatch, camera_inputs, change):
    # Exercise the on-disk reader at its gap gate, not the unrelated BAG/report processing.
    from research.scripts import audit_point_conception_4m_lineage as lineage

    camera, manifest, candidates = camera_inputs
    receipt = camera.audit(manifest, tmp_path, candidates)
    assert [(row["cruise"], row["records"]) for row in receipt["sources"]] == [
        ("fixture-one", 1), ("fixture-two", 1),
    ]
    assert {row["survey_id"]: row["bottom_observations_inside_component"]
            for row in receipt["components"]} == {"H11952": 0, "H11953": 0}
    assert all(row["camera_verified_bottom"] is False for row in receipt["components"])
    if change == "no-sources":
        receipt["sources"].clear()
    elif change == "one-source":
        receipt["sources"].pop()
    elif change == "same-size-wrong-hash":
        receipt["sources"][1]["sha256"] = receipt["sources"][0]["sha256"]
    elif change == "no-components":
        receipt["components"].clear()
    elif change == "one-component":
        receipt["components"].pop()
    elif change == "missing-count":
        receipt["components"][0]["bottom_observations_inside_component"] = None
    elif change == "detection":
        receipt["components"][0]["bottom_observations_inside_component"] = 1
    for name, payload in {
        "dist/data/point-conception-original-4m-rugged-overlap.json": {},
        "research/catalog/usgs-video-cruises.json": manifest,
        "research/receipts/point-conception-original-4m-camera-gap.json": receipt,
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))

    class ReachedTerrainProcessing(Exception):
        pass

    def terrain(*_):
        raise ReachedTerrainProcessing

    monkeypatch.setattr(lineage, "ROOT", tmp_path)
    monkeypatch.setattr(lineage, "candidate_footprints", terrain)
    expected = ReachedTerrainProcessing if change is None else ValueError
    with pytest.raises(expected):
        lineage.audit(tmp_path, tmp_path, tmp_path)


def test_checked_in_receipt_matches_the_reviewed_inventory_and_components():
    # Guard compatibility with the untouched receipt used by the dispatch workflow's --verify.
    from research.scripts import audit_point_conception_4m_camera_gap as camera

    manifest = json.loads((ROOT / "research/catalog/usgs-video-cruises.json").read_text())
    receipt = json.loads((ROOT / "research/receipts/point-conception-original-4m-camera-gap.json").read_text())
    camera.require_searched_zero(receipt, manifest)
