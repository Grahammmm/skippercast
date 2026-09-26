#!/usr/bin/env python3
"""Find upstream-source leads in bounded official Central Coast BlueTopo RATs.

Contributor presence in a tile is a catalog lead, not measured cell coverage,
native source access, 300 ft depth qualification, or substrate evidence.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from scripts.audit_nbs_modeling_tile import contributors, is_measured_survey, sha256, verified_file


SECTORS = ("pigeon-monterey", "monterey-sur", "big-sur", "sur-san-simeon",
           "cambria-morro", "morro-conception")
SCHEME_SHA = "62db77bda8ce8deea24b4824c78e204f727ff434f1d91450cb8acfea5e188dcc"
SCHEME_URL = "https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/BlueTopo/_BlueTopo_Tile_Scheme/BlueTopo_Tile_Scheme_20260924_191855.gpkg"


def select_tiles(screen):
    if (screen.get("scope") != "central-nbs-300ft-original-source-screen"
            or screen.get("status") != "complete-source-screen"
            or screen.get("failed_tiles") != {}
            or screen.get("requested_unique_tiles") != screen.get("screened_unique_tiles")):
        raise ValueError("Central source-screen selection is incomplete")
    selected = []
    for row in screen["sectors"]:
        if row["sector_id"] not in SECTORS:
            raise ValueError("Unexpected Central Coast sector")
        selected.extend((row["sector_id"], item["tile"]) for item in row["tiles"])
    if len({tile for _, tile in selected}) != screen["requested_unique_tiles"] or len(selected) > 50:
        raise ValueError("BlueTopo tile selection changed")
    return selected


def build(scheme, selections, cache):
    digest = sha256(scheme)
    if digest != SCHEME_SHA:
        raise ValueError("BlueTopo scheme bytes changed")
    if not selections or any(sector not in SECTORS for sector, _ in selections):
        raise ValueError("Empty or unreviewed Central Coast tile selection")
    with sqlite3.connect(scheme) as db:
        table = db.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()
        if not table or table[0] != "BlueTopo_Tile_Scheme_20260924_191855":
            raise ValueError("Unexpected NOAA BlueTopo scheme table")
        db.row_factory = sqlite3.Row
        rows = []
        for sector, tile in selections:
            row = db.execute(f'SELECT * FROM "{table[0]}" WHERE tile=?', (tile,)).fetchone()
            if row is None or not row["RAT_Link"] or not row["RAT_SHA256_Checksum"]:
                raise ValueError("Official BlueTopo tile has no contributor table")
            rat = cache / (tile + ".tiff.aux.xml")
            rat_sha = verified_file(row["RAT_Link"], row["RAT_SHA256_Checksum"], rat, True,
                                    max_bytes=3_000_000)
            source_rows = contributors(rat)
            measured_rows = {item["source_survey_id"]: item for item in source_rows.values()
                             if is_measured_survey(item)}
            measured = sorted(measured_rows)
            rows.append({"sector_id": sector, "tile_id": tile,
                         "tile_delivered_at": row["Delivered_Date"],
                         "raster_url": row["GeoTIFF_Link"],
                         "raster_sha256": row["GeoTIFF_SHA256_Checksum"],
                         "rat_url": row["RAT_Link"], "rat_sha256": rat_sha,
                         "resolution_label": row["Resolution"],
                         "rat_contributor_count": len(source_rows),
                         "rat_measured_survey_ids": measured,
                         "rat_measured_source_leads": [
                             {"source_survey_id": sid,
                              "survey_date_end": measured_rows[sid]["survey_date_end"],
                              "source_institution": measured_rows[sid].get("source_institution"),
                              "license_name": measured_rows[sid].get("license_name")}
                             for sid in measured],
                         "fishing_target": False, "exportable": False})
    return {"schema_version": 1, "scope": "central-bluetopo-rat-upstream-source-leads",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "scheme_url": SCHEME_URL, "scheme_sha256": digest, "sectors": rows,
            "fishing_target": False, "exportable": False,
            "limitations": "RAT rows describe tile contributors, including historical hydrography and coastal DEMs; they do not prove those sources contribute pixels inside a species habitat patch or 200–300 ft band. BlueTopo is a NAVD88 compilation; inspect original source grids, measured masks, dates, datum and uncertainty before candidate release."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scheme", type=Path, required=True)
    p.add_argument("--source-screen", type=Path, default=Path("dist/data/nbs-central-300-depth-screen.json"))
    p.add_argument("--cache", type=Path, default=Path("var/review/bluetopo-central-rat"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    selections = select_tiles(json.loads(args.source_screen.read_text()))
    result = build(args.scheme, selections, args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print([(row["sector_id"], len(row["rat_measured_survey_ids"])) for row in result["sectors"]])


if __name__ == "__main__":
    main()
