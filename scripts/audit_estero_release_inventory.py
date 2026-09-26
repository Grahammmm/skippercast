#!/usr/bin/env python3
"""Pin the public Estero report inventory; distinguish TPU work from a TPU release."""

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE = "https://pubs.usgs.gov/of/2013/1225/"
EXPECTED = {
    "Amplitude_utm10_EsteroBay.zip",
    "WGS84_utm10_EsteroBay.zip",
    "NAD83_utm10_EsteroBay.zip",
    "StDev_utm10_EsteroBay.zip",
}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.all_hrefs = []
        self.words = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.suppressed += 1
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.all_hrefs.append(href)
            if href.lower().endswith(".zip"):
                self.hrefs.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.suppressed -= 1

    def handle_data(self, data):
        if not self.suppressed and data.strip():
            self.words.append(data.strip())

    def normalized_text(self):
        return re.sub(r"\s+", " ", " ".join(self.words))


def build(pages):
    parsed = {}
    for name, body in pages.items():
        parser = Links()
        parser.feed(body.decode("utf-8"))
        parsed[name] = parser
    releases = sorted({urljoin(BASE, link) for link in parsed["data_tables.html"].hrefs})
    names = {Path(link).name for link in releases}
    if names != EXPECTED or len(releases) != len(EXPECTED):
        raise ValueError("Public Estero release inventory changed; review new source files")
    ptext = parsed["data_processing.html"].normalized_text().lower()
    if "total propagated uncertainty" not in ptext or "swath angle base" not in ptext:
        raise ValueError("Estero processing evidence changed")
    return {
        "schema_version": 1,
        "scope": "estero-2012-public-release-inventory",
        "field_activity_id": "S-05-12-SC",
        "source_pages": {name: {"url": urljoin(BASE, name),
                               "normalized_content_sha256": hashlib.sha256(
                                   (parsed[name].normalized_text() + "\n" + "\n".join(sorted(parsed[name].all_hrefs))).encode()
                               ).hexdigest()}
                         for name in sorted(pages)},
        "listed_downloads": releases,
        "listed_tpu_or_base_surface": False,
        "processing_reports_tpu_computed": True,
        "custodian_request": [
            "CARIS Swath Angle BASE or TPU uncertainty surface for S-05-12-SC, with statistical definition and confidence level",
            "Original WGS84(G1150) horizontal frame epoch and survey processing/settings report",
            "Cellwise total horizontal and vertical uncertainty or documented conservative upper bounds",
            "Rights and original soundings or other reproducible way to verify the error budget",
        ],
        "interpretation": "Only this report's four listed ZIPs were checked. The sounding-spread raster and 1.96-times-spread figures are not a complete product TPU or an upper depth-error bound. Other archives or a custodian may hold it.",
        "qualified_waypoints": 0,
        "fishing_target": False,
        "exportable": False,
    }


def fetch():
    pages = {}
    for name in ("data_tables.html", "data_processing.html"):
        request = Request(urljoin(BASE, name), headers={"User-Agent": "Mozilla/5.0 (SkipperCast source audit)"})
        with urlopen(request, timeout=45) as response:
            pages[name] = response.read()
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    result = build(fetch())
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.verify and args.verify.read_text() != encoded:
        raise SystemExit("Estero release inventory changed; human source review required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded)


if __name__ == "__main__":
    main()
