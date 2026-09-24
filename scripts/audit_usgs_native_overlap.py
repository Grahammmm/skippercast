"""Check original camera logs against published native NOAA/USGS context polygons.

This is a historical source-consistency check, not a fishing-point generator.
Camera position is described by USGS as highly variable, on the order of 10 m.
Only observations at least 25 m inside a generalized display polygon may be
shown as interior bottom evidence. Consecutive windows on one transect remain
one transect, never ten independent surveys.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import re
import zipfile

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from audit_usgs_video_observations import first_field, load_archive, open_original_zip


CONTEXTS = (
    "cape-mendocino-native-hard-context.geojson",
    "sf-native-hard-context.geojson",
    "point-conception-native-hard-context.geojson",
    "gaviota-native-hard-context.geojson",
)
MIN_INTERIOR_M = 25


def camera_accuracy(raw):
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        name = next(name for name in archive.namelist()
                    if name.lower().endswith("metadata.txt"))
        text = archive.read(name).decode("utf-8", errors="replace")
    match = re.search(r"Horizontal_Positional_Accuracy_Report:\s*([^\r\n]+)", text, re.I)
    if not match or not re.search(r"highly variable.+10 meters", match.group(1), re.I):
        raise ValueError("Original camera position accuracy requires new review")
    return match.group(1).strip()


def review_contexts(contexts):
    to_m = Transformer.from_crs(4326, 3310, always_xy=True).transform
    rows = []
    for path in contexts:
        data = json.loads(path.read_text())
        if data.get("type") != "FeatureCollection" or not data.get("features"):
            raise ValueError(f"Invalid context: {path}")
        if any(item.get("properties", {}).get("fishing_target") is not False
               or item.get("properties", {}).get("exportable") is not False
               for item in data["features"]):
            raise ValueError(f"Only non-target context can be audited: {path}")
        polygons = [transform(to_m, shape(item["geometry"])) for item in data["features"]]
        rows.append((path.name, data, polygons, STRtree(polygons)))
    return to_m, rows


def hit_counters(records, polygon, point, row, cruise):
    """Count interior evidence only beyond the conservative position margin."""
    if not polygon.contains(point):
        return False
    records["inside_display_outline"] += 1
    if polygon.boundary.distance(point) < MIN_INTERIOR_M:
        records["near_edge_held"] += 1
        return True
    records["interior_windows"] += 1
    primary = str(row["MAJOR_GEO"]).strip().lower()
    if primary in {"rock", "boulder", "cobble"}:
        records["rock_boulder_cobble_windows"] += 1
    elif primary in {"sand", "mud"}:
        records["sand_mud_windows"] += 1
    else:
        records["other_bottom_windows"] += 1
    rockfish = first_field(row, "rockfish", "ROCKFISH")
    lingcod = first_field(row, "lingcod", "LINGCOD")
    if isinstance(rockfish, (int, float)) and rockfish > 0:
        records["rockfish_positive_windows"] += 1
    if isinstance(lingcod, (int, float)) and lingcod > 0:
        records["lingcod_positive_windows"] += 1
    observation_date = first_field(row, "DATE", "Date", "Date_", "STARTOFENT", "StartofEnt")
    if isinstance(observation_date, date):
        records.setdefault("dates", set()).add(observation_date.isoformat())
    records.setdefault("cruises", set()).add(cruise)
    line = first_field(row, "LINE", "Line", "line")
    records.setdefault("transects", set()).add((cruise, str(observation_date or ""), str(line or "unknown")))
    return True


def audit(manifest, cache, contexts, *, checked_at=None):
    checked_at = checked_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    to_m, layers = review_contexts(contexts)
    results = defaultdict(lambda: defaultdict(lambda: Counter()))
    accuracy = {}
    for cruise, sha in sorted(manifest["archives"].items()):
        raw = load_archive(cache, cruise, sha, manifest["base_url"], False)
        accuracy[cruise] = camera_accuracy(raw)
        reader = open_original_zip(raw)
        for item in reader.iterShapeRecords():
            row = item.record.as_dict()
            if not item.shape.points or not row.get("MAJOR_GEO"):
                continue
            point = transform(to_m, Point(*item.shape.points[0]))
            for filename, data, polygons, tree in layers:
                for index in tree.query(point):
                    feature = data["features"][index]
                    props = feature["properties"]
                    hit_counters(results[filename][props["id"]], polygons[index], point, row, cruise)
    output = []
    for filename, data, _, _ in layers:
        matched = []
        for feature in data["features"]:
            id_ = feature["properties"]["id"]
            counts = results[filename].get(id_)
            if not counts or not counts["inside_display_outline"]:
                continue
            matched.append({
                "outline_id": id_,
                **{key: counts[key] for key in (
                    "inside_display_outline", "near_edge_held", "interior_windows",
                    "rock_boulder_cobble_windows", "sand_mud_windows",
                    "other_bottom_windows", "rockfish_positive_windows",
                    "lingcod_positive_windows")},
                "cruise_ids": sorted(counts.get("cruises", set())),
                "observation_dates": sorted(counts.get("dates", set())),
                "distinct_transects": len(counts.get("transects", set())),
                "source_urls": [manifest["base_url"] + f"{id_}_video_observations.zip"
                                for id_ in sorted(counts.get("cruises", set()))],
                "source_archive_sha256": {cruise: manifest["archives"][cruise]
                                          for cruise in sorted(counts.get("cruises", set()))},
            })
        output.append({"context_file": filename,
                       "context_scope": data["scope"],
                       "context_compiled_at": data.get("compiled_at"),
                       "outline_count": len(data["features"]),
                       "outlines_with_interior_camera_evidence": sum(row["interior_windows"] > 0 for row in matched),
                       "matched_outlines": matched})
    return {
        "schema_version": 1,
        "scope": "usgs-video-vs-native-hard-context-review",
        "checked_at": checked_at,
        "source_catalog_url": manifest["catalog_url"],
        "cruise_position_accuracy": accuracy,
        "minimum_interior_clearance_m": MIN_INTERIOR_M,
        "method": "Original WGS84 camera windows reprojected to California Albers meters; contains test and minimum clearance from generalized display boundary; same-line windows counted as one transect.",
        "limitations": "Historical observations are not independent catches, current fish presence, precise rock limits, legal clearance or navigable fishing spots. Missing species codes do not mean absence.",
        "fishing_target": False,
        "exportable": False,
        "layers": output,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("catalog/usgs-video-cruises.json"))
    parser.add_argument("--cache", type=Path, default=Path("var/usgs-video-cache"))
    parser.add_argument("--contexts", type=Path, default=Path("dist/data"))
    parser.add_argument("--context-name", action="append",
                        help="Repeat for an explicit reviewed GeoJSON context; defaults to the four native hard-bottom layers.")
    parser.add_argument("--output", type=Path, default=Path("dist/data/usgs-video-native-overlap.json"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    result = audit(manifest, args.cache,
                   [args.contexts / name for name in (args.context_name or CONTEXTS)])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Audited", sum(layer["outline_count"] for layer in result["layers"]),
          "native context outlines across", len(result["layers"]), "layers")


if __name__ == "__main__":
    main()
