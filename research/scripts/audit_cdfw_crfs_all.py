"""Audit CDFW's all-species CRFS blocks as a survey-coverage baseline.

These interview-reported blocks combine every species and fishing mode. They
cannot validate a reef, target species, current fish presence, or catch odds.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repository root, for research.*
from research.scripts.audit_cdfw_crfs_rcgl import center_of_block, classify, fetch, sector_for


ROOT = Path(__file__).resolve().parents[2]
LAYER = "https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds3186_fpu/FeatureServer/0"
EXPECTED_EDIT_MS = 1753738727693
EXPECTED_COUNT = 6936
FIELDS = "OBJECTID,BlockBox,Catch,Trip,All_21_24,Kept_21_24,Samples"
REVIEWED_OVERSIZE_GEOMETRY = {4098: "489-233"}


def summarize(features, sectors):
    groups = defaultdict(lambda: {"blocks": 0, "samples_all_periods": 0,
                                  "recent_all": defaultdict(int), "recent_kept": defaultdict(int)})
    seen_oid, seen_block = set(), set()
    outside = 0
    anomalous = []
    for feature in features:
        row = feature["attributes"]
        oid, block = row["OBJECTID"], row["BlockBox"]
        if oid in seen_oid or block in seen_block or not block:
            raise ValueError("Duplicate or missing all-species CRFS block identity")
        seen_oid.add(oid)
        seen_block.add(block)
        if row["Catch"] != "All" or row["Trip"] != "All":
            raise ValueError("CDFW all-species source scope changed")
        if not isinstance(row["Samples"], int) or row["Samples"] < 3:
            raise ValueError("Unexpected all-period CRFS sample count")
        try:
            lat, _ = center_of_block(feature["geometry"])
        except ValueError:
            if REVIEWED_OVERSIZE_GEOMETRY.get(oid) != block:
                raise
            # The public polygon spans about 0.044° longitude, beyond the
            # nominal 1' block. Keep it out of spatial summaries and surface it.
            anomalous.append({"object_id": oid, "block_box": block})
            continue
        sector = sector_for(lat, sectors)
        if sector is None:
            outside += 1
            continue
        group = groups[sector]
        group["blocks"] += 1
        group["samples_all_periods"] += row["Samples"]
        group["recent_all"][classify(row["All_21_24"])] += 1
        group["recent_kept"][classify(row["Kept_21_24"])] += 1
    return ([{"sector_id": s["id"], "reported_blocks": groups[s["id"]]["blocks"],
              "survey_samples_2004_2024_sum": groups[s["id"]]["samples_all_periods"],
              "blocks_2021_2024_all_catch": dict(sorted(groups[s["id"]]["recent_all"].items())),
              "blocks_2021_2024_kept_catch": dict(sorted(groups[s["id"]]["recent_kept"].items()))}
             for s in sectors], outside, anomalous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((ROOT / "dist").resolve()):
        raise ValueError("All-species block audit needs unpublished review before release")
    metadata, metadata_sha = fetch(LAYER + "?f=json")
    field_names = {field["name"] for field in metadata.get("fields", [])}
    if metadata.get("editingInfo", {}).get("lastEditDate") != EXPECTED_EDIT_MS or not set(FIELDS.split(",")) <= field_names:
        raise ValueError("CDFW all-species CRFS edition or schema changed")

    # Import the same HTTP/query handling used by the reviewed RCGL source.
    from urllib.parse import urlencode

    def query(**params):
        return fetch(LAYER + "/query?" + urlencode({**params, "f": "json"}))

    count_data, _ = query(where="1=1", returnCountOnly="true")
    if count_data.get("count") != EXPECTED_COUNT:
        raise ValueError("CDFW all-species CRFS count changed")
    features, pages = [], []
    for offset in range(0, EXPECTED_COUNT, 1000):
        expected = min(1000, EXPECTED_COUNT - offset)
        data, digest = query(where="1=1", outFields=FIELDS, outSR=4326,
                             returnGeometry="true", orderByFields="OBJECTID ASC",
                             resultOffset=offset, resultRecordCount=expected)
        page = data.get("features", [])
        if len(page) != expected:
            raise ValueError("Incomplete all-species CRFS page")
        features.extend(page)
        pages.append({"offset": offset, "rows": len(page), "response_sha256": digest})
    sectors = json.loads((ROOT / "catalog/coastal-sectors.json").read_text())["sectors"]
    groups, outside, anomalous = summarize(features, sectors)
    if {item["object_id"] for item in anomalous} != set(REVIEWED_OVERSIZE_GEOMETRY):
        raise ValueError("Reviewed CDFW geometry anomaly changed or disappeared")
    receipt = {
        "schema_version": 1, "scope": "CDFW CRFS historical all-species all-effort survey baseline",
        "source": LAYER, "source_metadata_sha256": metadata_sha,
        "source_last_edit_ms": EXPECTED_EDIT_MS,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "records_reviewed": len(features), "outside_browse_sectors": outside,
        "excluded_oversize_geometries": anomalous,
        "source_pages": pages, "sectors": groups,
        "fishing_target": False, "species_specific": False,
        "current_fish_presence": False, "exportable": False,
        "limitations": [
            "Catch and trip categories are both All. This is not lingcod, rockfish, or private-boat evidence.",
            "One-minute interview-reported blocks allocate catch across all reported blocks of a multi-block trip. They are not exact catch locations or seabed observations.",
            "2021–2024 fields are multi-year aggregates; Samples covers 2004–2024 and cannot weight a recent-period catch rate. -9999 means unavailable, not zero.",
            "Blocks require at least three trips over the full period. Approximate latitude browse sectors, clipped geometries, MPAs and legal access are not resolved by this audit.",
            "OBJECTID 4098 (489-233) has a public polygon roughly 0.044° wide, beyond the expected 1' block, and is excluded from spatial summaries pending source correction.",
            "This source is only a broad survey-coverage and potential sampling-bias reference. It cannot raise a 1–3 habitat rank or generate a fishing mark.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"records": len(features), "sectors_with_blocks": sum(g["reported_blocks"] > 0 for g in groups)}))


if __name__ == "__main__":
    main()
