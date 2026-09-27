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

# Region-independent acceptance contracts. A provider lead supplies evidence,
# never an automatic pass; each proposed patch is reviewed against these tests.
TRACK_PROTOCOLS = {
    "native-cells": ("Original measured cells cover the entire candidate geometry after nodata masks; record survey, year, hash and native grid spacing.", "Monthly catalog discovery; rerun original-cell joins when source bytes change."),
    "depth-uncertainty": ("Every cell plus positional buffer is within the legal depth band after documented chart-datum conversion and a conservative upper total-error bound.", "On original depth, processing, VDatum or regulation change."),
    "independent-substrate": ("A separately observed substrate class overlaps the measured depth footprint within supported registration error; record class confusion and negative samples.", "On source classification or groundtruth update."),
    "biological-observations": ("Species evidence is dated, open-reference and spatially linked at observation resolution, with method and detection limits stated.", "Quarterly observation discovery and reviewed imports."),
    "sampling-scope": ("Store effort, zero detections, transect or trip unit, location error and protected/reference role; never count correlated windows as independent surveys.", "On every biological import."),
    "current-fishery": ("Only consented dated trips with gear, depth, effort and failures contribute to effectiveness estimates; suppress individual tracks.", "After enough opt-in trips for held-out evaluation."),
    "legal-chart-access": ("Current official rules clear the complete target, drift and approach/return geometry; chart hazards and security restrictions are separately reviewed.", "Before promotion and for each fishing date or authority update."),
    "evidence-ladder": ("Research, depth/habitat-qualified, legal/chart-screened and field-verified states are disjoint in API, UI and exports.", "Every build and promotion."),
    "calibration": ("Compare a preregistered species baseline with later held-out trips and coastline sectors, including zero-catch effort and abstentions.", "After new consenting trip cohorts."),
    "promotion-refresh": ("A reviewed manifest passes all six release gates, reproducible build, geospatial regression and rollback snapshot before public ranks or exports change.", "Monthly source review; manual promotion only."),
}

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
        {"publisher": "CDFW / MARÉ", "url": "https://mareresearch.org/?p=1798",
         "request": "Original 2016 Soquel Canyon–Point Buchon one-second cleaned ROV positions, fish and substrate annotations, effort/transect-width table, survey-line shapefiles, protected/reference roles, positional error and reuse terms; report maps alone cannot qualify a spot"},
        {"publisher": "California OPC DataONE", "url": "https://opc.dataone.org/view/urn:uuid:7353f779-b722-4064-8074-3e9c651ed38e",
         "request": "Use the audited public CC BY 4.0 ROV count table for historical region/depth context only; its at-most-two-decimal coordinates cannot locate a 200–300 ft pile and independence from earlier ROV releases is unverified"},
        {"publisher": "The Nature Conservancy / Moss Landing Marine Laboratories", "url": "https://www.pcouncil.org/documents/2020/01/f5c_sup_pubcom4_apr2016bb.pdf/",
         "request": "Locate the original Pigeon Point Reef video-lander drop table: bottom/ship positions and offsets, dates, depth, taxon, rock/soft observations, no-fish drops, effort and reuse terms; compare actual drop footprints with W00614 cells before treating it as support"},
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
        "next": "Request the original TNC/MLML Pigeon Point Reef video-lander drop table mentioned to PFMC, including bottom positions, position error, substrate, taxon, dates, effort, no-fish drops and reuse terms. Test actual drops against W00614's qualifying cells; neither 13 published USGS video archives nor the NOAA SH-18-09 published coral/sponge occurrences reach within 100 m of the measured-cell envelope. Seek separate groundtruth for W00614 backscatter and check any full candidate patch against MPAs and ENC.",
        "hold": "Measured depth is geographically narrow and no paired rock/fish patch is qualified.",
    },
    "monterey-sur": {
        "lead": "USGS Offshore Monterey bathymetry, character and video; original 1995 EM1000 cells overlap 14/17 research outlines and original 1998 EM300 cells overlap 7/17. NOAA's 2013 merge has class-13 submerged-acoustic samples inside all 17 outlines. Five original processed 2009 CentralMontereyBay GSF files have 314,362 valid beams inside priority outline 023 and 72,083 inside 046. Nearest native USGS 2 m cell joins put these beams over 16,524 and 2,651 distinct hard/rugose nominal-band cell centers inside the outlines, respectively, with 10,886 and 1,705 surviving a one-cell-neighborhood sensitivity screen. Archived 2010 camera transects have one rockfish-positive window in each area, but only one independent transect per area and variable positioning on the order of 10 m. Across all 17 original-depth research outlines, the separate CDFW/MARE ROV release has open-reference source-depth subunits in only 023 (113; 28 surviving a 25 m inset) and 072 (15; none surviving a 25 m inset). These are correlated historical observations, not catch rates or precisely placed piles. Neither NOS BAG catalog nor BlueTopo supplies modern measured coverage there.",
        "next": "CSUMB's northern cmb_n_2mbathy project XML calls its finished raster NAVD88 Geoid09, but its stated footprint excludes priority outlines 023 and 046; it does not prove those selected GSF lines share that datum or provide an upper error bound. Obtain their actual tide-zone/vertical-datum, horizontal registration and upper uncertainty records from the 2009 CARIS processing package; trace original GSF line IDs to NOAA 2013 merge point_source_id, Full_DataInventory.xlsx and per-cell accuracy before claiming independence. Resolve ROV subunit centroid position error and bottom-camera footprint at outline 023; do not double count the processed ROV release with other CDFW/MARE tables. Resolve outline 040's 1995-vs-1998 discrepancy and seek genuinely independent later measured coverage. Only then attempt full-footprint MLLW depth qualification.",
        "hold": "Original processed 2009 beams prove spatial sounding support at two research outlines and align closely with native USGS 2 m cells, but the GSF processing record says TIDAL_DATUM=UNKNOWN. Close agreement may be shared lineage, not independent validation. The one-cell neighborhood is not an upper horizontal error bound; interpreted class 3 is not a photographed rock or fish. Beam error arrays are not a conservative product-depth bound. Outline 001 also fails bounded MPA/ENC screens. No conservative MLLW 200–300 ft depth is qualified.",
    },
    "big-sur": {
        "lead": "CSUMB BSS 2–5 m NAVD88 cells and original USGS/CSUMB habitat context",
        "next": "Obtain CSUMB survey processing, rights and TPU/CUBE surfaces; test independent rock and ROV overlap with the original 200–300 ft cells.",
        "hold": "Datum, upper uncertainty, source rights and independent substrate remain unresolved.",
    },
    "sur-san-simeon": {
        "lead": "CSUMB BSS Block03 2 m NAVD88 cells nominally overlap 46 USGS camera windows at 221–238 ft source-datum depth, including 11 rock/boulder windows on one camera line",
        "next": "A bounded original CARIS read contains one complete per-line HDCS TPE member, but that October line predates the released grid's listed November/December surveys and may not contribute. Locate the actual contributing lines; obtain a documented CARIS ExportHIPS depth/position TPU and accepted-sounding extract plus a CUBE/BASE surface, horizontal realization and epoch. Then transform and bound every candidate cell; review video positioning, source rights, current rules and full access routes.",
        "hold": "One historical camera line cannot define a full rock patch or current catch odds; chart-datum depth, upper uncertainty, rights and access remain unresolved.",
    },
    "cambria-morro": {
        "lead": "Original 2012 WGS84(G1150) ellipsoid-height cells with direct NOAA VDatum block samples, plus 2008 video-supervised character overlap",
        "next": "Confirm the WGS84 source coordinate epoch and obtain original 2012 CARIS TPU; build a bounded cellwise ellipsoid-to-MLLW surface and verify 2008 character registration. Seek a different independent video/grab survey on the 60 research blocks: the original C0212SC camera observations are all more than 250 m away. Then complete legal and route screens.",
        "hold": "Direct block-center VDatum does not bound product error or every 2 m cell; the 2010 depth cross-check reaches four shallow blocks and no deeper blocks, while the reviewed C0212SC camera survey has no nearby groundtruth.",
    },
    "morro-conception": {
        "lead": "CSUMB Block A3 NAVD88 Geoid03 grids, with metadata labeled 2009 but bundled bathymetry tracklines dated 2007, overlap the 2008 USGS hard/rugose class at 87,257 nominal 200–300 ft source-datum cells; H13152/W00479 MLLW cells are entirely deeper than 300 ft",
        "next": "Resolve the Block A3 2007-trackline to released-grid lineage with its custodian, then request upper uncertainty, NAD83 realization/epoch, 2008-class registration and written reuse terms. Continue targeted 2007 CARIS and processed GSF datum/TPU acquisition; obtain current Diablo/Vandenberg access and ENC route screens. The original Cal DIG I ROV biotic/substrate point tables have no 200–300 ft observations; do not use their deepwater labels or 2026 inferred CMECS polygons as shallow groundtruth.",
        "hold": "The grid metadata establish NAVD88 Geoid03 but not independent 2009 acquisition, vertical accuracy or rights. Nominal overlap can include protected or inaccessible areas; no full-patch MLLW depth, independent fish support, safe access or current legal review is complete.",
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
    bss03_tpe_path = "dist/data/bss03-caris-original-tpe-member-lead.json"
    bss03_vessel_path = "dist/data/bss03-original-vessel-tpu-inputs.json"
    pigeon_video_path = "dist/data/w00614-usgs-video-observation-gap.json"
    pigeon_noaa_rov_path = "dist/data/w00614-noaa-sh1809-observation-gap.json"
    pigeon_lander_path = "catalog/candidates/tnc-mlml-pigeon-video-lander.json"
    mare_2016_path = "catalog/candidates/cdfw-mare-ciap-2016-central-original-rov.json"
    mare_2016_service_path = "dist/data/ciap-2016-central-rov-public-service-audit.json"
    mare_2016_overlap_path = "dist/data/ciap-2016-central-video-private-block-overlap.json"
    buchon_private_access_path = "dist/data/point-buchon-private-block-access-screen.json"
    buchon_grid_bridge_path = "dist/data/point-buchon-vdatum-grid-api-bridge.json"
    monterey_bag_gap_path = "dist/data/monterey-17-noaa-bag-catalog-gap.json"
    monterey_bluetopo_path = "dist/data/monterey-17-bluetopo-contributor-pixels.json"
    monterey_1995_path = "dist/data/monterey-1995-original-multibeam-overlap.json"
    monterey_1998_path = "dist/data/monterey-1998-original-em300-overlap.json"
    monterey_merge_path = "dist/data/monterey-2013-merge-lineage-gap.json"
    monterey_points_path = "dist/data/monterey-noaa2612-acoustic-point-support.json"
    monterey_tracks_path = "dist/data/monterey-17-ncei-trackline-leads.json"
    monterey_2009_beams_path = "dist/data/monterey-2009-centralmontereybay-valid-beam-review.json"
    monterey_producer_path = "dist/data/monterey-2009-producer-metadata-review.json"
    monterey_project_path = "dist/data/monterey-2009-project-raster-datum-scope.json"
    monterey_cell_join_path = "dist/data/monterey-2009-beam-usgs-cell-screen.json"
    monterey_video_beam_path = "dist/data/monterey-2009-beam-2010-video-proximity.json"
    monterey_rov_path = "dist/data/monterey-rov-research-overlap.json"
    estero_direct_path = "dist/data/estero-wgs84-direct-vdatum-review.json"
    estero_inventory_path = "dist/data/estero-2012-public-release-inventory.json"
    estero_camera_path = "dist/data/estero-original-camera-block-gap.json"
    buchon_ncei_path = "dist/data/point-buchon-2007-ncei-multibeam-lead.json"
    buchon_ncei_index_path = "dist/data/point-buchon-2007-ncei-line-index.json"
    buchon_beams_path = "dist/data/point-buchon-2007-ncei-valid-beam-overlap.json"
    buchon_caris_path = "dist/data/point-buchon-2007-caris-prefix-lead.json"
    buchon_2009_path = "dist/data/point-buchon-2009-csumb-original-overlap.json"
    buchon_a3_lineage_path = "dist/data/point-buchon-block-a3-trackline-lineage.json"
    buchon_2009_terrain_path = "dist/data/point-buchon-2009-csumb-terrain-crosssurvey.json"
    buchon_2009_access_path = "dist/data/point-buchon-2009-csumb-access-triage.json"
    buchon_2009_vdatum_path = "dist/data/point-buchon-2009-conditional-vdatum-probes.json"
    cal_dig_rov_path = "dist/data/cal-dig-i-original-rov-300ft-gap.json"
    dataone_rov_path = "dist/data/central-dataone-rov-300ft-spot-precision.json"
    queue, ledger = load(root, queue_path), load(root, ledger_path)
    buchon, estero = load(root, buchon_path), load(root, estero_path)
    bss03_video = load(root, bss03_video_path)
    bss03_access = load(root, bss03_access_path)
    bss03_datum = load(root, bss03_datum_path)
    bss03_caris = load(root, bss03_caris_path)
    bss03_tpe = load(root, bss03_tpe_path)
    if (bss03_tpe.get("scope") != "bss03-original-caris-complete-single-line-tpe-member"
            or bss03_tpe.get("tpe_member_bytes") != 37668488
            or bss03_tpe.get("tpe_line_date_matches_released_grid_metadata_dates") is not False
            or bss03_tpe.get("tpe_values_decoded") is not False
            or bss03_tpe.get("grid_cell_upper_uncertainty_verified") is not False
            or bss03_tpe.get("fishing_target") is not False):
        raise ValueError("BSS03 original CARIS TPE member status changed")
    bss03_vessel = load(root, bss03_vessel_path)
    pigeon_video = load(root, pigeon_video_path)
    pigeon_noaa_rov = load(root, pigeon_noaa_rov_path)
    cal_dig_rov = load(root, cal_dig_rov_path)
    dataone_rov = load(root, dataone_rov_path)
    if (dataone_rov.get("scope") != "central-opc-dataone-rov-fish-count-300ft-spot-precision"
            or dataone_rov.get("central_location_date_depth_habitat_units_200_300ft") != 370
            or dataone_rov.get("native_spot_position_and_swath_verified") is not False
            or dataone_rov.get("independent_new_fish_survey") is not False
            or dataone_rov.get("fishing_target") is not False):
        raise ValueError("OPC DataONE ROV spatial support changed; review before promotion")
    if (cal_dig_rov.get("scope") != "cal-dig-i-original-rov-200-300ft-observation-gap"
            or any(cal_dig_rov.get("sources", {}).get(kind, {}).get("observations_in_200_300ft_depth_band") != 0
                   for kind in ("biotic", "substrate"))
            or cal_dig_rov.get("independent_substrate_gate_satisfied") is not False
            or cal_dig_rov.get("biological_fish_gate_satisfied") is not False
            or cal_dig_rov.get("fishing_target") is not False):
        raise ValueError("Cal DIG I original ROV depth support changed")
    if (pigeon_noaa_rov.get("scope") != "w00614-noaa-sh1809-coral-sponge-observation-gap"
            or pigeon_noaa_rov.get("source_rows") != 8612
            or pigeon_noaa_rov.get("qualified_w00614_cells") != 141331
            or pigeon_noaa_rov.get("points_within_100m_of_envelope") != 0
            or pigeon_noaa_rov.get("independent_substrate_gate_satisfied") is not False
            or pigeon_noaa_rov.get("biological_fish_gate_satisfied") is not False
            or pigeon_noaa_rov.get("fishing_target") is not False):
        raise ValueError("NOAA SH-18-09 original occurrence support changed")
    pigeon_lander = load(root, pigeon_lander_path)
    if (pigeon_lander.get("id") != "tnc-mlml-pigeon-video-lander"
            or pigeon_lander.get("access_status") != "original-drop-data-not-located"
            or pigeon_lander.get("spatial", {}).get("w00614_cell_overlap_verified") is not False
            or pigeon_lander.get("fishing_target") is not False
            or pigeon_lander.get("exportable") is not False):
        raise ValueError("Pigeon Point original lander source status changed; review before promotion")
    mare_2016 = load(root, mare_2016_path)
    if (mare_2016.get("id") != "cdfw-mare-ciap-2016-central-original-rov"
            or mare_2016.get("access_status") != "partial"
            or mare_2016.get("spatial", {}).get("candidate_cell_overlap_verified") is not False
            or mare_2016.get("spatial", {}).get("position_uncertainty_verified") is not False
            or mare_2016.get("provenance", {}).get("raw_sha256") is not None):
        raise ValueError("CDFW/MARE original 2016 ROV source status changed; review before promotion")
    mare_2016_service = load(root, mare_2016_service_path)
    if (mare_2016_service.get("scope") != "ciap-2016-central-public-wfs-service-access"
            or mare_2016_service.get("central_video", {}).get("total_features_reported") != 236960
            or mare_2016_service.get("fish_display", {}).get("total_features_reported") != 49076
            or mare_2016_service.get("original_row_level_fish_and_substrate_tables_retrieved") is not False
            or mare_2016_service.get("biological_fish_gate_satisfied") is not False
            or mare_2016_service.get("qualified_waypoints") != 0):
        raise ValueError("CIAP ROV WFS evidence scope changed; review before promotion")
    mare_2016_overlap = load(root, mare_2016_overlap_path)
    if (mare_2016_overlap.get("scope") != "ciap-2016-central-video-to-private-300ft-research-blocks"
            or mare_2016_overlap.get("groups", {}).get("point-buchon-rov", {}).get("video_fix_counts", {}).get("inside") != 1644
            or mare_2016_overlap.get("groups", {}).get("point-buchon-terrain", {}).get("video_fix_counts", {}).get("inside") != 1167
            or mare_2016_overlap.get("groups", {}).get("estero", {}).get("video_fix_counts", {}).get("within_250m") != 0
            or mare_2016_overlap.get("groups", {}).get("big-sur-block03", {}).get("video_fix_counts", {}).get("within_250m") != 0
            or mare_2016_overlap.get("original_fish_substrate_observation_table_joined") is not False
            or mare_2016_overlap.get("biological_fish_gate_satisfied") is not False
            or mare_2016_overlap.get("qualified_waypoints") != 0):
        raise ValueError("CIAP video/block overlap changed; review before promotion")
    buchon_private_access = load(root, buchon_private_access_path)
    if (buchon_private_access.get("scope") != "point-buchon-private-100m-blocks-cdfw-mpa-noaa-enc-research-screen"
            or buchon_private_access.get("groups", {}).get("rov_blocks", {}).get("block_count") != 26
            or buchon_private_access.get("groups", {}).get("terrain_blocks", {}).get("block_count") != 181
            or buchon_private_access.get("groups", {}).get("terrain_blocks", {}).get("any_mpa_intersection") != 5
            or buchon_private_access.get("groups", {}).get("terrain_blocks", {}).get("any_mpa_within_100m") != 8
            or any(buchon_private_access.get("groups", {}).get(group, {}).get("any_enc_feature_within_250m") != 0
                   for group in ("rov_blocks", "terrain_blocks"))
            or buchon_private_access.get("full_footprint_legal_chart_access_verified") is not False
            or buchon_private_access.get("fishing_target") is not False
            or buchon_private_access.get("exportable") is not False):
        raise ValueError("Point Buchon private block MPA/ENC screen changed; review before promotion")
    buchon_grid_bridge = load(root, buchon_grid_bridge_path)
    residual = buchon_grid_bridge.get("api_minus_raw_grid_shortcut_range_m", [])
    if (buchon_grid_bridge.get("scope") != "point-buchon-geoid03-vdatum-raw-grid-vs-api-diagnostic"
            or buchon_grid_bridge.get("sample_count") != 12
            or len(residual) != 2 or not (0.12 < residual[0] <= residual[1] < 0.16)
            or buchon_grid_bridge.get("full_cellwise_depth_conversion") is not False
            or buchon_grid_bridge.get("source_depth_upper_uncertainty_verified") is not False
            or buchon_grid_bridge.get("fishing_target") is not False):
        raise ValueError("Point Buchon VDatum grid/API bridge changed; review before promotion")
    monterey_bag_gap = load(root, monterey_bag_gap_path)
    if (monterey_bag_gap.get("scope") != "monterey-17-research-outlines-noaa-nos-bag-catalog-gap"
            or monterey_bag_gap.get("research_outline_count") != 17
            or monterey_bag_gap.get("outlines_with_downloadable_bag_catalog_leads") != 0
            or len(monterey_bag_gap.get("catalog_rows", [])) != 17
            or monterey_bag_gap.get("original_measured_mllw_cells_verified_on_outlines") is not False
            or monterey_bag_gap.get("depth_uncertainty_gate_satisfied") is not False
            or monterey_bag_gap.get("fishing_target") is not False):
        raise ValueError("Monterey NOAA NOS BAG catalog gap changed; review before promotion")
    monterey_bluetopo = load(root, monterey_bluetopo_path)
    if (monterey_bluetopo.get("scope") != "monterey-17-research-outlines-bluetopo-pixel-contributor-screen"
            or monterey_bluetopo.get("research_outline_count") != 17
            or monterey_bluetopo.get("historical_rockfish_positive_outline_count") != 4
            or monterey_bluetopo.get("camera_positive_outlines_with_measured_nominal_band_pixels") != 2
            or monterey_bluetopo.get("highest_priority_two_camera_outlines_with_measured_nominal_band_pixels") != 0
            or monterey_bluetopo.get("per_tile_measured_nominal_band_pixel_count") != 3
            or monterey_bluetopo.get("full_original_cell_depth_and_uncertainty_verified") is not False
            or monterey_bluetopo.get("fishing_target") is not False):
        raise ValueError("Monterey BlueTopo pixel contributor evidence changed; review before promotion")
    monterey_1995 = load(root, monterey_1995_path)
    if (monterey_1995.get("scope") != "monterey-1995-original-multibeam-research-overlap"
            or monterey_1995.get("outlines_reviewed") != 17
            or monterey_1995.get("outlines_with_original_cells") != 14
            or monterey_1995.get("rockfish_camera_positive_outlines_with_original_cells") != 3
            or monterey_1995.get("original_vertical_datum_documented") is not False
            or monterey_1995.get("original_upper_vertical_error_documented") is not False
            or monterey_1995.get("independence_from_2016_composite_established") is not False
            or monterey_1995.get("fishing_target") is not False):
        raise ValueError("Monterey 1995 original-source research status changed")
    monterey_1998 = load(root, monterey_1998_path)
    if (monterey_1998.get("scope") != "monterey-1998-original-em300-research-overlap"
            or monterey_1998.get("outlines_reviewed") != 17
            or monterey_1998.get("outlines_with_original_cells") != 7
            or monterey_1998.get("rockfish_camera_positive_outlines_with_original_cells") != 1
            or monterey_1998.get("previously_uncovered_camera_outline_001", {}).get("nominal_200_300ft_cells_unknown_datum") != 0
            or monterey_1998.get("original_vertical_datum_documented") is not False
            or monterey_1998.get("original_upper_vertical_error_documented") is not False
            or monterey_1998.get("independence_from_2016_composite_established") is not False
            or monterey_1998.get("fishing_target") is not False):
        raise ValueError("Monterey 1998 EM300 original-source research status changed")
    monterey_merge = load(root, monterey_merge_path)
    if (monterey_merge.get("scope") != "monterey-usgs-2m-noaa-2013-merge-lineage-gap"
            or monterey_merge.get("public_accuracy_layer_at_research_cells_obtained") is not False
            or monterey_merge.get("public_source_inventory_at_research_cells_obtained") is not False
            or monterey_merge.get("usgs_20cm_phrase_is_conservative_upper_bound") is not False
            or monterey_merge.get("independent_of_1995_or_1998_survey_established") is not False
            or monterey_merge.get("chart_datum_depth_qualified") is not False
            or monterey_merge.get("fishing_target") is not False):
        raise ValueError("Monterey NOAA 2013 merge lineage or hold status changed")
    monterey_points = load(root, monterey_points_path)
    if (monterey_points.get("scope") != "monterey-noaa-2013-merge-acoustic-point-support"
            or monterey_points.get("outlines_reviewed") != 17
            or monterey_points.get("outlines_with_class13_points") != 17
            or monterey_points.get("camera_positive_outlines_with_class13_points") != 4
            or monterey_points.get("fishing_target") is not False
            or any(row.get("mllw_depth_qualified") is not False
                   or row.get("upper_vertical_error_qualified") is not False
                   or row.get("independent_survey_qualified") is not False
                   or row.get("fishing_target") is not False
                   for row in monterey_points.get("outlines", []))):
        raise ValueError("Monterey acoustic-point support or hold status changed")
    monterey_tracks = load(root, monterey_tracks_path)
    if (monterey_tracks.get("scope") != "monterey-17-ncei-footprint-vs-trackline-survey-leads"
            or monterey_tracks.get("outlines_reviewed") != 17
            or monterey_tracks.get("camera_positive_outlines_with_2009_central_monterey_trackline") != 2
            or any(monterey_tracks.get("highest_priority_023_and_046_trackline_survey_ids", {}).get(ident) != ["CentralMontereyBay"]
                   for ident in ("023", "046"))
            or monterey_tracks.get("fishing_target") is not False
            or any(row.get("survey_has_native_200_300ft_cells_verified") is not False
                   or row.get("chart_datum_and_upper_error_verified") is not False
                   or row.get("fishing_target") is not False
                   for row in monterey_tracks.get("outlines", []))):
        raise ValueError("Monterey NCEI survey trackline lead or hold status changed")
    monterey_2009_beams = load(root, monterey_2009_beams_path)
    monterey_producer = load(root, monterey_producer_path)
    monterey_project = load(root, monterey_project_path)
    if (monterey_project.get("scope") != "monterey-2009-original-csumb-project-raster-datum-scope"
            or monterey_project.get("source_product") != "cmb_n_2mbathy"
            or monterey_project.get("selected_processed_gsf_line_datum_proven") is not False
            or any(monterey_project.get("priority_outlines", {}).get(ident, {}).get("within_documented_raster_bbox") is not False for ident in ("023", "046"))
            or monterey_project.get("mllw_depth_qualified") is not False
            or monterey_project.get("fishing_target") is not False):
        raise ValueError("Monterey finished-raster datum scope changed")
    if (monterey_producer.get("scope") != "monterey-2009-producer-general-metadata-review"
            or monterey_producer.get("source_sha256") != "bf9933a8d24c5a33c8465cf93efd4e0f6f2497236377e2fb1680071fd126e567"
            or monterey_producer.get("documented_controls", {}).get("tide_method_general") != "KGPS altitude used to account for tidal fluctuations"
            or monterey_producer.get("mllw_depth_qualified") is not False
            or monterey_producer.get("fishing_target") is not False):
        raise ValueError("Monterey producer processing lead changed")
    if (monterey_2009_beams.get("scope") != "monterey-2009-centralmontereybay-original-valid-beam-research"
            or monterey_2009_beams.get("processed_files_audited") != 5
            or [(monterey_2009_beams.get("outlines", {}).get(ident, {}).get("valid_beams_inside_outline"),
                 monterey_2009_beams.get("outlines", {}).get(ident, {}).get("valid_beams_nominal_200_300ft_unknown_datum"))
                for ident in ("023", "046")] != [(314362, 314362), (72083, 72083)]
            or any(monterey_2009_beams.get("outlines", {}).get(ident, {}).get("fishing_target") is not False
                   or monterey_2009_beams.get("outlines", {}).get(ident, {}).get("mllw_depth_qualified") is not False
                   for ident in ("023", "046"))
            or monterey_2009_beams.get("fishing_target") is not False):
        raise ValueError("Monterey original 2009 valid-beam support or hold status changed")
    monterey_cell_join = load(root, monterey_cell_join_path)
    if (monterey_cell_join.get("scope") != "monterey-2009-original-beams-to-usgs-native-cell-screen"
            or [(monterey_cell_join.get("outlines", {}).get(ident, {}).get("unique_paired_class3_band_cells_under_source_beams"),
                 monterey_cell_join.get("outlines", {}).get(ident, {}).get("unique_3x3_stable_class3_band_cells_under_source_beams"))
                for ident in ("023", "046")] != [(16524, 10886), (2651, 1705)]
            or any(monterey_cell_join.get("outlines", {}).get(ident, {}).get("mllw_depth_qualified") is not False
                   or monterey_cell_join.get("outlines", {}).get(ident, {}).get("independent_substrate_qualified") is not False
                   or monterey_cell_join.get("outlines", {}).get(ident, {}).get("fishing_target") is not False
                   for ident in ("023", "046"))
            or monterey_cell_join.get("fishing_target") is not False):
        raise ValueError("Monterey GSF-to-USGS cell support or hold status changed")
    monterey_video_beam = load(root, monterey_video_beam_path)
    monterey_rov = load(root, monterey_rov_path)
    if (monterey_rov.get("scope") != "monterey-zenodo-rov-to-original-research-outline-overlap"
            or len(monterey_rov.get("outlines", {})) != 17
            or monterey_rov.get("outlines", {}).get("023", {}).get("interior_sensitivity", {}).get("25", {}).get("subunits") != 28
            or monterey_rov.get("outlines", {}).get("072", {}).get("interior_sensitivity", {}).get("0", {}).get("subunits") != 15
            or monterey_rov.get("outlines", {}).get("072", {}).get("interior_sensitivity", {}).get("25", {}).get("subunits") != 0
            or monterey_rov.get("outlines", {}).get("046", {}).get("interior_sensitivity", {}).get("0", {}).get("subunits") != 0
            or monterey_rov.get("outlines", {}).get("023", {}).get("source_position_error_bounded") is not False
            or monterey_rov.get("fishing_target") is not False):
        raise ValueError("Monterey ROV historical proximity evidence changed")
    if (monterey_video_beam.get("scope") != "monterey-2009-beam-to-2010-video-proximity-research"
            or [(monterey_video_beam.get("outlines", {}).get(ident, {}).get("interior_camera_windows"),
                 monterey_video_beam.get("outlines", {}).get(ident, {}).get("rockfish_positive_windows"),
                 monterey_video_beam.get("outlines", {}).get(ident, {}).get("distinct_camera_transects"))
                for ident in ("023", "046")] != [(5, 1, 1), (2, 1, 1)]
            or any(monterey_video_beam.get("outlines", {}).get(ident, {}).get("independent_current_fish_presence_qualified") is not False
                   or monterey_video_beam.get("outlines", {}).get(ident, {}).get("fishing_target") is not False
                   for ident in ("023", "046"))
            or monterey_video_beam.get("fishing_target") is not False):
        raise ValueError("Monterey original camera-to-beam historical support or hold status changed")
    if (pigeon_video.get('scope') != 'w00614-original-usgs-video-observation-gap'
            or pigeon_video.get('qualified_cells') != 141331
            or len(pigeon_video.get('archives', [])) != 13
            or pigeon_video.get('points_on_or_within_100m_of_envelope') != 0
            or pigeon_video.get('independent_substrate_gate_satisfied') is not False
            or pigeon_video.get('biological_observation_gate_satisfied') is not False
            or pigeon_video.get('qualified_waypoints') != 0):
        raise ValueError('W00614 original USGS video observation coverage changed')
    estero_direct = load(root, estero_direct_path)
    estero_inventory = load(root, estero_inventory_path)
    estero_camera = load(root, estero_camera_path)
    if (estero_camera.get("scope") != "estero-original-camera-to-private-300ft-block-gap"
            or estero_camera.get("research_block_count") != 60
            or estero_camera.get("camera_records") != 5936
            or estero_camera.get("distance_counts", {}).get("within_250m", {}).get("all") != 0
            or estero_camera.get("independent_substrate_gate_satisfied") is not False
            or estero_camera.get("biological_observation_gate_satisfied") is not False
            or estero_camera.get("qualified_waypoints") != 0):
        raise ValueError("Estero original camera-to-block support changed")
    buchon_ncei = load(root, buchon_ncei_path)
    buchon_ncei_index = load(root, buchon_ncei_index_path)
    buchon_beams = load(root, buchon_beams_path)
    buchon_caris = load(root, buchon_caris_path)
    buchon_2009 = load(root, buchon_2009_path)
    buchon_a3_lineage = load(root, buchon_a3_lineage_path)
    buchon_2009_terrain = load(root, buchon_2009_terrain_path)
    buchon_2009_access = load(root, buchon_2009_access_path)
    buchon_2009_vdatum = load(root, buchon_2009_vdatum_path)
    if (buchon_2009.get("scope") != "point-buchon-2009-csumb-original-products-vs-2008-usgs-character"
            or buchon_2009.get("inner_grid_metadata_survey_year") != 2009
            or buchon_2009.get("bundled_bathy_trackline_year") != 2007
            or buchon_2009.get("cell_acquisition_year_verified") is not False
            or buchon_2009.get("inner_grid_native_vertical_datum") != "NAVD88 Geoid03 (inner original processing metadata)"
            or sum(band["usgs_hard_rugose_cells"]
                   for grid in buchon_2009.get("grid_summaries", {}).values()
                   for band in grid["bands"].values()) != 87257
            or buchon_2009.get("source_product_upper_uncertainty_verified") is not False
            or buchon_2009.get("reuse_rights_resolved") is not False
            or buchon_2009.get("qualified_waypoints") != 0):
        raise ValueError("Original 2009 CSUMB Block A3 research evidence changed")
    if (buchon_a3_lineage.get("scope") != "point-buchon-block-a3-trackline-acquisition-lineage"
            or buchon_a3_lineage.get("tracklines", {}).get("bathy", {}).get("count") != 112
            or buchon_a3_lineage.get("tracklines", {}).get("bathy", {}).get("date_counts") != {
                "24 Oct 2007": 72, "25 Oct 2007": 20, "26 Oct 2007": 20}
            or buchon_a3_lineage.get("catalog_2009_survey_intersects_envelope") is not False
            or buchon_a3_lineage.get("cell_acquisition_year_verified") is not False
            or buchon_a3_lineage.get("qualified_waypoints") != 0):
        raise ValueError("Block A3 delivered-grid acquisition lineage changed")
    if (buchon_2009_terrain.get("usgs_hard_rugose_cells_with_csumb_class") != 87115
            or buchon_2009_terrain.get("usgs_hard_rugose_cells_also_csumb_rough") != 66133
            or buchon_2009_terrain.get("independent_rock_groundtruth") is not False
            or buchon_2009_terrain.get("qualified_waypoints") != 0):
        raise ValueError("2009 CSUMB cross-survey terrain interpretation changed")
    if (buchon_2009_vdatum.get("scope") != "point-buchon-2009-csumb-conditional-geoid03-vdatum-model-probes"
            or buchon_2009_vdatum.get("sample_count") != 12
            or buchon_2009_vdatum.get("private_block_count") != 181
            or buchon_2009_vdatum.get("conditional_navd88_zero_to_mllw_offset_m") != [0.129, 0.149]
            or buchon_2009_vdatum.get("source_horizontal_realization_and_epoch_verified") is not False
            or buchon_2009_vdatum.get("source_product_upper_uncertainty_verified") is not False
            or buchon_2009_vdatum.get("full_source_cell_conversion") is not False
            or buchon_2009_vdatum.get("qualified_waypoints") != 0):
        raise ValueError("2009 CSUMB conditional VDatum diagnostic changed")
    access_counts = buchon_2009_access.get("totals", {})
    if (access_counts.get("blocks") != 181
            or access_counts.get("mpa_margin_blocks") != 8
            or access_counts.get("all_three_clear_margin_blocks") != 173
            or access_counts.get("gea_margin_blocks") != 0
            or access_counts.get("charted_danger_margin_blocks") != 0
            or buchon_2009_access.get("qualified_waypoints") != 0):
        raise ValueError("Original 2009 CSUMB access triage changed")
    if (buchon_caris.get("scope") != "point-buchon-2007-original-caris-prefix-acquisition-lead"
            or {row.get("survey_id") for row in buchon_caris.get("surveys", [])}
            != {"PointBuchon", "PointBuchon_Control"}
            or any(row.get("project_definition_projection") != "AUTO_UTM,WG84_10N"
                   or row.get("prefix_not_complete_archive") is not True
                   for row in buchon_caris["surveys"])
            or buchon_caris.get("qualified_waypoints") != 0
            or buchon_caris.get("fishing_target") is not False):
        raise ValueError("Point Buchon original CARIS acquisition lead changed")
    if (buchon_beams.get("scope") != "point-buchon-2007-ncei-original-valid-beam-overlap"
            or {row.get("survey_id") for row in buchon_beams.get("surveys", [])}
            != {"PointBuchon", "PointBuchon_Control"}
            or any(row.get("generated_inf_good_beams_match") is not True
                   or row.get("generated_fnv_navigation_rows_match") is not True
                   or row.get("valid_beams_both_nominal_depth_bands_and_usgs_hard_rugose", 0) <= 0
                   for row in buchon_beams["surveys"])
            or buchon_beams.get("qualified_waypoints") != 0
            or buchon_beams.get("fishing_target") is not False
            or buchon_beams.get("exportable") is not False):
        raise ValueError("Point Buchon NCEI original-beam overlap changed")
    if (buchon_ncei_index.get("scope") != "point-buchon-2007-ncei-generated-line-depth-index"
            or {row.get("survey_id") for row in buchon_ncei_index.get("surveys", [])}
            != {"PointBuchon", "PointBuchon_Control"}
            or sum(row.get("processed_line_count", 0) for row in buchon_ncei_index["surveys"]) != 186
            or sum(row.get("nominal_200_300ft_unknown_datum_envelope_line_count", 0)
                   for row in buchon_ncei_index["surveys"]) != 45
            or buchon_ncei_index.get("qualified_waypoints") != 0
            or buchon_ncei_index.get("fishing_target") is not False):
        raise ValueError("Point Buchon NCEI line-depth index changed")
    if (buchon_ncei.get("scope") != "point-buchon-2007-ncei-multibeam-acquisition-lead"
            or len(buchon_ncei.get("surveys", [])) != 2
            or any(row.get("metadata_vertical_datum") != "Unknown" for row in buchon_ncei["surveys"])
            or set(buchon_ncei.get("processed_gsf_probes", {})) != {"PointBuchon", "PointBuchon_Control"}
            or any("TIDAL_DATUM=UNKNOWN" not in probe.get("processing_parameters", [])
                   or probe.get("datum_qualified") is not False
                   for probe in buchon_ncei["processed_gsf_probes"].values())
            or set(buchon_ncei.get("selected_line_unknown_datum_depth_ranges", {})) != {"PointBuchon", "PointBuchon_Control"}
            or set(buchon_ncei.get("selected_line_navigation_swath_screens", {})) != {"PointBuchon", "PointBuchon_Control"}
            or any(screen.get("actual_gsf_beam_to_usgs_cell_overlap_verified") is not False
                   or screen.get("sampled_usgs_pixels_by_class", {}).get("200_300ft_hard_rugose", 0) <= 0
                   for screen in buchon_ncei["selected_line_navigation_swath_screens"].values())
            or buchon_ncei.get("qualified_waypoints") != 0
            or buchon_ncei.get("fishing_target") is not False):
        raise ValueError("Point Buchon NCEI processed sounding lead changed")
    if (estero_inventory.get("scope") != "estero-2012-public-release-inventory"
            or estero_inventory.get("listed_tpu_or_base_surface") is not False
            or estero_inventory.get("processing_reports_tpu_computed") is not True
            or estero_inventory.get("qualified_waypoints") != 0):
        raise ValueError("Estero public release inventory changed; review uncertainty acquisition")
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
    if (bss03_vessel.get('scope') != 'bss03-original-vessel-tpu-inputs'
            or len(bss03_vessel.get('vessel_configurations', [])) != 8
            or bss03_vessel.get('line_to_configuration_assignment_verified') is not False
            or bss03_vessel.get('survey_or_cell_total_propagated_uncertainty_verified') is not False
            or bss03_vessel.get('released_grid_upper_error_verified') is not False
            or bss03_vessel.get('depth_qualified') is not False
            or bss03_vessel.get('fishing_target') is not False):
        raise ValueError('Block03 original vessel uncertainty inputs changed')
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
        if sector_id in ("monterey-sur", "big-sur", "sur-san-simeon", "morro-conception"):
            receipts.append(dataone_rov_path)
        if sector_id == "monterey-sur":
            receipts.append(monterey_bag_gap_path)
            receipts.append(monterey_bluetopo_path)
            receipts.append(monterey_1995_path)
            receipts.append(monterey_1998_path)
            receipts.append(monterey_merge_path)
            receipts.append(monterey_points_path)
            receipts.append(monterey_tracks_path)
            receipts.append(monterey_2009_beams_path)
            receipts.append(monterey_producer_path)
            receipts.append(monterey_project_path)
            receipts.append(monterey_cell_join_path)
            receipts.append(monterey_video_beam_path)
            receipts.append(monterey_rov_path)
        if sector_id == 'sur-san-simeon':
            receipts.append(bss03_video_path)
            receipts.append(bss03_access_path)
            receipts.append(bss03_datum_path)
            receipts.append(bss03_caris_path)
            receipts.append(bss03_tpe_path)
            receipts.append(bss03_vessel_path)
        if estero_lead:
            receipts.extend((estero_lead["depth_receipt"], estero_lead["overlap_receipt"]))
            receipts.append(estero_direct_path)
            receipts.append(estero_inventory_path)
            receipts.append(estero_camera_path)
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
            receipts.append(buchon_private_access_path)
            receipts.append(buchon_grid_bridge_path)
            receipts.append(cal_dig_rov_path)
            receipts.append(buchon_path)
            receipts.append(buchon_ncei_path)
            receipts.append(buchon_ncei_index_path)
            receipts.append(buchon_beams_path)
            receipts.append(buchon_caris_path)
            receipts.append(buchon_2009_path)
            receipts.append(buchon_a3_lineage_path)
            receipts.append(buchon_2009_terrain_path)
            receipts.append(buchon_2009_access_path)
            receipts.append(buchon_2009_vdatum_path)
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
        if sector_id == 'pigeon-monterey':
            receipts.append(pigeon_video_path)
            receipts.append(pigeon_noaa_rov_path)
            receipts.append(pigeon_lander_path)
        if sector_id in mare_2016["sector_ids"]:
            receipts.append(mare_2016_path)
            receipts.append(mare_2016_service_path)
            receipts.append(mare_2016_overlap_path)
        tracks = []
        for key, requirement in TRACKS:
            stage = "research-evidence" if key == "native-cells" and measured else "missing-release-evidence"
            if key == "depth-uncertainty" and chart_depth:
                stage = "partial-release-evidence"
            if sector_id == 'sur-san-simeon' and key in ('independent-substrate', 'biological-observations'):
                stage = 'research-evidence'
            if sector_id == 'sur-san-simeon' and key == 'legal-chart-access':
                stage = 'partial-release-evidence'
            if sector_id == 'morro-conception' and key == 'legal-chart-access':
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
        "source_sha256": {p: digest(root, p) for p in (queue_path, ledger_path, buchon_path, buchon_ncei_path, buchon_beams_path, buchon_caris_path, buchon_2009_path, buchon_a3_lineage_path, buchon_2009_terrain_path, buchon_2009_access_path, buchon_2009_vdatum_path, buchon_private_access_path, buchon_grid_bridge_path, monterey_bag_gap_path, monterey_bluetopo_path, monterey_1995_path, monterey_1998_path, monterey_merge_path, monterey_points_path, monterey_tracks_path, monterey_2009_beams_path, monterey_producer_path, monterey_project_path, monterey_cell_join_path, monterey_video_beam_path, monterey_rov_path, cal_dig_rov_path, dataone_rov_path, estero_path, estero_direct_path, estero_inventory_path, estero_camera_path, bss03_video_path, bss03_access_path, bss03_datum_path, bss03_caris_path, bss03_tpe_path, bss03_vessel_path, pigeon_video_path, pigeon_noaa_rov_path, pigeon_lander_path, mare_2016_path, mare_2016_service_path, mare_2016_overlap_path)},
        "release_gate_ids": list(RELEASE_GATES),
        "tracks": [{"id": k, "requirement": v,
                    "acceptance_test": TRACK_PROTOCOLS[k][0],
                    "refresh_trigger": TRACK_PROTOCOLS[k][1]} for k, v in TRACKS],
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
