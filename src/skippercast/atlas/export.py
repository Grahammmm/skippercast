"""Export the public habitat atlas to GPX, GeoJSON, and an offline notes page."""

import argparse
from collections import Counter
import hashlib
import html
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET

from skippercast.atlas.scoring import habitat_grade, habitat_score

GPX = "http://www.topografix.com/GPX/1/1"
ET.register_namespace("", GPX)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def coordinate(value):
    require(isinstance(value, (list, tuple)) and len(value) == 2,
            "A coordinate must be [longitude, latitude]")
    lon, lat = value
    require(all(isinstance(x, (int, float)) and not isinstance(x, bool)
                and math.isfinite(x) for x in value), "Invalid coordinate")
    require(-180 <= lon <= 180 and -90 <= lat <= 90, "Coordinate outside WGS84 bounds")


def index_unique(rows, label):
    result = {r["id"]: r for r in rows}
    require(len(result) == len(rows), f"Duplicate {label} IDs")
    return result


def validate(data):
    """Check data consistency and recorded evidence; do not revalidate the sea floor."""
    require(data["schema_version"] == 1, "Unsupported atlas schema")
    require(data["fishing_depth_limit_ft"] == 200, "This edition uses a 200-foot ceiling")
    sources = index_unique(data["sources"], "source")
    targets = index_unique(data["targets"], "target")
    areas = index_unique(data["areas"], "area")
    drifts = index_unique(data["drifts"], "drift")
    require(bool(targets), "An atlas must contain targets")
    scores = [r["habitat_score"] for r in targets.values()]
    for row in targets.values():
        coordinate([row["longitude"], row["latitude"]])
        require(row["source_id"] in sources, "Unknown target source")
        score = habitat_score(row["metrics"])
        require(row["habitat_score"] == score, "Stored habitat score disagrees with metrics")
        require(row["habitat_grade"] == habitat_grade(score), "Stored habitat grade disagrees")
        require(row["rank"] == 1 + sum(s > score for s in scores), "Incorrect subset rank")
        check = row["recorded_validation"]
        require(check["native_circle_has_gap"] is False, "Target has missing native depth evidence")
        require(0 < check["native_center_depth_ft"] <= 200, "Target exceeds source-depth ceiling")
        require(0 < check["native_100m_circle_min_depth_ft"]
                <= check["native_100m_circle_max_depth_ft"] <= 200,
                "Target neighborhood exceeds source-depth ceiling")
        for area_id in row["area_ids"]:
            require(area_id in areas and row["id"] in areas[area_id]["target_ids"],
                    "Broken target-to-area reference")
        if row["drift_id"]:
            require(row["drift_id"] in drifts
                    and drifts[row["drift_id"]]["target_id"] == row["id"],
                    "Broken target-to-drift reference")
    for kind, rows in (("area", areas.values()), ("drift", drifts.values())):
        for row in rows:
            require(row["source_id"] in sources, "Unknown geometry source")
            check = row["recorded_validation"]
            require(check["missing_depth"] is False, "Geometry has incomplete depth evidence")
            require(0 < check["minimum_ft"] <= check["maximum_ft"] <= 195,
                    "Geometry fails recorded conservative source-depth screen")
            require(check["closure_clearance_m"] >= 500,
                    "Geometry fails recorded closure planning margin")
            geometry = row["geometry"]
            if kind == "area":
                require(geometry["type"] == "Polygon", "Area must be a Polygon")
                require(bool(geometry["coordinates"]), "Empty polygon")
                require(bool(row["target_ids"]), "Unlinked area")
                for target_id in row["target_ids"]:
                    require(target_id in targets and row["id"] in targets[target_id]["area_ids"],
                            "Broken area-to-target reference")
                for ring in geometry["coordinates"]:
                    require(len(ring) >= 4 and ring[0] == ring[-1], "Polygon ring must be closed")
                    for point in ring:
                        coordinate(point)
            else:
                require(geometry["type"] == "LineString"
                        and len(geometry["coordinates"]) == 2, "Drift must have two endpoints")
                require(row["target_id"] in targets
                        and targets[row["target_id"]]["drift_id"] == row["id"],
                        "Broken drift-to-target reference")
                require(150 <= row["length_m"] <= 401, "Unexpected drift length")
                for point in geometry["coordinates"]:
                    coordinate(point)
    return {"targets": len(targets), "areas": len(areas), "drifts": len(drifts),
            "grades": dict(sorted(Counter(r["habitat_grade"] for r in targets.values()).items())),
            "validation_scope": "Structure and recorded survey evidence only; no current legal, depth, or navigation clearance."}


