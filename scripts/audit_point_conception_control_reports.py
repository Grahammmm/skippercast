#!/usr/bin/env python3
"""Pin NOAA Point Conception processing/control evidence without inventing an error bound."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "var/review/point-conception-control-reports"
OUTPUT = ROOT / "dist/data/point-conception-processing-control-review.json"
SOURCES = {
    "project_dapr": (
        "https://data.ngdc.noaa.gov/platforms/ocean/nos/DAPRs/M-L906-KR-08_DAPR_Part2.pdf",
        "64758c2bcc8f2dee28170f95e2fde06afc4ad8290a5d5d681a707663cda70257",
        1819044,
    ),
    "H11952_tide_note": (
        "https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11952/TIDES/H11952.tn.pdf",
        "08ee39d79e88685d5f0acab18f351cf1c9d45c08bf2aef657ffefce4e99fc7ee",
        58808,
    ),
    "H11953_tide_note": (
        "https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11953/TIDES/H11953.tn.pdf",
        "a776f760250c4d80cf487cb93e0c445bbd7c872b6f7f928699772df3ee0fa6e0",
        114865,
    ),
}


def verified_pdf(name, cache, fetch):
    url, digest, size = SOURCES[name]
    path = cache / url.rsplit("/", 1)[-1]
    if fetch:
        cache.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"User-Agent": "SkipperCast-source-audit/1.0"})
        with urlopen(request, timeout=60) as response:
            body = response.read(size + 1)
        if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
            raise ValueError(f"NOAA {name} source changed")
        path.write_bytes(body)
    if not path.exists() or path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f"NOAA {name} source missing or changed")
    return path


def build(cache=CACHE, fetch=False):
    texts = {}
    for name in SOURCES:
        path = verified_pdf(name, cache, fetch)
        texts[name] = re.sub(r"\s+", " ", " ".join(page.extract_text() or "" for page in PdfReader(path).pages)).lower()
    dapr = texts["project_dapr"]
    if not all(token in dapr for token in ("h11952", "h11953", "navigation", "0.10 m", "rms", "gps", "vdatum")):
        raise ValueError("NOAA project processing meaning changed")
    for name in ("H11952_tide_note", "H11953_tide_note"):
        body = texts[name]
        if not all(token in body for token in ("ppk", "nad83", "mllw", "vdatum", "gpstide", "horizontal and vertical")):
            raise ValueError(f"NOAA {name} control meaning changed")
    return {
        "schema_version": 1, "scope": "point-conception-h11952-h11953-noaa-processing-control-review",
        "source_urls": {name: item[0] for name, item in SOURCES.items()},
        "source_sha256": {name: item[1] for name, item in SOURCES.items()},
        "survey_ids": ["H11952", "H11953"],
        "documented_method": "Post-processed GPS/SBET, CARIS GPSTide and NOAA VDatum NAD83-ellipsoid to MLLW offset grids; BAG is already MLLW.",
        "position_model_base_navigation_input_m": 0.10,
        "position_model_base_is_total_horizontal_bound": False,
        "per_line_dynamic_rms_overrides_documented": True,
        "per_patch_line_rms_available_in_reviewed_public_reports": False,
        "usgs_character_to_bag_horizontal_registration_bounded": False,
        "fishing_target": False, "exportable": False,
        "limitations": [
            "The 0.10 m navigation input is a model parameter; project processing says line-specific RMS often overrides it. It is not a total horizontal uncertainty bound.",
            "The published tide notes establish the reduction path but not a per-patch VDatum or horizontal error envelope.",
            "The original line-specific CARIS RMS/TPU and independent USGS-class registration still need review before promoting a small reef patch.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = build(args.cache, args.fetch)
    if args.verify and result != json.loads(args.verify.read_text()):
        raise SystemExit("Point Conception processing review changed; hold for review")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("NOAA processing and tide documents reviewed; horizontal registration remains unbounded")


if __name__ == "__main__":
    main()
