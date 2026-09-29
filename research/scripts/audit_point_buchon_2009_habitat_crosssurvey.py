"""Compare CSUMB Block A3 terrain classes with separate 2008 USGS classes.

Both classes are terrain interpretations; agreement is not independent rock or fish
groundtruth. The receipt contains aggregate counts, never fishing coordinates.
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tarfile
import tempfile
from zipfile import ZipFile

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from research.scripts.audit_point_buchon_2009_csumb_products import (
    ARCHIVE_SHA256, ARCHIVE_BYTES, GRIDS, ROOT, extract_grids, sha256_file,
)
from research.scripts.audit_point_buchon_original_pair import EXPECTED_CLASS, original_tiff


MEMBER = "CC_BlkA3_2m.5m_habitat.zip"
MEMBER_SHA256 = "357522e6fd5a879c1243fc0947e6d00df6725eb951ba201bbe18091231ed5b66"


def extract_habitat(archive, directory):
    if archive.stat().st_size != ARCHIVE_BYTES or sha256_file(archive) != ARCHIVE_SHA256:
        raise ValueError("Original NOAA archive changed")
    with tarfile.open(archive, "r:gz") as outer:
        inner = outer.extractfile(outer.getmember(MEMBER)).read()
    if hashlib.sha256(inner).hexdigest() != MEMBER_SHA256:
        raise ValueError("Original CSUMB habitat member changed")
    metadata = {}
    with ZipFile(BytesIO(inner)) as package:
        for _, spacing, _, _ in GRIDS:
            sub_name = f"cc_ba3_{spacing}msub"
            hab_name = f"cc_ba3_{spacing}mhab"
            for name in (sub_name, hab_name):
                prefix = f"ArcViewGrids/{name}/"
                members = [n for n in package.namelist() if n.startswith(prefix) and not n.endswith("/")]
                if not {"hdr.adf", "prj.adf", "w001001.adf", "w001001x.adf", "metadata.xml"} <= {Path(n).name for n in members}:
                    raise ValueError("Original CSUMB habitat raster missing")
                xml = package.read(prefix + "metadata.xml")
                metadata[name] = hashlib.sha256(xml).hexdigest()
                if name == sub_name:
                    source = xml.decode("utf-8", "replace")
                    if ("chosen subjectively" not in source
                            or "hand-drawn mask" not in source
                            or "rugosity indices" not in source
                            or "NAVD88 (Geoid03)" not in source):
                        raise ValueError("Original habitat method or datum changed")
                for member in members:
                    relative = Path(member)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("Unsafe original habitat member")
                    target = directory / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(package.read(member))
    return metadata


def audit(archive, class_zip):
    if sha256_file(class_zip) != EXPECTED_CLASS:
        raise ValueError("Original USGS character grid changed")
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        depth_metadata = extract_grids(archive, directory)
        habitat_metadata = extract_habitat(archive, directory)
        summaries = {}
        with rasterio.open(original_tiff(class_zip)) as usgs:
            if str(usgs.crs) != "EPSG:32610" or usgs.res != (2, 2):
                raise ValueError("Original USGS class reference changed")
            for grid_name, spacing, minimum_m, maximum_m in GRIDS:
                sub_name = f"cc_ba3_{spacing}msub"
                hab_name = f"cc_ba3_{spacing}mhab"
                with (rasterio.open(directory / "ArcViewGrids" / grid_name) as depth,
                      rasterio.open(directory / "ArcViewGrids" / sub_name) as sub,
                      rasterio.open(directory / "ArcViewGrids" / hab_name) as hab):
                    if (str(depth.crs) != "EPSG:26910" or depth.res != (spacing, spacing)
                            or sub.transform != depth.transform or sub.shape != depth.shape
                            or hab.transform != depth.transform or hab.shape != depth.shape):
                        raise ValueError("Original habitat/depth registration changed")
                    z = depth.read(1, masked=True)
                    terrain = sub.read(1, masked=True)
                    habitat = hab.read(1, masked=True)
                    base = (~np.ma.getmaskarray(z) & ~np.ma.getmaskarray(terrain)
                            & ~np.ma.getmaskarray(habitat)
                            & (-z.data >= minimum_m) & (-z.data < maximum_m))
                    if np.count_nonzero(base & (terrain.data == 1) & ~np.isin(habitat.data, (-1, -31, -101, -201))):
                        raise ValueError("CSUMB rough class does not match depth-stratified habitat")
                    if np.count_nonzero(base & (terrain.data == 0) & ~np.isin(habitat.data, (0, -30, -100, -200))):
                        raise ValueError("CSUMB smooth class does not match depth-stratified habitat")
                    usgs_class = np.zeros(depth.shape, dtype="uint8")
                    reproject(usgs.read(1), usgs_class, src_transform=usgs.transform,
                              src_crs=usgs.crs, src_nodata=usgs.nodata,
                              dst_transform=depth.transform, dst_crs=depth.crs,
                              dst_nodata=0, resampling=Resampling.nearest)
                    bands = {}
                    for lo_ft, hi_ft in ((200, 250), (250, 300)):
                        lower = max(minimum_m, lo_ft * .3048)
                        upper = min(maximum_m, hi_ft * .3048)
                        valid = base & (-z.data >= lower) & (-z.data < upper)
                        table = {}
                        for class_id, label in ((1, "usgs_soft_flat"), (2, "usgs_hard_flat"),
                                                (3, "usgs_hard_rugose")):
                            table[label] = {
                                "csumb_smooth": int(np.count_nonzero(valid & (usgs_class == class_id) & (terrain.data == 0))),
                                "csumb_rough": int(np.count_nonzero(valid & (usgs_class == class_id) & (terrain.data == 1))),
                            }
                        bands[f"{lo_ft}-{hi_ft}ft"] = table
                    summaries[grid_name] = {"native_spacing_m": spacing, "bands": bands}
    hard_rugose = sum(row["usgs_hard_rugose"]["csumb_smooth"] + row["usgs_hard_rugose"]["csumb_rough"]
                       for grid in summaries.values() for row in grid["bands"].values())
    repeat_rough = sum(row["usgs_hard_rugose"]["csumb_rough"]
                       for grid in summaries.values() for row in grid["bands"].values())
    return {
        "schema_version": 1,
        "scope": "point-buchon-2009-csumb-terrain-vs-2008-usgs-character",
        "archive_url": "https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/Point_Buchon_Control/multibeam/data/version2/products/Pt_Buchon_control_additional_products.tar.gz",
        "archive_sha256": ARCHIVE_SHA256,
        "inner_member": MEMBER, "inner_member_sha256": MEMBER_SHA256,
        "depth_metadata_sha256": depth_metadata,
        "habitat_metadata_sha256": habitat_metadata,
        "independent_survey_character_sha256": EXPECTED_CLASS,
        "delivered_product_metadata_year": 2009,
        "bundled_bathymetry_trackline_year": 2007,
        "cell_acquisition_year_verified": False,
        "grid_summaries": summaries,
        "usgs_hard_rugose_cells_with_csumb_class": hard_rugose,
        "usgs_hard_rugose_cells_also_csumb_rough": repeat_rough,
        "method": "CSUMB rough/smooth is subjectively thresholded bathymetric rugosity with hand-drawn artifact masks. The delivered package's bathymetry tracklines date to 2007; the separate 2008 USGS terrain class is a cross-survey comparison, not biological or in-situ rock validation.",
        "independent_rock_groundtruth": False,
        "depth_mllw_and_upper_uncertainty_verified": False,
        "cross_survey_registration_verified": False,
        "reuse_rights_resolved": False,
        "qualified_waypoints": 0, "fishing_target": False, "exportable": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "var/review/point-buchon-additional-products/Pt_Buchon_control_additional_products.tar.gz")
    parser.add_argument("--character", type=Path, default=ROOT / "var/review/usgs-point-buchon/SeafloorCharacter_OffshorePointBuchon.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/point-buchon-2009-csumb-terrain-crosssurvey.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = audit(args.archive, args.character)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise ValueError("Point Buchon cross-survey terrain comparison changed; review before publication")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print({"hard_rugose_with_csumb_class": result["usgs_hard_rugose_cells_with_csumb_class"],
           "also_csumb_rough": result["usgs_hard_rugose_cells_also_csumb_rough"]})


if __name__ == "__main__":
    main()