def target_note(row, data):
    areas = {a["id"]: a for a in data["areas"]}
    drifts = {d["id"]: d for d in data["drifts"]}
    low, high = row["neighborhood_depth_ft"]
    metrics = row["metrics"]
    parts = [
        f"Habitat search priority {row['habitat_grade']} ({row['habitat_score']}/100); tied rank {row['rank']} of {len(data['targets'])}. Not a catch prediction.",
        row["terrain_interpretation"],
        f"Source depth: center {row['center_depth_ft']} ft; 100-m neighborhood {low}–{high} ft below {row['vertical_datum']}. Confirm actual depth <=200 ft with a sounder.",
        f"Local relief {metrics['relief_210m_m'] / 0.3048:.0f} ft; mapped rough habitat {metrics['rugose_or_bedrock_fraction_210m']:.0%}; usable nearby rough habitat {metrics['rough_habitat_within_250m_ha'] * 2.47105:.1f} acres.",
    ]
    if row["area_ids"]:
        parts.append("Partial reef outlines: " + ", ".join(
            f"{i} ({areas[i]['area_ha'] * 2.47105:.1f} acres)" for i in row["area_ids"])
            + ". These are selected mapped footprints, not entire reefs or individual boulders.")
    else:
        parts.append("No outline selected. Start a sounder search near this habitat candidate.")
    if row["drift_id"]:
        drift = drifts[row["drift_id"]]
        bearing = round(drift["bearing_true_axis_deg"]) % 180
        parts.append(f"{drift['id']}: {drift['length_m']:.0f} m alignment, {bearing:03d}/{bearing + 180:03d} degrees TRUE. Use whichever direction measured drift supports. A 25-m corridor each side was screened in the source survey. This is not an approach or navigation route.")
    else:
        parts.append("No fixed drift alignment selected; establish the drift on the water.")
    parts.extend([row["ais_status"], row["evidence_status"],
                  "Historical charter-ground annotations are not included in the public edition.",
                  f"Habitat confidence: {row['confidence']}."])
    if row["survey_flags"]:
        parts.append("Survey flags: " + ", ".join(map(str, row["survey_flags"])))
    if not row["special_note"].startswith("No additional"):
        parts.append(row["special_note"])
    parts.append(f"Survey: {row['survey_year']}; {row['source_url']}. Legacy ID: {row['legacy_id']}. Edition: {data['edition']}.")
    parts.append("Recheck current rules, closures, weather, and entrance conditions. Source measurements and screening are dated.")
    return "\n".join(parts)


def element(parent, tag, text=None, **attributes):
    child = ET.SubElement(parent, f"{{{GPX}}}{tag}", attributes)
    if text is not None:
        child.text = str(text)
    return child


def gpx_document(data, components):
    root = ET.Element(f"{{{GPX}}}gpx", version="1.1", creator="SkipperCast 0.1.0")
    metadata = element(root, "metadata")
    element(metadata, "name", data["title"])
    element(metadata, "desc", "Dated survey-derived habitat candidates and optional fishing alignments. Source-datum depth screen <=200 ft. Not for passage navigation. Derived from public-domain USGS surveys; credit USGS, CSUMB Seafloor Mapping Lab, and University of California Center for Integrated Spatial Research. Underlying source rights remain unchanged. See repository NOTICE.md for original-material terms.")
    for source in data["sources"]:
        link = element(metadata, "link", href=source["url"])
        element(link, "text", source["id"] + " source survey and metadata")
    if "targets" in components:
        for row in data["targets"]:
            waypoint = element(root, "wpt", lat=f"{row['latitude']:.6f}", lon=f"{row['longitude']:.6f}")
            element(waypoint, "name", row["name"])
            element(waypoint, "cmt", f"Habitat priority {row['habitat_grade']}; source depth {row['center_depth_ft']} ft MLLW; AIS unverified.")
            element(waypoint, "desc", target_note(row, data))
            link = element(waypoint, "link", href=row["source_url"])
            element(link, "text", row["source_id"] + " USGS survey")
            element(waypoint, "sym", "Fishing Area")
            element(waypoint, "type", "Survey-derived habitat candidate")
    if "drifts" in components:
        for row in data["drifts"]:
            route = element(root, "rte")
            element(route, "name", row["id"])
            element(route, "desc", f"Optional structure alignment for {row['target_id']}. {row['basis']} Not a passage route or current forecast.")
            element(route, "type", "Fishing structure alignment")
            for suffix, (lon, lat) in zip(("A", "B"), row["geometry"]["coordinates"]):
                point = element(route, "rtept", lat=f"{lat:.6f}", lon=f"{lon:.6f}")
                element(point, "name", f"{row['id']}-{suffix}")
                element(point, "desc", "End of a fishing alignment, not a safe-passage waypoint.")
    if "areas" in components:
        for row in data["areas"]:
            track = element(root, "trk")
            element(track, "name", row["id"])
            element(track, "desc", row["extent_note"] + " Interior rings are holes in the selected habitat. Not a navigation route.")
            element(track, "type", "Interpreted habitat boundary")
            for ring in row["geometry"]["coordinates"]:
                segment = element(track, "trkseg")
                for lon, lat in ring:
                    element(segment, "trkpt", lat=f"{lat:.6f}", lon=f"{lon:.6f}")
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def geojson_document(data):
    features = []
    for row in data["targets"]:
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
                         "properties": {"id": row["id"], "name": row["name"], "habitat_grade": row["habitat_grade"], "habitat_score": row["habitat_score"], "source_url": row["source_url"], "note": target_note(row, data)}})
    for kind in ("areas", "drifts"):
        for row in data[kind]:
            features.append({"type": "Feature", "geometry": row["geometry"],
                             "properties": {k: v for k, v in row.items() if k != "geometry"}})
    return {"type": "FeatureCollection", "features": features}


