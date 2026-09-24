"""Cross-check original USGS camera windows with measured regular NOAA BAG cells.

This produces a historical source receipt, never a fishing target or export.
Each camera window is kept under its original transect, not counted as a site.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import zipfile

import numpy as np
import rasterio
from rasterio.windows import Window
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union

from scripts.audit_usgs_video_observations import first_field, load_archive, open_original_zip
from skippercast.platform.bottom_targets import bag_metadata, cells_qualified, sha256, source_url_allowed


def camera_accuracy(raw):
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        name = next(name for name in archive.namelist() if name.lower().endswith("metadata.txt"))
        metadata = archive.read(name).decode("utf-8", errors="replace")
    match = re.search(r"Horizontal_Positional_Accuracy_Report:\s*([^\r\n]+)", metadata, re.I)
    if not match or not re.search(r"highly variable.+10 meters", match.group(1), re.I):
        raise ValueError("Original camera position accuracy requires new review")
    return match.group(1).strip()


def cell_review(raster, x, y, *, radius_m=25):
    """Sample the actual depth and uncertainty bands and a local validity window."""
    row, col = raster.index(x, y)
    if not (0 <= row < raster.height and 0 <= col < raster.width):
        return {"status": "outside_grid"}
    depth = float(raster.read(1, window=Window(col, row, 1, 1))[0, 0])
    uncertainty = float(raster.read(2, window=Window(col, row, 1, 1))[0, 0])
    valid = bool(cells_qualified(np.array([depth]), np.array([uncertainty]), max(raster.res))[0])
    if not valid:
        return {"status": "masked_or_ineligible_cell"}
    pad = int(np.ceil(radius_m / min(raster.res)))
    if col < pad or row < pad or col + pad >= raster.width or row + pad >= raster.height:
        return {"status": "native_grid_edge_held"}
    left, top = max(0, col - pad), max(0, row - pad)
    width = min(raster.width - left, 2 * pad + 1)
    height = min(raster.height - top, 2 * pad + 1)
    d = raster.read(1, window=Window(left, top, width, height))
    u = raster.read(2, window=Window(left, top, width, height))
    yy, xx = np.ogrid[top:top + height, left:left + width]
    within = ((xx - col) * raster.res[0]) ** 2 + ((yy - row) * raster.res[1]) ** 2 <= radius_m ** 2
    fraction = float(np.count_nonzero(cells_qualified(d, u, max(raster.res)) & within) / np.count_nonzero(within))
    return {"status": "measured_qualified_cell", "depth_m_mllw": round(-depth, 2),
            "product_uncertainty_m": round(uncertainty, 3),
            "qualified_neighborhood_fraction": round(fraction, 4)}


def reviewed_archive(audit, survey_id, cache, *, bag_url=None):
    matches = [r for r in audit["files"] if r.get("survey_id") == survey_id
               and (bag_url is None or r.get("url") == bag_url)]
    if bag_url is None and len(matches) != 1:
        raise ValueError("Survey has multiple original BAG files; select an exact --bag-url")
    record = matches[0] if len(matches) == 1 else None
    if not record or record.get("status") != "ok" or not source_url_allowed(record["url"]):
        raise ValueError("Reviewed NOAA BAG record is unavailable")
    path = cache / (survey_id + "-" + hashlib.sha256(record["url"].encode()).hexdigest()[:16] + ".bag")
    if not path.is_file() or path.stat().st_size != record["file_bytes"] or sha256(path) != record["file_sha256"]:
        raise ValueError("Original NOAA BAG changed or is missing")
    return record, path


def review(audit, manifest, snapshot, cache, video_cache, *, survey_id="H11981", cruise="c109nc", bag_url=None):
    record, path = reviewed_archive(audit, survey_id, cache, bag_url=bag_url)
    source = snapshot["sources"]["mpas"]
    data = source["data"]
    features = data["geojson"]["features"]
    checked = datetime.fromisoformat(source["data_retrieved_at"].replace("Z", "+00:00"))
    if (source["status"] != "ok" or data["feature_count"] != len(features) or len(features) < 100
            or not 0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 36 * 3600):
        raise ValueError("Complete fresh CDFW MPA geometry is required")
    protected = unary_union([shape(f["geometry"]) for f in features])
    raw = load_archive(video_cache, cruise, manifest["archives"][cruise], manifest["base_url"], False)
    reader = open_original_zip(raw)
    fields = {field.name.lower() for field in reader.fields[1:]}
    has_rockfish = "rockfish" in fields
    has_lingcod = "lingcod" in fields
    counts = Counter()
    transects = defaultdict(lambda: {"windows": 0, "rock": 0, "boulder": 0,
                                     "rockfish_positive_windows": 0, "lingcod_positive_windows": 0,
                                     "depths_m": [], "uncertainties_m": [], "coverage": [],
                                     "coordinates": []})
    with rasterio.open(path) as raster:
        if raster.count != 2 or max(raster.res) > 4:
            raise ValueError("Expected fine regular two-band BAG")
        import h5py
        with h5py.File(path) as handle:
            metadata = bag_metadata(handle["BAG_root"]["metadata"][:].tobytes().decode().rstrip("\0"), survey_id)
        if metadata["metadata_sha256"] != record["metadata_sha256"]:
            raise ValueError("Embedded NOAA metadata changed")
        project = Transformer.from_crs("EPSG:4326", raster.crs, always_xy=True)
        inverse = Transformer.from_crs(raster.crs, "EPSG:4326", always_xy=True)
        for item in reader.iterShapeRecords():
            if not item.shape.points:
                continue
            lon, lat = item.shape.points[0]
            row = item.record.as_dict()
            major = str(row.get("MAJOR_GEO") or "").strip().lower()
            if not major or major not in {"rock", "boulder", "cobble"}:
                continue
            x, y = project.transform(lon, lat)
            if not (raster.bounds.left <= x <= raster.bounds.right and raster.bounds.bottom <= y <= raster.bounds.top):
                continue
            counts["rocky_camera_windows_in_bag_bounds"] += 1
            # Buffer in projected meters, then test the entire uncertainty neighborhood.
            footprint = transform(inverse.transform, Point(x, y).buffer(25))
            if protected.intersects(footprint):
                counts["mpa_or_edge_held"] += 1
                continue
            sample = cell_review(raster, x, y)
            counts[sample["status"]] += 1
            if sample["status"] != "measured_qualified_cell" or sample["qualified_neighborhood_fraction"] < .9:
                continue
            counts["qualified_rocky_camera_windows"] += 1
            when = first_field(row, "STARTOFENT", "StartofEnt", "DATE", "Date", "Date_")
            day = when.isoformat() if isinstance(when, date) else str(when)[:10]
            key = (day, str(first_field(row, "LINE", "Line")))
            group = transects[key]
            group["windows"] += 1
            group[major] = group.get(major, 0) + 1
            if has_rockfish:
                group["rockfish_positive_windows"] += int(float(first_field(row, "ROCKFISH", "rockfish") or 0) > 0)
            if has_lingcod:
                group["lingcod_positive_windows"] += int(float(first_field(row, "LINGCOD", "lingcod") or 0) > 0)
            group["depths_m"].append(sample["depth_m_mllw"])
            group["uncertainties_m"].append(sample["product_uncertainty_m"])
            group["coverage"].append(sample["qualified_neighborhood_fraction"])
            group["coordinates"].append((lon, lat))
    groups = []
    for (day, line), g in sorted(transects.items()):
        groups.append({"date": day, "line": line, "window_count": g["windows"],
                       "bottom_classes": {k: g[k] for k in ("rock", "boulder", "cobble") if g.get(k)},
                       "rockfish_positive_windows": g["rockfish_positive_windows"] if has_rockfish else None,
                       "lingcod_positive_windows": g["lingcod_positive_windows"] if has_lingcod else None,
                       "depth_m_mllw_range": [min(g["depths_m"]), max(g["depths_m"])],
                       "product_uncertainty_m_range": [min(g["uncertainties_m"]), max(g["uncertainties_m"])],
                       "minimum_25m_qualified_fraction": min(g["coverage"]),
                       "camera_position_bounds": [round(min(p[0] for p in g["coordinates"]), 6),
                                                  round(min(p[1] for p in g["coordinates"]), 6),
                                                  round(max(p[0] for p in g["coordinates"]), 6),
                                                  round(max(p[1] for p in g["coordinates"]), 6)]})
    return {"schema_version": 1, "scope": "historical-camera-original-regular-bag-review",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "survey_id": survey_id, "bag_url": record["url"], "bag_sha256": record["file_sha256"],
            "bag_acquisition": [metadata["survey_start"], metadata["survey_end"]],
            "native_cell_m": list(raster.res), "vertical_datum": metadata["vertical_datum"],
            "camera_archive_url": manifest["base_url"] + cruise + "_video_observations.zip",
            "camera_archive_sha256": manifest["archives"][cruise],
            "camera_accuracy": camera_accuracy(raw),
            "camera_species_fields": {"rockfish": has_rockfish, "lingcod": has_lingcod},
            "mpa_url": data["source_url"], "mpa_retrieved_at": source["data_retrieved_at"],
            "mpa_geojson_sha256": hashlib.sha256(json.dumps(data["geojson"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "counts": dict(counts), "transects": groups,
            "method": "Original camera rock/boulder/cobble windows sampled against original regular BAG depth and product uncertainty; 25 m local cell coverage, native grid-edge and MPA holds. A line of windows counts as one historical transect.",
            "limitations": ["Camera positions have variable accuracy on the order of 10 m; a 25 m window is a conservative review device, not an exact rock footprint.",
                            "Historical visual fish codes do not establish current fish, catch rate, or charter AIS activity.",
                            "Current chart hazards, local rules, access and route are not cleared."],
            "fishing_target": False, "exportable": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit", type=Path, default=Path("var/noaa-native-audit-100mb-refined.json"))
    p.add_argument("--manifest", type=Path, default=Path("catalog/usgs-video-cruises.json"))
    p.add_argument("--mpas", type=Path, default=Path("var/qualification-current/coastal/latest.json"))
    p.add_argument("--cache", type=Path, default=Path("var/noaa-native-cache"))
    p.add_argument("--video-cache", type=Path, default=Path("var/usgs-video-cache"))
    p.add_argument("--survey-id", default="H11981")
    p.add_argument("--bag-url", help="Required when a survey has multiple original BAG files")
    p.add_argument("--cruise", default="c109nc")
    p.add_argument("--output", type=Path, default=Path("dist/data/noaa-h11981-camera-depth-review.json"))
    a = p.parse_args()
    result = review(json.loads(a.audit.read_text()), json.loads(a.manifest.read_text()),
                    json.loads(a.mpas.read_text()), a.cache, a.video_cache,
                    survey_id=a.survey_id, cruise=a.cruise, bag_url=a.bag_url)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["survey_id"], result["counts"], len(result["transects"]), "transects")


if __name__ == "__main__":
    main()
