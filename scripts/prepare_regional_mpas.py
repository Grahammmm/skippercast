"""Prepare a bounded official CDFW MPA snapshot for one reviewed region.

The first capture is a source-review artifact, not permission to fish. Existing
snapshots are immutable unless the caller explicitly requests a replacement;
the separate closure verifier compares a reviewed snapshot with the live source.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query"


def source_url(bounds: list[float]) -> str:
    return BASE + "?" + urlencode({
        "where": "1=1",
        "geometry": ",".join(str(value) for value in bounds),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "NAME,FULLNAME,Type,CCR",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    })


def validate_response(data: dict, bounds: list[float], minimum: int,
                      allowed_repairs: tuple[str, ...] = ()) -> list[dict]:
    if data.get("type") != "FeatureCollection" or data.get("exceededTransferLimit"):
        raise ValueError("CDFW MPA response is incomplete or not GeoJSON")
    features = data.get("features")
    if not isinstance(features, list) or len(features) < minimum:
        raise ValueError("Too few CDFW MPAs for this reviewed regional envelope")
    region = box(*bounds)
    seen = set()
    for feature in features:
        properties = feature.get("properties") or {}
        name = properties.get("NAME")
        geom = shape(feature.get("geometry"))
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ValueError("CDFW MPA identity missing or duplicated")
        if not geom.is_valid and name in allowed_repairs and geom.geom_type == "MultiPolygon":
            # Some CDFW GeoJSON exports serialize nested polygon shells as
            # overlapping MultiPolygon members. Unioning every original member
            # retains its entire prohibited footprint, including the nested
            # member, rather than turning it into a hole or dropping it.
            members = list(geom.geoms)
            if not members or any(not member.is_valid or member.is_empty for member in members):
                raise ValueError("CDFW MPA repair has invalid original components")
            repaired = unary_union(members)
            if (not repaired.is_valid or repaired.is_empty
                    or repaired.geom_type not in ("Polygon", "MultiPolygon")
                    or any(not repaired.covers(member) for member in members)):
                raise ValueError("CDFW MPA conservative union did not preserve every component")
            feature["geometry"] = mapping(repaired)
            feature["properties"]["geometry_repair"] = "conservative_union_of_original_components"
            feature["properties"]["original_component_count"] = len(members)
            geom = repaired
        if geom.geom_type not in ("Polygon", "MultiPolygon") or not geom.is_valid or geom.is_empty:
            raise ValueError("CDFW MPA polygon invalid")
        if not geom.intersects(region):
            raise ValueError("CDFW returned an MPA outside the requested region")
        seen.add(name)
    return features


def prepare(region_id: str, *, replace_after_review: bool = False) -> dict:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", region_id):
        raise ValueError("Invalid region ID")
    config = json.loads((ROOT / "regions" / region_id / "region.json").read_text())
    if config.get("id") != region_id:
        raise ValueError("Region identity mismatch")
    expected = f"regions/{region_id}/protected-areas.geojson"
    if config.get("assets", {}).get("protected_areas") != expected:
        raise ValueError("Region must bind its own bounded protected-area asset")
    destination = ROOT / "dist" / expected
    if destination.exists() and not replace_after_review:
        raise ValueError("Existing reviewed MPA snapshot; use the verifier or explicit replacement review")
    bounds = config["mpa"]["bounds"]
    minimum = config["mpa"]["minimum_features"]
    url = source_url(bounds)
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast regional MPA source review"}), timeout=45) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("CDFW MPA source redirected or failed")
        raw = response.read(6_000_001)
    if not raw or len(raw) > 6_000_000:
        raise ValueError("CDFW MPA source empty or oversized")
    data = json.loads(raw)
    features = validate_response(data, bounds, minimum,
                                 tuple(config["mpa"].get("conservative_union_invalid_names", [])))
    data.update({
        "region_id": region_id,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_url": url,
        "verification_sha256": hashlib.sha256(raw).hexdigest(),
        "screening_policy": "Conservatively exclude every mapped CDFW MPA from fishing targets and exports; exceptions require separate legal review.",
    })
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n")
    return {"region_id": region_id, "features": len(features), "names": [f["properties"]["NAME"] for f in features], "path": str(destination)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True)
    parser.add_argument("--replace-after-review", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.region, replace_after_review=args.replace_after_review)))
