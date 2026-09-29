"""Check original USGS camera points against private Estero research blocks.

Only aggregate distances leave the private review directory. The 100 m blocks
are a search index, not independently surveyed rock polygons or waypoints.
"""
import argparse
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from research.scripts.audit_usgs_video_observations import load_archive, open_original_zip


ROOT = Path(__file__).resolve().parents[2]
CRUISE = "c0212sc"
RADII_M = (0, 100, 250)


def inspect(blocks, camera_rows):
    if (blocks.get("scope") != "private-estero-nominal-research-blocks"
            or blocks.get("crs") != "EPSG:32610"
            or len(blocks.get("features", [])) != 60):
        raise ValueError("Private original-cell block index changed")
    polygons = [shape(feature["geometry"]) for feature in blocks["features"]]
    if any(p.is_empty or not p.is_valid or p.area != 10_000 for p in polygons):
        raise ValueError("Original-cell review block geometry changed")
    tree = STRtree(polygons)
    project = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)
    counts = Counter()
    nearest = float("inf")
    for lon, lat, row in camera_rows:
        if not (-125 <= lon <= -117 and 32 <= lat <= 42):
            raise ValueError("Unexpected original camera position")
        counts["records"] += 1
        point = Point(*project.transform(lon, lat))
        index = tree.nearest(point)
        distance = polygons[index].distance(point)
        nearest = min(nearest, distance)
        bottom = str(row.get("MAJOR_GEO") or "").strip().lower()
        for radius in RADII_M:
            if distance > radius:
                continue
            key = f"within_{radius}m"
            counts[key] += 1
            if bottom:
                counts[f"interpreted_{key}"] += 1
            if bottom in ("rock", "boulder", "cobble"):
                counts[f"rock_{key}"] += 1
            if bottom and row.get("rockfish", 0) > 0:
                counts[f"rockfish_{key}"] += 1
            if bottom and row.get("lingcod", 0) > 0:
                counts[f"lingcod_{key}"] += 1
    if not counts["records"]:
        raise ValueError("Original camera archive contains no point records")
    return {
        "camera_records": counts["records"],
        "nearest_camera_to_any_block_m": round(nearest, 1),
        "distance_counts": {
            f"within_{radius}m": {
                "all": counts[f"within_{radius}m"],
                "interpreted_bottom": counts[f"interpreted_within_{radius}m"],
                "rock_boulder_cobble": counts[f"rock_within_{radius}m"],
                "rockfish_positive": counts[f"rockfish_within_{radius}m"],
                "lingcod_positive": counts[f"lingcod_within_{radius}m"],
            } for radius in RADII_M
        },
    }


def build(manifest, blocks, cache, download=False):
    raw = load_archive(cache, CRUISE, manifest["archives"][CRUISE],
                       manifest["base_url"], download)
    with ZipFile(BytesIO(raw)) as archive:
        metadata = archive.read(next(name for name in archive.namelist()
                                     if name.lower().endswith("metadata.txt"))).decode("utf-8", "replace")
    if "Highly variable on the order of 10 meters." not in metadata:
        raise ValueError("Original camera position caveat changed")
    reader = open_original_zip(raw)
    result = inspect(blocks, ((record.shape.points[0][0], record.shape.points[0][1],
                               record.record.as_dict())
                              for record in reader.iterShapeRecords()
                              if record.shape.points))
    return {
        "schema_version": 1,
        "scope": "estero-original-camera-to-private-300ft-block-gap",
        "research_block_count": len(blocks["features"]),
        "research_block_size_m": 100,
        "camera_cruise": CRUISE,
        "camera_archive_url": manifest["base_url"] + CRUISE + "_video_observations.zip",
        "camera_archive_sha256": manifest["archives"][CRUISE],
        "camera_position_accuracy": "Highly variable on the order of 10 meters (original metadata)",
        **result,
        "independent_substrate_gate_satisfied": False,
        "biological_observation_gate_satisfied": False,
        "qualified_waypoints": 0,
        "fishing_target": False,
        "exportable": False,
        "limitation": "The blocks are 100 m bins of nominal NAVD88 depth and older 2008 hard/rugose class, not exact rock footprints. Distances are to entire block polygons, so a negative proximity result also excludes contained candidate cell centers at the same radius. Camera position accuracy is order 10 m, not a strict bound. Historical video absence is not absence of rock or fish. Product TPU, MLLW depth, registration, current legal access and full routes remain unresolved."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "research/catalog/usgs-video-cruises.json")
    parser.add_argument("--blocks", type=Path, default=ROOT / "var/review/estero-nominal-research-blocks.geojson")
    parser.add_argument("--cache", type=Path, default=ROOT / "var/usgs-video-cache")
    parser.add_argument("--download-video", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "research/receipts/estero-original-camera-block-gap.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = build(json.loads(args.manifest.read_text()), json.loads(args.blocks.read_text()),
                   args.cache, args.download_video)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise ValueError("Original Estero camera/block evidence changed; review before publication")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".partial")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"camera_records": result["camera_records"],
                      "nearest_m": result["nearest_camera_to_any_block_m"],
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
