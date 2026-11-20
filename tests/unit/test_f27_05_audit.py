"""F27-05: a truncated CDFW response must be rejected even when it covers the request."""
from datetime import datetime, timezone

import pytest

pytest.importorskip("shapely")
pytest.importorskip("pyproj")

from research.scripts.audit_monterey_300_closures import audit  # noqa: E402

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
URL = ("https://services2.arcgis.com/x/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query"
       "?geometry=-123%2C35%2C-121%2C37&geometryType=esriGeometryEnvelope&inSR=4326"
       "&spatialRel=esriSpatialRelIntersects")


def square(x, y, d=0.001):
    return {"type": "Polygon", "coordinates": [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]}


def region(name, **extra):
    feats = [{"type": "Feature", "properties": {}, "geometry": square(-122.5 + i * 0.1, 36.0)}
             for i in range(8)]
    return {"region_id": name, "features": feats, "checked_at": "2026-11-01T06:00:00Z",
            "source_url": URL, **extra}


def inputs(**extra):
    pixel = {"scope": "monterey-original-pixel-depth-band-audit", "fishing_target": False,
             "outline_count": 1,
             "outlines": [{"context_id": "a", "native_cells_200_300ft_below_navd88": 5}]}
    context = {"features": [{"type": "Feature",
                             "properties": {"id": "a", "fishing_target": False},
                             "geometry": square(-122.0, 36.4)}]}
    mpas = [region("santa-cruz-monterey-bay", **extra), region("monterey-point-sur")]
    geas = [{"type": "Feature", "properties": {"area_type": "GEA"}, "geometry": square(-122.9 + i * 0.01, 35.5)}
            for i in range(10)]
    federal = {"status": "ok", "scope": "noaa-west-coast-groundfish-conservation-areas",
               "source_layers": list(range(25)), "retrieved_at": "2026-11-01T06:00:00Z",
               "features": geas}
    return pixel, context, mpas, federal


def test_complete_control_still_screens():
    pixel, context, mpas, federal = inputs(exceededTransferLimit=False)
    report = audit(pixel, context, mpas, federal, now=NOW)
    assert report["outline_count"] == 1


def test_missing_flag_still_screens():
    pixel, context, mpas, federal = inputs()
    assert audit(pixel, context, mpas, federal, now=NOW)["outline_count"] == 1


def test_truncated_covering_response_is_rejected_despite_eight_features():
    pixel, context, mpas, federal = inputs(exceededTransferLimit=True)
    assert len(mpas[0]["features"]) >= 8
    with pytest.raises(ValueError, match="truncated"):
        audit(pixel, context, mpas, federal, now=NOW)
