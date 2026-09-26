#!/usr/bin/env python3
"""Pin related Point Buchon datum clues without assigning a datum to USGS cells."""

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
USGS_SHA = "67f5bd344c133d44fdabc3893f15dc7da6f0c69a30017d62ccfcfed60b4eec63"
PGE_SHA = "49babc172bc2de9e6fa349aa257499e9f88a5c69b89817f0963634f2bab9d77a"
CSUMB_SHA = "e8dbb107fce2008462fec99228a13897cda86fa1bda83dda002b98ede970b49c"
USGS_URL = "https://cmgds.marine.usgs.gov/catalog/pcmsc/DataReleases/CMGDS_DR_tool/DR_P9KBGELE/Bathymetry_OffshorePointBuchon_metadata.html"
PGE_URL = "https://www.pge.com/assets/pge/docs/about/pge-systems/Ch2.GEO.DCPP.TR.12.01_R1_AppA.pdf"
CSUMB_URL = "http://seafloor.otterlabs.org/SFMLwebDATA_c.htm#BUCHON"
CSUMB_ARCHIVES = (
    "http://arcims.csumb.edu/DATA_DOWNLOAD/PointBuchon07/PtBuchon_CON_2m_BathyGrids.zip",
    "http://arcims.csumb.edu/DATA_DOWNLOAD/PointBuchon07/PtBuchon_MPA_2m_BathyGrids.zip",
    "http://arcims.csumb.edu/DATA_DOWNLOAD/PointBuchon07/PtBuchon07_2m_xyz.zip",
)


def pinned(path, expected):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Original source changed: {path}")


def fetch(url, path, expected):
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast original-source audit"}), timeout=45) as response:
        if response.status != 200 or response.url != url:
            raise ValueError(f"Source unavailable or redirected: {url}")
        raw = response.read(20_000_001)
    if not raw or len(raw) > 20_000_000 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"Source bytes changed: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def build(usgs_path, pge_path, csumb_path):
    for path, expected in ((usgs_path, USGS_SHA), (pge_path, PGE_SHA), (csumb_path, CSUMB_SHA)):
        pinned(path, expected)
    root = ET.parse(usgs_path).getroot()
    vertical_statement = root.findtext("./dataqual/posacc/vertacc/vertaccr", default="")
    process = " ".join(node.text or "" for node in root.findall("./dataqual/lineage/procstep/procdesc"))
    if ("no less than 20 cm" not in vertical_statement
            or "2-meter resolution image for depths less than 80 meters" not in process
            or "5-meter resolution image for deeper areas" not in process
            or root.find("./spref/vertdef") is not None):
        raise ValueError("USGS processing or vertical datum metadata changed")
    pdf = PdfReader(pge_path)
    page = pdf.pages[12].extract_text()
    required = ("CSMB MBES Survey", "Pt. Buchon", "NAD83 (cors96 epoch 2002)",
                "NAVD88", "geoids03-09")
    if len(pdf.pages) != 111 or any(phrase not in page for phrase in required):
        raise ValueError("PG&E appendix datum table changed")
    html = csumb_path.read_text(errors="replace")
    if any(url not in html for url in CSUMB_ARCHIVES):
        raise ValueError("CSUMB legacy Point Buchon archive leads changed")
    return {
        "schema_version": 1,
        "scope": "point-buchon-datum-and-original-grid-provenance-leads",
        "source_sha256": {"usgs_bathymetry_metadata": USGS_SHA,
                          "pge_technical_appendix_pdf": PGE_SHA,
                          "csumb_legacy_library_html": CSUMB_SHA},
        "source_urls": {"usgs_bathymetry_metadata": USGS_URL,
                        "pge_technical_appendix_pdf": PGE_URL,
                        "csumb_legacy_library": CSUMB_URL,
                        "csumb_listed_archive_leads": list(CSUMB_ARCHIVES)},
        "related_csmp_mbes_product": {"reported_horizontal_frame": "NAD83(CORS96), epoch 2002, UTM 10N",
                                       "reported_vertical_datum": "NAVD88 (geoids03-09)",
                                       "table_pdf_page": 13,
                                       "same_bytes_or_processing_lineage_as_usgs_release_proven": False},
        "usgs_published_raster": {"horizontal_crs": "WGS84 UTM 10N",
                                  "output_vertical_datum": "unresolved",
                                  "upper_depth_uncertainty_m": None,
                                  "published_pixel_spacing_m": 2,
                                  "source_gridding_m_under_80m": 2,
                                  "source_gridding_m_deeper_than_80m": 5,
                                  "metadata_uncertainty_phrase_is_lower_bound_only": True},
        "acquisition_actions": ["Obtain CSUMB/Fugro original Point Buchon bathymetry survey processing report and CUBE/TPU or BASE uncertainty surface.",
                                "Establish source file and processing-lineage linkage between the PG&E CSMP comparison grid and the USGS 2022 GeoTIFF.",
                                "Obtain an explicitly declared output vertical datum, horizontal realization and epoch for the USGS raster and original 5 m deep grid.",
                                "Resolve the two listed 2007 Point Buchon control and MPA bathymetry archives or request current copies from the CSUMB data custodian."],
        "qualified_waypoints": 0, "fishing_target": False, "exportable": False,
        "limitations": ["A datum stated for a related CSMP grid cannot be assigned to the later USGS mosaic without source-to-source provenance.",
                        "The 20 cm phrase is a lower bound on accuracy, not a maximum vertical error.",
                        "Listed legacy download URLs are acquisition leads, not verified accessible or same-survey products."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usgs", type=Path, default=ROOT / "var/review/usgs-point-buchon/Bathymetry_OffshorePointBuchon_metadata.xml")
    parser.add_argument("--pge", type=Path, default=ROOT / "var/review/pge-point-buchon-mbes-datum-comparison.pdf")
    parser.add_argument("--csumb", type=Path, default=ROOT / "var/review/csumb-central-library.html")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/point-buchon-datum-provenance-leads.json")
    parser.add_argument("--fetch", action="store_true", help="Fetch the pinned official USGS, PG&E and CSUMB sources")
    args = parser.parse_args()
    if args.fetch:
        usgs_raw = "https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9KBGELE/134dbdd47ee649b1863acc6cfa6ed0e6/Bathymetry_OffshorePointBuchon_metadata.xml"
        fetch(usgs_raw, args.usgs, USGS_SHA)
        fetch(PGE_URL, args.pge, PGE_SHA)
        fetch(CSUMB_URL.split("#")[0], args.csumb, CSUMB_SHA)
    report = build(args.usgs, args.pge, args.csumb)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Point Buchon related datum and original-grid leads pinned; USGS datum unresolved")


if __name__ == "__main__":
    main()
