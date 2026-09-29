#!/usr/bin/env python3
"""Pin NOAA 2013 merge lineage behind the USGS Monterey 2 m composite.

The source report identifies potentially useful vertical-accuracy and source-
inventory deliverables; it does not establish their values on a research cell.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[2]
USGS_URL = "https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/metadata/Bathymetry_2m_OffshoreMonterey_metadata.xml"
USGS_SHA = "1c12c1df827d8071565d655368ec35d8c276dc8e6f2c40d45ce4263b15081b12"
NOAA_URL = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/2612/supplemental/ca2013_noaa_topobathy_merge_m2612_final_report.pdf"
NOAA_SHA = "71d08d9dcb748b077ea6ff7b2c166816c2c5461bce637c2bee7532369a948de5"


def source(path, url, expected, fetch, limit):
    if fetch:
        request = urllib.request.Request(url, headers={"User-Agent": "SkipperCast-source-audit/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read(limit + 1)
        if len(data) > limit or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Original merge lineage source changed or oversized")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Pinned merge lineage source changed")
    return path.read_bytes()


def build(root, fetch=False):
    usgs = source(root / "var/review/Bathymetry_2m_OffshoreMonterey_metadata.xml",
                  USGS_URL, USGS_SHA, fetch, 2_000_000)
    noaa = source(root / "var/review/ca2013-noaa-topobathy-merge-report.pdf",
                  NOAA_URL, NOAA_SHA, fetch, 5_000_000)
    if not noaa.startswith(b"%PDF-"):
        raise ValueError("NOAA processing report is not a PDF")
    xml = ElementTree.fromstring(usgs)
    processes = [item.text or "" for item in xml.iter("procdesc")]
    merge = [text for text in processes if "2013 NOAA Coastal California TopoBathy Merge Project" in text]
    if (len(merge) != 1 or "re-sampled to 2-m spatial resolution" not in merge[0]
            or "The 2-m and 5-m grids were not merged" not in merge[0]):
        raise ValueError("USGS 2 m composite source lineage changed")
    vertical = [item.text or "" for item in xml.iter("vertaccr")]
    if len(vertical) != 1 or "no less than 20 cm" not in vertical[0]:
        raise ValueError("USGS vertical-accuracy wording changed")
    return {
        "schema_version": 1, "scope": "monterey-usgs-2m-noaa-2013-merge-lineage-gap",
        "usgs_metadata_url": USGS_URL, "usgs_metadata_sha256": USGS_SHA,
        "noaa_processing_report_url": NOAA_URL, "noaa_processing_report_sha256": NOAA_SHA,
        "usgs_2m_source": "NOAA 2013 Coastal California TopoBathy Merge data resampled to 2 m; separate deeper MBARI 5 m grid not merged",
        "noaa_merge_reference_frame": "NAD83 NSRS2007 UTM 10/11; NAVD88 Geoid09, per 2013 NOAA report",
        "noaa_report_deliverables": [
            "Full_DataInventory.xlsx identifying source dates and dataset inventory",
            "File geodatabase of acoustic-source spatial extents",
            "Raster and vector vertical-accuracy layers, plus void mask and seamlines",
        ],
        "noaa_report_acoustic_accuracy": "Varies by source or unavailable; undefined values encoded as -9999 in raster accuracy layer",
        "noaa_report_accuracy_is_cellwise_upper_bound": False,
        "public_accuracy_layer_at_research_cells_obtained": False,
        "public_source_inventory_at_research_cells_obtained": False,
        "usgs_20cm_phrase_is_conservative_upper_bound": False,
        "independent_of_1995_or_1998_survey_established": False,
        "chart_datum_depth_qualified": False,
        "next_acquisition": "Locate NOAA's original 2013 Full_DataInventory.xlsx, acoustic-source extent FGDB and vertical-accuracy raster/vector; intersect their actual records with Monterey research cells, then obtain any missing contributing survey's tide, datum and TPU records. Source-reported RMSE or undefined accuracy cannot be treated as an upper safety bound without a justified conversion and transformation error.",
        "fishing_target": False, "exportable": False,
        "limitations": [
            "The NOAA project report documents deliverable types, not their cell values or public retrieval path; no accuracy value has been sampled on a candidate.",
            "The 2013 merge may incorporate either historical USGS/MBARI multibeam source, so agreement with the USGS 2016 resample is not independent validation.",
            "The USGS metadata's 'no less than 20 cm' wording is not a maximum vertical error and cannot close the 300 ft release gate.",
            "NOAA's accuracy layer uses source-reported RMSE where available and undefined values for some acoustic data; neither is automatically a conservative all-cell upper error.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path, default=Path("research/receipts/monterey-2013-merge-lineage-gap.json"))
    args = parser.parse_args()
    report = build(args.root.resolve(), args.fetch)
    if args.verify:
        saved = json.loads(args.verify.read_text())
        if report != {key: value for key, value in saved.items() if key != "checked_at"}:
            raise ValueError("NOAA merge lineage changed; hold for review")
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("NOAA merge source inventory and accuracy layers are acquisition leads; zero depth qualifications")


if __name__ == "__main__":
    main()
