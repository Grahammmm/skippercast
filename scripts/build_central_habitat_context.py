"""Build research-only reef context for the Monterey–Point Conception gap.

USGS original seafloor-character patches are preferred where available. PMEP
rocky-reef HAPC is broad compiled context for the Big Sur survey gap. Neither
source establishes a safe fishing position, a 300-foot depth, or fish presence.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[1]
REGIONS = (
    "santa-cruz-monterey-bay", "monterey-point-sur", "big-sur-coast",
    "south-big-sur-san-simeon", "cambria-san-simeon",
)
PMEP = "https://gis.psmfc.org/server/rest/services/PMEP/West_Coast_Nearshore_CMECS_Substrate_Habitat/MapServer/1/query"
TO_METERS = Transformer.from_crs(4326, 32610, always_xy=True).transform
TO_WGS84 = Transformer.from_crs(32610, 4326, always_xy=True).transform


def read(path):
    return json.loads((ROOT / path).read_text())


def pmep_features(bounds):
    params = {
        "where": "NMFS_HAPC='Rocky Reefs' AND (PMEP_Zone LIKE 'Core Zone%' OR PMEP_Zone LIKE 'Seaward Zone%')",
        "geometry": ",".join(map(str, bounds)), "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "outFields":
        "OBJECTID,CMECS_SC_Name,Induration,NMFS_HAPC,PMEP_Zone,Shape_Area",
        "returnGeometry": "true", "outSR": "4326", "geometryPrecision": "6",
        "maxAllowableOffset": "0.001", "f": "geojson",
    }
    url = PMEP + "?" + urlencode(params)
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast public habitat research"}), timeout=90) as response:
        raw = response.read()
    data = json.loads(raw)
    if data.get("type") != "FeatureCollection" or "features" not in data:
        raise ValueError("PMEP feature query failed")
    return data["features"], hashlib.sha256(raw).hexdigest(), url


def build_region(region_id, usgs, usgs_digest):
    region = read(f"regions/{region_id}/region.json")
    existing = region["assets"].get("survey_habitat")
    expected = f"regions/{region_id}/survey-habitat.geojson"
    if region["status"] != "preview" or existing not in (None, expected):
        raise ValueError(f"Unexpected active or already populated region: {region_id}")
    bounds = region["fishing_bounds"]
    clip = transform(TO_METERS, box(*bounds))
    mpa_path = ROOT / "dist" / region["assets"]["protected_areas"]
    mpa_raw = mpa_path.read_bytes()
    mpa = json.loads(mpa_raw)
    if mpa.get("type") != "FeatureCollection" or len(mpa.get("features", [])) < region["mpa"]["minimum_features"]:
        raise ValueError(f"Protected area coverage insufficient: {region_id}")
    if mpa.get("region_id") not in (None, region_id):
        raise ValueError(f"Wrong protected area region: {region_id}")
    closures = unary_union([transform(TO_METERS, shape(f["geometry"])) for f in mpa["features"]]).buffer(102)
    features = []
    if region_id in ("big-sur-coast", "south-big-sur-san-simeon"):
        candidates, source_digest, source_url = pmep_features(bounds)
        source_kind = "PMEP compiled rocky-reef HAPC"
    else:
        candidates = usgs["features"]
        source_digest = usgs_digest
        source_url = usgs.get("source_catalog_url")
        source_kind = "USGS original seafloor-character class 3"
    for item in candidates:
        p = item["properties"]
        if source_kind.startswith("USGS"):
            if p.get("fishing_target") is not False or p.get("exportable") is not False or p.get("depth_qualified") is not False:
                raise ValueError("USGS research patch asserts fishing qualification")
            identifier = p["id"]
            url = p["metadata_url"]
            year = str(p["source_year"])
            code = "USGS seafloor-character class 3 · hard, rugose rock/boulder"
        else:
            if p.get("NMFS_HAPC") != "Rocky Reefs" or not p.get("PMEP_Zone", "").startswith(("Core Zone", "Seaward Zone")):
                raise ValueError("PMEP result exceeds approved habitat zones")
            identifier = f"pmep-hapc-{p['OBJECTID']}"
            url = source_url
            year = "PMEP compiled layer"
            code = f"PMEP {p['PMEP_Zone']} · {p['CMECS_SC_Name']}"
        geometry = item["geometry"]
        if source_kind.startswith("PMEP") and geometry["type"] == "MultiPolygon":
            # The service returns nationwide multipart features even for a
            # regional query. Discard distant parts before geometry repair.
            west, south, east, north = bounds
            local = []
            for polygon in geometry["coordinates"]:
                outer = polygon[0]
                if not outer:
                    continue
                xs = [v[0] for v in outer]
                ys = [v[1] for v in outer]
                if max(xs) >= west and min(xs) <= east and max(ys) >= south and min(ys) <= north:
                    local.append(polygon)
            if not local:
                continue
            geometry = {"type": "MultiPolygon", "coordinates": local}
        geom = shape(geometry)
        if not geom.is_valid and source_kind.startswith("PMEP"):
            geom = make_valid(geom)
        if geom.is_empty or not geom.is_valid:
            raise ValueError(f"Invalid habitat geometry: {identifier}")
        projected = transform(TO_METERS, geom).simplify(4, preserve_topology=True)
        if not projected.intersects(clip):
            continue
        eligible = projected.intersection(clip).difference(closures)
        # A projected rectangular clip can bow slightly outside the original
        # WGS84 extent, so enforce the published region bounds once more.
        eligible = transform(TO_METERS, transform(TO_WGS84, eligible).intersection(box(*bounds)))
        if eligible.is_empty:
            continue
        parts = [eligible] if eligible.geom_type == "Polygon" else list(getattr(eligible, "geoms", []))
        for part_index, part in enumerate(parts):
            minimum_area_m2 = 5_000 if source_kind.startswith("PMEP") else 100
            if part.geom_type != "Polygon" or part.area < minimum_area_m2:
                continue
            display = transform(TO_WGS84, part)
            center = display.representative_point()
            features.append({"type": "Feature", "geometry": mapping(display), "properties": {
                "id": f"{region_id}-{identifier}-{part_index}",
                "name": f"{region['name']} · rocky habitat context {len(features) + 1:03d}",
                "habitat_kind": "rock", "species_ids": ["reef"],
                "latitude": round(center.y, 6), "longitude": round(center.x, 6),
                "bounds": [round(x, 6) for x in display.bounds],
                "area_km2": round(part.area / 1_000_000, 5),
                "source_id": identifier, "source_url": url, "source_date": year,
                "native_source_codes": [code], "vertical_datum": "No qualified local depth attached",
                "depth_qualified": False, "depth_note": "Habitat classification only; the full footprint has not been verified within 300 ft or against a current nautical chart",
                "limitations": "Compiled historical habitat, not a waypoint, fish observation, charter stop or verified rock boundary. PMEP zones are broad depth bands; even the seaward band extends to 100 m (328 ft). MPA polygons were subtracted with a 102 m processing margin, and current closures are screened again on the map. Verify current chart, access, rules and conditions before fishing.",
                "evidence_kind": "historical-habitat-context", "catch_evidence": False,
                "charter_evidence": False, "quality_grade": None, "fishing_target": False,
                "fishing_export": False, "bottom_view": False,
            }})
    if not features:
        raise ValueError(f"No usable habitat context in {region_id}")
    output = {"type": "FeatureCollection", "schema_version": 1,
              "region_id": region_id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "source_kind": source_kind, "source_sha256": source_digest,
              "protected_areas_sha256": hashlib.sha256(mpa_raw).hexdigest(),
              "mpa_margin_m": 102, "depth_qualified": False, "fishing_targets": 0,
              "features": features}
    dest = ROOT / "dist/regions" / region_id / "survey-habitat.geojson"
    dest.write_text(json.dumps(output, separators=(",", ":")) + "\n")
    config_path = ROOT / "regions" / region_id / "region.json"
    config_text = config_path.read_text()
    if existing is None and '"survey_habitat": null' in config_text:
        config_text = config_text.replace('"survey_habitat": null', f'"survey_habitat": "{expected}"', 1)
    elif existing is None:
        needle = f'"search_plans": "regions/{region_id}/search-plans.json"'
        if config_text.count(needle) != 1:
            raise ValueError(f"Cannot locate assets block for {region_id}")
        config_text = config_text.replace(needle, needle + f',\n    "survey_habitat": "{expected}"', 1)
    config_path.write_text(config_text)
    print(region_id, len(features), round(sum(f["properties"]["area_km2"] for f in features), 2), "km²")


def main():
    source = ROOT / "dist/data/usgs-hard-context-central.geojson"
    raw = source.read_bytes()
    usgs = json.loads(raw)
    if usgs.get("scope") != "generalized-statewide-usgs-hard-bottom-context" or usgs.get("coast_id") != "central":
        raise ValueError("Unreviewed USGS context source")
    for region_id in REGIONS:
        build_region(region_id, usgs, hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
