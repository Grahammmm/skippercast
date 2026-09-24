"""Audit CDFW historical RCGL recreational catch blocks as broad context only.

The 1-minute blocks are interview-reported and may include multiple blocks per
trip, mixed species, shore trips, MPAs and old rules. Never generate target marks.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
LAYER = "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds3185_fpu/FeatureServer/0"
EXPECTED_EDIT_MS = 1753738702086
EXPECTED_COUNT = 4471
FIELDS = "OBJECTID,BlockBox,Catch,Trip,All_21_24,Kept_21_24,Samples"


def fetch(url):
    with urlopen(url, timeout=90) as response:
        body = response.read()
    data = json.loads(body)
    if "error" in data:
        raise ValueError(f"CDFW service failed: {data['error']}")
    return data, hashlib.sha256(body).hexdigest()


def query(**params):
    return fetch(LAYER + "/query?" + urlencode({**params, "f": "json"}))


def sector_for(lat, sectors):
    matches = [s["id"] for s in sectors if s["latitude"][0] <= lat < s["latitude"][1]]
    if lat == 42.0:
        matches = [s["id"] for s in sectors if s["latitude"][1] == 42.0]
    if len(matches) > 1:
        raise ValueError("Overlapping browse sectors")
    return matches[0] if matches else None


def center_of_block(geometry):
    rings = geometry.get("rings") or []
    points = [p for ring in rings for p in ring]
    if not points or any(len(p) < 2 or not all(math.isfinite(v) for v in p[:2]) for p in points):
        raise ValueError("CDFW block lacks valid geometry")
    west, east = min(p[0] for p in points), max(p[0] for p in points)
    south, north = min(p[1] for p in points), max(p[1] for p in points)
    if not (-126 <= west < east <= -116 and 32 <= south < north <= 43
            and east - west <= .03 and north - south <= .03):
        raise ValueError("CDFW block has an invalid California location or extent")
    return (south + north) / 2, (west + east) / 2


def classify(value):
    if value == -9999 or value is None:
        return "unavailable"
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid CDFW CPUA")
    return "positive" if value > 0 else "zero"


def summarize(features, sectors):
    groups = defaultdict(lambda: {"blocks": 0, "samples_all_periods": 0,
                                  "recent_all": defaultdict(int), "recent_kept": defaultdict(int)})
    seen_oid, seen_block = set(), set()
    outside = 0
    for feature in features:
        row = feature["attributes"]
        oid, block = row["OBJECTID"], row["BlockBox"]
        if oid in seen_oid or block in seen_block or not block:
            raise ValueError("Duplicate or missing CRFS block identity")
        seen_oid.add(oid)
        seen_block.add(block)
        if row["Catch"] != "RCGL" or row["Trip"] != "Bottomfish":
            raise ValueError("Unexpected CRFS catch or effort scope")
        samples = row["Samples"]
        if not isinstance(samples, int) or samples < 3:
            raise ValueError("Unexpected CRFS all-period survey sample count")
        lat, _ = center_of_block(feature["geometry"])
        sector = sector_for(lat, sectors)
        if sector is None:
            outside += 1
            continue
        group = groups[sector]
        group["blocks"] += 1
        group["samples_all_periods"] += samples
        group["recent_all"][classify(row["All_21_24"])] += 1
        group["recent_kept"][classify(row["Kept_21_24"])] += 1
    return [{"sector_id": s["id"], "reported_blocks": groups[s["id"]]["blocks"],
             "survey_samples_2004_2024_sum": groups[s["id"]]["samples_all_periods"],
             "blocks_2021_2024_all_catch": dict(sorted(groups[s["id"]]["recent_all"].items())),
             "blocks_2021_2024_kept_catch": dict(sorted(groups[s["id"]]["recent_kept"].items()))}
            for s in sectors], outside


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((ROOT / "dist").resolve()):
        raise ValueError("CRFS block review needs unpublished inspection before release")
    metadata, metadata_sha = fetch(LAYER + "?f=json")
    if (metadata.get("editingInfo", {}).get("lastEditDate") != EXPECTED_EDIT_MS
            or not set(FIELDS.split(",")) <= {f["name"] for f in metadata.get("fields", [])}):
        raise ValueError("CDFW CRFS layer revision or schema changed")
    count_data, _ = query(where="1=1", returnCountOnly="true")
    if count_data["count"] != EXPECTED_COUNT:
        raise ValueError("CDFW CRFS block count changed")
    features, pages = [], []
    for offset in range(0, EXPECTED_COUNT, 1000):
        data, digest = query(where="1=1", outFields=FIELDS, outSR=4326,
                             returnGeometry="true", orderByFields="OBJECTID ASC",
                             resultOffset=offset, resultRecordCount=min(1000, EXPECTED_COUNT - offset))
        page = data.get("features", [])
        if len(page) != min(1000, EXPECTED_COUNT - offset):
            raise ValueError("Incomplete CRFS source page")
        features.extend(page)
        pages.append({"offset": offset, "rows": len(page), "response_sha256": digest})
    sectors = json.loads((ROOT / "catalog/coastal-sectors.json").read_text())["sectors"]
    groups, outside = summarize(features, sectors)
    receipt = {"schema_version": 1, "source": LAYER, "source_metadata_sha256": metadata_sha,
               "source_last_edit_ms": EXPECTED_EDIT_MS, "retrieved_at": datetime.now(timezone.utc).isoformat(),
               "records_reviewed": len(features), "outside_browse_sectors": outside,
               "source_pages": pages, "sectors": groups,
               "fishing_target": False, "current_fish_presence": False, "exportable": False,
               "limitations": ["CDFW combined RCGL catch per bottomfish angler, not species-specific lingcod or rockfish catch and not a boat-only survey.",
                               "One-minute blocks are interview-reported; when a trip reported several blocks, catch was divided among them. They are not observed catch coordinates or seafloor habitat.",
                               "Data are multi-year historical 2004–2024; the recent columns combine 2021–2024 and may contain -9999 missing values, which this audit keeps separate from zero.",
                               "Only blocks with at least three reported trips over the whole period were included; the Samples field is all-period and cannot weight the recent 2021–2024 CPUA.",
                               "Some service polygons are clipped smaller than the nominal one-minute block. Browse-sector assignment uses their envelope centers and latitude only; legal MPAs, fisheries rules, exact target areas, chart hazards, season and depth are not inferred.",
                               "No public block-level catch polygons, fishing scores, routes or chartplotter exports are generated."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"records": len(features), "sectors_with_blocks": sum(g["reported_blocks"] > 0 for g in groups)}))


if __name__ == "__main__":
    main()
