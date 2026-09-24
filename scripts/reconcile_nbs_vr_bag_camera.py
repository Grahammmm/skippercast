"""Compare one NBS tile's rocky-camera leads with its original NOAA VR BAG.

This detects apparent measured NBS coverage that is not corroborated by the
original survey's fine native cells. It produces a source-review receipt only.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import h5py
from pyproj import Transformer
import rasterio
from shapely.geometry import Point, Polygon, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from scripts.audit_nbs_modeling_tile import audit as audit_nbs, contributors
from scripts.audit_nbs_statewide_camera_tiles import camera_window_screen
from scripts.audit_regular_bag_camera import cell_review
from scripts.audit_usgs_video_observations import load_archive, open_original_zip
from scripts.screen_vr_native_depth import fine_grid_rows
from skippercast.platform.bottom_targets import bag_metadata, sha256, vr_transform


def bag_grid_index(path, record):
    with rasterio.open(path) as raster, h5py.File(path) as handle:
        metadata = bag_metadata(handle["BAG_root"]["metadata"][:].tobytes().decode().rstrip("\0"),
                                record["survey_id"])
        if metadata["metadata_sha256"] != record["metadata_sha256"]:
            raise ValueError("Original BAG embedded metadata changed")
        array = handle["BAG_root"]["varres_metadata"][:]
        positions = fine_grid_rows(array)
        if len(positions) != record["refinement_grids_at_most_4m"]:
            raise ValueError("Original BAG fine-grid count changed")
        polygons, coordinates = [], []
        for row, col in positions:
            item = array[row, col]
            affine = vr_transform(raster.bounds.left, raster.bounds.bottom,
                                  raster.res[0], raster.res[1], int(row), int(col), item)
            x0, y1 = affine.c, affine.f
            x1 = x0 + int(item["dimensions_x"]) * float(item["resolution_x"])
            y0 = y1 - int(item["dimensions_y"]) * float(item["resolution_y"])
            polygons.append(Polygon(((x0, y0), (x1, y0), (x1, y1), (x0, y1))))
            coordinates.append((int(row), int(col)))
        return raster.crs, polygons, coordinates


def bag_camera_status(path, polygons, coordinates, tree, x, y):
    point = Point(x, y)
    matches = [int(i) for i in tree.query(point) if polygons[int(i)].covers(point)]
    if not matches:
        return "outside_original_fine_grid"
    match = max(matches, key=lambda i: polygons[i].boundary.distance(point))
    if polygons[match].boundary.distance(point) < 25:
        return "original_fine_grid_edge_held"
    row, col = coordinates[match]
    with rasterio.open(f"BAG:{path}:supergrid:{row}:{col}") as grid:
        cell = cell_review(grid, x, y)
    if cell["status"] != "measured_qualified_cell":
        return "original_cell_not_qualified"
    if cell["qualified_neighborhood_fraction"] < .9:
        return "original_neighborhood_not_qualified"
    return "original_locally_qualified_90pct"


def review(tile, survey_id, cruise, scheme, nbs_cache, bag_audit, bag_cache,
           video_manifest, video_cache, mpa_snapshot, latitude, candidate_context=None):
    nbs = audit_nbs(scheme, tile, nbs_cache)
    if not any(item["survey_id"].startswith(survey_id) for item in nbs["qualified_contributors"]):
        raise ValueError("Selected NOAA NBS tile has no qualified pixels from the original survey")
    records = [item for item in bag_audit["files"] if item["survey_id"] == survey_id]
    if len(records) != 1:
        raise ValueError("Expected exactly one audited original BAG for survey")
    record = records[0]
    path = bag_cache / (survey_id + "-" + hashlib.sha256(record["url"].encode()).hexdigest()[:16] + ".bag")
    if not path.is_file() or path.stat().st_size != record["file_bytes"] or sha256(path) != record["file_sha256"]:
        raise ValueError("Original BAG size or checksum changed")
    bag_crs, polygons, coordinates = bag_grid_index(path, record)
    tree = STRtree(polygons)
    if not polygons:
        raise ValueError("Original BAG has no fine grids")
    mpa = mpa_snapshot["sources"]["mpas"]
    features = mpa["data"]["geojson"]["features"]
    checked = datetime.fromisoformat(mpa["data_retrieved_at"].replace("Z", "+00:00"))
    if (mpa["status"] != "ok" or len(features) != mpa["data"]["feature_count"]
            or len(features) < 100 or not 0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 36 * 3600):
        raise ValueError("Complete fresh CDFW MPA source required")
    protected = unary_union([shape(feature["geometry"]) for feature in features])
    raw = load_archive(video_cache, cruise, video_manifest["archives"][cruise],
                       video_manifest["base_url"], False)
    counts = Counter()
    compare = Counter()
    with rasterio.open(nbs_cache / f"{tile}.tiff") as raster:
        source_rows = contributors(nbs_cache / f"{tile}.tiff.aux.xml")
        nbs_project = Transformer.from_crs("EPSG:4326", raster.crs, always_xy=True)
        nbs_inverse = Transformer.from_crs(raster.crs, "EPSG:4326", always_xy=True)
        bag_project = Transformer.from_crs("EPSG:4326", bag_crs, always_xy=True)
        for item in open_original_zip(raw).iterShapeRecords():
            if not item.shape.points:
                continue
            lon, lat = item.shape.points[0]
            if not latitude[0] <= lat < latitude[1]:
                continue
            major = str(item.record.as_dict().get("MAJOR_GEO") or "").strip().lower()
            if major not in {"rock", "boulder", "cobble"}:
                continue
            x, y = nbs_project.transform(lon, lat)
            if not (raster.bounds.left <= x < raster.bounds.right
                    and raster.bounds.bottom <= y < raster.bounds.top):
                continue
            counts["rocky_camera_windows_in_tile_envelope"] += 1
            nbs_status = camera_window_screen(raster, source_rows, lon, lat,
                                              nbs_project, nbs_inverse, protected)
            counts["nbs_" + nbs_status] += 1
            if nbs_status == "mpa_or_edge_held":
                continue
            bx, by = bag_project.transform(lon, lat)
            bag_status = bag_camera_status(path, polygons, coordinates, tree, bx, by)
            compare[(nbs_status, bag_status)] += 1
            if (candidate_context is not None and nbs_status == 'locally_qualified_90pct'
                    and bag_status == 'original_locally_qualified_90pct'):
                candidate_context.append({
                    'type': 'Feature',
                    'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
                    'properties': {'id': f'{survey_id}-camera-window-{len(candidate_context) + 1}',
                                   'survey_id': survey_id,
                                   'evidence': 'historical-camera-window-and-original-bag-screen',
                                   'fishing_target': False, 'exportable': False}})
    if counts["rocky_camera_windows_in_tile_envelope"] != sum(
            count for key, count in counts.items() if key.startswith("nbs_")):
        raise ValueError("Camera windows lost in NBS screen")
    return {"schema_version": 1, "scope": "nbs-versus-original-vr-bag-rocky-camera-reconciliation",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tile": tile, "nbs_raster_url": nbs["raster_url"],
            "nbs_raster_sha256": nbs["raster_sha256"], "nbs_rat_sha256": nbs["rat_sha256"],
            "original_survey_id": survey_id, "original_bag_url": record["url"],
            "original_bag_sha256": record["file_sha256"],
            "original_report_url": record["source_report_url"],
            "camera_archive_url": video_manifest["base_url"] + cruise + "_video_observations.zip",
            "camera_archive_sha256": video_manifest["archives"][cruise],
            "cdfw_mpa_source_url": mpa["data"]["source_url"],
            "cdfw_mpa_retrieved_at": mpa["data_retrieved_at"],
            "counts": dict(counts),
            "comparison": [{"nbs_status": nbs_status, "original_bag_status": bag_status,
                            "historical_camera_windows": count}
                           for (nbs_status, bag_status), count in sorted(compare.items())],
            "fishing_target": False, "exportable": False,
            "limitations": ["NBS reuses original NOAA survey measurements; it is not an independent seabed observation.",
                            "Camera windows are correlated historical transect records, not unique sites or present fish evidence.",
                            "Survey descriptive-report hazards, current chart, federal closures, local rules and route remain unreviewed for target promotion."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tile", required=True)
    parser.add_argument("--survey-id", required=True)
    parser.add_argument("--cruise", required=True)
    parser.add_argument("--sector-id", required=True)
    parser.add_argument("--scheme", type=Path, default=Path("var/nbs-cache/modeling-tile-scheme.gpkg"))
    parser.add_argument("--nbs-cache", type=Path, default=Path("var/nbs-cache"))
    parser.add_argument("--bag-audit", type=Path, default=Path("var/noaa-native-audit-100mb-refined.json"))
    parser.add_argument("--bag-cache", type=Path, default=Path("var/noaa-native-cache"))
    parser.add_argument("--video-manifest", type=Path, default=Path("catalog/usgs-video-cruises.json"))
    parser.add_argument("--video-cache", type=Path, default=Path("var/usgs-video-cache"))
    parser.add_argument("--mpas", type=Path, default=Path("var/qualification-current/coastal/latest.json"))
    parser.add_argument("--sectors", type=Path, default=Path("catalog/coastal-sectors.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-context", type=Path,
                        help="Optional research-only positions of original-grid-qualified historical camera windows")
    args = parser.parse_args()
    sector = next(item for item in json.loads(args.sectors.read_text())["sectors"]
                  if item["id"] == args.sector_id)
    candidate_context = [] if args.candidate_context else None
    result = review(args.tile, args.survey_id, args.cruise, args.scheme, args.nbs_cache,
                    json.loads(args.bag_audit.read_text()), args.bag_cache,
                    json.loads(args.video_manifest.read_text()), args.video_cache,
                    json.loads(args.mpas.read_text()), sector["latitude"], candidate_context)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if args.candidate_context:
        if len(candidate_context) != next((row['historical_camera_windows'] for row in result['comparison']
            if row['nbs_status'] == 'locally_qualified_90pct'
            and row['original_bag_status'] == 'original_locally_qualified_90pct'), 0):
            raise ValueError('Research-only camera context count disagrees with reconciliation')
        args.candidate_context.parent.mkdir(parents=True, exist_ok=True)
        args.candidate_context.write_text(json.dumps({
            'type': 'FeatureCollection', 'schema_version': 1,
            'scope': 'unpublished-historical-camera-window-research',
            'fishing_target': False, 'exportable': False,
            'limitations': 'Correlated camera windows from one historical transect. These points are not verified fish sites or navigational clearances.',
            'features': candidate_context}, indent=2) + '\n')
    print(result["counts"], result["comparison"])


if __name__ == "__main__":
    main()
