#!/usr/bin/env python3
"""Nominally intersect 2012 NAVD88 depth with independent 2008 USGS class.

This is a coordinate-free research summary. The two horizontal realizations,
survey years and classification errors prevent exact fishing marks.
"""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import rasterio
from pyproj import Transformer

from scripts.audit_usgs_estero_2012_original import ARCHIVES, ascii_member, header
from scripts.audit_point_estero_original_pair import PIN as ESTERO_2008_PIN

ROOT = Path(__file__).resolve().parents[1]
CLASS_NAMES = {1: "soft_flat", 2: "hard_flat", 3: "hard_rugose"}
BANDS = ((200, 250), (250, 300))


def original_character(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != ESTERO_2008_PIN[path.name]:
        raise ValueError("Original USGS 2008 classification changed")
    with zipfile.ZipFile(path) as package:
        names = [name for name in package.namelist() if name.lower().endswith(".tif")]
        if len(names) != 1:
            raise ValueError("Expected one original 2008 class GeoTIFF")
        return f"zip://{path.resolve()}!{names[0]}"


def audit(depth_zip, class_zip):
    archive, source = ascii_member(depth_zip)
    transformer = Transformer.from_crs("EPSG:26910", "EPSG:32610", always_xy=True)
    counts = {f"{lo}-{hi}ft": {name: 0 for name in CLASS_NAMES.values()} for lo, hi in BANDS}
    band_cells = {key: 0 for key in counts}
    class_supported = {key: 0 for key in counts}
    try:
        grid = header(source)
        if grid["xllcorner"] != 665811.16966312 or grid["yllcorner"] != 3900237.4867247:
            raise ValueError("2012 depth origin changed")
        ncol, nrow, cell = int(grid["ncols"]), int(grid["nrows"]), grid["cellsize"]
        xs = grid["xllcorner"] + (np.arange(ncol) + .5) * cell
        with rasterio.open(original_character(class_zip)) as character:
            if (str(character.crs) != "EPSG:32610" or character.count != 1
                    or any(abs(x - 2) > .01 for x in character.res)):
                raise ValueError("2008 class grid changed")
            classes = character.read(1)
            for row in range(nrow):
                line = np.fromstring(source.readline().decode("ascii"), sep=" ")
                if line.size != ncol:
                    raise ValueError(f"Truncated 2012 depth row {row}")
                y = grid["yllcorner"] + (nrow - row - .5) * cell
                if y < character.bounds.bottom - 5 or y > character.bounds.top + 5:
                    continue
                northing = np.full(ncol, y)
                x2, y2 = transformer.transform(xs, northing)
                cols = np.floor((x2 - character.bounds.left) / 2).astype("int32")
                rows = np.floor((character.bounds.top - y2) / 2).astype("int32")
                inside = ((cols >= 0) & (cols < character.width)
                          & (rows >= 0) & (rows < character.height))
                for lo, hi in BANDS:
                    label = f"{lo}-{hi}ft"
                    band = (line != -9999) & (-line >= lo / 3.280839895) & (-line < hi / 3.280839895)
                    band_cells[label] += int(np.count_nonzero(band & inside))
                    included = np.where(band & inside)[0]
                    if not included.size:
                        continue
                    codes = classes[rows[included], cols[included]]
                    class_supported[label] += int(np.count_nonzero(np.isin(codes, [1, 2, 3])))
                    for code, name in CLASS_NAMES.items():
                        counts[label][name] += int(np.count_nonzero(codes == code))
        return {"schema_version": 1, "scope": "estero-independent-2012-depth-2008-character-nominal-overlap",
                "source_2012": "https://doi.org/10.3133/ofr20131225",
                "source_2008": "https://doi.org/10.5066/P9ZSTUK1",
                "depth_archive_sha256": ARCHIVES[depth_zip.name],
                "character_archive_sha256": ESTERO_2008_PIN[class_zip.name],
                "native_depth_vertical_datum": "NAVD88 Geoid12",
                "native_depth_resolution_m_in_band": 2,
                "depth_bands": {key: {"2012_depth_cells_within_2008_raster_bounds": band_cells[key],
                                      "independently_classified_cells": class_supported[key],
                                      "classified_cells_by_type": counts[key]}
                                for key in counts},
                "fishing_target": False, "exportable": False, "qualified_waypoints": 0,
                "limitations": [
                    "Nominal EPSG:26910-to-EPSG:32610 transform does not resolve source horizontal realization, epoch or registration uncertainty; these counts are not exact fishing polygons.",
                    "2012 depth and 2008 video-supervised class are independent surveys but may reflect seafloor change and class error.",
                    "NAVD88-to-MLLW transformation and full upper depth uncertainty are absent; 200–300 ft here is a source-datum comparison only.",
                    "Full current MPA, ENC hazard, access, approach, return and drift screens have not cleared these cells.",
                ]}
    finally:
        source.close()
        archive.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--depth", type=Path, default=ROOT / "var/review/estero-bay-2012/NAD83_utm10_EsteroBay.zip")
    p.add_argument("--character", type=Path, default=ROOT / "var/review/usgs-point-estero/SeafloorCharacter_OffshorePointEstero.zip")
    p.add_argument("--output", type=Path, default=ROOT / "dist/data/estero-independent-2012-depth-2008-character-overlap.json")
    args = p.parse_args()
    result = audit(args.depth, args.character)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print({key: item["independently_classified_cells"] for key, item in result["depth_bands"].items()})


if __name__ == "__main__":
    main()
