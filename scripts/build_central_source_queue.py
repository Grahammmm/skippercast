#!/usr/bin/env python3
"""Join official survey discovery receipts to Central Coast gap priorities."""

import argparse
import hashlib
import json
import re
from pathlib import Path


SECTORS = (
    "pigeon-monterey", "monterey-sur", "big-sur", "sur-san-simeon",
    "cambria-morro", "morro-conception",
)


def read(path):
    return json.loads(Path(path).read_text())


def build(root):
    root = Path(root)
    discovery = read(root / "dist/data/noaa-survey-discovery.json")
    products = read(root / "dist/data/noaa-survey-products.json")
    native = read(root / "dist/data/noaa-region-bag-envelope-review.json")
    usgs = read(root / "catalog/usgs-ds781-source-leads.json")
    metadata = read(root / "catalog/usgs-ds781-metadata-review.json")
    ledger = read(root / "dist/data/central-coverage-ledger-v1.json")
    bindings = read(root / "catalog/central-native-depth-review-bindings.json")
    monterey_bindings = read(root / "catalog/monterey-original-bag-overlap-bindings.json")
    bluetopo = read(root / "dist/data/central-bluetopo-upstream-source-leads.json")
    bluetopo_manifest = read(root / "catalog/bluetopo-statewide-sample.json")
    multibeam = read(root / "dist/data/noaa-central-multibeam-footprint-leads.json")
    if bindings.get("schema_version") != 1:
        raise ValueError("Invalid original depth review bindings")
    if discovery["health"]["status"] != "ok" or products["health"]["status"] != "ok":
        raise ValueError("NOAA discovery incomplete")
    if metadata["record_count"] != len(metadata["records"]):
        raise ValueError("USGS metadata receipt incomplete")
    if (bluetopo.get("scope") != "central-bluetopo-rat-upstream-source-leads"
            or bluetopo.get("fishing_target") is not False
            or bluetopo.get("exportable") is not False
            or bluetopo.get("scheme_url") != bluetopo_manifest["scheme_url"]
            or bluetopo.get("scheme_sha256") != bluetopo_manifest["scheme_sha256"]):
        raise ValueError("BlueTopo upstream-source receipt is missing or stale")
    bluetopo_by_sector = {sector: [] for sector in SECTORS}
    for row in bluetopo.get("sectors", []):
        sector = row.get("sector_id")
        if (sector not in bluetopo_by_sector or row.get("fishing_target") is not False
                or row.get("exportable") is not False or not row.get("rat_sha256")):
            raise ValueError("Unreviewed BlueTopo contributor-table lead")
        bluetopo_by_sector[sector].append(row)
    if not all(bluetopo_by_sector[s] for s in ("monterey-sur", "big-sur", "sur-san-simeon")):
        raise ValueError("Central Coast BlueTopo contributor-table coverage incomplete")
    if (multibeam.get("scope") != "noaa-ncei-central-multibeam-footprint-discovery"
            or multibeam.get("status") != "complete-catalog-query"
            or multibeam.get("fishing_target") is not False
            or multibeam.get("exportable") is not False
            or {row["sector_id"] for row in multibeam.get("sectors", [])} != set(SECTORS)
            or any(row["footprint_lead_count"] != len(row["footprints"])
                   for row in multibeam["sectors"])):
        raise ValueError("NOAA multibeam footprint discovery incomplete")
    footprint_by_sector = {row["sector_id"]: row for row in multibeam["sectors"]}
    discovery_rows = {s["sector_id"]: s for s in discovery["sectors"]}
    surveyed = {s["id"]: s for s in products["surveys"]}
    if (monterey_bindings.get("scope") != "original-noaa-mllw-bag-overlap-with-17-monterey-research-outlines"
            or monterey_bindings.get("claim") != "no-measured-native-cells-inside-these-17-outlines"):
        raise ValueError("Unreviewed original Monterey BAG overlap claim")
    original_pixel = read(root / "dist/data/monterey-original-300-pixel-review.json")
    w00614_300 = read(root / "dist/data/w00614-original-300-pigeon-monterey-review.json")
    if (w00614_300.get("scope") != "original-noaa-vr-300ft-browse-sector-screen"
            or w00614_300.get("survey_id") != "W00614"
            or w00614_300.get("sector_id") != "pigeon-monterey"
            or w00614_300.get("source_url") not in surveyed["W00614"]["products"]["bag"]
            or w00614_300.get("fishing_target") is not False
            or w00614_300.get("exportable") is not False
            or w00614_300["counts"]["depth_uncertainty_qualified_200_300ft_cells"] <= 0
            or w00614_300["eligible_supergrid_center_bounds"][1] < 37.1):
        raise ValueError("Unreviewed W00614 300 ft native-cell source lead")
    original_ids = {row["context_id"] for row in original_pixel["outlines"]}
    original_context_sha = hashlib.sha256(
        (root / "dist/data/usgs-offshore-monterey-hard-context.geojson").read_bytes()).hexdigest()
    original_pixel_sha = hashlib.sha256(
        (root / "dist/data/monterey-original-300-pixel-review.json").read_bytes()).hexdigest()
    monterey_no_overlap = {}
    for binding in monterey_bindings["bindings"]:
        sid = binding["survey_id"]
        path = binding["review_path"]
        report = read(root / path)
        if (sid in monterey_no_overlap
                or binding["bag_url"] not in surveyed.get(sid, {}).get("products", {}).get("bag", [])
                or report.get("scope") != "monterey-original-noaa-bag-cell-overlap"
                or report.get("survey_id") != sid or report.get("source_url") != binding["bag_url"]
                or report.get("file_sha256") != binding["bag_sha256"]
                or report.get("context_sha256") != original_context_sha
                or report.get("pixel_review_sha256") != original_pixel_sha
                or report.get("outline_count") != len(original_ids)
                or {row["context_id"] for row in report.get("outlines", [])} != original_ids
                or report.get("outlines_with_measured_cells") != 0
                or report.get("measured_native_cells_inside_research_outlines") != 0
                or report.get("fishing_target") is not False):
            raise ValueError(f"Original Monterey BAG overlap refutation failed for {sid}")
        monterey_no_overlap[sid] = path
    depth_refuted = {}
    deeper_sector_refuted = {}
    for binding in bindings["bindings"]:
        sid = binding["survey_id"]
        catalog_urls = surveyed.get(sid, {}).get("products", {}).get("bag", [])
        paths = binding.get("review_paths", [])
        if not paths or len(paths) != len(set(paths)):
            raise ValueError(f"Missing or duplicate native depth receipts for {sid}")
        receipts = [read(root / path) for path in paths]
        for receipt in receipts:
            if (receipt.get("survey_id") != sid or receipt.get("source_url") not in catalog_urls
                    or receipt.get("scope") != "original-regular-bag-300-depth-source-review"
                    or receipt.get("vertical_datum") != "MLLW"
                    or receipt.get("fishing_target") is not False
                    or receipt.get("counts", {}).get("measured_native_cells", 0) <= 0):
                raise ValueError(f"Unreviewed native depth receipt for {sid}")
        if binding.get("claim") == "no-eligible-25-300ft-anywhere":
            if sid in depth_refuted or any(r["counts"]["eligible_25_300ft_cells_with_margin"] != 0 for r in receipts):
                raise ValueError(f"Original depth refutation failed for {sid}")
            depth_refuted[sid] = paths
        elif binding.get("claim") == "no-eligible-200-300ft-in-sector":
            sector_id = binding.get("sector_id")
            fine_urls = {url for url in catalog_urls if re.search(r"_(?:50cm|[1-4]m)_MLLW", url)}
            if (not sector_id or (sid, sector_id) in deeper_sector_refuted
                    or {r["source_url"] for r in receipts} != fine_urls
                    or any(r.get("sector_cell_center_screen", {}).get("sector_id") != sector_id
                           or r["sector_cell_center_screen"]["counts"]["nominal_200_300ft_cells_passing_300ft_uncertainty_margin"] != 0
                           for r in receipts)):
                raise ValueError(f"Original deeper-band sector refutation failed for {sid}")
            deeper_sector_refuted[(sid, sector_id)] = paths
        else:
            raise ValueError(f"Unknown original native-depth review claim for {sid}")
    native_links = {lead["bag_url"]: lead for region in native["regions"]
                    for lead in region.get("leads", [])}
    source_rows = []
    for sector_id in SECTORS:
        area = discovery_rows[sector_id]
        # The discovery service is broad-track geometry; counts are leads only.
        survey_ids = sorted({s["id"] for s in area.get("surveys", [])})
        original_bag = [sid for sid in survey_ids if surveyed.get(sid, {}).get("products", {}).get("bag")]
        fine_leads = []
        coarse_audited = []
        for sid in original_bag:
            urls = surveyed[sid]["products"]["bag"]
            # A filename is only a triage hint. The native raster still has to
            # prove spacing, actual measured-cell location, datum and quality.
            candidate_urls = [url for url in urls if "_VR_MLLW" in url or
                              re.search(r"_(?:50cm|[1-4]m)_MLLW", url)]
            if sid in depth_refuted:
                continue
            if any(url not in native_links or
                   max(native_links[url]["resolution_m"]) <= 4 or
                   native_links[url]["fine_refinement_grids"] > 0
                   for url in candidate_urls):
                fine_leads.append(sid)
            elif candidate_urls:
                coarse_audited.append(sid)
        usgs_areas = [m for m in usgs["map_areas"] if sector_id in m.get("planning_sector_ids", [])]
        paired = [m for m in usgs_areas if
                  {"bathymetry", "seafloor-character"}.issubset({p["kind"] for p in m.get("products", [])})]
        upstream_ids = {sid for row in bluetopo_by_sector[sector_id]
                        for sid in row["rat_measured_survey_ids"]}
        historical_hydrography = sorted(sid for sid in upstream_ids if re.fullmatch(r"[BHW]\d{5}(?:_.*)?", sid))
        coastal_dem = sorted(upstream_ids - set(historical_hydrography))
        region_gaps = [r["region_id"] for r in ledger["regions"] if not r["qualified_targets_at_or_under_200ft"]]
        # Priority is a *source-review* queue, not a predicted fish-density map.
        tier = 1 if paired else 2 if fine_leads else 3
        source_rows.append({
            "sector_id": sector_id,
            "priority_tier": tier,
            "noaa_catalog_lead_count": len(survey_ids),
            "noaa_catalog_leads_with_bag_links": len(original_bag),
            "noaa_survey_ids": original_bag,
            "noaa_filename_fine_grid_leads": fine_leads,
            "noaa_native_audit_refuted_fine_hint": coarse_audited,
            "noaa_original_300ft_depth_refutations": [
                {"survey_id": sid, "review_paths": depth_refuted[sid]}
                for sid in original_bag if sid in depth_refuted],
            "noaa_original_200_300ft_sector_refutations": [
                {"survey_id": sid, "review_paths": deeper_sector_refuted[(sid, sector_id)]}
                for sid in original_bag if (sid, sector_id) in deeper_sector_refuted],
            "noaa_no_measured_cells_in_17_monterey_outlines": [
                {"survey_id": sid, "review_path": monterey_no_overlap[sid]}
                for sid in original_bag if sid in monterey_no_overlap
                and sector_id in ("pigeon-monterey", "monterey-sur")],
            "noaa_coarse_or_unresolved_leads": sorted(set(original_bag) - set(fine_leads) - set(depth_refuted)),
            "noaa_original_300ft_depth_leads": ([{
                "survey_id": "W00614", "review_path": "dist/data/w00614-original-300-pigeon-monterey-review.json",
                "qualified_200_300ft_native_cells": w00614_300["counts"]["depth_uncertainty_qualified_200_300ft_cells"],
                "eligible_supergrid_center_bounds": w00614_300["eligible_supergrid_center_bounds"],
                "coverage_note": "Native measured cells cluster near Pigeon Point, north of Monterey Bay; no substrate or fishable target qualified."}]
                if sector_id == "pigeon-monterey" else []),
            "bluetopo_rat_tile_count": len(bluetopo_by_sector[sector_id]),
            "bluetopo_rat_historical_hydrography_ids": historical_hydrography,
            "bluetopo_rat_coastal_dem_ids": coastal_dem,
            "bluetopo_rat_receipt": "dist/data/central-bluetopo-upstream-source-leads.json",
            "ncei_multibeam_footprint_lead_count": footprint_by_sector[sector_id]["footprint_lead_count"],
            "ncei_multibeam_distinct_survey_id_count": len({item["survey_id"] for item in footprint_by_sector[sector_id]["footprints"]
                                                             if item["survey_id"]}),
            "ncei_multibeam_footprint_receipt": "dist/data/noaa-central-multibeam-footprint-leads.json",
            "usgs_map_areas": [{"name": m["name"], "catalog_url": m["resolved_url"],
                                "paired_original_products": m in paired} for m in usgs_areas],
            "next_action": "Open original native BAG and paired substrate pixels; document measured-cell footprint, MLLW datum, uncertainty, source age and rights before any target screen" if fine_leads or paired
                           else "Find a local finer original survey; currently cataloged BAG filenames suggest only coarse grids and broad track envelopes",
            "blocking_checks": ["valid measured cells within 300 ft plus uncertainty margin",
                                "paired high-resolution substrate and independent groundtruth",
                                "current MPA/federal/security/chart screen of full footprint"],
        })
    return {
        "schema_version": 1,
        "scope": "central-original-source-acquisition-queue",
        "source_catalog_times": {"noaa_discovery": discovery["collected_at"],
                                 "noaa_products": products["collected_at"], "usgs": usgs["retrieved_at"]},
        "status": "research-only",
        "region_gaps": region_gaps,
        "sectors": source_rows,
        "method_note": "Catalog intersections, BAG links, BlueTopo contributor-table IDs, multibeam swath-footprint intersections and filename spacing hints are not measured 25–300 ft raster coverage or evidence of fish. Re-run discovery and inspect original pixels before promotion.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="dist/data/central-source-acquisition-queue.json")
    args = parser.parse_args()
    queue = build(args.root)
    path = Path(args.root) / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, indent=2) + "\n")
    print([(s["sector_id"], s["noaa_catalog_leads_with_bag_links"], s["priority_tier"]) for s in queue["sectors"]])


if __name__ == "__main__":
    main()
