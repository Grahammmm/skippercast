#!/usr/bin/env python3
"""Compile source-backed 200–300 ft research priorities without making fishing marks.

This is a work queue, not a habitat model. A catalog hit never satisfies a
measured-cell, chart-datum, legal, biological, or navigation release gate.
"""

import argparse
import hashlib
import json
from pathlib import Path


TRACKS = (
    ("native-cells", "Locate populated original cells over the full proposed patch"),
    ("depth-uncertainty", "Establish MLLW depth plus horizontal and vertical error over the full patch"),
    ("independent-substrate", "Pair measured depth with surveyed substrate at supported resolution"),
    ("biological-observations", "Link dated species observations at their actual spatial support"),
    ("sampling-scope", "Preserve effort, zero detections, method, and position uncertainty"),
    ("current-fishery", "Collect consented, dated trips with effort and unsuccessful drifts"),
    ("legal-chart-access", "Screen full patch, approach, drift, and return using current authorities"),
    ("evidence-ladder", "Keep research geometry separate from releasable targets and exports"),
    ("calibration", "Evaluate future species-specific trips against a held-out baseline"),
    ("promotion-refresh", "Publish only after all release gates pass and retain rollback"),
)

RELEASE_GATES = (
    "native-cells", "depth-uncertainty", "independent-substrate",
    "biological-observations", "sampling-scope", "legal-chart-access",
)

PROVIDERS = {
    "bathymetry": [
        {"publisher": "NOAA NCEI", "url": "https://www.ncei.noaa.gov/products/nos-hydrographic-survey",
         "request": "Original BAG and descriptive report by survey ID; inspect elevation, product uncertainty, datum, age, valid-cell mask and actual grid locations"},
        {"publisher": "NOAA Office of Coast Survey", "url": "https://www.nauticalcharts.noaa.gov/data/bluetopo_specs.html",
         "request": "BlueTopo contributor IDs and measured-coverage flag to discover the upstream survey, not to substitute interpolated cells"},
        {"publisher": "USGS CSMP", "url": "https://cmgds.marine.usgs.gov/",
         "request": "Original gridded bathymetry, processing report, horizontal reference frame, vertical datum and total propagated uncertainty"},
    ],
    "substrate": [
        {"publisher": "USGS CSMP", "url": "https://cmgds.marine.usgs.gov/",
         "request": "Original video-supervised seafloor character and confusion assessment; verify cellwise overlap with the depth source"},
    ],
    "fish": [
        {"publisher": "CDFW MPA Monitoring", "url": "https://wildlife.ca.gov/Conservation/Marine/MPAs/Management/monitoring/ROV",
         "request": "Georeferenced ROV transects, species observations and zero-observation effort, retaining protected/reference roles and positional error"},
    ],
    "legal": [
        {"publisher": "CDFW", "url": "https://wildlife.ca.gov/Conservation/Marine/MPAs",
         "request": "Current MPA boundaries and species/method rules for the date"},
        {"publisher": "NOAA Office of Coast Survey", "url": "https://nauticalcharts.noaa.gov/",
         "request": "Current ENC danger and approach context; certified navigation review remains separate"},
    ],
}

