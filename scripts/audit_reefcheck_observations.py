"""Audit a pinned statewide historical Reef Check sampling-event archive.

The output is broad-sector research context. Diver-site positions have 250 m
uncertainty, many are in MPAs, and the surveys target shallow rocky habitat.
It must never be compiled into a fishing waypoint or catch score.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def rows(archive, name):
    with archive.open(name) as data:
        reader = csv.DictReader(io.TextIOWrapper(data, encoding="utf-8-sig"), delimiter="\t")
        if not reader.fieldnames:
            raise ValueError("Missing archive header: " + name)
        yield from reader


def sector_for(latitude, sectors):
    matches = [s["id"] for s in sectors if s["latitude"][0] <= latitude < s["latitude"][1]]
    if latitude == 42.0:
        matches = [s["id"] for s in sectors if s["latitude"][1] == 42.0]
    if len(matches) > 1:
        raise ValueError("Overlapping sector latitude bands")
    return matches[0] if matches else None


def build(archive_path, manifest, sectors):
    with open(archive_path, "rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != manifest["archive_sha256"]:
        raise ValueError("Reef Check archive changed; review publisher version and contents")
    sector_list = sectors["sectors"]
    events = {}
    totals = Counter()
    by_sector = defaultdict(lambda: {"events": 0, "sites": set(), "years": set(),
                                     "depths_m": [], "uncertainty_m": set(),
                                     "substrate_events": set(), "relief_events": set(),
                                     "lingcod_present_events": set(), "rockfish_present_events": set(),
                                     "fish_taxa_present": set()})
    with zipfile.ZipFile(archive_path) as archive:
        if set(archive.namelist()) != set(manifest["expected_rows"]) | {"eml.xml", "meta.xml"}:
            raise ValueError("Unexpected Darwin Core archive members")
        for row in rows(archive, "event.txt"):
            totals["event.txt"] += 1
            ident = row["eventID"]
            if not ident or ident in events:
                raise ValueError("Missing or duplicate transect event ID")
            lat, lon = float(row["decimalLatitude"]), float(row["decimalLongitude"])
            uncertainty = float(row["coordinateUncertaintyInMeters"])
            if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(uncertainty)
                    and 32 <= lat <= 42.1 and -125 <= lon <= -117 and uncertainty >= 250):
                raise ValueError("Event lacks bounded coordinates or conservative uncertainty")
            sector = sector_for(lat, sector_list)
            events[ident] = sector
            if not sector:
                continue
            item = by_sector[sector]
            item["events"] += 1
            item["sites"].add((row["locality"], lat, lon))
            item["years"].add(row["eventDate"][:4])
            item["uncertainty_m"].add(uncertainty)
            depth = row["minimumDepthInMeters"]
            if depth and depth.lower() != "nan":
                number = float(depth)
                if not math.isfinite(number) or number < 0:
                    raise ValueError("Invalid transect depth")
                item["depths_m"].append(number)
        for row in rows(archive, "occurrence.txt"):
            totals["occurrence.txt"] += 1
            ident = row["eventID"]
            if ident not in events:
                raise ValueError("Occurrence refers to unknown transect")
            sector = events[ident]
            if not sector or row["occurrenceStatus"] != "present":
                continue
            item = by_sector[sector]
            scientific = row["scientificName"]
            if scientific == "Ophiodon elongatus":
                item["lingcod_present_events"].add(ident)
                item["fish_taxa_present"].add(scientific)
            elif scientific == "Sebastes" or scientific.startswith("Sebastes "):
                item["rockfish_present_events"].add(ident)
                item["fish_taxa_present"].add(scientific)
        for row in rows(archive, "extendedmeasurementorfact.txt"):
            totals["extendedmeasurementorfact.txt"] += 1
            ident = row["id"]
            if ident not in events:
                raise ValueError("Measurement refers to unknown transect")
            sector = events[ident]
            if sector and row["measurementType"] in {"substrate", "relief"}:
                by_sector[sector][row["measurementType"] + "_events"].add(ident)
    if dict(totals) != manifest["expected_rows"]:
        raise ValueError("Darwin Core table row counts changed")
    result = []
    for sector in sector_list:
        item = by_sector[sector["id"]]
        depths = item["depths_m"]
        result.append({"sector_id": sector["id"], "events": item["events"],
                       "distinct_site_labels_and_coordinates": len(item["sites"]),
                       "observation_years": sorted(item["years"]),
                       "observed_transect_depth_m": [round(min(depths), 1), round(max(depths), 1)] if depths else None,
                       "declared_position_uncertainty_m": sorted(item["uncertainty_m"]),
                       "events_with_substrate_measurement": len(item["substrate_events"]),
                       "events_with_relief_measurement": len(item["relief_events"]),
                       "events_with_lingcod_present": len(item["lingcod_present_events"]),
                       "events_with_any_rockfish_present": len(item["rockfish_present_events"]),
                       "identified_lingcod_or_rockfish_taxa_present": sorted(item["fish_taxa_present"])})
    return {"schema_version": 1, "scope": "statewide-historical-shallow-diver-observation-audit",
            "source_id": manifest["source_id"], "source_url": manifest["publisher_url"],
            "archive_sha256": digest, "publisher_date": manifest["publisher_date"],
            "fishing_target": False, "current_fish_presence": False, "exportable": False,
            "archive_table_rows": dict(totals), "sampled_sectors": sum(r["events"] > 0 for r in result),
            "sectors": result,
            "limitations": ["2006–2019 selected shallow reef/kelp scuba transects; not contemporary fishing effort or catch probability.",
                            "Every event declares at least 250 m position uncertainty. Site counts are label/coordinate combinations, not independent reef areas or exact fishing spots.",
                            "Sector assignment uses approximate latitude bands; islands and MPAs are not legal-screened by this audit.",
                            "Absences and presences are recorded only for the survey's selected taxa and methods. Do not infer deep-water absence from these shallow samples.",
                            "Research context only: no coordinates, target ranking, season badge or GPX export."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "catalog/reefcheck-observations.json")
    parser.add_argument("--sectors", type=Path, default=ROOT / "catalog/coastal-sectors.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((ROOT / "dist").resolve()):
        raise ValueError("Historical observation audit needs unpublished review before public release")
    receipt = build(args.archive, json.loads(args.manifest.read_text()), json.loads(args.sectors.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"sampled_sectors": receipt["sampled_sectors"], "events": receipt["archive_table_rows"]["event.txt"]}))


if __name__ == "__main__":
    main()
