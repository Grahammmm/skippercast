"""Launch points: the ramps, hoists and beach launches a trip starts from.

``catalog/launch-points.json`` lists them for every region with a source record
each; this compiles ``dist/regions/<id>/launch-points.json`` per published
region (an empty list for regions with none yet) and refuses a point that lies
outside its region, names an unknown forecast point, or repeats an id.
"""
import math

from .contracts import atomic_json, read_json

EARTH_NM = 3440.065


def distance_nm(a_lat, a_lon, b_lat, b_lon):
    """Great-circle distance in nautical miles (haversine)."""
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    d_lat, d_lon = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(d_lat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_NM * math.asin(math.sqrt(h))


def validate_launch_point(point, region, sources):
    west, south, east, north = region["bounds"]
    if point["region"] != region["id"]:
        raise ValueError(f"Launch point {point['id']} belongs to {point['region']}, not {region['id']}")
    if not (west <= point["longitude"] <= east and south <= point["latitude"] <= north):
        raise ValueError(f"Launch point {point['id']} lies outside the {region['id']} bounds")
    dep = point["departure"]
    if not (west <= dep["longitude"] <= east and south <= dep["latitude"] <= north):
        raise ValueError(f"Launch point {point['id']} departure lies outside the {region['id']} bounds")
    if distance_nm(point["latitude"], point["longitude"], dep["latitude"], dep["longitude"]) > 5:
        raise ValueError(f"Launch point {point['id']} departure is more than 5 nm from the facility")
    if not any(p["id"] == point["forecast_point"] for p in region["forecast_points"]):
        raise ValueError(f"Launch point {point['id']} names an unknown forecast point {point['forecast_point']}")
    if point["source"] not in sources:
        raise ValueError(f"Launch point {point['id']} cites an unlisted source {point['source']}")


def compile_launch_points(root, regions):
    """Write one launch-points file per region in ``regions`` (loaded region dicts)."""
    catalog = read_json(root / "catalog/launch-points.json")
    by_region = {}
    seen = set()
    for point in catalog["launch_points"]:
        if point["id"] in seen:
            raise ValueError(f"Duplicate launch point id {point['id']}")
        seen.add(point["id"])
        by_region.setdefault(point["region"], []).append(point)
    known = {r["id"] for r in regions}
    for region_id in by_region:
        if region_id not in known:
            raise ValueError(f"Launch points list an unknown or draft region {region_id}")
    outputs = {}
    for region in regions:
        points = sorted(by_region.get(region["id"], []), key=lambda p: p["id"])
        for point in points:
            validate_launch_point(point, region, catalog["sources"])
        used = sorted({p["source"] for p in points})
        document = {
            "schema_version": 1,
            "region_id": region["id"],
            "note": catalog["description"],
            "sources": {k: catalog["sources"][k] for k in used},
            "launch_points": points,
        }
        outputs[region["id"]] = atomic_json(root / "dist/regions" / region["id"] / "launch-points.json", document, kind="launch-points")
    return outputs
