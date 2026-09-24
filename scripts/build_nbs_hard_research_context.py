"""Build limited Central Coast research outlines from reviewed NBS/USGS overlap.

These are historical physical-context areas at a relaxed 2 m *research* screen,
not fishing points, target-qualified depths, routes or legal permission.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from affine import Affine
from pyproj import Transformer
import rasterio
from rasterio.features import shapes
from scipy.ndimage import label
from shapely import make_valid
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

from scripts.audit_nbs_modeling_tile import audit, contributors, qualified_mask
from scripts.review_nbs_hard_overlap import current_federal, mask_for, original_usgs_class, digest


def compile_context(review, scheme, cache, hard_context, usgs_audit, usgs_cache, mpas, federal,
                    *, sector_ids=("cambria-morro", "monterey-sur"), max_per_tile=10,
                    minimum_area_m2=2500):
    if (review.get("scope") != "central-nbs-usgs-hard-source-review"
            or review.get("status") != "research-leads-only"
            or review["scheme_sha256"] != digest(scheme)):
        raise ValueError("Reviewed source overlap or scheme changed")
    mpa_record = mpas["sources"]["mpas"]
    checked = datetime.fromisoformat(mpa_record["data_retrieved_at"].replace("Z", "+00:00"))
    if (mpa_record["status"] != "ok" or not 0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 36 * 3600
            or len(mpa_record["data"]["geojson"]["features"]) < 100):
        raise ValueError("Fresh complete CDFW MPA polygons required")
    geas = current_federal(federal)
    mpa_features = mpa_record["data"]["geojson"]["features"]
    hard_features = hard_context["features"]
    output, omitted = [], 0
    for sector in review["sectors"]:
        if sector["sector_id"] not in sector_ids:
            continue
        for source_tile in sector["tiles"]:
            if source_tile["sensitivity_2m_original_class3_unique_pixels"] * 16 < minimum_area_m2:
                continue
            tile = source_tile["tile"]
            checked_tile = audit(scheme, tile, cache)
            if (checked_tile["raster_sha256"] != source_tile["source_raster_sha256"]
                    or checked_tile["rat_sha256"] != source_tile["source_rat_sha256"]):
                raise ValueError("NBS tile changed after overlap review: " + tile)
            with rasterio.open(cache / f"{tile}.tiff") as raster:
                to_geo = Transformer.from_crs(raster.crs, 4326, always_xy=True).transform
                to_native = Transformer.from_crs(4326, raster.crs, always_xy=True).transform
                bounds = transform(to_geo, box(*raster.bounds))
                local_hard = sorted({f["properties"]["release_id"] for f in hard_features
                                     if shape(f["geometry"]).intersects(bounds)})
                local_closures = [f for f in mpa_features + geas if shape(f["geometry"]).intersects(bounds)]
                closure_shapes = [transform(to_native, shape(f["geometry"])) for f in local_closures]
                closed = mask_for(raster, closure_shapes, buffer_m=100, all_touched=True)
                class3 = np.zeros(closed.shape, dtype=bool)
                usgs_sources = []
                for release_id in local_hard:
                    cells, originals = original_usgs_class(
                        release_id, raster, bounds, usgs_audit["products"], usgs_cache)
                    class3 |= cells
                    usgs_sources.extend({"release_id": release_id, "archive_sha256": row["archive_sha256"],
                                         "metadata_url": row["metadata_url"]} for row in originals)
                elevation, uncertainty, contributor = raster.read()
                supported = (qualified_mask(elevation, uncertainty, contributor,
                                            contributors(cache / f"{tile}.tiff.aux.xml"),
                                            max_uncertainty_m=2, resolution_m=max(raster.res))
                             & class3 & ~closed)
                if int(supported.sum()) != source_tile["sensitivity_2m_original_class3_unique_pixels"]:
                    raise ValueError("Source-overlap count changed: " + tile)
                block = 5  # A displayed 20 m square requires all 25 measured 4 m cells.
                coarse_height, coarse_width = raster.height // block, raster.width // block
                conservative = supported[:coarse_height * block, :coarse_width * block].reshape(
                    coarse_height, block, coarse_width, block).all(axis=(1, 3))
                labels, count = label(conservative)
                areas = np.bincount(labels[conservative], minlength=count + 1)
                ranked = sorted((int(areas[index]), index) for index in range(1, count + 1)
                                if areas[index] * abs(raster.res[0] * raster.res[1]) * block * block >= minimum_area_m2)
                ranked.reverse()
                omitted += max(0, len(ranked) - max_per_tile)
                exclusion = unary_union([g.buffer(100) for g in closure_shapes]) if closure_shapes else None
                for pixels, index in ranked[:max_per_tile]:
                    component = labels == index
                    parts = [shape(geometry) for geometry, value in shapes(component.astype("uint8"),
                             mask=component, transform=raster.transform * Affine.scale(block, block)) if value == 1]
                    if len(parts) != 1:
                        raise ValueError("Connected component polygonization changed")
                    display = make_valid(parts[0])
                    if display.is_empty or not display.is_valid or (exclusion is not None and display.intersects(exclusion)):
                        raise ValueError("Research display footprint escaped closure/validity screen")
                    fine_component = np.repeat(np.repeat(component, block, axis=0), block, axis=1)
                    fine_component = np.pad(fine_component, ((0, raster.height - fine_component.shape[0]),
                                                             (0, raster.width - fine_component.shape[1])))
                    local_depth = -elevation[fine_component] / .3048
                    effective = (-elevation[fine_component] + uncertainty[fine_component] + 2) / .3048
                    if not np.isfinite(local_depth).all() or effective.max() > 200.0001:
                        raise ValueError("Research component escaped depth-plus-uncertainty screen")
                    wgs = make_valid(transform(to_geo, display))
                    if wgs.is_empty or not wgs.is_valid:
                        raise ValueError("Invalid research display geometry")
                    center = display.representative_point()
                    ident = hashlib.sha256(f"{tile}:{center.x:.1f}:{center.y:.1f}".encode()).hexdigest()[:10]
                    output.append({"type": "Feature", "geometry": mapping(wgs), "properties": {
                        "id": "nbs-usgs-" + ident, "sector_id": sector["sector_id"], "tile": tile,
                        "approx_display_area_m2": round(display.area), "support_native_cells": pixels * block * block,
                        "display_cell_m": round(float(block * max(raster.res))),
                        "measured_depth_ft_range": [round(float(local_depth.min()), 1), round(float(local_depth.max()), 1)],
                        "maximum_depth_with_uncertainty_and_margin_ft": round(float(effective.max()), 1),
                        "maximum_supplied_uncertainty_m": round(float(uncertainty[fine_component].max()), 2),
                        "nbs_raster_url": checked_tile["raster_url"],
                        "nbs_raster_sha256": checked_tile["raster_sha256"],
                        "usgs_sources": usgs_sources,
                        "fishing_target": False, "exportable": False, "legal_clearance": False,
                        "fish_confirmed": False, "depth_qualified_for_target": False}})
    return {"type": "FeatureCollection", "schema_version": 1,
            "scope": "central-nbs-usgs-hard-research-context", "coast_id": "central",
            "compiled_at": datetime.now(timezone.utc).isoformat(),
            "source_review": "data/nbs-central-usgs-hard-overlap-review.json",
            "mpa_screened_at": mpa_record["data_retrieved_at"],
            "federal_screened_at": federal["retrieved_at"],
            "minimum_component_area_m2": minimum_area_m2, "maximum_displayed_per_tile": max_per_tile,
            "sector_ids": list(sector_ids),
            "omitted_smaller_or_lower_ranked_components": omitted,
            "method": "Original 2 m USGS class-3 pixels sampled at NOAA NBS 4 m measured-contributor cells; 25–200 ft MLLW with supplied uncertainty <=2 m and 2 m planning margin; complete 100 m MPA/GEA buffers. Each displayed 20 m square requires all 25 underlying 4 m cells to pass; largest connected components only.",
            "limitations": ["Research sensitivity tier, not the existing 1 m target qualification policy.",
                            "Historical USGS classes and compiled NBS cells are not independent confirmations of fish, recent bottom stability or catch success.",
                            "Original NBS contributor provenance, present chart hazards, routes, species rules and access need review before any point or export.",
                            "No fishing target, legal clearance or navigation claim; recheck current MPA and GEA boundaries."],
            "features": output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=Path("dist/data/nbs-central-usgs-hard-overlap-review.json"))
    parser.add_argument("--scheme", type=Path, default=Path("var/modeling-tile-scheme-20260923.gpkg"))
    parser.add_argument("--cache", type=Path, default=Path("var/nbs-cache"))
    parser.add_argument("--hard", type=Path, default=Path("dist/data/usgs-hard-context-central.geojson"))
    parser.add_argument("--usgs-audit", type=Path, default=Path("var/usgs-doi-native-audit.json"))
    parser.add_argument("--usgs-cache", type=Path, default=Path("var/usgs-doi-native-cache"))
    parser.add_argument("--mpas", type=Path, default=Path("var/qualification-current/coastal/latest.json"))
    parser.add_argument("--federal", type=Path, default=Path("dist/data/noaa-federal-areas.json"))
    parser.add_argument("--output", type=Path, default=Path("dist/data/central-nbs-usgs-hard-research-context.geojson"))
    args = parser.parse_args()
    result = compile_context(json.loads(args.review.read_text()), args.scheme, args.cache,
                             json.loads(args.hard.read_text()), json.loads(args.usgs_audit.read_text()),
                             args.usgs_cache, json.loads(args.mpas.read_text()),
                             json.loads(args.federal.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    temporary.replace(args.output)
    print(len(result["features"]), "research outlines; zero fishing targets")


if __name__ == "__main__":
    main()
