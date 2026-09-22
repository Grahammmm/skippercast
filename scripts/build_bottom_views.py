"""Compile small, masked survey windows. Run with the optional GIS environment.

Input manifest: {"sources": {"PointBuchon": {"path": "/local/grid.tif",
"source_id": "usgs-point-buchon", "survey_year": 2008, "vertical_datum": "MLLW"}}}
Local paths are never included in public output. No interpolation fills gaps.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from skippercast.platform.contracts import REPO, atomic_json, load_catalogs, load_region, read_json, within


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--region", required=True)
    p.add_argument("--manifest", type=Path, required=True)
    args = p.parse_args()
    region = load_region(args.region)
    _, sources = load_catalogs()
    atlas = read_json(within(REPO / "dist", region["assets"]["atlas"]))
    manifest = read_json(args.manifest)["sources"]
    output = within(REPO / "dist", region["assets"]["bottom_index"]).parent
    records, source_receipts = {}, {}
    for name, spec in manifest.items():
        ident = spec["source_id"]
        reviewed = sources[ident]
        if reviewed["review_status"] != "approved" or ident not in region["source_bindings"]["bathymetry"]:
            raise ValueError("Seabed source is not approved and bound to this region")
        if spec["vertical_datum"] != "MLLW":
            raise ValueError("This adapter expects signed MLLW elevations in metres")
        path = Path(spec["path"])
        digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
        source_receipts[ident] = {"sha256": digest, "bytes": path.stat().st_size,
                                  "url": reviewed["documentation_url"], "survey_year": spec["survey_year"]}
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
                        "source_id": ident, "source_sha256": digest, "source_url": reviewed["documentation_url"],
                        "survey_year": spec["survey_year"], "vertical_datum": "MLLW", "horizontal_crs": str(grid.crs),
                        "width": 129, "height": 129, "cell_m": grid.res[0], "native_cell_m": grid.res[0],
                        "span_m": 128 * grid.res[0], "center_pixel": [64, 64],
                        "target_offset_m": [round(x-grid.xy(row,col)[0], 3), round(y-grid.xy(row,col)[1], 3)],
                        "coverage_fraction": round(float((~mask).mean()), 4),
                        "depth_range_ft": [round(float(-valid.max())*3.28084, 1), round(float(-valid.min())*3.28084, 1)],
                        "relief_m": round(float(valid.max()-valid.min()), 2),
                        "encoding": "base64-int16-le", "elevation_unit_m": 0.1, "nodata": -32768,
                        "elevations": base64.b64encode(encoded.tobytes()).decode(),
                        "limitations": "Survey relief, not a photograph. Native cell size is not individual-rock measurement accuracy. Gaps remain blank; fish and boulder sizes are not inferred."}
                receipt = atomic_json(output / (target["id"] + ".json"), item)
                records[target["id"]] = {"status": "surveyed", "path": (output.relative_to(REPO / "dist") / (target["id"] + ".json")).as_posix(), **receipt,
                                           "source_id": ident, "coverage_fraction": item["coverage_fraction"]}
    for target in atlas["targets"]:
        records.setdefault(target["id"], {"status": "unavailable", "reason": "No reviewed native survey window"})
    atomic_json(output / "index.json", {"schema_version": 1, "region_id": region["id"], "views": records, "sources": source_receipts})
    print(json.dumps({"region": region["id"], "surveyed": sum(v["status"] == "surveyed" for v in records.values()), "total": len(records)}))


if __name__ == "__main__":
    main()
