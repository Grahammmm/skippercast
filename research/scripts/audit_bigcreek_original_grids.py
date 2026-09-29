"""Screen original Big Creek/Lopez Point DEM and habitat cells to 300 ft.

This is a research-only NAVD88 comparison, not MLLW clearance or a waypoint.
The supplied DEM cells were gridded/interpolated from processed soundings and
the rough class is derived from that DEM, not independent bottom observation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
from urllib.request import Request, urlopen
import zipfile

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_bounds
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

from research.scripts.prepare_regional_mpas import source_url, validate_response
from skippercast.platform.contracts import atomic_json


ARCHIVE_URL = ("https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/BigCreek/"
               "multibeam/data/version2/products/BigCreek_additional_products.tar.gz")
ARCHIVE_SHA256 = "5e688dae2eca47844cf9727f70d212b0492e0d28e0aa5b261acbd8911dd2ada1"
MAX_ARCHIVE_BYTES = 400_000_000
BOUNDS = [-121.69, 36.0, -121.52, 36.14]
LOCATIONS = (("BigCreekN", "bc_n"), ("BigCreekS", "bc_s"), ("LopezPt", "lp"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_archive(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        request = Request(ARCHIVE_URL, headers={"User-Agent": "SkipperCast original-grid audit/1.0"})
        temporary = path.with_suffix(path.suffix + ".part")
        try:
            with urlopen(request, timeout=90) as response, temporary.open("wb") as target:
                if (response.status != 200 or response.url != ARCHIVE_URL or
                        int(response.headers.get("Content-Length", 0)) > MAX_ARCHIVE_BYTES):
                    raise ValueError("Original Big Creek archive unavailable, redirected or oversized")
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        raise ValueError("Original Big Creek archive exceeded size bound")
                    target.write(chunk)
            with temporary.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != ARCHIVE_SHA256:
                    raise ValueError("Original Big Creek archive bytes changed")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != ARCHIVE_SHA256:
        raise ValueError("Original Big Creek archive bytes changed")


def fetch_mpas() -> tuple[dict, str]:
    url = source_url(BOUNDS)
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast Big Creek MPA audit/1.0"}), timeout=45) as response:
        raw = response.read(6_000_001)
        if response.status != 200 or response.url != url or not raw or len(raw) > 6_000_000:
            raise ValueError("Official CDFW MPA response failed")
    data = json.loads(raw)
    features = validate_response(data, BOUNDS, 2)
    if {f["properties"]["NAME"] for f in features} != {"Big Creek SMCA", "Big Creek SMR"}:
        raise ValueError("Big Creek protected-area identity changed")
    return data, sha256(raw)


def extract_grid(zip_data: bytes, prefix: str, destination: Path) -> tuple[Path, str]:
    with zipfile.ZipFile(io.BytesIO(zip_data)) as archive:
        members = [x for x in archive.infolist() if x.filename.startswith(prefix + "/") and not x.is_dir()]
        if not members or not any(x.filename == prefix + "/metadata.xml" for x in members):
            raise ValueError(f"Original grid absent: {prefix}")
        for member in members:
            # Only named ESRI grid members, never arbitrary archive paths.
            suffix = member.filename[len(prefix) + 1:]
            if "/" in suffix or suffix.startswith("."):
                raise ValueError("Unexpected original grid path")
            path = destination / prefix / suffix
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(member))
        metadata = archive.read(prefix + "/metadata.xml")
    return destination / prefix, sha256(metadata)


def inspect_location(tar: tarfile.TarFile, loc: str, stem: str, mpa_shapes: list) -> dict:
    product_hashes = {}
    grids = {}
    named_uncertainty_grids = []
    with tempfile.TemporaryDirectory(prefix="skippercast-bigcreek-") as temp:
        destination = Path(temp)
        for kind in ("bathygrids", "habitat"):
            member = next((x for x in tar.getmembers() if x.name.startswith("BigCreek2010/" + loc + ".")
                           and x.name.endswith("_" + kind + ".zip")), None)
            if not member or member.size > 50_000_000:
                raise ValueError(f"Missing or oversized {loc} {kind} product")
            data = tar.extractfile(member).read()
            product_hashes[kind] = sha256(data)
            if kind == "bathygrids":
                with zipfile.ZipFile(io.BytesIO(data)) as inventory:
                    named_uncertainty_grids = [name for name in inventory.namelist()
                                               if any(word in name.lower() for word in
                                                      ("uncert", "tpe", "cube"))]
            for spacing in (2, 5):
                suffix = f"{stem}_{spacing}m"
                names = [suffix + "bathy"] if kind == "bathygrids" else [suffix + "hab"]
                for name in names:
                    grid_path, metadata_hash = extract_grid(data, "ArcViewGrids/" + name, destination)
                    grids[name] = grid_path
                    product_hashes[name + "_metadata"] = metadata_hash
                    text = (grid_path / "metadata.xml").read_text(errors="replace")
                    if kind == "bathygrids" and "NAVD88 Geoid09 vertical" not in text:
                        raise ValueError("Original bathymetry datum changed")
                    if kind == "habitat" and "Substrate = Rough" not in text:
                        raise ValueError("Original habitat classification changed")
        rows = []
        for spacing, minimum_depth_m, maximum_depth_m in ((2, 60.96, 80.0), (5, 80.0, 91.44)):
            with rasterio.open(grids[f"{stem}_{spacing}mbathy"]) as depth_grid, \
                    rasterio.open(grids[f"{stem}_{spacing}mhab"]) as class_grid:
                if (depth_grid.crs.to_epsg() != 26910 or depth_grid.res != (float(spacing), float(spacing)) or
                        depth_grid.shape != class_grid.shape or depth_grid.transform != class_grid.transform):
                    raise ValueError("Original paired grid registration changed")
                depth = depth_grid.read(1, masked=True)
                habitat = class_grid.read(1, masked=True)
                # Both tiers have a common 80 m published overlap; use a
                # half-open partition to avoid counting that overlap twice.
                band = (~np.ma.getmaskarray(depth)) & (~np.ma.getmaskarray(habitat)) & \
                       (depth <= -minimum_depth_m) & (depth >= -maximum_depth_m)
                if spacing == 5:
                    band = (~np.ma.getmaskarray(depth)) & (~np.ma.getmaskarray(habitat)) & \
                           (depth < -minimum_depth_m) & (depth >= -maximum_depth_m)
                rough = band & (habitat == -31)
                smooth = band & (habitat == -30)
                if int((band & ~rough & ~smooth).sum()):
                    raise ValueError("Unexpected Big Creek habitat class in depth band")
                # A 75 m inward clearance is a conservative research screen,
                # not a legal boundary interpretation or a trip-date clearance.
                mpa_mask = rasterize([geom.buffer(75) for geom in mpa_shapes],
                                     out_shape=depth_grid.shape, transform=depth_grid.transform,
                                     all_touched=True)
                rows.append({
                    "source_grid_resolution_m": spacing,
                    "nominal_navd88_depth_band_m": [minimum_depth_m, maximum_depth_m],
                    "populated_paired_dem_class_cells": int(band.sum()),
                    "derived_rough_cells": int(rough.sum()),
                    "derived_smooth_cells": int(smooth.sum()),
                    "derived_rough_cells_outside_mpa_plus_75m": int((rough & (mpa_mask == 0)).sum()),
                    "derived_rough_cells_in_mpa_plus_75m": int((rough & (mpa_mask != 0)).sum()),
                    "grid_bounds_wgs84": [round(v, 7) for v in transform_bounds(
                        depth_grid.crs, "EPSG:4326", *depth_grid.bounds)],
                })
    return {"survey_area": loc, "product_sha256": product_hashes,
            "named_uncertainty_grids_in_bathy_zip": named_uncertainty_grids,
            "tiers": rows}


def audit(archive: Path, mpas: dict, mpa_sha: str) -> dict:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:26910", always_xy=True).transform
    mpa_shapes = [transform(transformer, shape(f["geometry"])) for f in mpas["features"]]
    with tarfile.open(archive, "r:gz") as original:
        areas = [inspect_location(original, loc, stem, mpa_shapes) for loc, stem in LOCATIONS]
    return {
        "schema_version": 1,
        "scope": "original-bigcreek-lopez-300ft-dem-habitat-research",
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_archive_url": ARCHIVE_URL,
        "source_archive_sha256": ARCHIVE_SHA256,
        "source_grid_vertical_datum": "NAVD88 Geoid09",
        "cdfw_mpa_url": source_url(BOUNDS),
        "cdfw_mpa_raw_sha256": mpa_sha,
        "cdfw_mpa_names": sorted(f["properties"]["NAME"] for f in mpas["features"]),
        "mpa_review_buffer_m": 75,
        "areas": areas,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "200–300 ft is a nominal NAVD88 comparison band; no full-grid MLLW conversion or total upper error bound was established.",
            "Cells are published 2 m/5 m processed DEM outputs interpolated from decimated CUBE soundings, not independent direct soundings at every pixel.",
            "The rough class is terrain-derived from the same bathymetry, not an independent rock observation or fish-presence estimate.",
            "CDFW polygon and 75 m proximity checks do not establish legal permission, chart clearance, drift geometry, or current trip-date access.",
            "Original producer metadata says access/use constraints remain to be determined, and CSUMB public-use policy does not authorize for-profit use without express permission. No public grid redistribution is approved.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("var/noaa-native-cache/BigCreek_additional_products.tar.gz"))
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.fetch:
        fetch_archive(args.archive)
    else:
        with args.archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != ARCHIVE_SHA256:
                raise ValueError("Original Big Creek archive hash differs")
    mpas, mpa_sha = fetch_mpas()
    result = audit(args.archive, mpas, mpa_sha)
    if args.verify:
        baseline = json.loads(args.verify.read_text())
        stable = lambda x: {k: v for k, v in x.items() if k != "checked_at"}
        if stable(result) != stable(baseline):
            raise ValueError("Big Creek source or MPA cell screen changed; review before use")
    atomic_json(args.output, result)
    print(json.dumps({"areas": len(result["areas"]), "fishing_target": False}))


if __name__ == "__main__":
    main()
