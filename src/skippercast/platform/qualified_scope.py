"""Validate an immutable measured subset without promoting a whole coastline.

This publication check binds reviewed inputs, compiler receipts, footprints and
bottom views to one release. Dated closure receipts prove the compilation input
only; the app still requires its independent fresh closure and season screen.
"""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import math
from pathlib import Path
import re

from .bottom_targets import VERSION, source_url_allowed, target_prefix
from .contracts import read_json, within, load_catalogs


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, minimum=0, maximum=math.inf):
    return (type(value) in (int, float) and math.isfinite(value)
            and minimum <= value <= maximum)


def _identity(value, region_id, label):
    _require(type(value.get("schema_version")) is int and value["schema_version"] == 1
             and value.get("region_id") == region_id, f"Wrong schema or region: {label}")


def _indexed(items, key, label):
    _require(isinstance(items, list), f"Missing {label}")
    result = {}
    for item in items:
        ident = item.get(key)
        _require(isinstance(ident, str) and ident and ident not in result, f"Invalid or duplicate {label}")
        result[ident] = item
    return result


def _timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(parsed.tzinfo is not None, "Compilation receipts need explicit time zones")


def _held_original_surveys(root):
    path = root / "catalog" / "noaa-survey-lead-holds.json"
    _require(path.is_file(), "Reviewed original-survey hold registry is missing")
    registry = read_json(path)
    _require(registry.get("schema_version") == 1
             and registry.get("scope") == "reviewed-noaa-survey-fishing-lead-holds"
             and isinstance(registry.get("holds"), list), "Invalid original-survey hold registry")
    held = set()
    for row in registry["holds"]:
        ident = row.get("survey_id")
        _require(isinstance(ident, str) and re.fullmatch(r"[A-Z][0-9]{5}", ident)
                 and ident not in held
                 and row.get("disposition") == "withhold_from_fishing_promotion"
                 and isinstance(row.get("reason"), str) and row["reason"]
                 and isinstance(row.get("report_sha256"), str)
                 and re.fullmatch(r"[a-f0-9]{64}", row["report_sha256"]),
                 "Invalid reviewed original-survey hold")
        held.add(ident)
    return held


def _require_unheld_original_source(url, held_surveys):
    match = re.search(r"/([A-Z][0-9]{5})/BAG/", url)
    _require(not match or match.group(1) not in held_surveys,
             "Reviewed original NOAA survey is held from fishing promotion")


def _digest(path, receipt=None):
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if receipt is not None:
        _require(type(receipt.get("bytes")) is int and len(content) == receipt["bytes"]
                 and digest == receipt.get("sha256"), "Survey subset artifact integrity mismatch")
    return digest


def _polygons(geometry):
    """Finite, closed WGS84 polygons; no point or centroid substitutes."""
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    _require(kind in ("Polygon", "MultiPolygon") and isinstance(coordinates, list) and coordinates,
             "Qualified and closure geometry must contain full polygons")
    polygons = [coordinates] if kind == "Polygon" else coordinates
    for polygon in polygons:
        _require(isinstance(polygon, list) and polygon, "Polygon has no rings")
        for ring in polygon:
            _require(isinstance(ring, list) and len(ring) >= 4 and ring[0] == ring[-1],
                     "Polygon ring is not closed")
            for point in ring:
                _require(isinstance(point, (list, tuple)) and len(point) == 2
                         and _number(point[0], -180, 180) and _number(point[1], -90, 90),
                         "Polygon needs finite WGS84 coordinates")
            _require(len({tuple(p) for p in ring}) >= 3, "Degenerate polygon ring")
    return polygons


def _on_segment(point, a, b):
    return (abs((point[0] - a[0]) * (b[1] - a[1]) - (point[1] - a[1]) * (b[0] - a[0])) <= 1e-12
            and min(a[0], b[0]) - 1e-10 <= point[0] <= max(a[0], b[0]) + 1e-10
            and min(a[1], b[1]) - 1e-10 <= point[1] <= max(a[1], b[1]) + 1e-10)


