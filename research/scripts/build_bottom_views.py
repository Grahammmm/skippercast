"""Compile small, masked survey windows. Run with the optional GIS environment.

See docs/seabed-views.md for the held Morro Bay manifest and output layout.
Local source paths are never included in output. No interpolation fills gaps.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio.windows import Window
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from skippercast.platform.contracts import REPO, atomic_json, load_catalogs, load_region, read_json, within


# Original GeoTIFF digests from the committed Morro Bay bottom index (not ZIP digests).
# The product-level review in research/receipts/usgs-depth-datum-ledger.json
# finds no declared datum in these TIFFs. The report's MLLW does not apply here.
MORRO_PRODUCTS = {
    "PointBuchon": ("usgs-point-buchon", "6c43b4661c1d90bd201b4ca8f3a4032ad90eb05d62ed817cae0b2dc8e6e2ed65"),
    "MorroBay": ("usgs-morro-bay", "4da54faeca049274ae2772a426f7637a26051ea5680c2cd674d483748c984547"),
    "PointEstero": ("usgs-point-estero", "8cbd047609c6dc38163335136a97eb014dbac22e93aa56140bb5a2539a83ed2b"),
}
UNVERIFIED_DATUM = "unverified source datum"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--region", required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--held-output", type=Path, help="New private output directory outside the checkout")
    args = p.parse_args()
    region = load_region(args.region)
    _, sources = load_catalogs()
    atlas = read_json(within(REPO / "dist", region["assets"]["atlas"]))
    manifest = read_json(args.manifest)["sources"]
    if region["id"] == "morro-bay" and args.held_output is None:
        raise ValueError("Morro Bay products require private --held-output")
    relative_output = Path(region["assets"]["bottom_index"]).parent
    output = within(REPO / "dist", region["assets"]["bottom_index"]).parent
    if args.held_output is not None:
        held_root = args.held_output.resolve()
        if held_root.is_relative_to(REPO) or held_root.exists():
            raise ValueError("--held-output must be a new directory outside the checkout")
        output = within(held_root, relative_output)
    records, source_receipts = {}, {}
    prepared = []
    held_ids = {ident for ident, _ in MORRO_PRODUCTS.values()}
    # Validate the entire manifest before writing any tile, even in a mixed build.
    for name, spec in manifest.items():
        ident = spec["source_id"]
        reviewed = sources[ident]
        if reviewed["review_status"] != "approved" or ident not in region["source_bindings"]["bathymetry"]:
            raise ValueError("Seabed source is not approved and bound to this region")
        research_only = region["id"] == "morro-bay" or ident in held_ids
        datum = UNVERIFIED_DATUM if research_only else "MLLW"
        product = MORRO_PRODUCTS.get(name) if research_only else None
        if research_only:
            if product is None or product[0] != ident:
                raise ValueError(f"{name}: expected a reviewed Morro Bay product binding")
            if spec["vertical_datum"] != datum:
                raise ValueError(f"{name}: reviewed raster datum is {datum}, not MLLW")
            if args.held_output is None:
                raise ValueError("Morro Bay products require private --held-output")
        elif spec["vertical_datum"] != datum:
            raise ValueError("This adapter expects signed MLLW elevations in metres")
        path = Path(spec["path"])
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if product is not None and digest != product[1]:
            raise ValueError(f"{name}: raster SHA-256 differs from the reviewed product")
        source_receipts[ident] = {"sha256": digest, "bytes": path.stat().st_size,
                                  "url": reviewed["documentation_url"], "survey_year": spec["survey_year"]}
        prepared.append((name, path, datum, research_only, source_receipts[ident], ident))
    for name, path, datum, research_only, source, ident in prepared:
        with rasterio.open(path) as grid:
            if grid.crs is None or not grid.crs.is_projected or grid.crs.linear_units != "metre":
                raise ValueError("Expected a projected, metre-based survey grid")
            if abs(grid.res[0] - grid.res[1]) > 1e-6 or grid.res[0] > 2.01:
                raise ValueError("This detailed-view adapter requires square cells at 2 m or finer")
            transform = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
            for target in (t for t in atlas["targets"] if t["source_id"] == name):
                x, y = transform.transform(target["longitude"], target["latitude"])
                row, col = grid.index(x, y)
                half = 64
                elevations = grid.read(1, window=Window(col-half, row-half, 129, 129), boundless=True, masked=True)
                mask = np.ma.getmaskarray(elevations) | ~np.isfinite(elevations.data)
                mask |= (elevations.data > 0) | (elevations.data < -3000)
                valid = elevations.data[~mask]
                if not len(valid) or mask[half, half]:
                    records[target["id"]] = {"status": "unavailable", "reason": "Survey gap at target center"}
                    continue
                # Signed 0.1 m elevations. -32768 is the only nodata value.
                encoded = np.full(elevations.shape, -32768, dtype="<i2")
                encoded[~mask] = np.rint(elevations.data[~mask] * 10).astype("<i2")
                item = {"schema_version": 1, "region_id": region["id"], "target_id": target["id"],
                        "source_id": ident, "source_sha256": source["sha256"], "source_url": source["url"],
                        "survey_year": source["survey_year"], "vertical_datum": datum, "horizontal_crs": str(grid.crs),
                        "width": 129, "height": 129, "cell_m": grid.res[0], "native_cell_m": grid.res[0],
                        "span_m": 128 * grid.res[0], "center_pixel": [64, 64],
                        "target_offset_m": [round(x-grid.xy(row,col)[0], 3), round(y-grid.xy(row,col)[1], 3)],
                        "coverage_fraction": round(float((~mask).mean()), 4),
                        "depth_range_ft": [round(float(-valid.max())*3.28084, 1), round(float(-valid.min())*3.28084, 1)],
                        "relief_m": round(float(valid.max()-valid.min()), 2),
                        "encoding": "base64-int16-le", "elevation_unit_m": 0.1, "nodata": -32768,
                        "elevations": base64.b64encode(encoded.tobytes()).decode(),
                        "limitations": "Survey relief, not a photograph. Native cell size is not individual-rock measurement accuracy. Gaps remain blank; fish and boulder sizes are not inferred."}
                status = "surveyed"
                if research_only:
                    item["research_only"] = True
                    status = "research_only"
                filename = target["id"] + ".json"
                receipt = atomic_json(output / filename, item)
                record = {"status": status, "path": (relative_output / filename).as_posix(), **receipt,
                          "source_id": ident, "coverage_fraction": item["coverage_fraction"]}
                if research_only:
                    record.update(vertical_datum=datum, research_only=True)
                records[target["id"]] = record
    for target in atlas["targets"]:
        records.setdefault(target["id"], {"status": "unavailable", "reason": "No reviewed native survey window"})
    atomic_json(output / "index.json", {"schema_version": 1, "region_id": region["id"], "views": records, "sources": source_receipts})
    print(json.dumps({"region": region["id"], "surveyed": sum(v["status"] == "surveyed" for v in records.values()), "total": len(records)}))


if __name__ == "__main__":
    main()
