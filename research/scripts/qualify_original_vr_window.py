#!/usr/bin/env python3
"""Private bounded native-cell qualification for an original VR BAG.

This research CLI is intentionally outside product/runtime imports. It reads
the producer BAG and emits source-cell rows with original GDAL affine,
elevation, uncertainty, and resolution. It never creates a raster.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

import h5py
import numpy as np
import rasterio
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from skippercast.platform.bottom_targets import bag_metadata, cells_qualified, vr_transform  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_source_hash(path: Path, expected: str) -> str:
    actual = sha256(path)
    if len(expected) != 64 or actual != expected.lower():
        raise ValueError("source SHA-256 mismatch")
    return actual


def add_selected(current: int, added: int, limit: int) -> int:
    total = current + added
    if limit < 1 or limit > 262144 or total > limit:
        raise ValueError("selected native-cell limit exceeded")
    return total


def add_full_grid_slots(current: int, grid_slots: int, limit: int) -> int:
    total = current + grid_slots
    if grid_slots < 1 or limit < 1 or limit > 262144 or total > limit:
        raise ValueError("full native supergrid-slot limit exceeded")
    return total


def bounds_intersect(a, b) -> bool:
    aw, as_, ae, an = a
    bw, bs, be, bn = b
    return aw < be and ae > bw and as_ < bn and an > bs


def native_resolution_allowed(dx: float, dy: float, policy: str) -> bool:
    if policy == "exact-1-2-4m":
        return dx in (1.0, 2.0, 4.0) and dy in (1.0, 2.0, 4.0)
    if policy == "source-native-1-to-4m-band":
        return 1.0 <= dx <= 4.0 and 1.0 <= dy <= 4.0
    raise ValueError("unknown native spacing policy")


def semantic_projected_crs_matches(source: CRS, expected: CRS) -> bool:
    if not source.is_projected or not expected.is_projected:
        return False
    if any(axis.unit_name.lower() not in ("metre", "meter") for axis in source.axis_info + expected.axis_info):
        return False
    source_base = source.source_crs if source.is_bound else source
    expected_base = expected.source_crs if expected.is_bound else expected
    return bool(source_base and expected_base and source_base.equals(expected_base, ignore_axis_order=True))


def native_qualified_mask(elevation, uncertainty, resolution_x, resolution_y, inside,
                          qualification_mode="direct-depth", planning_margin_m=None,
                          spacing_policy="exact-1-2-4m"):
    if not native_resolution_allowed(resolution_x, resolution_y, spacing_policy):
        raise ValueError("unsupported native resolution")
    if qualification_mode == "direct-depth" and planning_margin_m is not None:
        raise ValueError("direct-depth mode does not accept a planning margin")
    elevation = np.asarray(elevation)
    uncertainty = np.asarray(uncertainty)
    inside = np.asarray(inside, dtype=bool)
    if elevation.shape != uncertainty.shape or elevation.shape != inside.shape:
        raise ValueError("source bands and window mask must have matching shapes")
    finite = (np.isfinite(elevation) & (elevation < 0) & (elevation > -3000) &
              np.isfinite(uncertainty) & (uncertainty > 0) & (uncertainty < 100))
    if qualification_mode == "direct-depth":
        qualified = (np.isfinite(elevation) & np.isfinite(uncertainty) &
                     (-elevation >= 25 * .3048) & (-elevation <= 300 * .3048) &
                     (uncertainty > 0) & (uncertainty <= 1.0))
    elif qualification_mode == "uncertainty-plus-planning-margin":
        if planning_margin_m is None or not math.isfinite(planning_margin_m) or planning_margin_m <= 0:
            raise ValueError("legacy margin mode requires a positive explicit planning margin")
        qualified = cells_qualified(elevation, uncertainty, max(resolution_x, resolution_y),
                                    limit_ft=300, minimum_ft=25,
                                    planning_margin_m=planning_margin_m, maximum_uncertainty_m=1)
    else:
        raise ValueError("unknown qualification mode")
    return finite, qualified & finite & inside


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bag", type=Path, required=True)
    p.add_argument("--expected-sha256", required=True)
    p.add_argument("--survey-id", required=True)
    p.add_argument("--expected-crs", required=True, help="Expected authority, e.g. EPSG:26911")
    window = p.add_mutually_exclusive_group(required=True)
    window.add_argument("--window-wgs84", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    window.add_argument("--window-native", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                        help="Bounds in --expected-crs; use only when the source proof defined a native projected window")
    p.add_argument("--max-selected-cells", type=int, required=True)
    p.add_argument("--max-full-grid-cells", type=int, default=262144,
                   help="Separate bound on complete intersecting native supergrids before reading arrays")
    p.add_argument("--native-spacing-policy", choices=("exact-1-2-4m", "source-native-1-to-4m-band"),
                   default="exact-1-2-4m",
                   help="Keep exact 1/2/4m grids distinct from a bounded source-native spacing band")
    p.add_argument("--qualification-mode", choices=("direct-depth", "uncertainty-plus-planning-margin"),
                   default="direct-depth")
    p.add_argument("--planning-margin-m", type=float,
                   help="Required only for the separately named legacy margin qualification mode")
    p.add_argument("--output-dir", type=Path, required=True, help="New private directory; must not already exist")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    bag = args.bag.resolve()
    if not bag.is_file():
        raise SystemExit("FAIL CLOSED: missing source or required source SHA-256 mismatch")
    try:
        source_hash = verify_source_hash(bag, args.expected_sha256)
    except ValueError as exc:
        raise SystemExit(f"FAIL CLOSED: {exc}") from exc
    if not 1 <= args.max_selected_cells <= 262144:
        raise SystemExit("FAIL CLOSED: max-selected-cells must be 1..262144")
    if not 1 <= args.max_full_grid_cells <= 262144:
        raise SystemExit("FAIL CLOSED: max-full-grid-cells must be 1..262144")
    if args.qualification_mode == "direct-depth" and args.planning_margin_m is not None:
        raise SystemExit("FAIL CLOSED: direct-depth mode cannot take a planning margin")
    if args.qualification_mode == "uncertainty-plus-planning-margin" and (
            args.planning_margin_m is None or not math.isfinite(args.planning_margin_m) or args.planning_margin_m <= 0):
        raise SystemExit("FAIL CLOSED: legacy margin mode requires a positive explicit planning margin")
    requested_window = args.window_wgs84 or args.window_native
    west, south, east, north = requested_window
    if not all(map(math.isfinite, requested_window)) or west >= east or south >= north:
        raise SystemExit("FAIL CLOSED: invalid window bounds")
    if args.window_wgs84 and not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise SystemExit("FAIL CLOSED: invalid WGS84 bounds")
    out = args.output_dir.resolve()
    if out.exists():
        raise SystemExit("FAIL CLOSED: output directory must be new; existing evidence is never overwritten")
    out.mkdir(parents=True)

    rows_out: list[dict] = []
    grid_records: list[dict] = []
    counts = {"selected_native_slots": 0, "full_intersecting_grid_slots": 0,
              "finite_source_cells": 0, "qualified_cells": 0}
    per_res: dict[str, dict[str, int]] = {}
    qualified_footprints = []
    with rasterio.open(bag) as overview, h5py.File(bag, "r") as h5:
        root = h5["BAG_root"]
        xml = root["metadata"][:].tobytes().decode().rstrip("\0")
        meta = bag_metadata(xml, args.survey_id, strict=True)
        crs = CRS.from_wkt(meta["horizontal_wkt"])
        if not crs.is_projected or any(axis.unit_name.lower() not in ("metre", "meter") for axis in crs.axis_info):
            raise SystemExit("FAIL CLOSED: embedded horizontal CRS must be projected in metres")
        expected = CRS.from_user_input(args.expected_crs)
        if not semantic_projected_crs_matches(crs, expected):
            raise SystemExit("FAIL CLOSED: expected CRS must semantically match the embedded projected metre CRS")
        forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        if args.window_wgs84:
            west_m, south_m = forward.transform(west, south)
            east_m, north_m = forward.transform(east, north)
        else:
            west_m, south_m, east_m, north_m = requested_window
        if not all(map(math.isfinite, (west_m, south_m, east_m, north_m))) or west_m >= east_m or south_m >= north_m:
            raise SystemExit("FAIL CLOSED: projected window is invalid")

        md = root["varres_metadata"][:]
        if args.native_spacing_policy == "exact-1-2-4m":
            mask = ((md["dimensions_x"] > 0) & (md["dimensions_y"] > 0) &
                    np.isin(md["resolution_x"], (1, 2, 4)) & np.isin(md["resolution_y"], (1, 2, 4)))
        else:
            mask = ((md["dimensions_x"] > 0) & (md["dimensions_y"] > 0) &
                    (md["resolution_x"] >= 1) & (md["resolution_x"] <= 4) &
                    (md["resolution_y"] >= 1) & (md["resolution_y"] <= 4))
        for rr, cc in np.argwhere(mask):
            row, col = int(rr), int(cc)
            m = md[row, col]
            nx, ny = int(m["dimensions_x"]), int(m["dimensions_y"])
            dx, dy = float(m["resolution_x"]), float(m["resolution_y"])
            metadata_affine = vr_transform(overview.bounds.left, overview.bounds.bottom,
                                           overview.res[0], overview.res[1], row, col, m)
            with rasterio.open(f"BAG:{bag}:supergrid:{row}:{col}") as ds:
                affine = ds.transform
                if ds.count != 2 or ds.shape != (ny, nx) or (affine.a, affine.b, affine.d, affine.e) != (dx, 0.0, 0.0, -dy):
                    raise SystemExit(f"FAIL CLOSED: native GDAL shape/band/resolution mismatch at {args.survey_id}:{row}:{col}")
                x0, y0 = affine.c, affine.f
                gdal_bounds = (x0, y0 - ny * dy, x0 + nx * dx, y0)
                if not bounds_intersect(gdal_bounds, (west_m, south_m, east_m, north_m)):
                    continue
                try:
                    counts["full_intersecting_grid_slots"] = add_full_grid_slots(
                        counts["full_intersecting_grid_slots"], nx * ny, args.max_full_grid_cells)
                except ValueError as exc:
                    raise SystemExit(f"FAIL CLOSED: {exc} before native band read") from exc
                elev = ds.read(1).astype("float64")
                unc = ds.read(2).astype("float64")
            yy, xx = np.indices((ny, nx))
            xc, yc = affine * (xx + .5, yy + .5)
            inside = (xc >= west_m) & (xc < east_m) & (yc >= south_m) & (yc < north_m)
            selected = int(inside.sum())
            try:
                counts["selected_native_slots"] = add_selected(counts["selected_native_slots"], selected, args.max_selected_cells)
                finite, qualified = native_qualified_mask(
                    elev, unc, dx, dy, inside, args.qualification_mode, args.planning_margin_m,
                    args.native_spacing_policy)
            except ValueError as exc:
                raise SystemExit(f"FAIL CLOSED: {exc}") from exc
            counts["finite_source_cells"] += int((finite & inside).sum())
            counts["qualified_cells"] += int(qualified.sum())
            key = f"{dx:g}x{dy:g}m"
            bucket = per_res.setdefault(key, {"selected_native_slots": 0, "finite_source_cells": 0, "qualified_cells": 0})
            bucket["selected_native_slots"] += selected
            bucket["finite_source_cells"] += int((finite & inside).sum())
            bucket["qualified_cells"] += int(qualified.sum())
            grid_records.append({
                "supergrid_id": f"{args.survey_id}:{row}:{col}", "resolution_m": [dx, dy],
                "shape_rows_cols": [ny, nx], "native_gdal_transform": [float(v) for v in tuple(affine)[:6]],
                "metadata_derived_transform": [float(v) for v in tuple(metadata_affine)[:6]],
                "metadata_origin_delta_m": [float(metadata_affine.c - affine.c), float(metadata_affine.f - affine.f)],
            })
            for i, j in zip(*np.nonzero(qualified)):
                px0, py1 = affine * (int(j), int(i))
                px1, py0 = affine * (int(j) + 1, int(i) + 1)
                qualified_footprints.append(box(min(px0, px1), min(py0, py1), max(px0, px1), max(py0, py1)))
                rows_out.append({
                    "source_cell_id": f"{args.survey_id}:{row}:{col}:{int(i)}:{int(j)}",
                    "supergrid_id": f"{args.survey_id}:{row}:{col}", "cell_row": int(i), "cell_col": int(j),
                    "native_resolution_m": [dx, dy], "native_gdal_transform": [float(v) for v in tuple(affine)[:6]],
                    "footprint_bounds_projected_m": [px0, py0, px1, py1],
                    "elevation_m_mllw": float(elev[i, j]), "product_uncertainty_m": float(unc[i, j]),
                })

    if counts["qualified_cells"] != len(rows_out) or len({r["source_cell_id"] for r in rows_out}) != len(rows_out):
        raise SystemExit("FAIL CLOSED: qualified cell inventory is inconsistent")
    window_geom = box(west_m, south_m, east_m, north_m)
    support = shapely.union_all(qualified_footprints) if qualified_footprints else shapely.Polygon()
    overlap_pairs = 0
    pairwise_overlap_area = 0.0
    if qualified_footprints:
        pair_i, pair_j = shapely.STRtree(qualified_footprints).query(qualified_footprints, predicate="intersects")
        upper = pair_i < pair_j
        pair_i, pair_j = pair_i[upper], pair_j[upper]
        if len(pair_i):
            areas = shapely.area(shapely.intersection(np.asarray(qualified_footprints, dtype=object)[pair_i],
                                                      np.asarray(qualified_footprints, dtype=object)[pair_j]))
            positive = areas > 0
            overlap_pairs = int(positive.sum())
            pairwise_overlap_area = float(areas[positive].sum())
    support_in = support.intersection(window_geom)
    uncovered = window_geom.difference(support)
    cell_path = out / "qualified-native-cells.jsonl.gz"
    with gzip.open(cell_path, "wt", encoding="utf-8", compresslevel=6) as stream:
        for record in rows_out:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")
    receipt = {
        "schema_version": 1, "scope": "private-original-vr-native-cell-qualification",
        "product_importable": False, "activation_or_publication": False,
        "survey_id": args.survey_id, "source_sha256": source_hash, "source_bytes": bag.stat().st_size,
        "embedded_metadata_sha256": meta["metadata_sha256"], "horizontal_crs": crs.to_string(),
        "vertical_datum": meta["vertical_datum"], "uncertainty_type": meta["uncertainty_type"],
        "effective_resolution": "unknown; stored cell spacing is not effective resolution",
        "interpolation_status": "unknown unless producer metadata explicitly states it",
        "window_input": {"crs": "EPSG:4326" if args.window_wgs84 else crs.to_string(), "bounds": requested_window},
        "wgs84_window_projection_operator": ("transform southwest and northeast corners only, then use their axis-aligned projected bounding box; not exact geographic polygon clipping"
                                               if args.window_wgs84 else "not applicable; caller supplied native projected rectangle"),
        "window_projected_m": [west_m, south_m, east_m, north_m],
        "selection": "native GDAL cell-center in half-open projected window",
        "max_selected_cells": args.max_selected_cells, "max_full_grid_cells": args.max_full_grid_cells,
        "native_spacing_policy": args.native_spacing_policy,
        "counts": counts, "by_resolution": per_res,
        "native_grid_records": grid_records,
        "qualified_footprint_audit": {
            "scope": "qualified original cell footprints only; not a full survey coverage model",
            "footprint_count": len(qualified_footprints),
            "sum_native_footprint_area_m2": float(sum(g.area for g in qualified_footprints)),
            "deduplicated_native_union_area_m2": float(support.area),
            "union_inside_window_m2": float(support_in.area),
            "uncovered_window_area_m2": float(uncovered.area),
            "positive_area_overlap_pairs": overlap_pairs,
            "pairwise_overlap_area_sum_m2": pairwise_overlap_area,
            "overlap_rule": "strict intersection area > 0; no epsilon",
        },
        "qualification": {"mode": args.qualification_mode, "minimum_depth_ft": 25, "maximum_depth_ft": 300,
                          "maximum_product_uncertainty_m": 1, "planning_margin_m": args.planning_margin_m,
                          "rule": ("nominal source depth independently in [25,300] ft and finite productUncert in (0,1] m"
                                   if args.qualification_mode == "direct-depth" else
                                   "legacy cells_qualified rule combines product uncertainty and explicit planning margin with upper depth cutoff")},
        "limitations": ["No interpolation, rasterization, smoothing, repair, or fabricated cells.",
                        "No habitat grade, public clearance, publication, activation, or measurement-credit claim."],
        "output": {"file": cell_path.name, "sha256": sha256(cell_path), "bytes": cell_path.stat().st_size,
                   "record_count": len(rows_out)},
    }
    receipt_path = out / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    (out / "receipt.sha256").write_text(f"{sha256(receipt_path)}  receipt.json\n")
    print(json.dumps({"receipt": str(receipt_path), "receipt_sha256": sha256(receipt_path),
                      "counts": counts, "by_resolution": per_res}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