def _in_ring(point, ring):
    inside = False
    x, y = point
    for a, b in zip(ring, ring[1:]):
        if _on_segment(point, a, b):
            return 2
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return int(inside)


def _inside(point, polygons):
    for polygon in polygons:
        outer = _in_ring(point, polygon[0])
        if outer == 2:
            return True
        if outer:
            holes = [_in_ring(point, ring) for ring in polygon[1:]]
            if 2 in holes or not any(holes):
                return True
    return False


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a, b, c, d):
    if (_on_segment(a, c, d) or _on_segment(b, c, d)
            or _on_segment(c, a, b) or _on_segment(d, a, b)):
        return True
    return _cross(a, b, c) * _cross(a, b, d) < 0 and _cross(c, d, a) * _cross(c, d, b) < 0


def _bounds(polygons):
    points = [p for polygon in polygons for ring in polygon for p in ring]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def _intersects(a, b):
    ax, ay, az, aw = _bounds(a)
    bx, by, bz, bw = _bounds(b)
    if az < bx or bz < ax or aw < by or bw < ay:
        return False
    ar = [ring for polygon in a for ring in polygon]
    br = [ring for polygon in b for ring in polygon]
    if any(_inside(p, b) for ring in ar for p in ring) or any(_inside(p, a) for ring in br for p in ring):
        return True
    return any(_segments_intersect(p, q, r, s) for ring in ar for p, q in zip(ring, ring[1:])
               for other in br for r, s in zip(other, other[1:]))


def _within_bounds(polygons, bounds):
    west, south, east, north = bounds
    a, b, c, d = _bounds(polygons)
    return west <= a <= c <= east and south <= b <= d <= north


def _qualification(record, config):
    q = record["qualification"]
    _require(q.get("policy") == VERSION and q.get("native_datum") == "MLLW"
             and q.get("full_geometry_screened") is True and q.get("verified_catches") is False,
             "Target lacks a complete native-depth qualification")
    for key, setting in (("planning_margin_m", "planning_margin_m"),
                         ("maximum_product_uncertainty_m", "maximum_product_uncertainty_m"),
                         ("closure_clearance_m", "closure_clearance_m"),
                         ("native_resolution_limit_m", "maximum_native_cell_m")):
        _require(_number(q.get(key)) and q[key] == config[setting], "Target qualification policy changed")
    maximum = q.get("max_depth_including_uncertainty_and_margin_ft")
    _require(_number(maximum, config["minimum_depth_ft"], config["depth_limit_ft"])
             and type(q.get("source_cell_count_in_outline")) is int and q["source_cell_count_in_outline"] > 0,
             "Target exceeds its native depth or source-cell qualification")
    recorded = record["recorded_validation"]
    _require(recorded.get("datum") == "MLLW" and recorded.get("missing_depth") is False,
             "Target native datum or valid-depth evidence is missing")
    minimum, measured_maximum = recorded.get("minimum_ft"), recorded.get("maximum_ft")
    _require(_number(minimum, config["minimum_depth_ft"], config["depth_limit_ft"])
             and _number(measured_maximum, minimum, config["depth_limit_ft"])
             and maximum + .001 >= measured_maximum + config["planning_margin_m"] / .3048
             and _number(recorded.get("closure_clearance_m"), config["closure_clearance_m"]),
             "Native depth or closure evidence contradicts qualification")


def qualified_subset_satisfies(report, qualification):
    """Only the two physical coverage gaps can be replaced by this subset."""
    gate = report.get("capabilities", {}).get("surveyed-bottom-targets", {})
    protected = next((n for n in report.get("needs", []) if n.get("id") == "protected-areas"), {})
    return (isinstance(qualification, dict) and qualification.get("ready") is True
            and qualification.get("complete_region_coverage") is False
            and protected.get("status") == "ready" and bool(protected.get("approved_sources"))
            and isinstance(gate.get("gaps"), list)
            and set(gate["gaps"]) <= {"bathymetry", "substrate"})


