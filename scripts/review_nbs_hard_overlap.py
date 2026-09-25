"""Prioritize original-source review where measured NBS cells meet USGS hard context.

The USGS polygons are 20 m display generalizations and NBS Modeling is a
compiled test product. This audit publishes counts and provenance, never spots.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.vrt import WarpedVRT
from shapely.geometry import box, shape
from shapely.ops import transform

from scripts.audit_nbs_coast_camera_tiles import checked_mpas
from scripts.audit_nbs_modeling_tile import audit, contributors, qualified_mask


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def current_federal(data):
    if data.get("scope") != "noaa-west-coast-groundfish-conservation-areas" or data.get("status") != "ok":
        raise ValueError("Complete NOAA federal area snapshot required")
    checked = datetime.fromisoformat(data["retrieved_at"].replace("Z", "+00:00"))
    if not 0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 36 * 3600:
        raise ValueError("NOAA federal area snapshot is stale")
    features = [row for row in data["features"] if row["properties"].get("groundfish_candidate_exclusion") is True]
    if len(features) < 10:
        raise ValueError("NOAA GEA inventory is incomplete")
    return features


def mask_for(raster, geometries, *, buffer_m=0, all_touched=False):
    if not geometries:
        return np.zeros((raster.height, raster.width), dtype=bool)
    shapes = [(geometry.buffer(buffer_m), 1) for geometry in geometries]
    return rasterize(shapes, out_shape=(raster.height, raster.width), transform=raster.transform,
                     all_touched=all_touched, dtype="uint8").astype(bool)


def original_usgs_class(release_id, raster, bounds_wgs84, audit_rows, usgs_cache):
    sources = [row for row in audit_rows if row.get("release_id") == release_id
               and row.get("kind") == "seafloor_character" and row.get("status") == "ok"
               and box(*row["raster_bounds_wgs84"]).intersects(bounds_wgs84)]
    if not sources:
        raise ValueError("Original USGS class grid not audited: " + release_id)
    cache_dirs = usgs_cache if isinstance(usgs_cache, (tuple, list)) else (usgs_cache,)
    matches = [path for directory in cache_dirs for path in
               directory.glob(release_id + "-seafloor_character-*.zip")]
    cached = {digest(path): path for path in matches}
    hard = np.zeros((raster.height, raster.width), dtype=bool)
    for source in sources:
        path = cached.get(source["archive_sha256"])
        if path is None:
            raise ValueError("Original USGS class archive absent or changed: " + release_id)
        with ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".tif")
                       and not name.startswith('__MACOSX/') and not Path(name).name.startswith('._')]
        if len(members) != 1:
            raise ValueError("Original USGS class archive is ambiguous: " + release_id)
        with rasterio.open(f"/vsizip/{path.resolve()}/{members[0]}") as original:
            source_crs = str(original.crs) if original.crs else (
                source["native_crs"] if source.get("crs_from_original_xml") else None)
            if (original.count != 1 or original.width != source["native_width"]
                    or original.height != source["native_height"]
                    or list(original.res) != source["native_resolution"]
                    or source_crs != source["native_crs"]):
                raise ValueError("Original USGS class raster changed: " + release_id)
            with WarpedVRT(original, crs=raster.crs, transform=raster.transform,
                           width=raster.width, height=raster.height,
                           src_crs=source_crs, resampling=Resampling.nearest,
                           nodata=original.nodata) as aligned:
                hard |= aligned.read(1) == 3
    return hard, sources


def build(review, scheme, cache, hard_context, hard_path, usgs_audit, usgs_audit_path, usgs_cache, mpas, federal,
          *, map_audit=None, map_audit_path=None, map_cache=None):
    if review.get("scope") not in ("coast-nbs-multiple-rocky-camera-tile-source-review",
                                   "coast-nbs-hard-footprint-depth-source-audit"):
        raise ValueError("Expected reviewed multi-tile source audit")
    if review["scheme_sha256"] != digest(scheme) or review.get("failed_tiles"):
        raise ValueError("NBS scheme changed or source audit has failures")
    checked_mpas(mpas)
    geas = current_federal(federal)
    if hard_context.get("type") != "FeatureCollection" or not isinstance(hard_context.get("features"), list):
        raise ValueError("USGS class-3 context is invalid")
    hard = hard_context["features"]
    if usgs_audit.get("scope") != "usgs-state-waters-doi-native-grid-audit" or not usgs_audit.get("products"):
        raise ValueError("Original USGS class audit required")
    original_products = list(usgs_audit["products"])
    if map_audit is not None:
        if (map_audit.get("scope") != "usgs-state-waters-native-grid-audit"
                or not map_audit.get("products") or map_audit_path is None or map_cache is None):
            raise ValueError("Original older USGS map-block audit required")
        original_products.extend({**row, "release_id": row["block_id"]}
                                 for row in map_audit["products"])
        usgs_cache = (usgs_cache, map_cache)
    mpa_features = mpas["sources"]["mpas"]["data"]["geojson"]["features"]
    rows = []
    for sector in review["sectors"]:
        tiles = []
        for choice in sector["reviewed_tiles"]:
            tile = choice["tile"]
            checked = audit(scheme, tile, cache)
            original = choice.get("source_audit") or {}
            if (checked["raster_sha256"] != original.get("raster_sha256")
                    or checked["rat_sha256"] != original.get("rat_sha256")):
                raise ValueError("Reviewed NBS tile changed: " + tile)
            rat = contributors(cache / f"{tile}.tiff.aux.xml")
            with rasterio.open(cache / f"{tile}.tiff") as raster:
                to_geo = Transformer.from_crs(raster.crs, 4326, always_xy=True).transform
                to_native = Transformer.from_crs(4326, raster.crs, always_xy=True).transform
                bounds = transform(to_geo, box(*raster.bounds))
                locally_hard = [f for f in hard if shape(f["geometry"]).intersects(bounds)]
                local_mpas = [f for f in mpa_features if shape(f["geometry"]).intersects(bounds)]
                local_geas = [f for f in geas if shape(f["geometry"]).intersects(bounds)]
                closed = mask_for(raster, [transform(to_native, shape(f["geometry"]))
                                           for f in local_mpas + local_geas], buffer_m=100, all_touched=True)
                elevation, uncertainty, contributor = raster.read()
                strict = qualified_mask(elevation, uncertainty, contributor, rat,
                                        resolution_m=max(raster.res)) & ~closed
                sensitive = qualified_mask(elevation, uncertainty, contributor, rat,
                                           resolution_m=max(raster.res), max_uncertainty_m=2) & ~closed
                hard_by_release = defaultdict(list)
                for feature in locally_hard:
                    source_id = feature["properties"].get("release_id") or feature["properties"].get("block_id")
                    if not source_id:
                        raise ValueError("USGS hard-context feature lacks a source identity")
                    hard_by_release[source_id].append(
                        transform(to_native, shape(feature["geometry"])))
                release_rows = []
                unavailable_original_classes = []
                overlap = np.zeros(strict.shape, dtype=bool)
                native_overlap = np.zeros(strict.shape, dtype=bool)
                for release_id, polygons in sorted(hard_by_release.items()):
                    inside = mask_for(raster, polygons)
                    overlap |= inside
                    candidate = sensitive & inside
                    if not any(row.get("release_id") == release_id and row.get("kind") == "seafloor_character"
                               and row.get("status") == "ok"
                               and box(*row["raster_bounds_wgs84"]).intersects(bounds)
                               for row in original_products):
                        unavailable_original_classes.append(release_id)
                        continue
                    native_hard, usgs_sources = original_usgs_class(
                        release_id, raster, bounds, original_products, usgs_cache)
                    native_overlap |= native_hard
                    native_candidate = sensitive & native_hard
                    ids, counts = np.unique(contributor[candidate], return_counts=True)
                    release_rows.append({"usgs_release_id": release_id,
                                         "display_hard_polygons": len(polygons),
                                         "original_usgs_class_sources": [
                                             {"archive_sha256": row["archive_sha256"],
                                              "metadata_sha256": row["metadata_sha256"]}
                                             for row in usgs_sources],
                                         "strict_1m_overlap_pixels": int((strict & inside).sum()),
                                         "sensitivity_2m_overlap_pixels": int(candidate.sum()),
                                         "strict_1m_original_class3_pixels": int((strict & native_hard).sum()),
                                         "sensitivity_2m_original_class3_pixels": int(native_candidate.sum()),
                                         "nbs_contributors": [{"id": int(ident),
                                                               "source_survey_id": rat[int(ident)]["source_survey_id"],
                                                               "survey_date_end": rat[int(ident)]["survey_date_end"],
                                                               "pixels": int(count)}
                                                              for ident, count in zip(ids, counts)]})
                combined = sensitive & overlap
                native_combined = sensitive & native_overlap
                tiles.append({"tile": tile, "resolution_m": list(raster.res),
                              "source_raster_sha256": checked["raster_sha256"],
                              "source_rat_sha256": checked["rat_sha256"],
                              "closure_polygons_intersecting_tile": len(local_mpas) + len(local_geas),
                              "original_class_releases_not_audited": unavailable_original_classes,
                              "strict_1m_measured_pixels_outside_closures": int(strict.sum()),
                              "sensitivity_2m_measured_pixels_outside_closures": int(sensitive.sum()),
                              "strict_1m_hard_overlap_unique_pixels": int((strict & overlap).sum()),
                              "sensitivity_2m_hard_overlap_unique_pixels": int(combined.sum()),
                              "sensitivity_2m_hard_overlap_area_km2": round(float(combined.sum()) * abs(raster.res[0] * raster.res[1]) / 1e6, 5),
                              "strict_1m_original_class3_unique_pixels": int((strict & native_overlap).sum()),
                              "sensitivity_2m_original_class3_unique_pixels": int(native_combined.sum()),
                              "sensitivity_2m_original_class3_area_km2": round(float(native_combined.sum()) * abs(raster.res[0] * raster.res[1]) / 1e6, 5),
                              "usgs_releases": release_rows})
        rows.append({"sector_id": sector["sector_id"], "tiles": tiles})
    return {"schema_version": 1, "scope": "central-nbs-usgs-hard-source-review",
            "reviewed_at": datetime.now(timezone.utc).isoformat(), "status": "research-leads-only",
            "scheme_sha256": digest(scheme), "usgs_context_sha256": digest(hard_path),
            "usgs_original_audit_sha256": digest(usgs_audit_path),
            "usgs_map_audit_sha256": digest(map_audit_path) if map_audit_path else None,
            "cdfw_mpa_retrieved_at": mpas["sources"]["mpas"]["data_retrieved_at"],
            "noaa_federal_retrieved_at": federal["retrieved_at"],
            "method": "Actual NBS MLLW measured-contributor cells at 25–200 ft; supplied uncertainty plus 2 m planning margin. Strict 1 m and research-only 2 m sensitivity. Compare 20 m display-generalized USGS hard polygons with separately hash-checked original 2 m USGS class-3 raster; 100 m conservative MPA/GEA buffers.",
            "fishing_target": False, "exportable": False,
            "limitations": ["Counts can overlap across USGS releases and neighboring NBS tiles; unique counts are per tile only.",
                            "Original-class counts exclude releases without an audited original class grid; the tile lists those releases explicitly.",
                            "Original USGS class is sampled at NBS 4 m cell centers with nearest-neighbor category transfer; this is a cross-source screen, not an independent position-accuracy estimate.",
                            "USGS class and NBS contributors are historical; original contributor products, source hazard reports and legal access must be inspected before any target.",
                            "NBS Modeling is a test-and-evaluation compilation, not a navigation chart or independent original sounding.",
                            "A measured hard overlap is habitat context, not fish presence, a catch prediction, legal clearance or a waypoint."],
            "sectors": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=Path("dist/data/nbs-central-multiple-camera-tile-review.json"))
    parser.add_argument("--scheme", type=Path, default=Path("var/modeling-tile-scheme-20260923.gpkg"))
    parser.add_argument("--cache", type=Path, default=Path("var/nbs-cache"))
    parser.add_argument("--hard", type=Path, default=Path("dist/data/usgs-hard-context-central.geojson"))
    parser.add_argument("--usgs-audit", type=Path, default=Path("var/usgs-doi-native-audit.json"))
    parser.add_argument("--usgs-cache", type=Path, default=Path("var/usgs-doi-native-cache"))
    parser.add_argument("--mpas", type=Path, default=Path("var/qualification-current/coastal/latest.json"))
    parser.add_argument("--federal", type=Path, default=Path("dist/data/noaa-federal-areas.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    hard = json.loads(args.hard.read_text())
    usgs_audit = json.loads(args.usgs_audit.read_text())
    result = build(json.loads(args.review.read_text()), args.scheme, args.cache, hard, args.hard,
                   usgs_audit, args.usgs_audit, args.usgs_cache,
                   json.loads(args.mpas.read_text()), json.loads(args.federal.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(args.output)
    print(sum(t["sensitivity_2m_hard_overlap_unique_pixels"] for s in result["sectors"] for t in s["tiles"]),
          "tile-level research overlap pixels; no fishing targets")


if __name__ == "__main__":
    main()
