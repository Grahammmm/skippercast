#!/usr/bin/env python3
"""Index original Point Buchon processed-line depth envelopes for research triage.

An .inf minimum/maximum spans a whole line in its *unknown* vertical datum.
It does not locate a 200–300 ft sounding or establish fishable habitat.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re

from scripts.audit_point_buchon_ncei_multibeam_lead import (
    LOWER_M, UPPER_M, Page, PROBES, SURVEYS, companion_urls, fetch,
)


def line_range(data):
    match = re.search(rb"Minimum Depth:\s*([-\d.]+)\s+Maximum Depth:\s*([-\d.]+)", data)
    if not match:
        raise ValueError("NCEI generated line summary lacks a depth range")
    low, high = map(float, match.groups())
    if low < 0 or high < low or high > 3000:
        raise ValueError("NCEI generated line summary depth range changed")
    return low, high


def archive_lines(name, fetcher=fetch):
    url = f"https://www.ngdc.noaa.gov/ships/ventresca/{name}_mb.html"
    page = Page()
    page.feed(fetcher(url).decode("utf-8", errors="replace"))
    lines = sorted({link.replace("http://", "https://", 1) for link in page.links
                    if link.endswith(".gsf.mb121.gz")})
    if name not in SURVEYS or len(lines) < 50 or PROBES[name]["url"] not in lines:
        raise ValueError("NCEI Point Buchon processed-line inventory changed")
    return url, lines


def index(fetcher=fetch):
    surveys = []
    for name in SURVEYS:
        page_url, lines = archive_lines(name, fetcher)
        def one(url):
            inf_url, _ = companion_urls(url)
            body = fetcher(inf_url)
            low, high = line_range(body)
            return {"line": url.rsplit("/", 1)[1], "inf_url": inf_url,
                    "inf_sha256": hashlib.sha256(body).hexdigest(),
                    "minimum_depth_m_unknown_datum": low,
                    "maximum_depth_m_unknown_datum": high}
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(one, lines))
        if len(rows) != len(lines) or len({row["line"] for row in rows}) != len(lines):
            raise ValueError("NCEI generated line summaries incomplete")
        candidates = [row for row in rows
                      if row["minimum_depth_m_unknown_datum"] <= UPPER_M
                      and row["maximum_depth_m_unknown_datum"] >= LOWER_M]
        canonical = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        surveys.append({"survey_id": name, "archive_page_url": page_url,
                        "processed_line_count": len(rows),
                        "all_generated_line_summaries_sha256": hashlib.sha256(canonical).hexdigest(),
                        "nominal_200_300ft_unknown_datum_envelope_line_count": len(candidates),
                        "nominal_envelope_candidate_lines": candidates})
    return {"schema_version": 1, "scope": "point-buchon-2007-ncei-generated-line-depth-index",
            "source_datum": "Unknown; nominal line-depth-envelope triage only",
            "surveys": surveys, "qualified_waypoints": 0, "fishing_target": False,
            "limitation": "A whole-line depth range does not locate an individual beam in the band, confirm chart datum or uncertainty, or establish rock, lawful access or fish. Candidate lines require valid sounding-position, datum, uncertainty and cross-survey registration checks."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(index(), indent=2) + "\n"
    if args.verify and args.verify.read_text() != encoded:
        raise SystemExit("Point Buchon NCEI line-depth index changed; review before using")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded)


if __name__ == "__main__":
    main()