SECTOR_OVERRIDES = {
    "pigeon-monterey": {
        "lead": "W00614 measured 200–300 ft MLLW cells near Pigeon Point",
        "next": "Seek a different independent surveyed rock class and dated open-reference fish observations over those exact BAG cells; inspect W00614's archived backscatter as a classification input only after groundtruth, then check full patch against MPAs and ENC.",
        "hold": "Measured depth is geographically narrow and no paired rock/fish patch is qualified.",
    },
    "monterey-sur": {
        "lead": "USGS Offshore Monterey bathymetry, character and video; cataloged NOAA BAGs do not overlap the 17 researched outlines at measured cells",
        "next": "Resolve the USGS NAVD88-to-MLLW surface and upper error, then seek another original depth survey on the same class pixels.",
        "hold": "No chart-datum depth and uncertainty over the reviewed rock outlines.",
    },
    "big-sur": {
        "lead": "CSUMB BSS 2–5 m NAVD88 cells and original USGS/CSUMB habitat context",
        "next": "Obtain CSUMB survey processing, rights and TPU/CUBE surfaces; test independent rock and ROV overlap with the original 200–300 ft cells.",
        "hold": "Datum, upper uncertainty, source rights and independent substrate remain unresolved.",
    },
    "sur-san-simeon": {
        "lead": "CSUMB BSS Block03 2 m NAVD88 cells nominally overlap 46 USGS camera windows at 221–238 ft source-datum depth, including 11 rock/boulder windows on one camera line",
        "next": "Request a targeted extract from the official 42 GB CARIS project for original TPU/CUBE, horizontal realization and epoch. Only then transform and bound every candidate cell; review video positioning, source rights, current rules and full access routes.",
        "hold": "One historical camera line cannot define a full rock patch or current catch odds; chart-datum depth, upper uncertainty, rights and access remain unresolved.",
    },
    "cambria-morro": {
        "lead": "Original 2012 WGS84(G1150) ellipsoid-height cells with direct NOAA VDatum block samples, plus 2008 video-supervised character overlap",
        "next": "Confirm the WGS84 source coordinate epoch and obtain original 2012 CARIS TPU; build a bounded cellwise ellipsoid-to-MLLW surface and verify 2008 character registration before full legal and route screens.",
        "hold": "Direct block-center VDatum removes the CORS96 frame shortcut but does not bound product error or every 2 m cell; the 2010 independent cross-check reaches four shallow blocks and no deeper blocks.",
    },
    "morro-conception": {
        "lead": "Original Point Buchon 2 m USGS depth/character pair and open-reference ROV context; reviewed H13152/W00479 MLLW cells are entirely deeper than 300 ft",
        "next": "Establish Point Buchon output datum and upper uncertainty from USGS/CSUMB processing records; search non-NOS archives or unpublished original MLLW surveys over the hard cells, then obtain current Diablo/Vandenberg access and ENC screens.",
        "hold": "BlueTopo's nominal overlap is almost entirely interpolated historical contributor pixels; historical class and fish observations cannot replace chart-datum depth, safe access or current legal review.",
    },
}


def load(root, relative):
    return json.loads((root / relative).read_text())


def digest(root, relative):
    return hashlib.sha256((root / relative).read_bytes()).hexdigest()


