"""Repeat the measured-depth/original-substrate source screen across five coasts.

This is a source inventory, not a fishing-ground or legal-clearance publisher.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.review_nbs_hard_overlap import build


COASTS = ("northern", "mendocino", "san-francisco", "central", "southern")


def compile_statewide(review, sectors, hard_paths, scheme, cache, usgs_audit, usgs_audit_path,
                      usgs_cache, map_audit, map_audit_path, map_cache, mpas, federal):
    if review.get("scope") != "coast-nbs-multiple-rocky-camera-tile-source-review" or review.get("failed_tiles"):
        raise ValueError("Complete statewide NOAA tile review required")
    coast_by_sector = {row["id"]: row["coast"] for row in sectors["sectors"]}
    if set(coast_by_sector) != {row["sector_id"] for row in review["sectors"]}:
        raise ValueError("Statewide sector inventory changed")
    output = []
    for coast in COASTS:
        path = hard_paths[coast]
        coast_review = dict(review, sectors=[row for row in review["sectors"]
                                             if coast_by_sector[row["sector_id"]] == coast])
        source = build(coast_review, scheme, cache, json.loads(path.read_text()), path,
                       usgs_audit, usgs_audit_path, usgs_cache, mpas, federal,
                       map_audit=map_audit, map_audit_path=map_audit_path, map_cache=map_cache)
        output.append({"coast_id": coast, "source_file": str(path),
                       "source_review": source})
    return {"schema_version": 1, "scope": "california-nbs-usgs-original-class-source-review",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "status": "research-leads-only", "fishing_target": False, "exportable": False,
            "sample_method": "Top three historical rocky-camera-envelope NBS tiles per each of 19 approximate outer-coast sectors; this is not exhaustive statewide source coverage.",
            "limitations": ["Source-research overlap counts are not fish, spots, or catch probabilities.",
                            "Original-class counts use both hash-pinned USGS DOI and older DS 781 rasters; each tile names missing audited source classes.",
                            "NBS Modeling is a test-and-evaluation compilation; original NOAA contributor surveys, hazards and current charts require review.",
                            "Current species-specific rules, MPA/GEA boundaries and transit clearance require a separate site review."],
            "coasts": output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=Path("dist/data/nbs-statewide-multiple-camera-tile-review.json"))
    parser.add_argument("--sectors", type=Path, default=Path("catalog/coastal-sectors.json"))
    parser.add_argument("--scheme", type=Path, default=Path("var/modeling-tile-scheme-20260923.gpkg"))
    parser.add_argument("--cache", type=Path, default=Path("var/nbs-cache"))
    parser.add_argument("--hard-dir", type=Path, default=Path("dist/data"))
    parser.add_argument("--usgs-audit", type=Path, default=Path("var/usgs-doi-native-audit.json"))
    parser.add_argument("--usgs-cache", type=Path, default=Path("var/usgs-doi-native-cache"))
    parser.add_argument("--map-audit", type=Path, default=Path("var/usgs-native-audit.json"))
    parser.add_argument("--map-cache", type=Path, default=Path("var/usgs-native-cache"))
    parser.add_argument("--mpas", type=Path, default=Path("var/qualification-current/coastal/latest.json"))
    parser.add_argument("--federal", type=Path, default=Path("dist/data/noaa-federal-areas.json"))
    parser.add_argument("--output", type=Path, default=Path("dist/data/nbs-statewide-usgs-hard-overlap-review.json"))
    args = parser.parse_args()
    paths = {coast: args.hard_dir / f"usgs-hard-context-{coast}.geojson" for coast in COASTS}
    report = compile_statewide(json.loads(args.review.read_text()), json.loads(args.sectors.read_text()),
                               paths, args.scheme, args.cache, json.loads(args.usgs_audit.read_text()),
                               args.usgs_audit, args.usgs_cache, json.loads(args.map_audit.read_text()),
                               args.map_audit, args.map_cache, json.loads(args.mpas.read_text()),
                               json.loads(args.federal.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(args.output)
    for coast in report["coasts"]:
        tiles = [tile for sector in coast["source_review"]["sectors"] for tile in sector["tiles"]]
        print(coast["coast_id"], "sampled tiles", len(tiles), "original-class research cells",
              sum(tile["sensitivity_2m_original_class3_unique_pixels"] for tile in tiles),
              "unreviewed original class releases", len({name for tile in tiles for name in
                                                            tile["original_class_releases_not_audited"]}))


if __name__ == "__main__":
    main()
