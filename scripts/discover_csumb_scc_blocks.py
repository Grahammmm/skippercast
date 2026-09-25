"""Inventory original CSUMB SCC and Big Sur South survey blocks at NOAA NCEI.

Catalog envelopes are discovery leads, never measured footprints or fishing marks.
The large native archives are deliberately not downloaded by this inventory.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

REPORT = "https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block{number:02d}_mb.html"
DATA_HOST = "data.ngdc.noaa.gov"
SERIES = {
    "scc": {"prefix": "SCC", "count": 28, "report": REPORT,
            "metadata_name": "SCC_CSMP_Metadata.txt", "metadata_marker": "South Central Coast California GIS Products Metadata"},
    "bss": {"prefix": "BSS", "count": 13,
            "report": "https://www.ngdc.noaa.gov/ships/r_v_harold_heath/BSS_Block{number:02d}_mb.html",
            "metadata_name": "BigSurSouth_BSS_Project.xml", "metadata_marker": "Big Sur"},
}
SECTORS = {
    "big-sur": (35.9, 36.3),
    "sur-san-simeon": (35.6, 35.9),
    "cambria-morro": (35.35, 35.6),
    "morro-conception": (34.45, 35.35),
}


def fetch(url, limit=500_000):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ("www.ngdc.noaa.gov", DATA_HOST):
        raise ValueError("Unreviewed survey host")
    with urlopen(Request(url, headers={"User-Agent": "SkipperCast source inventory/1.0"}), timeout=25) as response:
        if urlsplit(response.url).hostname not in ("www.ngdc.noaa.gov", DATA_HOST):
            raise ValueError("Survey source redirected outside NOAA NCEI")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Survey metadata exceeds size limit")
        return data


def parse_report(number, raw, *, series="scc"):
    spec = SERIES[series]
    survey = f"{spec['prefix']}_Block{number:02d}"
    page = raw.decode("utf-8", errors="replace")
    def extent(label):
        match = re.search(rf"<b>{re.escape(label)}:</b></td>\s*<td>(-?\d+(?:\.\d+)?)</td>", page)
        if not match:
            raise ValueError(f"{survey}: missing {label}")
        return float(match.group(1))
    north, south = extent("Northern Extent"), extent("Southern Extent")
    west, east = extent("Western Extent"), extent("Eastern Extent")
    if not (-125 < west < east < -116 and 32 < south < north < 42):
        raise ValueError(f"{survey}: impossible California envelope")
    archive_match = re.search(
        rf'href="(https?://data\.ngdc\.noaa\.gov/[^" ]+/{survey}_additional_products\.tar\.gz)"', page
    )
    metadata_match = re.search(
        rf'href="(https?://data\.ngdc\.noaa\.gov/[^" ]+/{spec["metadata_name"]})"', page
    )
    if not archive_match or not metadata_match:
        raise ValueError(f"{survey}: original product or metadata link absent")
    archive = archive_match.group(1).replace("http://", "https://")
    metadata = metadata_match.group(1).replace("http://", "https://")
    for url in (archive, metadata):
        if urlsplit(url).hostname != DATA_HOST or f"/{survey}/" not in url:
            raise ValueError(f"{survey}: unrelated archive or metadata")
    return {
        "survey_id": survey,
        "report_url": spec["report"].format(number=number),
        "report_sha256": hashlib.sha256(raw).hexdigest(),
        "catalog_envelope": [west, south, east, north],
        "sector_ids": [key for key, (low, high) in SECTORS.items() if south < high and north > low],
        "original_products_url": archive,
        "metadata_url": metadata,
        "footprint_kind": "survey-track-envelope",
        "status": "source-lead-only",
    }


def collect(*, series="scc", fetcher=fetch, checked_at=None):
    spec = SERIES[series]
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    with ThreadPoolExecutor(max_workers=5) as pool:
        pages = list(pool.map(lambda n: fetcher(spec["report"].format(number=n)), range(1, spec["count"] + 1)))
    rows = [parse_report(n, raw, series=series) for n, raw in enumerate(pages, 1)]
    metadata_url = rows[0]["metadata_url"]
    metadata = fetcher(metadata_url)
    text = metadata.decode("cp1252", errors="replace")
    if spec["metadata_marker"].lower() not in text.lower():
        raise ValueError("CSUMB series metadata does not match the reviewed edition")
    return {
        "schema_version": 1,
        "series": series,
        "checked_at": checked_at,
        "producer": "CSU Monterey Bay Seafloor Mapping Lab; NOAA NCEI distribution",
        "series_metadata_url": metadata_url,
        "series_metadata_sha256": hashlib.sha256(metadata).hexdigest(),
        "survey_count": len(rows),
        "surveys": rows,
        "limitations": [
            "Survey-track envelopes overlap and do not establish measured-cell coverage or a reef boundary.",
            "The original native archives, per-file XML, horizontal and vertical datums, uncertainty, substrate, rights and current chart hazards require review before any fishing target.",
            "Blocks named for MPAs in the series metadata are not legal fishing areas; all blocks require current CDFW and federal closure screening.",
            "No catalog lead is a fishing waypoint, drift, catch record, safe route or chartplotter export.",
        ],
    }


def compare(current, baseline):
    if current.get("series", "scc") != baseline.get("series", "scc"):
        return ["series-identity"]
    old = {row["survey_id"]: row for row in baseline["surveys"]}
    changed = []
    for row in current["surveys"]:
        prior = old.get(row["survey_id"])
        if prior is None or any(row[key] != prior.get(key) for key in ("catalog_envelope", "original_products_url", "metadata_url")):
            changed.append(row["survey_id"])
    if len(old) != SERIES[current.get("series", "scc")]["count"] or current["series_metadata_sha256"] != baseline.get("series_metadata_sha256"):
        changed.append("series-metadata-or-roster")
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--series", choices=sorted(SERIES), default="scc")
    args = parser.parse_args()
    result = collect(series=args.series)
    if args.baseline:
        result["changed_source_ids"] = compare(result, json.loads(Path(args.baseline).read_text()))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['survey_count']} CSUMB blocks; changed source IDs: {result.get('changed_source_ids', [])}")
    if result.get("changed_source_ids"):
        raise SystemExit("Original source identity changed; review before updating the baseline")


if __name__ == "__main__":
    main()
