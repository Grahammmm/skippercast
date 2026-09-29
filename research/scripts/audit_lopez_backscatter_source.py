#!/usr/bin/env python3
"""Inventory original Lopez Point backscatter products without inferring rock.

The backscatter images share an archived survey with the depth products. Their
native metadata and rights must be inspected before a substrate comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import xml.etree.ElementTree as ET
import zipfile

import rasterio
from rasterio.io import MemoryFile

from research.scripts.audit_bigcreek_original_grids import ARCHIVE_SHA256, fetch_archive
from skippercast.platform.contracts import atomic_json


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "var/noaa-native-cache/BigCreek_additional_products.tar.gz"
OUTPUT = ROOT / "research/receipts/lopez-original-backscatter-source-review.json"
PRODUCT_NAME = "BigCreek2010/LopezPt.2010_1m_sss.zip"
MOSAICS = {
    "reson_7125": "Sidescan/LopezPoint_7125_1m_SSS.tif",
    "sea_swathplus": "Sidescan/LopezPoint_SWATH_1m_SSS.tif",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit(archive_path: Path) -> dict:
    with archive_path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != ARCHIVE_SHA256:
            raise ValueError("Original Big Creek product archive changed")
    with tarfile.open(archive_path, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.name == PRODUCT_NAME]
        if len(members) != 1 or members[0].size > 25_000_000:
            raise ValueError("Original Lopez sidescan product missing or oversized")
        package = archive.extractfile(members[0]).read()
    rows = []
    with zipfile.ZipFile(io.BytesIO(package)) as zipped:
        for sensor, path in MOSAICS.items():
            xml_path = path + ".xml"
            if path not in zipped.namelist() or xml_path not in zipped.namelist():
                raise ValueError("Original backscatter raster or metadata missing")
            metadata = zipped.read(xml_path)
            root = ET.fromstring(metadata)
            process = " ".join((node.text or "").strip() for node in root.iter("procdesc"))
            use = " ".join((node.text or "").strip() for node in root.iter("useconst"))
            access = " ".join((node.text or "").strip() for node in root.iter("accconst"))
            horizontal = " ".join((node.text or "").strip() for node in root.iter("horizpar"))
            if ("NAD_83(CORS96)" not in process or "To be determined" not in use
                    or "To be determined" not in access or "varies with depth" not in horizontal):
                raise ValueError("Backscatter positioning, precision or rights metadata changed")
            data = zipped.read(path)
            with MemoryFile(data) as memory, memory.open() as raster:
                if (raster.crs.to_epsg() != 26910 or raster.res != (1.0, 1.0)
                        or raster.count != 1 or raster.width < 1000 or raster.height < 1000):
                    raise ValueError("Original backscatter raster identity changed")
                row = {
                    "sensor": sensor,
                    "product_member": path,
                    "raster_sha256": sha(data),
                    "metadata_sha256": sha(metadata),
                    "horizontal_crs": "EPSG:26910",
                    "metadata_horizontal_realization": "NAD83(CORS96)",
                    "resolution_m": 1,
                    "bounds_source_crs_m": [round(value, 3) for value in raster.bounds],
                    "dimensions": [raster.width, raster.height],
                    "dtype": raster.dtypes[0],
                    "declared_nodata": raster.nodata,
                    "mask_flags": [flag.name for flag in raster.mask_flag_enums[0]],
                    "producer_stated_horizontal_accuracy": horizontal,
                    "producer_rights": use,
                }
                rows.append(row)
    return {
        "schema_version": 1,
        "scope": "lopez-original-backscatter-source-identity-review",
        "source_archive_url": "https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/BigCreek/multibeam/data/version2/products/BigCreek_additional_products.tar.gz",
        "source_archive_sha256": ARCHIVE_SHA256,
        "nested_product_sha256": sha(package),
        "mosaics": rows,
        "valid_backscatter_footprint_verified": False,
        "backscatter_to_rock_calibration_verified": False,
        "bathymetry_horizontal_realization_verified_from_this_source": False,
        "public_redistribution_rights_verified": False,
        "fishing_target": False,
        "exportable": False,
        "limitations": [
            "The mosaics are acoustic intensity, not independently validated rock or fish observations. Reson backscatter shares a sonar and survey with bathymetry; SWATHplus is a separate instrument in the same survey.",
            "CORS96 is stated for backscatter processing, not explicitly for the paired final bathymetry grids; the source raster frame cannot be inferred from this related product.",
            "The TIFFs report all-valid raster masks and no nodata value, while display/background values occur in the images. A native valid-data mask and radiometric treatment must be verified before spatial comparison.",
            "Producer metadata leave access and use constraints to be determined; no public redistribution or for-profit deployment is authorized by this audit.",
            "No bathymetric chart datum, total depth uncertainty, MPA access or fishing route is resolved by backscatter imagery.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.fetch:
        fetch_archive(args.archive)
    result = audit(args.archive)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise SystemExit("Original Lopez backscatter source changed; review before use")
    atomic_json(args.output, result)
    print(json.dumps({"mosaics": len(result["mosaics"]), "fishing_target": False}))


if __name__ == "__main__":
    main()
