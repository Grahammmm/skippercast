"""Review every cached fine regular NOAA BAG with actual USGS rocky camera overlap.

The result is a source-review queue, never a statewide fishing-spot generator.
Every BAG is selected by exact original URL and SHA, not a shared survey ID.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from scripts.audit_regular_bag_camera import review
from scripts.audit_usgs_video_observations import load_archive, open_original_zip, sector_for


def rocky_camera_positions(manifest, cache):
    positions = {}
    for cruise, digest in sorted(manifest["archives"].items()):
        raw = load_archive(cache, cruise, digest, manifest["base_url"], False)
        points = []
        for item in open_original_zip(raw).iterShapeRecords():
            if not item.shape.points:
                continue
            kind = str(item.record.as_dict().get("MAJOR_GEO") or "").strip().lower()
            if kind in {"rock", "boulder", "cobble"}:
                lon, lat = item.shape.points[0]
                points.append((lon, lat))
        positions[cruise] = points
    return positions


def candidate_pairs(audit, positions):
    pairs = []
    for record in audit["files"]:
        bounds = record.get("raster_bounds_wgs84")
        resolution = record.get("overview_resolution_m")
        if (record.get("status") != "ok" or not bounds or not resolution
                or max(resolution) > 4 or record.get("variable_refinement_records") != 0):
            continue
        west, south, east, north = bounds
        for cruise, points in positions.items():
            overlap = sum(west <= lon <= east and south <= lat <= north for lon, lat in points)
            if overlap:
                pairs.append((record, cruise, overlap))
    return pairs


def deduplicate_camera_windows(rows):
    """Count original camera records once across overlapping NOAA BAG files."""
    archives = {}
    unique = set()
    positive_rockfish = set()
    positive_lingcod = set()
    transects = set()
    sector_windows = {}
    sector_transects = {}
    attributed_sectors = {}
    pair_window_count = 0
    for row in rows:
        cruise = row["cruise"]
        digest = row["camera_archive_sha256"]
        if cruise in archives and archives[cruise] != digest:
            raise ValueError(f"One cruise refers to different camera archive bytes: {cruise}")
        archives[cruise] = digest
        local = set()
        sector = row.get("sector_id")
        for group in row["transects"]:
            indices = group["camera_record_indices"]
            if len(indices) != group["window_count"] or len(indices) != len(set(indices)):
                raise ValueError("Camera record indices do not match transect windows")
            keys = {(cruise, index) for index in indices}
            if local & keys:
                raise ValueError("Camera record appears twice in one BAG review")
            local.update(keys)
            transect = (cruise, group["date"], group["line"])
            transects.add(transect)
            sector_transects.setdefault(sector, set()).add(transect)
            for field, destination, count_field in (
                ("rockfish_positive_record_indices", positive_rockfish, "rockfish_positive_windows"),
                ("lingcod_positive_record_indices", positive_lingcod, "lingcod_positive_windows"),
            ):
                positives = group[field]
                if positives is None:
                    if group[count_field] is not None:
                        raise ValueError("Missing camera species field has a positive count")
                    continue
                if len(positives) != group[count_field] or not set(positives) <= set(indices):
                    raise ValueError("Positive camera record indices do not match transect counts")
                destination.update((cruise, index) for index in positives)
        if len(local) != row["counts"].get("qualified_rocky_camera_windows", 0):
            raise ValueError("Camera record indices do not match BAG pair counts")
        pair_window_count += len(local)
        unique.update(local)
        if local:
            sector_windows.setdefault(sector, set()).update(local)
        for key in local:
            attributed_sectors.setdefault(key, set()).add(sector)
    return {
        "pair_attributed_qualified_windows": pair_window_count,
        "distinct_original_camera_windows": len(unique),
        "repeated_pair_attributions": pair_window_count - len(unique),
        "distinct_original_camera_transects": len(transects),
        "distinct_historical_rockfish_positive_windows": len(positive_rockfish),
        "distinct_historical_lingcod_positive_windows": len(positive_lingcod),
        "camera_windows_attributed_to_multiple_browse_sectors": sum(len(v) > 1 for v in attributed_sectors.values()),
        "by_approximate_sector": [
            {"sector_id": sector, "distinct_original_camera_windows": len(windows),
             "distinct_original_camera_transects": len(sector_transects.get(sector, set()))}
            for sector, windows in sorted(sector_windows.items(), key=lambda item: item[0] or "")
        ],
        "identity": "Original camera archive cruise plus zero-based shapefile record index; source ZIP SHA-256 is checked separately.",
        "limitations": ["The same transect can cross survey BAG files or browse sectors; a transect is not an independent fishing site.",
                        "Historical visual species codes are not catches, abundance estimates or evidence of current presence.",
                        "Rows omitted by missing BAGs, unsupported datums or closure screens are not represented by these counts."]
    }


def reviewed_hazards(catalog, report_cache, survey_id, report_url):
    """Link a lead only to the exact original report inspected for hazards."""
    matches = [item for item in catalog["surveys"] if item["survey_id"] == survey_id]
    if len(matches) > 1:
        raise ValueError(f"Duplicate historical hazard review: {survey_id}")
    if not matches:
        return None
    item = matches[0]
    if item["report_url"] != report_url:
        raise ValueError(f"Historical hazard review refers to another report: {survey_id}")
    original = report_cache / f"{survey_id}.pdf"
    if not original.is_file():
        return None
    actual = hashlib.sha256(original.read_bytes()).hexdigest()
    if actual != item["report_sha256"]:
        raise ValueError(f"Original report changed since historical hazard review: {survey_id}")
    return {"report_sha256": actual, "report_section": item["report_section"],
            "historical_hazard_ids": [hazard["id"] for hazard in item["hazards"]],
            "scope": "historical survey hazards only; no current chart or route clearance"}


def audit_all(source, manifest, snapshot, sectors, holds, bag_cache, video_cache, *, hazard_catalog=None, report_cache=None, limit=None):
    positions = rocky_camera_positions(manifest, video_cache)
    pairs = candidate_pairs(source, positions)
    if limit is not None:
        pairs = pairs[:limit]
    held = {item["survey_id"]: item["reason"] for item in holds["holds"]}
    hazard_catalog = hazard_catalog or {"surveys": []}
    report_cache = report_cache or Path("var/noaa-report-cache")
    rows = []
    failures = []
    for record, cruise, camera_count in pairs:
        path = bag_cache / (record["survey_id"] + "-" + hashlib.sha256(record["url"].encode()).hexdigest()[:16] + ".bag")
        if not path.is_file():
            failures.append({"survey_id": record["survey_id"], "bag_url": record["url"],
                             "cruise": cruise, "reason": "reviewed original BAG is not cached"})
            continue
        try:
            result = review(source, manifest, snapshot, bag_cache, video_cache,
                            survey_id=record["survey_id"], cruise=cruise, bag_url=record["url"])
        except (ValueError, KeyError, OSError) as exc:
            failures.append({"survey_id": record["survey_id"], "bag_url": record["url"],
                             "cruise": cruise, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        latitudes = [g["camera_position_bounds"][1:4:2] for g in result["transects"]]
        midpoint = sum(sum(pair) / 2 for pair in latitudes) / len(latitudes) if latitudes else None
        hazard_review = reviewed_hazards(hazard_catalog, report_cache,
                                         record["survey_id"], record.get("source_report_url"))
        rows.append({"survey_id": record["survey_id"], "bag_url": record["url"],
                     "bag_sha256": result["bag_sha256"], "cruise": cruise,
                     "camera_archive_url": result["camera_archive_url"],
                     "camera_archive_sha256": result["camera_archive_sha256"],
                     "sector_id": sector_for(midpoint, sectors) if midpoint is not None else None,
                     "rocky_camera_windows_in_bag_bounds": camera_count,
                     "native_cell_m": result["native_cell_m"],
                     "counts": result["counts"], "transects": result["transects"],
                     "survey_report_url": record.get("source_report_url"),
                     "report_hazard_review_complete": hazard_review is not None,
                     "historical_hazard_review": hazard_review,
                     "survey_hold": held.get(record["survey_id"]),
                     "camera_species_fields": result["camera_species_fields"]})
    rows.sort(key=lambda row: (row["sector_id"] or "", row["survey_id"],
                               row["bag_url"], row["cruise"]))
    mpa = snapshot["sources"]["mpas"]
    mpa_digest = hashlib.sha256(json.dumps(mpa["data"]["geojson"], sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": 1, "scope": "statewide-original-camera-regular-bag-discovery-review",
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cdfw_mpa_source_url": mpa["data"]["source_url"],
            "cdfw_mpa_retrieved_at": mpa["data_retrieved_at"],
            "cdfw_mpa_geojson_sha256": mpa_digest,
            "original_bag_catalog_count": len(source["files"]),
            "candidate_pairs_with_actual_rocky_camera_positions": len(pairs),
            "reviewed_pairs": len(rows), "failed_or_uncached_pairs": failures,
            "summary": dict(Counter({"pairs_with_qualified_windows": sum(bool(r["counts"].get("qualified_rocky_camera_windows")) for r in rows),
                                     "distinct_surveys_with_qualified_windows": len({r["survey_id"] for r in rows if r["counts"].get("qualified_rocky_camera_windows")}),
                                     "failed_pairs": len(failures)})),
            "observation_deduplication": deduplicate_camera_windows(rows),
            "pair_reviews": rows,
            "caveats": ["Rows are sorted by browsing sector and source identity, not fishing quality.",
                        "The same camera window can intersect multiple survey files; pair counts are not unique sites or fish abundance.",
                        "A 25 m qualified depth neighborhood corroborates measured depth only around a historical camera window; it is not an exact rock outline.",
                        "Survey report, current chart hazards, local species rules, access notices and separate area-source review are still required before any target promotion."],
            "fishing_target": False, "exportable": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit", type=Path, default=Path("var/noaa-native-audit-100mb-refined.json"))
    p.add_argument("--manifest", type=Path, default=Path("catalog/usgs-video-cruises.json"))
    p.add_argument("--mpas", type=Path, default=Path("var/qualification-current/coastal/latest.json"))
    p.add_argument("--sectors", type=Path, default=Path("catalog/coastal-sectors.json"))
    p.add_argument("--holds", type=Path, default=Path("catalog/noaa-survey-lead-holds.json"))
    p.add_argument("--hazards", type=Path, default=Path("catalog/noaa-survey-hazards.json"))
    p.add_argument("--report-cache", type=Path, default=Path("var/noaa-report-cache"))
    p.add_argument("--bag-cache", type=Path, default=Path("var/noaa-native-cache"))
    p.add_argument("--video-cache", type=Path, default=Path("var/usgs-video-cache"))
    p.add_argument("--limit", type=int, help="Bounded diagnostic run; omit for a complete review")
    p.add_argument("--output", type=Path, default=Path("dist/data/noaa-statewide-regular-camera-review.json"))
    a = p.parse_args()
    result = audit_all(json.loads(a.audit.read_text()), json.loads(a.manifest.read_text()),
                       json.loads(a.mpas.read_text()), json.loads(a.sectors.read_text())["sectors"],
                       json.loads(a.holds.read_text()), a.bag_cache, a.video_cache,
                       hazard_catalog=json.loads(a.hazards.read_text()), report_cache=a.report_cache,
                       limit=a.limit)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["candidate_pairs_with_actual_rocky_camera_positions"], "pairs;",
          result["summary"])


if __name__ == "__main__":
    main()
