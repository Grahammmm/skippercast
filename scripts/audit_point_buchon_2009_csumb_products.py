"""Audit CSUMB Block A3 delivered grids archived under NOAA's 2007 cruise.

The inner metadata mention 2009 block surveys, but the bundled Block A3 bathy
tracklines are dated 2007. Acquisition year at the counted cells is unverified.
The public result has area counts only and cannot create fishing coordinates.
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tarfile
import tempfile
from urllib.request import Request, urlopen
from zipfile import ZipFile

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from scripts.audit_point_buchon_original_pair import EXPECTED_CLASS, original_tiff


ROOT = Path(__file__).resolve().parents[1]
URL = ("https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/"
       "Point_Buchon_Control/multibeam/data/version2/products/"
       "Pt_Buchon_control_additional_products.tar.gz")
ARCHIVE_SHA256 = "4677c538c50a8bacb1e8ca61ed2cdcde5aa9259143f27fe16c146e54d8243a5c"
ARCHIVE_BYTES = 515493040
MEMBER = "CC_BlkA3_2m.5m_bathygrids.zip"
MEMBER_SHA256 = "2a32196f18af1b2ce2332e397f42c153d393d31d41c7434fa7ffc8f511616376"
GRIDS = (("cc_ba3_2mbthy", 2, 60.96, 85),
         ("cc_ba3_5mbthy", 5, 85, 91.44))
BANDS = ((200, 250), (250, 300))


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_archive(path):
    if path.exists() and path.stat().st_size == ARCHIVE_BYTES and sha256_file(path) == ARCHIVE_SHA256:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".download")
    with urlopen(Request(URL, headers={"User-Agent": "SkipperCast original-grid audit/1.0"}),
                 timeout=120) as source, partial.open("wb") as output:
        if source.status != 200 or source.url != URL or int(source.headers.get("Content-Length", -1)) != ARCHIVE_BYTES:
            raise ValueError("Original NOAA archive URL or length changed")
        while chunk := source.read(1024 * 1024):
            output.write(chunk)
    if partial.stat().st_size != ARCHIVE_BYTES or sha256_file(partial) != ARCHIVE_SHA256:
        partial.unlink()
        raise ValueError("Original NOAA archive bytes changed")
    partial.replace(path)


def extract_grids(archive, directory):
    if archive.stat().st_size != ARCHIVE_BYTES or sha256_file(archive) != ARCHIVE_SHA256:
        raise ValueError("Original NOAA archive changed")
    with tarfile.open(archive, "r:gz") as outer:
        names = [m.name for m in outer if m.isfile()]
        if len(names) != 9 or MEMBER not in names or any(not n.startswith("CC_BlkA3_") for n in names):
            raise ValueError("Original NOAA archive product list changed")
        inner = outer.extractfile(outer.getmember(MEMBER)).read()
    if len(inner) != 60077844 or hashlib.sha256(inner).hexdigest() != MEMBER_SHA256:
        raise ValueError("Original CSUMB grid package changed")
    metadata_hashes = {}
    with ZipFile(BytesIO(inner)) as package:
        for name, spacing, _, _ in GRIDS:
            prefix = f"ArcViewGrids/{name}/"
            members = [n for n in package.namelist() if n.startswith(prefix) and not n.endswith("/")]
            required = {"hdr.adf", "prj.adf", "w001001.adf", "w001001x.adf", "metadata.xml"}
            if not required <= {Path(n).name for n in members}:
                raise ValueError("Original CSUMB grid files missing")
            xml = package.read(prefix + "metadata.xml")
            metadata_hashes[name] = hashlib.sha256(xml).hexdigest()
            source = xml.decode("utf-8", "replace")
            if ("NAVD88 Geoid03 vertical  datum" not in source
                    or "Surveys for blocks CC_BlockA1-A3 were conducted on April 9 and May 25-26, 29, 2009" not in source
                    or "<vertacc/>" not in source
                    or "<useconst>To be determined by Seafloor Mapping Lab" not in source
                    or f'<rastxsz Sync="TRUE">{spacing:.6f}</rastxsz>' not in source):
                raise ValueError("Original CSUMB date, datum, uncertainty or rights changed")
            for member in members:
                relative = Path(member)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe original grid member")
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(member))
    return metadata_hashes


def summarize_grid(depth, classes, *, spacing, minimum_m, maximum_m):
    values = depth.read(1, masked=True)
    category = np.zeros(depth.shape, dtype="uint8")
    reproject(classes.read(1), category, src_transform=classes.transform,
              src_crs=classes.crs, src_nodata=classes.nodata,
              dst_transform=depth.transform, dst_crs=depth.crs, dst_nodata=0,
              resampling=Resampling.nearest)
    valid = ~np.ma.getmaskarray(values)
    metres = -values.data
    bands = {}
    for lower_ft, upper_ft in BANDS:
        lo = max(minimum_m, lower_ft * .3048)
        hi = min(maximum_m, upper_ft * .3048)
        included = valid & (metres >= lo) & (metres < hi)
        bands[f"{lower_ft}-{upper_ft}ft"] = {
            "source_datum_depth_cells": int(np.count_nonzero(included)),
            "usgs_soft_flat_cells": int(np.count_nonzero(included & (category == 1))),
            "usgs_hard_flat_cells": int(np.count_nonzero(included & (category == 2))),
            "usgs_hard_rugose_cells": int(np.count_nonzero(included & (category == 3))),
            "unclassified_or_outside_usgs_cells": int(np.count_nonzero(included & (category == 0))),
        }
    return {"native_spacing_m": spacing, "valid_depth_cells": int(np.count_nonzero(valid)),
            "source_depth_range_m": [round(float(np.min(metres[valid])), 2),
                                     round(float(np.max(metres[valid])), 2)],
            "exclusive_depth_slice_m": [minimum_m, maximum_m], "bands": bands}


def audit(archive, class_zip):
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        metadata_hashes = extract_grids(archive, directory)
        with rasterio.open(original_tiff(class_zip)) as classes:
            if (str(classes.crs) != "EPSG:32610" or classes.res != (2.0, 2.0)
                    or sha256_file(class_zip) != EXPECTED_CLASS):
                raise ValueError("Original USGS character grid changed")
            grids = {}
            for name, spacing, minimum_m, maximum_m in GRIDS:
                with rasterio.open(directory / "ArcViewGrids" / name) as depth:
                    if (str(depth.crs) != "EPSG:26910" or depth.res != (spacing, spacing)
                            or depth.count != 1):
                        raise ValueError("Original CSUMB bathymetry reference changed")
                    grids[name] = summarize_grid(depth, classes, spacing=spacing,
                                                 minimum_m=minimum_m, maximum_m=maximum_m)
    return {
        "schema_version": 1,
        "scope": "point-buchon-2009-csumb-original-products-vs-2008-usgs-character",
        "archive_catalog_url": "https://www.ngdc.noaa.gov/ships/ventresca/PointBuchon_Control_mb.html",
        "archive_url": URL, "archive_sha256": ARCHIVE_SHA256,
        "archive_label_cruise_year": 2007,
        "inner_grid_member": MEMBER, "inner_grid_sha256": MEMBER_SHA256,
        "inner_grid_metadata_survey_year": 2009,
        "bundled_bathy_trackline_year": 2007,
        "cell_acquisition_year_verified": False,
        "acquisition_lineage_receipt": "dist/data/point-buchon-block-a3-trackline-lineage.json",
        "inner_metadata_sha256": metadata_hashes,
        "inner_grid_native_vertical_datum": "NAVD88 Geoid03 (inner original processing metadata)",
        "inner_grid_horizontal_crs": "NAD83 / UTM zone 10N, realization/epoch not specified",
        "independent_character_archive_sha256": EXPECTED_CLASS,
        "grid_summaries": grids,
        "source_product_upper_uncertainty_verified": False,
        "cross_survey_registration_verified": False,
        "reuse_rights_resolved": False,
        "qualified_waypoints": 0, "fishing_target": False, "exportable": False,
        "limitations": [
            "The NOAA 2007 PointBuchon_Control products link contains a later CC_BlockA3 delivery whose metadata mention 2009 block surveys, but its bundled bathymetry tracklines are all dated October 2007. Package processing date is not a verified acquisition year at these cells; only NAVD88 Geoid03 is explicitly declared for the delivered grid.",
            "The 2 m grid is used only through 85 m and the 5 m grid beyond 85 m to avoid double counting resampled overlapping depth slices.",
            "Nominal cross-survey class counts use a nearest-cell EPSG:32610-to-EPSG:26910 transform; horizontal realization, epoch and registration error remain unverified.",
            "Original metadata leave vertical accuracy empty and access/use constraints to be determined. Neither per-cell TPU nor a conservative released-grid upper error is available.",
            "NAVD88 source depths are not MLLW fishing depths. Independent class does not establish current rockfish/lingcod presence, legal access or a safe route.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "var/review/point-buchon-additional-products/Pt_Buchon_control_additional_products.tar.gz")
    parser.add_argument("--character", type=Path, default=ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/point-buchon-2009-csumb-original-overlap.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.fetch:
        fetch_archive(args.archive)
    result = audit(args.archive, args.character)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise ValueError("Original 2009 CSUMB Block A3 evidence changed; review before publication")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print({"grids": len(result["grid_summaries"]),
           "hard_rugose_nominal_cells": sum(b["usgs_hard_rugose_cells"]
               for grid in result["grid_summaries"].values() for b in grid["bands"].values())})


if __name__ == "__main__":
    main()