def build(root):
    root = Path(root)
    queue_path = "dist/data/central-source-acquisition-queue.json"
    ledger_path = "dist/data/central-coverage-ledger-v1.json"
    buchon_path = "dist/data/point-buchon-original-paired-200-300ft-review.json"
    estero_path = "dist/data/estero-independent-2012-depth-2008-character-overlap.json"
    bss03_video_path = "dist/data/bss03-video-grid-overlap.json"
    bss03_access_path = "dist/data/bss03-camera-access-triage.json"
    bss03_datum_path = "dist/data/bss03-footprint-vdatum-diagnostic.json"
    bss03_caris_path = "dist/data/bss03-caris-acquisition-lead.json"
    estero_direct_path = "dist/data/estero-wgs84-direct-vdatum-review.json"
    queue, ledger = load(root, queue_path), load(root, ledger_path)
    buchon, estero = load(root, buchon_path), load(root, estero_path)
    bss03_video = load(root, bss03_video_path)
    bss03_access = load(root, bss03_access_path)
    bss03_datum = load(root, bss03_datum_path)
    bss03_caris = load(root, bss03_caris_path)
    estero_direct = load(root, estero_direct_path)
    if (bss03_video.get('scope') != 'bss03-original-video-vs-populated-grid'
            or bss03_video.get('camera_windows_in_200_300ft_source_datum_band') != 46
            or bss03_video.get('rock_boulder_cobble_windows_in_band') != 11
            or bss03_video.get('distinct_nonempty_camera_line_ids_in_band') != 1
            or bss03_video.get('rank_effect') != 'none'
            or bss03_video.get('fishing_target') is not False
            or bss03_video.get('exportable') is not False):
        raise ValueError('Original Big Sur Block03 camera/grid evidence changed')
    if (bss03_access.get('scope') != 'bss03-original-camera-100m-access-triage'
            or bss03_access.get('totals', {}).get('blocks') != 3
            or bss03_access.get('totals', {}).get('rock_boulder_cobble_windows') != 11
            or bss03_access.get('qualified_waypoints') != 0
            or bss03_access.get('fishing_target') is not False
            or bss03_access.get('exportable') is not False):
        raise ValueError('Big Sur Block03 partial official-area screen changed')
    if (bss03_datum.get('scope') != 'bss03-private-footprint-vdatum-diagnostic'
            or bss03_datum.get('sample_count') != 15
            or bss03_datum.get('source_horizontal_realization_verified') is not False
            or bss03_datum.get('upper_bounded_mllw_depth_verified') is not False
            or bss03_datum.get('fishing_target') is not False
            or bss03_caris.get('scope') != 'bss03-caris-original-project-acquisition-lead'
            or bss03_caris.get('bounded_original_prefix', {}).get('project_projection') != 'AUTO_UTM,WG84_10N'
            or bss03_caris.get('bounded_original_prefix', {}).get('processing_log_computed_tpu') is not True
            or bss03_caris.get('bounded_original_prefix', {}).get('tpe_member_downloaded_or_decoded') is not False
            or bss03_caris.get('archive_contents_verified') is not False
            or bss03_caris.get('cube_or_tpu_surface_confirmed') is not False
            or bss03_caris.get('depth_qualified') is not False):
        raise ValueError('Block03 datum or CARIS acquisition evidence changed')
    if (estero_direct.get('scope') != 'estero-2012-original-wgs84-direct-vdatum-research'
            or estero_direct.get('sample_count') != 60
            or estero_direct.get('source_product_upper_uncertainty_verified') is not False
            or estero_direct.get('full_cellwise_mllw_surface_verified') is not False
            or estero_direct.get('qualified_waypoints') != 0
            or estero_direct.get('fishing_target') is not False):
        raise ValueError('Original Estero direct-frame evidence changed')
    if queue.get("status") != "research-only" or ledger.get("depth_planning_ceiling_ft") != 300:
        raise ValueError("Central 300 ft source and coverage receipts are not current")
    if (buchon.get("fishing_target") is not False or buchon.get("qualified_waypoints") != 0
            or buchon.get("native_depth_datum") != "unresolved"
            or estero.get("fishing_target") is not False):
        raise ValueError("A deeper source changed status; review the plan before publishing")
    if ledger["totals"]["qualified_targets_200_to_300ft"] != 0:
        raise ValueError("Deeper targets exist; reconcile the qualification manifest first")
    sectors = []
    for row in queue["sectors"]:
        sector_id = row["sector_id"]
        if sector_id not in SECTOR_OVERRIDES:
            raise ValueError(f"No reviewed acquisition plan for {sector_id}")
        original = row["noaa_original_300ft_depth_leads"]
        csumb = row["csumb_native_band_leads"]
        estero_lead = row["estero_independent_depth_character_lead"]
        measured = bool(original or csumb or estero_lead or sector_id in ("monterey-sur", "morro-conception"))
        chart_depth = bool(original)
        receipts = [lead["review_path"] for lead in original]
        deep_refutations = row.get("noaa_original_deepwater_300ft_refutations", [])
        if any(lead["shallowest_native_depth_m_mllw"] <= 300 * .3048 for lead in deep_refutations):
            raise ValueError("Reviewed deepwater survey now intersects 300 ft band")
        receipts.extend(lead["review_path"] for lead in deep_refutations)
        if csumb:
            receipts.append(row["csumb_native_band_receipt"])
        if sector_id == 'sur-san-simeon':
            receipts.append(bss03_video_path)
            receipts.append(bss03_access_path)
            receipts.append(bss03_datum_path)
            receipts.append(bss03_caris_path)
        if estero_lead:
            receipts.extend((estero_lead["depth_receipt"], estero_lead["overlap_receipt"]))
            receipts.append(estero_direct_path)
            direct = row.get("estero_wgs84_direct_diagnostic")
            if (not direct or direct["sample_points"] != 60
                    or direct["nominal_center_offset_200_300ft_cells"] != sum(
                        band["nominal_center_offset_200_300ft_cells"]
                        for band in estero_direct["by_prior_nominal_band"].values())
                    or direct["fishing_target"] is not False
                    or direct["exportable"] is not False):
                raise ValueError("Estero direct source queue changed")
            spatial = row.get("estero_vdatum_spatial_diagnostic")
            if (not spatial or spatial["sample_points"] != 28
                    or spatial["fishing_target"] is not False
                    or spatial["exportable"] is not False):
                raise ValueError("Estero VDatum spatial evidence changed")
            receipts.append(spatial["receipt"])
        if sector_id == "morro-conception":
            receipts.append(buchon_path)
            catalog_gap = row.get("point_buchon_noaa_catalog_gap")
            if (not catalog_gap or catalog_gap["catalog_bag_survey_ids"] != ["W00479"]
                    or catalog_gap["fishing_target"] is not False):
                raise ValueError("Point Buchon source catalog gap changed")
            receipts.append(catalog_gap["receipt"])
            compiled = row.get("point_buchon_bluetopo_contributor_overlap")
            if (not compiled or compiled["original_usgs_hard_rugose_cell_centers"] != 804337
                    or compiled["measured_survey_contributor_centers"] != 16
                    or compiled["fishing_target"] is not False):
                raise ValueError("Point Buchon BlueTopo source-lineage review changed")
            receipts.append(compiled["receipt"])
            rov_access = row.get("point_buchon_rov_access_triage")
            if (not rov_access or rov_access["private_research_blocks"] != 26
                    or rov_access["historic_open_reference_subunits"] != 183
                    or rov_access["fishing_target"] is not False
                    or rov_access["exportable"] is not False):
                raise ValueError("Point Buchon ROV access triage changed")
            receipts.append(rov_access["receipt"])
            source_grid = row.get("point_buchon_source_gridding_resolution")
            if (not source_grid or source_grid["source_grid_m_deeper_than_80m"] != 5
                    or source_grid["nominal_hard_rugose_published_cells_from_5m_source"] != 70158
                    or source_grid["fishing_target"] is not False):
                raise ValueError("Point Buchon deeper source-gridding resolution changed")
            receipts.append(source_grid["receipt"])
            datum_lead = row.get("point_buchon_datum_provenance_lead")
            if (not datum_lead or datum_lead["usgs_published_raster_output_datum"] != "unresolved"
                    or datum_lead["fishing_target"] is not False):
                raise ValueError("Point Buchon datum provenance lead changed")
            receipts.append(datum_lead["receipt"])
        if row.get("noaa_usgs_original_character_overlap"):
            class_lead = row["noaa_usgs_original_character_overlap"]
            if (class_lead["depth_qualified_cells"] != 141331
                    or class_lead["classified_cells_on_those_depth_cells"] != 0
                    or class_lead["fishing_target"] is not False):
                raise ValueError("Pigeon Point independent substrate claim changed")
            receipts.append(class_lead["receipt"])
        tracks = []
        for key, requirement in TRACKS:
            stage = "research-evidence" if key == "native-cells" and measured else "missing-release-evidence"
            if key == "depth-uncertainty" and chart_depth:
                stage = "partial-release-evidence"
            if sector_id == 'sur-san-simeon' and key in ('independent-substrate', 'biological-observations'):
                stage = 'research-evidence'
            if sector_id == 'sur-san-simeon' and key == 'legal-chart-access':
                stage = 'partial-release-evidence'
            if key == "evidence-ladder":
                stage = "implemented-hold"
            if key == "promotion-refresh":
                stage = "implemented-guarded"
            tracks.append({"id": key, "requirement": requirement, "stage": stage,
                           "release_gate_satisfied": False if key in RELEASE_GATES else None})
        sectors.append({
            "sector_id": sector_id, "source_review_priority_tier": row["priority_tier"],
            "reviewed_lead": SECTOR_OVERRIDES[sector_id]["lead"],
            "next_acquisition": SECTOR_OVERRIDES[sector_id]["next"],
            "limiting_evidence": SECTOR_OVERRIDES[sector_id]["hold"],
            "native_cell_evidence": "source-datum-only" if measured and not chart_depth else
                                    "measured-mllw-substrate-unpaired" if chart_depth else "not-demonstrated-in-overlap",
            "source_receipts": sorted(set(receipts)),
            "independent_groundtruth_at_candidate_scale": False,
            "full_patch_current_legal_chart_access_review": False,
            "qualified_200_to_300ft_targets": 0,
            "fishing_rank": None,
            "exportable": False,
            "tracks": tracks,
        })
    if len(sectors) != 6 or len({s["sector_id"] for s in sectors}) != 6:
        raise ValueError("Incomplete or duplicate Central Coast sector plan")
    return {
        "schema_version": 1, "scope": "monterey-to-point-conception-300ft-qualification-work-queue",
        "status": "research-only", "depth_ceiling_ft": 300,
        "source_sha256": {p: digest(root, p) for p in (queue_path, ledger_path, buchon_path, estero_path, estero_direct_path, bss03_video_path, bss03_access_path, bss03_datum_path, bss03_caris_path)},
        "release_gate_ids": list(RELEASE_GATES), "tracks": [{"id": k, "requirement": v} for k, v in TRACKS],
        "source_search_order": PROVIDERS, "sectors": sectors,
        "promotion_rule": "A rank or export requires original measured full-patch depth with reviewed chart datum and uncertainty; independent surveyed substrate and spatially supported fish evidence; current full-footprint legal, access, hazard and route review. A future outcome model also needs held-out effort including zero catches.",
        "limitations": "This work queue does not certify a fishing spot, chartplotter coordinate, catch probability, safe navigation, or open season. Provider URLs are authoritative discovery entry points; only audited original cells and current rules can close gates.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("dist/data/central-300ft-qualification-plan.json"))
    args = parser.parse_args()
    plan = build(args.root)
    output = args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2) + "\n")
    print(f"{len(plan['sectors'])} sectors; {len(plan['tracks'])} tracks; zero promoted deeper targets")


if __name__ == "__main__":
    main()