def notes_document(data):
    escape = html.escape
    articles = []
    for row in sorted(data["targets"], key=lambda r: (r["rank"], r["id"])):
        text = target_note(row, data)
        articles.append(f'<article id="{escape(row["id"])}"><h2>{escape(row["name"])} · {escape(row["label"])}</h2><p class="coordinates">{row["latitude"]:.6f}, {row["longitude"]:.6f}</p><p>{escape(text).replace(chr(10), "<br>")}</p></article>')
    return f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(data['title'])}</title>
<style>body{{font:17px/1.55 system-ui,sans-serif;max-width:850px;margin:40px auto;padding:0 20px;color:#163747;background:#f7fbfc}}h1,h2{{line-height:1.2}}h2{{font-size:1.2rem}}article{{border-top:1px solid #c4d4dc;padding:20px 0}}input{{font:inherit;padding:12px;width:100%;box-sizing:border-box}}.coordinates{{font-family:monospace}}[hidden]{{display:none}}</style>
<h1>SkipperCast habitat notes</h1><p>{escape(data['coverage'])}</p>
<p>{len(data['targets'])} candidates · {escape(data['edition'])}. Habitat priorities are not catch predictions. Source depths are below MLLW; confirm actual depth and current restrictions. These fishing alignments are not passage routes.</p>
<label for="search">Filter by ID, priority, depth, area, or note</label><input id="search" type="search" placeholder="Example: SC26-001 or priority A">
<p id="count" aria-live="polite">{len(data['targets'])} targets</p>
{''.join(articles)}
<footer><p>Derived from USGS surveys; credits: USGS, CSUMB Seafloor Mapping Lab, and University of California Center for Integrated Spatial Research. Underlying source rights remain unchanged. See the repository NOTICE.md and docs/data-sources.md. No external services or trackers are used on this page.</p></footer>
<script>const search=document.getElementById('search');const articles=[...document.querySelectorAll('article')];search.addEventListener('input',()=>{{const q=search.value.trim().toLowerCase();let n=0;for(const a of articles){{a.hidden=!a.textContent.toLowerCase().includes(q);if(!a.hidden)n++;}}document.getElementById('count').textContent=n+' targets';}});</script></html>'''


def write_exports(data, output):
    summary = validate(data)
    output.mkdir(parents=True, exist_ok=False)
    variants = {"complete.gpx": ("targets", "drifts", "areas"),
                "waypoints.gpx": ("targets",), "drift-lines.gpx": ("drifts",),
                "reef-outlines.gpx": ("areas",)}
    for filename, components in variants.items():
        (output / filename).write_bytes(gpx_document(data, components))
    (output / "atlas.geojson").write_text(json.dumps(geojson_document(data), ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "spot-notes.html").write_text(notes_document(data), encoding="utf-8")
    summary["edition"] = data["edition"]
    summary["files"] = [{"name": p.name, "bytes": p.stat().st_size,
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in sorted(output.iterdir())]
    (output / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "export"])
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.action == "export" and args.output is None:
        parser.error("export requires --output pointing to a new directory")
    try:
        data = json.loads(args.data.read_text(encoding="utf-8"))
        result = validate(data) if args.action == "validate" else write_exports(data, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Atlas operation failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
