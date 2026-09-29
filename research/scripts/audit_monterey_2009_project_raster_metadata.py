#!/usr/bin/env python3
"""Check original CSUMB project-raster datum without assigning it to GSF lines."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
URL = ("https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/"
       "CentralMontereyBay/multibeam/data/version1/metadata/"
       "CentralMontereyBay_Project.xml")
SHA256 = "36ca10ff75830005baeb4338a03ea51d080fc1cb2d793660730cfecda37cb8c3"
CONTEXT = ROOT / "dist/data/usgs-offshore-monterey-hard-context.geojson"


def bounds_of_feature(feature):
    geometry = feature["geometry"]
    if geometry["type"] not in ("Polygon", "MultiPolygon"):
        raise ValueError("Research outline geometry changed")

    def pairs(value):
        if isinstance(value[0], (int, float)):
            yield value
        else:
            for item in value:
                yield from pairs(item)

    coords = list(pairs(geometry["coordinates"]))
    if not coords:
        raise ValueError("Empty research geometry")
    return (min(x for x, _ in coords), min(y for _, y in coords),
            max(x for x, _ in coords), max(y for _, y in coords))


def intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def evaluate(raw: bytes, context_path: Path = CONTEXT) -> dict:
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("Original CSUMB project XML changed; review source")
    root = ET.fromstring(raw)
    product = root.findtext("./idinfo/citation/citeinfo/ftname")
    process = root.findtext("./dataqual/lineage/procstep/procdesc") or ""
    horizontal = root.findtext("./dataqual/posacc/horizpa/horizpar")
    vertical = root.findtext("./dataqual/posacc/vertacc/vertaccr")
    if (product != "cmb_n_2mbathy"
            or "Final x,y,z soundings, surface models, and derived products are relative to the NAVD88 Geoid09 vertical  datum" not in process
            or "Combined Uncertainty and Bathymetry Estimator (CUBE) Surface" not in process
            or horizontal != "±2 m horizontal, but varies with depth"
            or vertical != "± 20 cm vertical, but varies with depth"):
        raise ValueError("Project product, processing or accuracy semantics changed")
    bbox = root.find("./idinfo/spdom/bounding")
    if bbox is None:
        raise ValueError("Project metadata footprint missing")
    product_bounds = tuple(float(bbox.findtext(name)) for name in
                           ("westbc", "southbc", "eastbc", "northbc"))
    context = json.loads(context_path.read_text())
    research = {}
    for feature in context["features"]:
        ident = feature["properties"].get("id", "")
        if ident.endswith(("-023", "-046")):
            if feature["properties"].get("fishing_target") is not False:
                raise ValueError("Research-only outline changed")
            research[ident[-3:]] = {
                "within_documented_raster_bbox": intersects(product_bounds, bounds_of_feature(feature)),
                "selected_gsf_line_datum_proven": False,
                "fishing_target": False,
            }
    if (set(research) != {"023", "046"}
            or any(item["within_documented_raster_bbox"] for item in research.values())):
        raise ValueError("Project raster/research-outline footprint relationship changed")
    return {
        "schema_version": 1,
        "scope": "monterey-2009-original-csumb-project-raster-datum-scope",
        "source_url": URL,
        "source_sha256": SHA256,
        "source_product": product,
        "source_documented_bounds_wgs84": list(product_bounds),
        "source_process_summary": "CARIS HIPS and POSPAC SBET; finished x/y/z soundings, CUBE surface and derived raster described as NAVD88 Geoid09.",
        "source_reported_accuracy": {
            "horizontal": horizontal,
            "vertical": vertical,
            "conservative_upper_product_error_bounded": False,
        },
        "priority_outlines": research,
        "selected_processed_gsf_line_datum_proven": False,
        "mllw_depth_qualified": False,
        "fishing_target": False,
        "exportable": False,
        "limitation": "The XML describes the northern cmb_n_2mbathy raster, whose stated bounds exclude priority outlines 023 and 046. Its general final-product datum and depth-varying accuracy text cannot be assigned to the selected GSF files or used as an upper error bound.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "research/receipts/monterey-2009-project-raster-datum-scope.json")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    with urlopen(Request(URL, headers={"User-Agent": "SkipperCast-source-audit/1.0"}), timeout=30) as response:
        report = evaluate(response.read())
    if args.verify and report != json.loads(args.verify.read_text()):
        raise SystemExit("Project raster metadata changed; review before inference")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("Scoped original project XML to its northern raster; selected GSF datum still unproven")


if __name__ == "__main__":
    main()
