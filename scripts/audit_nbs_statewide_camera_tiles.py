"""Select and audit one NOAA NBS Modeling source tile per California browse sector.

Historical USGS rocky camera locations prioritize *source review*, not fishing
spots. Tile rectangles, camera density and a successful audit do not prove
reef extent, fish abundance, MPA access or a qualified target.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import Window
from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union

from scripts.audit_nbs_modeling_tile import audit, contributors, qualified_mask
from scripts.audit_statewide_regular_camera import rocky_camera_positions
from scripts.audit_usgs_video_observations import sector_for


def select_tiles(scheme, manifest, video_cache, sectors):
    candidates = Counter()
    camera_counts = Counter()
    camera_positions = defaultdict(list)
    with sqlite3.connect(scheme) as db:
        table = db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()
        if not table or not table[0].startswith("Modeling_Tile_Scheme_"):
            raise ValueError("Expected NOAA NBS Modeling GeoPackage")
        name = table[0]
        rtree = f"rtree_{name}_geom"
        for points in rocky_camera_positions(manifest, video_cache).values():
            for longitude, latitude in points:
                sector = sector_for(latitude, sectors)
                if sector is None:
                    continue
                camera_counts[sector] += 1
                rows = db.execute(
                    f'SELECT a.tile FROM "{name}" a JOIN "{rtree}" r ON a.fid=r.id '
                    'WHERE r.minx<=? AND r.maxx>=? AND r.miny<=? AND r.maxy>=? '
                    "AND a.Resolution IN ('2m','4m') AND a.GeoTIFF_Link IS NOT NULL AND a.RAT_Link IS NOT NULL",
                    (longitude, longitude, latitude, latitude)).fetchall()
                for (tile,) in rows:
                    candidates[(sector, tile)] += 1
                    camera_positions[(sector, tile)].append((longitude, latitude))
    selected = {}
    for sector in sectors:
        ident = sector["id"]
        choices = sorted(((count, tile) for (sector_id, tile), count in candidates.items()
                          if sector_id == ident), key=lambda item: (-item[0], item[1]))
        selected[ident] = {"sector_id": ident, "name": sector["name"], "coast": sector["coast"],
                           "historical_rocky_camera_windows": camera_counts[ident],
                           "selected_tile": choices[0][1] if choices else None,
                           "camera_windows_in_selected_tile_envelope": choices[0][0] if choices else 0,
                           "candidate_tiles": len(choices)}
    return selected, camera_positions


def camera_window_screen(raster, source_rows, longitude, latitude, project, inverse, protected,
                         *, radius_m=25):
    x, y = project.transform(longitude, latitude)
    footprint = transform(inverse.transform, Point(x, y).buffer(radius_m))
    if protected.intersects(footprint):
        return "mpa_or_edge_held"
    row, col = raster.index(x, y)
    if not (0 <= row < raster.height and 0 <= col < raster.width):
        return "outside_raster"
    pad = int(np.ceil(radius_m / min(raster.res)))
    if col < pad or row < pad or col + pad >= raster.width or row + pad >= raster.height:
        return "raster_edge_held"
    window = Window(col - pad, row - pad, pad * 2 + 1, pad * 2 + 1)
    elevation, uncertainty, contributor = raster.read(window=window)
    eligible = qualified_mask(elevation, uncertainty, contributor, source_rows,
                              resolution_m=max(raster.res))
    if not eligible[pad, pad]:
        return "center_not_qualified"
    xx, yy = np.meshgrid(np.arange(-pad, pad + 1) * raster.res[0],
                         np.arange(-pad, pad + 1) * raster.res[1])
    circle = xx * xx + yy * yy <= radius_m * radius_m
    fraction = np.count_nonzero(eligible & circle) / np.count_nonzero(circle)
    return "locally_qualified_90pct" if fraction >= .9 else "neighborhood_not_qualified"


def screen_camera_positions(cache, tile, positions, protected):
    counts = Counter()
    source_rows = contributors(cache / f"{tile}.tiff.aux.xml")
    with rasterio.open(cache / f"{tile}.tiff") as raster:
        project = Transformer.from_crs("EPSG:4326", raster.crs, always_xy=True)
        inverse = Transformer.from_crs(raster.crs, "EPSG:4326", always_xy=True)
        for longitude, latitude in positions:
            counts[camera_window_screen(raster, source_rows, longitude, latitude,
                                        project, inverse, protected)] += 1
    return dict(counts)


def build(scheme, manifest, video_cache, sectors, cache, mpa_snapshot, *, fetch=False, workers=4):
    mpa_source = mpa_snapshot["sources"]["mpas"]
    features = mpa_source["data"]["geojson"]["features"]
    if mpa_source["status"] != "ok" or len(features) != mpa_source["data"]["feature_count"] or len(features) < 100:
        raise ValueError("Complete current CDFW MPA source required")
    checked = datetime.fromisoformat(mpa_source["data_retrieved_at"].replace("Z", "+00:00"))
    if not 0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 36 * 3600:
        raise ValueError("CDFW MPA snapshot is stale")
    protected = unary_union([shape(feature["geometry"]) for feature in features])
    selected, camera_positions = select_tiles(scheme, manifest, video_cache, sectors)
    tile_ids = sorted({row["selected_tile"] for row in selected.values() if row["selected_tile"]})
    results = {}
    failures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(audit, scheme, tile, cache, fetch=fetch): tile for tile in tile_ids}
        for future in as_completed(pending):
            tile = pending[future]
            try:
                results[tile] = future.result()
            except (OSError, ValueError, KeyError) as exc:
                failures[tile] = f"{type(exc).__name__}: {exc}"
    rows = []
    for sector in sectors:
        row = selected[sector["id"]].copy()
        tile = row["selected_tile"]
        row["source_audit"] = results.get(tile)
        row["source_failure"] = failures.get(tile)
        if tile in results:
            row["historical_camera_native_cell_screen"] = screen_camera_positions(
                cache, tile, camera_positions[(sector["id"], tile)], protected)
        rows.append(row)
    return {"schema_version": 1, "scope": "statewide-nbs-modeling-rocky-camera-tile-source-sample",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scheme_sha256": hashlib.sha256(scheme.read_bytes()).hexdigest(),
            "cdfw_mpa_source_url": mpa_source["data"]["source_url"],
            "cdfw_mpa_retrieved_at": mpa_source["data_retrieved_at"],
            "cdfw_mpa_geojson_sha256": hashlib.sha256(json.dumps(
                mpa_source["data"]["geojson"], sort_keys=True,
                separators=(",", ":")).encode()).hexdigest(),
            "camera_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            "sector_count": len(sectors), "unique_selected_tiles": len(tile_ids),
            "audited_tiles": len(results), "failed_tiles": len(failures),
            "sectors_without_sample_tile": [row["sector_id"] for row in rows if not row["selected_tile"]],
            "sectors": rows,
            "fishing_target": False, "exportable": False,
            "limitations": ["One tile per sector is a prioritized sample, not coastwide bathymetry coverage.",
                            "Camera positions select tile bounding envelopes; the subsequent 25 m native-cell screen is historical transect evidence, not unique sites or catch rates.",
                            "Even qualifying source pixels need original substrate, hazards, MPA and date-specific local-rule reviews before target promotion.",
                            "NOAA NBS Modeling is a test-and-evaluation product, not a navigation chart."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scheme", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("catalog/usgs-video-cruises.json"))
    parser.add_argument("--video-cache", type=Path, default=Path("var/usgs-video-cache"))
    parser.add_argument("--sectors", type=Path, default=Path("catalog/coastal-sectors.json"))
    parser.add_argument("--cache", type=Path, default=Path("var/nbs-cache"))
    parser.add_argument("--mpas", type=Path, default=Path("var/qualification-current/coastal/latest.json"))
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path("dist/data/nbs-statewide-camera-tile-review.json"))
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("workers must be between 1 and 8")
    result = build(args.scheme, json.loads(args.manifest.read_text()), args.video_cache,
                   json.loads(args.sectors.read_text())["sectors"], args.cache,
                   json.loads(args.mpas.read_text()), fetch=args.fetch, workers=args.workers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["sector_count"], "sectors;", result["audited_tiles"], "audited tiles;",
          result["failed_tiles"], "failures")
    if result["failed_tiles"] or result["sectors_without_sample_tile"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