def validate_qualified_scope(region, atlas, root, *, bottom_index=None):
    """Return limited readiness, or fail closed on an inconsistent release."""
    if not region.get("assets", {}).get("target_qualification"):
        return None
    try:
        return _validate(region, atlas, Path(root), bottom_index=bottom_index)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("Incomplete or malformed qualified subset release") from exc


def _validate(region, atlas, root, *, bottom_index=None):
    ident = region["id"]
    asset = region["assets"]["target_qualification"]
    _require(asset.startswith(f"regions/{ident}/"), "Qualification must belong to its region")
    manifest_path = within(root / "dist", asset)
    manifest = read_json(manifest_path)
    _identity(manifest, ident, "manifest")
    _require(manifest.get("status") == "ready" and manifest.get("transformation_version") == VERSION,
             "Unqualified survey subset manifest")
    _timestamp(manifest["generated_at"])
    names = {"atlas.json", "quality.json", "bottom-index-fragment.json"}
    _require(set(manifest["artifacts"]) == names, "Unexpected qualification artifacts")
    artifacts = {}
    for name in names:
        path = within(manifest_path.parent, name)
        _digest(path, manifest["artifacts"][name])
        artifacts[name] = read_json(path)
        _identity(artifacts[name], ident, name)
    quality, fragment, views = (artifacts[n] for n in ("quality.json", "atlas.json", "bottom-index-fragment.json"))
    _identity(atlas, ident, "published atlas")
    _require(quality.get("status") == "qualified-partial" and quality.get("transformation_version") == VERSION
             and fragment.get("edition") == VERSION, "Subset method or scope changed")
    claims = quality["claims"]
    _require(claims.get("measured_datum") == "MLLW" and claims.get("depth_qualified") is True
             and all(claims.get(k) is False for k in ("catch_calibrated", "boulder_size_measured", "complete_island_coverage")),
             "Subset must preserve its limited, uncalibrated claims")
    config_path = root / "regions" / ident / "bottom-sources.reviewed.json"
    _require(_digest(config_path) == quality["config_sha256"], "Survey subset review changed; rebuild required")
    config = read_json(config_path)
    _identity(config, ident, "reviewed config")
    _require(config.get("status") == "reviewed", "Survey source configuration is not reviewed")
    prefix = target_prefix(config)
    for key in ("depth_limit_ft", "minimum_depth_ft", "planning_margin_m", "maximum_product_uncertainty_m",
                "maximum_native_cell_m", "closure_clearance_m"):
        _require(_number(config.get(key)) and config[key] > 0, "Invalid reviewed qualification policy")
    _require(config["minimum_depth_ft"] < config["depth_limit_ft"] <= region["boat"]["bottom_depth_limit_ft"]
             and config["maximum_native_cell_m"] <= 4
             and fragment["fishing_depth_limit_ft"] == config["depth_limit_ft"], "Unsupported subset depth or resolution policy")
    habitat_path = within(root, config["habitat_path"])
    _require(_digest(habitat_path) == config["habitat_sha256"] == quality["habitat_sha256"],
             "Survey substrate input changed; rebuild required")
    _identity(read_json(habitat_path), ident, "substrate input")
    _, catalog = load_catalogs(root)
    protected = region["source_bindings"].get("protected-areas", [])
    _require(region.get("coverage", {}).get("protected-areas", {}).get("status") == "ready"
             and any(catalog[s]["review_status"] == "approved" for s in protected),
             "Protected-area coverage and an approved binding remain mandatory")
    specs = _indexed(config["sources"], "id", "reviewed source")
    _require(bool(specs) and len({s.lower() for s in specs}) == len(specs), "Empty or ambiguous reviewed sources")
    held_surveys = _held_original_surveys(root)
    for spec in specs.values():
        _require_unheld_original_source(spec.get("url", ""), held_surveys)
    receipts = _indexed(quality["source_receipts"], "url", "source receipt")
    _require(set(receipts) == {s["url"] for s in specs.values()}, "Subset source receipts differ from reviewed sources")
    expected_sources = []
    expected_index_sources = {}
    for source_id, spec in specs.items():
        source = catalog.get(source_id.lower(), {})
        _require(source_id.lower() in region["source_bindings"].get("bathymetry", [])
                 and source.get("review_status") == "approved" and source.get("adapter") == "noaa-native-vr-bag"
                 and source.get("pinned_sha256") == spec["sha256"] and source.get("access_url") == spec["url"]
                 and source.get("vertical_datum") == spec.get("vertical_datum") == "MLLW"
                 and source.get("qualified_resolution_limit_m") == spec.get("qualification_resolution_limit_m") == config["maximum_native_cell_m"],
                 "Unreviewed, unbound or differently pinned qualified survey source")
        _require(source_url_allowed(spec["url"]) and re.fullmatch(r"[a-f0-9]{64}", spec["sha256"])
                 and type(spec.get("bytes")) is int and 0 < spec["bytes"] <= 160_000_000,
                 "Invalid reviewed source identity")
        receipt = receipts[spec["url"]]
        _require(receipt.get("sha256") == spec["sha256"] and type(receipt.get("bytes")) is int
                 and receipt["bytes"] == spec["bytes"] and receipt.get("http_status") in (200, 206),
                 "Native source acquisition receipt mismatch")
        _timestamp(receipt["retrieved_at"])
        expected_sources.append({**spec, "url": spec["documentation_url"], "native_data_url": spec["url"],
                                 "survey_year": int(spec["survey_start"][:4]), "datum": "MLLW"})
        expected_index_sources[source_id] = {"source_id": source_id, "sha256": spec["sha256"], "url": spec["url"],
                                              "survey_year": int(spec["survey_start"][:4]), "vertical_datum": "MLLW"}
    _require(quality["sources"] == fragment["sources"] == expected_sources
             and views["sources"] == expected_index_sources, "Subset source provenance changed")
    expected_closures = {"dist/" + region["assets"][key] for key in ("protected_areas", "closures") if region["assets"].get(key)}
    closure_inputs = _indexed(config["closure_inputs"], "path", "reviewed closure input")
    closure_receipts = _indexed(quality["closure_receipts"], "path", "closure receipt")
    _require(expected_closures and set(closure_inputs) == set(closure_receipts) == expected_closures,
             "Subset closure scope differs from regional closures")
    closed = []
    for path, receipt in closure_receipts.items():
        source_path = within(root, path)
        _require(_digest(source_path) == receipt["sha256"], "Survey subset closure geometry changed; rebuild required")
        data = read_json(source_path)
        minimum = closure_inputs[path]["minimum_features"]
        _require(type(minimum) is int and minimum > 0 and data.get("region_id") == ident
                 and data.get("type") == "FeatureCollection" and isinstance(data.get("features"), list)
                 and len(data["features"]) >= minimum and type(receipt.get("features")) is int
                 and receipt["features"] == len(data["features"])
                 and receipt.get("checked_at") == data.get("checked_at")
                 and receipt.get("source_url") == data.get("source_url"), "Incomplete or wrong-region closure receipt")
        _timestamp(data["checked_at"])  # Provenance, never an assertion of current clearance.
        closed.extend(_polygons(f["geometry"]) for f in data["features"])
    for key in ("targets", "areas", "drifts"):
        _require(fragment[key] == atlas[key], "Published target/area/drift geometry differs from the qualified subset")
    _require(fragment["drifts"] == [], "This qualification method does not authorize drift lines")
    targets, areas = (_indexed(fragment[k], "id", k) for k in ("targets", "areas"))
    _require(targets and set(views["views"]) == set(targets), "Missing or extra qualified bottom views")
    for key, count in (("target_count", len(targets)), ("area_count", len(areas)), ("bottom_views", len(targets))):
        _require(type(quality.get(key)) is int and quality[key] == count, "Inconsistent qualified subset count")
    index = bottom_index if bottom_index is not None else read_json(within(root / "dist", region["assets"]["bottom_index"]))
    _identity(index, ident, "published bottom index")
    used_areas = set()
    for target_id, target in targets.items():
        _require(re.fullmatch(re.escape(prefix) + r"-[a-f0-9]{10}", target_id), "Target identity differs from reviewed prefix")
        spec = specs[target["source_id"]]
        _qualification(target, config)
        _require(all(target.get(key) is True for key in ("depth_qualified", "fishing_target", "fishing_export"))
                 and target.get("vertical_datum") == "MLLW" and target.get("drift_id") is None
                 and target.get("rating", {}).get("catch_probability") is None
                 and target["rating"].get("score_type") == "uncalibrated-habitat-rank",
                 "Target publication or catch claim differs from the reviewed method")
        resolution = target["native_resolution_range_m"]
        _require(len(resolution) == 2 and _number(resolution[0], .01, config["maximum_native_cell_m"])
                 and _number(resolution[1], resolution[0], config["maximum_native_cell_m"])
                 and _number(target["analysis_cell_m"], resolution[1], 4), "Target overstates native resolution")
        point = [target["longitude"], target["latitude"]]
        _require(_number(point[0], -180, 180) and _number(point[1], -90, 90), "Invalid target coordinate")
        expected_area = prefix + "-AREA-" + target_id.rsplit("-", 1)[1]
        _require(target["area_ids"] == [expected_area], "Target lacks its exact qualified footprint")
        area = areas[expected_area]
        _require(area["target_ids"] == [target_id] and area["source_id"] == target["source_id"]
                 and area["qualification"] == target["qualification"], "Target/area qualification differs")
        _qualification(area, config)
        polygons = _polygons(area["geometry"])
        _require(_inside(point, polygons) and _within_bounds(polygons, region["fishing_bounds"])
                 and _within_bounds(polygons, catalog[target["source_id"].lower()]["bounds"]),
                 "Target footprint or center escapes its reviewed geographic extent")
        _require(not any(_intersects(polygons, closure) for closure in closed), "Qualified footprint intersects a protected or excluded area")
        used_areas.add(expected_area)
        record = views["views"][target_id]
        _require(record == index["views"].get(target_id) and record.get("status") == "surveyed"
                 and record.get("source_id") == target["source_id"]
                 and record.get("path") == f"regions/{ident}/bottom/{target_id}.json", "Published bottom view differs from its qualified target")
        tile_path = within(root / "dist", record["path"])
        _digest(tile_path, record)
        tile = read_json(tile_path)
        _identity(tile, ident, "bottom view")
        _require(tile.get("target_id") == target_id and tile.get("source_id") == spec["id"]
                 and tile.get("source_sha256") == spec["sha256"] and tile.get("source_url") == spec["documentation_url"]
                 and tile.get("vertical_datum") == "MLLW" and tile.get("horizontal_crs") == spec["horizontal_crs"]
                 and tile.get("depth_qualified") is True and tile.get("fishing_target") is True,
                 "Bottom view source, target or datum identity mismatch")
        _require(type(tile.get("width")) is int and 1 <= tile["width"] <= 1025
                 and type(tile.get("height")) is int and 1 <= tile["height"] <= 1025
                 and tile.get("encoding") == "base64-int16-le" and tile.get("nodata") == -32768
                 and _number(tile.get("cell_m"), config["maximum_native_cell_m"], 4)
                 and _number(tile.get("native_cell_m"), .01, config["maximum_native_cell_m"])
                 and _number(tile.get("elevation_unit_m"), .001, 1)
                 and _number(tile.get("coverage_fraction"), 0, 1)
                 and tile["coverage_fraction"] == record["coverage_fraction"], "Unsupported bottom-view raster contract")
        _require(len(base64.b64decode(tile["elevations"], validate=True)) == tile["width"] * tile["height"] * 2,
                 "Bottom view raster is incomplete")
    _require(used_areas == set(areas), "Orphan qualified footprint")
    return {"ready": True, "scope": "Only the explicitly qualified survey footprints", "target_count": len(targets),
            "complete_region_coverage": False, "method": VERSION, "manifest": asset,
            "current_legal_clearance": False, "runtime_closure_screen_required": True}
