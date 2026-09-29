#!/usr/bin/env python3
"""Screen direct-VDatum Estero source cells against independent 2008 bottom class.

Block-center VDatum offsets and horizontal alignment remain nominal. This audit
does not qualify chart depths or publish private research geometry.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from scipy.ndimage import binary_erosion, label
from shapely.geometry import shape

from research.lib.paths import ROOT

from research.scripts.audit_estero_wgs84_direct import check_inputs, stable
from research.scripts.audit_estero_2012_2008_overlap import original_character
from research.scripts.audit_point_estero_original_pair import PIN as CLASS_PIN
from skippercast.platform.contracts import atomic_json


BLOCKS = ROOT / "var/review/estero-nominal-research-blocks.geojson"
PRIVATE_OFFSETS = ROOT / "var/review/estero-wgs84-direct-vdatum-blocks.json"
SOURCE_RECEIPT = ROOT / "research/receipts/estero-wgs84-direct-vdatum-review.json"
DEPTH = ROOT / "var/review/estero-bay-2012/WGS84_utm10_EsteroBay.zip"
METADATA = ROOT / "var/review/estero-bay-2012/WGS84_metadata_EsteroBay.xml"
CHARACTER = ROOT / "var/review/usgs-point-estero/SeafloorCharacter_OffshorePointEstero.zip"
OUTPUT = ROOT / "research/receipts/estero-wgs84-2008-character-sensitivity.json"
RADII_M = (10, 25)
CLASS_NAMES = {1: "soft_flat", 2: "hard_flat", 3: "hard_rugose"}


def disk(radius_m: int, resolution_m: int = 2) -> np.ndarray:
    reach = math.ceil(radius_m / resolution_m)
    y, x = np.ogrid[-reach:reach + 1, -reach:reach + 1]
    return (x * resolution_m) ** 2 + (y * resolution_m) ** 2 <= radius_m ** 2


def checked_offsets(blocks: dict, private: dict, receipt: dict) -> list[dict]:
    rows = private.get("blocks", [])
    if (private.get("scope") != "private-estero-direct-vdatum-blocks"
            or receipt.get("scope") != "estero-2012-original-wgs84-direct-vdatum-research"
            or receipt.get("sample_count") != 60 or len(rows) != len(blocks["features"])):
        raise ValueError("Pinned direct-VDatum research sample set changed")
    totals = Counter()
    for index, (feature, row) in enumerate(zip(blocks["features"], rows)):
        if (row["block_index"] != index or row["band"] != feature["properties"]["band"]
                or row["vdatum"].get("response", {}).get("s_h_frame") != "WGS84_G1150"
                or row["vdatum"].get("response", {}).get("t_v_frame") != "MLLW"
                or not 35 < row["vdatum"]["offset_m"] < 37
                or not 0 < row["vdatum"]["transform_uncertainty_m"] < 1):
            raise ValueError("Private Estero block/VDatum identity changed")
        totals[row["band"]] += row["nominal_center_offset_200_300ft_cells"]
    for band, count in totals.items():
        if receipt["by_prior_nominal_band"][band]["nominal_center_offset_200_300ft_cells"] != count:
            raise ValueError("Private offsets no longer match public VDatum receipt")
    return rows


def audit(blocks: dict, private: dict, receipt: dict, depth_zip: Path,
          metadata: Path, character_zip: Path) -> dict:
    block_fingerprint = check_inputs(blocks, depth_zip, metadata)
    offsets = checked_offsets(blocks, private, receipt)
    character_path = original_character(character_zip)
    summary = defaultdict(Counter)
    source_path = f"/vsizip/{depth_zip.resolve()}/wgs84_utm10_esterobay.asc"
    with rasterio.open(source_path) as depth, rasterio.open(character_path) as character:
        if (depth.shape != (16020, 11456) or depth.res != (2.0, 2.0)
                or depth.nodata != -9999 or depth.bounds.left != 665810
                or character.crs.to_epsg() != 32610 or character.res != (2.0, 2.0)
                or character.nodata != 255):
            raise ValueError("Original Estero source layout changed")
        footprints = {radius: disk(radius) for radius in RADII_M}
        for feature, offset in zip(blocks["features"], offsets):
            bounds = shape(feature["geometry"]).bounds
            band = feature["properties"]["band"]
            c = summary[band]
            source_window = from_bounds(*bounds, transform=depth.transform).round_offsets().round_lengths()
            cells = depth.read(1, window=source_window, masked=True)
            rows, cols = np.indices(cells.shape)
            transform = depth.window_transform(source_window)
            xs = transform.c + (cols + 0.5) * transform.a
            ys = transform.f + (rows + 0.5) * transform.e
            in_block = ((xs >= bounds[0]) & (xs < bounds[2]) &
                        (ys >= bounds[1]) & (ys < bounds[3]))
            valid = in_block & ~np.ma.getmaskarray(cells)
            c["valid_original_source_cells"] += int(valid.sum())
            nominal_depth = -(np.asarray(cells) + offset["vdatum"]["offset_m"])
            selected = valid & (nominal_depth >= 60.96) & (nominal_depth <= 91.44)
            if int(selected.sum()) != offset["nominal_center_offset_200_300ft_cells"]:
                raise ValueError("Direct-VDatum block cell count changed")
            c["nominal_200_300ft_cells"] += int(selected.sum())
            # Class window includes a margin beyond the largest 25 m test.
            halo = max(RADII_M) + 4
            class_window = from_bounds(bounds[0] - halo, bounds[1] - halo,
                                       bounds[2] + halo, bounds[3] + halo,
                                       transform=character.transform).round_offsets().round_lengths()
            classes = character.read(1, window=class_window, boundless=True, fill_value=255)
            eroded = {radius: binary_erosion(classes == 3, structure=footprint,
                                             border_value=0)
                      for radius, footprint in footprints.items()}
            selected_rows, selected_cols = np.nonzero(selected)
            if not selected_rows.size:
                continue
            selected_xs = xs[selected_rows, selected_cols]
            selected_ys = ys[selected_rows, selected_cols]
            class_cols = np.floor((selected_xs - character.bounds.left) / 2).astype(int)
            class_rows = np.floor((character.bounds.top - selected_ys) / 2).astype(int)
            local_cols = class_cols - int(class_window.col_off)
            local_rows = class_rows - int(class_window.row_off)
            inside = ((local_cols >= 0) & (local_cols < classes.shape[1]) &
                      (local_rows >= 0) & (local_rows < classes.shape[0]))
            codes = np.full(selected_rows.size, 255, dtype=np.uint8)
            codes[inside] = classes[local_rows[inside], local_cols[inside]]
            for code, name in CLASS_NAMES.items():
                c[name + "_cells"] += int(np.count_nonzero(codes == code))
            rugged = codes == 3
            for radius in RADII_M:
                stable_class = np.zeros(selected_rows.size, dtype=bool)
                stable_class[inside] = eroded[radius][local_rows[inside], local_cols[inside]]
                stable_cells = rugged & stable_class
                c[f"rugose_class_stable_within_{radius}m_cell_centers"] += int(np.count_nonzero(stable_cells))
                if radius == 25 and np.any(stable_cells):
                    # This is deliberately per block. Components crossing a block edge
                    # are split, making the reported maximum a conservative lower bound.
                    patch = np.zeros(cells.shape, dtype=bool)
                    patch[selected_rows[stable_cells], selected_cols[stable_cells]] = True
                    components, n_components = label(patch, structure=np.ones((3, 3), dtype=int))
                    sizes = np.bincount(components[patch], minlength=n_components + 1)[1:]
                    c["within_block_25m_stable_component_count"] += int(n_components)
                    c["largest_within_block_25m_stable_component_cells"] = max(
                        c["largest_within_block_25m_stable_component_cells"], int(sizes.max()))
    bands = {key: dict(sorted(values.items())) for key, values in sorted(summary.items())}
    for band in bands.values():
        for key in ("valid_original_source_cells", "nominal_200_300ft_cells"):
            if band.get(key, 0) <= 0:
                raise ValueError("Original Estero block screen empty")
        for name in CLASS_NAMES.values():
            band.setdefault(name + "_cells", 0)
        for radius in RADII_M:
            band.setdefault(f"rugose_class_stable_within_{radius}m_cell_centers", 0)
        band.setdefault("within_block_25m_stable_component_count", 0)
        band.setdefault("largest_within_block_25m_stable_component_cells", 0)
    return {
        "schema_version": 1,
        "scope": "estero-wgs84-direct-vdatum-2008-independent-character-sensitivity",
        "source_2012": "https://doi.org/10.3133/ofr20131225",
        "source_2008": "https://doi.org/10.5066/P9ZSTUK1",
        "source_depth_archive_sha256": receipt["source_archive_sha256"],
        "source_depth_metadata_sha256": receipt["source_metadata_sha256"],
        "source_character_archive_sha256": CLASS_PIN[character_zip.name],
        "private_block_fingerprint": block_fingerprint,
        "private_vdatum_receipt_sha256": hashlib.sha256(private_path_bytes(private)).hexdigest(),
        "nominal_conversion": "2012 WGS84(G1150) ellipsoid height plus one NOAA VDatum MLLW offset per 100 m block; epoch 2012.6 assumed",
        "character_source": "independent 2008 USGS video-supervised 2 m class grid",
        "character_sensitivity_radii_m": list(RADII_M),
        "by_prior_research_band": bands,
        "full_cellwise_mllw_surface_verified": False,
        "source_product_upper_uncertainty_verified": False,
        "cross_survey_horizontal_registration_bounded": False,
        "independent_fish_evidence_on_cells_verified": False,
        "full_route_and_fishing_date_cleared": False,
        "qualified_waypoints": 0,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "Each 100 m block uses a single VDatum center offset and an assumed coordinate epoch; this is not a cellwise chart-MLLW depth surface or its upper error bound.",
            "The 2008 and 2012 rasters have different survey/frame lineages; their achieved relative horizontal registration and seafloor change remain unresolved.",
            "The 10 m/25 m erosion tests concern 2008 class-pixel centers only. They are sensitivity distances, not measured cross-survey position error or full candidate-patch clearance.",
            "Connected 25 m-stable cells are grouped within each separate 100 m research block; groups crossing block boundaries are split and the largest size is only a lower bound for nominal class continuity, not surveyed rock area.",
            "USGS class 3 is a video-supervised historical interpretation, not an independent 2012 rock survey or a fish-presence estimate.",
            "Only aggregate counts leave the private block workspace; no coordinates, spot ranks or exports are approved.",
        ],
    }


def private_path_bytes(private: dict) -> bytes:
    """Stable hash of reviewed offsets, excluding only retrieval time/formatting."""
    stable_private = {key: value for key, value in private.items() if key != "checked_at"}
    return json.dumps(stable_private, sort_keys=True, separators=(",", ":")).encode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=Path, default=BLOCKS)
    parser.add_argument("--private-offsets", type=Path, default=PRIVATE_OFFSETS)
    parser.add_argument("--source-receipt", type=Path, default=SOURCE_RECEIPT)
    parser.add_argument("--depth", type=Path, default=DEPTH)
    parser.add_argument("--metadata", type=Path, default=METADATA)
    parser.add_argument("--character", type=Path, default=CHARACTER)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = audit(json.loads(args.blocks.read_text()),
                   json.loads(args.private_offsets.read_text()),
                   json.loads(args.source_receipt.read_text()),
                   args.depth, args.metadata, args.character)
    if args.verify and stable(result) != stable(json.loads(args.verify.read_text())):
        raise SystemExit("Estero direct-datum/independent-class join changed; review before use")
    atomic_json(args.output, result)
    print(json.dumps({"bands": result["by_prior_research_band"], "fishing_target": False}))


if __name__ == "__main__":
    main()
