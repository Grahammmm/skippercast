#!/usr/bin/env python3
"""Count original USGS Point Estero depth/character cells by nominal depth band.

The underlying bathymetry's output vertical datum and cell uncertainty are
unverified. Counts are research context only, never MLLW fishing depths.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[1]
PIN = {
    "Bathymetry_OffshorePointEstero.zip": "43244d9ca2e61f6c4154bd50c9ec05286b1d01772e1354fc247f905176e8d37a",
    "Bathymetry_OffshorePointEstero_metadata.xml": "26c3b384597cdd9d29f6280f6c99951c80d6114fbb0e706fe0939200862a30e1",
    "SeafloorCharacter_OffshorePointEstero.zip": "1deb5eb5130e2d0aaf39d0b73bbb2841b4aaff50f0b85b7a2a4b22d7fe9ece3c",
    "SeafloorCharacter_OffshorePointEstero_metadata.xml": "1110921a69d3bdd8d8603d7768ece981a08acb2a85417c6d860dc3b39df37708",
}
CLASSES = {1: "soft_flat", 2: "hard_flat", 3: "hard_rugose"}
BANDS = ((200, 250), (250, 300))


def checked(path):
    expected = PIN[path.name]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"Point Estero official source changed: {path.name}")


def fetch_sources(base, leads):
    area = next(row for row in leads["map_areas"] if row["name"] == "Offshore of Point Estero")
    products = {row["description"]: row for row in area["products"]}
    base.mkdir(parents=True, exist_ok=True)
    for name, expected in PIN.items():
        stem = name.removesuffix("_metadata.xml").removesuffix(".zip")
        item = products[stem]
        url = item["metadata_url"] if name.endswith(".xml") else item["archive_url"]
        path = base / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            continue
        temporary = path.with_suffix(path.suffix + ".download")
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SkipperCast source audit; +https://skippercast.com)"})
        with urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            temporary.unlink()
            raise ValueError(f"Official source changed: {url}")
        temporary.replace(path)


def tiff(path):
    checked(path)
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".tif")]
        if len(names) != 1:
            raise ValueError("Expected one original GeoTIFF")
        return f"zip://{path.resolve()}!{names[0]}"


def audit(base):
    bathy_meta = base / "Bathymetry_OffshorePointEstero_metadata.xml"
    class_meta = base / "SeafloorCharacter_OffshorePointEstero_metadata.xml"
    checked(bathy_meta)
    checked(class_meta)
    text = class_meta.read_text()
    for phrase in ("There were 299 observations in the study area",
                   "hard and flat coarse grain sediment and bedrock seafloor",
                   "hard and rugose boulder, megaclast, and bedrock seafloor"):
        if phrase not in text:
            raise ValueError("USGS class semantics or video validation changed")
    bathy_zip = base / "Bathymetry_OffshorePointEstero.zip"
    class_zip = base / "SeafloorCharacter_OffshorePointEstero.zip"
    counts = {f"{lo}-{hi}ft": {label: 0 for label in CLASSES.values()} for lo, hi in BANDS}
    with rasterio.open(tiff(bathy_zip)) as bathy, rasterio.open(tiff(class_zip)) as character:
        if (bathy.count != 1 or character.count != 1 or bathy.shape != character.shape
                or bathy.transform != character.transform or str(bathy.crs) != "EPSG:32610"
                or str(character.crs) != "EPSG:32610"
                or any(abs(resolution - 2) > .01 for resolution in bathy.res + character.res)):
            raise ValueError("Original Point Estero rasters are not aligned 2 m UTM grids")
        for _, window in bathy.block_windows(1):
            d = bathy.read(1, window=window, masked=True)
            c = character.read(1, window=window, masked=True)
            elevations = np.ma.getdata(d)
            classes = np.ma.getdata(c)
            valid = (~np.ma.getmaskarray(d) & ~np.ma.getmaskarray(c) & np.isfinite(elevations))
            for lo, hi in BANDS:
                label = f"{lo}-{hi}ft"
                band = valid & (-elevations >= lo / 3.280839895) & (-elevations < hi / 3.280839895)
                for code, name in CLASSES.items():
                    counts[label][name] += int(np.count_nonzero(band & (classes == code)))
    return {"schema_version": 1, "scope": "point-estero-original-paired-200-300ft-research",
            "source_release": "https://doi.org/10.5066/P9ZSTUK1",
            "survey_year": 2008, "native_grid_resolution_m": 2,
            "native_depth_vertical_datum": None, "has_per_cell_upper_uncertainty": False,
            "source_sha256": PIN, "character_classes": CLASSES,
            "nominal_depth_bands": {band: {"cells_by_class": by_class,
                                           "paired_area_m2": 4 * sum(by_class.values())}
                                    for band, by_class in counts.items()},
            "fishing_target": False, "exportable": False, "qualified_waypoints": 0,
            "limitations": [
                "Original 2008 USGS raster cells, not MLLW or navigational soundings; depth datum and upper uncertainty remain unresolved.",
                "Class 3 is a video-supervised hard/rugose class, not a measurement of individual boulder dimensions or fish abundance.",
                "No same-footprint species observation, current legal-area screen, chart-danger screen, or approach/drift review qualifies these cells.",
            ]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--base", type=Path, default=ROOT / "var/review/usgs-point-estero")
    p.add_argument("--output", type=Path, default=ROOT / "dist/data/point-estero-original-paired-200-300ft-review.json")
    args = p.parse_args()
    if args.fetch:
        leads = json.loads((ROOT / "dist/data/usgs-ds781-source-leads.json").read_text())
        fetch_sources(args.base, leads)
    result = audit(args.base)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["nominal_depth_bands"])


if __name__ == "__main__":
    main()
