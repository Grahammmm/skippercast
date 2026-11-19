#!/usr/bin/env python3
"""Join official survey discovery receipts to Central Coast gap priorities."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repository root, for research.*
from research.lib.receipts import locate
from research.scripts.build_central_coverage_ledger import regions_without_qualified_targets


SECTORS = (
    "pigeon-monterey", "monterey-sur", "big-sur", "sur-san-simeon",
    "cambria-morro", "morro-conception",
)


def read(path):
    return json.loads(Path(path).read_text())


def fine_bag_hint(url):
    return bool(re.search(r"_(?:VR|50cm|[1-4]m)_MLLW", url))


def depth_review_paths(root, bindings, surveyed):
    depth_reviews = {}
    sector_reviews = {}
    for binding in bindings:
        sid = binding["survey_id"]
        catalog_urls = surveyed.get(sid, {}).get("products", {}).get("bag", [])
        paths = binding.get("review_paths", [])
        if not paths or len(paths) != len(set(paths)):
            raise ValueError(f"Missing or duplicate native depth receipts for {sid}")
        reviews = {}
        for path in paths:
            receipt = read(locate(path, root))
            url = receipt.get("source_url")
            if (receipt.get("survey_id") != sid or url not in catalog_urls or url in reviews
                    or receipt.get("scope") != "original-regular-bag-300-depth-source-review"
                    or receipt.get("vertical_datum") != "MLLW"
                    or receipt.get("fishing_target") is not False
                    or receipt.get("counts", {}).get("measured_native_cells", 0) <= 0):
                raise ValueError(f"Unreviewed native depth receipt for {sid}")
            reviews[url] = (path, receipt)
        if binding.get("claim") == "no-eligible-25-300ft-anywhere":
            if sid in depth_reviews or any(r["counts"]["eligible_25_300ft_cells_with_margin"] != 0
                                           for _, r in reviews.values()):
                raise ValueError(f"Original depth refutation failed for {sid}")
            depth_reviews[sid] = {url: path for url, (path, _) in reviews.items()}
        elif binding.get("claim") == "no-eligible-200-300ft-in-sector":
            sector_id = binding.get("sector_id")
            if (not sector_id or (sid, sector_id) in sector_reviews
                    or any(not re.search(r"_(?:50cm|[1-4]m)_MLLW", url)
                           or r.get("sector_cell_center_screen", {}).get("sector_id") != sector_id
                           or r["sector_cell_center_screen"]["counts"]["nominal_200_300ft_cells_passing_300ft_uncertainty_margin"] != 0
                           for url, (_, r) in reviews.items())):
                raise ValueError(f"Original deeper-band sector refutation failed for {sid}")
            sector_reviews[(sid, sector_id)] = {url: path for url, (path, _) in reviews.items()}
        else:
            raise ValueError(f"Unknown original native-depth review claim for {sid}")
    return depth_reviews, sector_reviews


def noaa_bag_evidence(original_bag, surveyed, sector_id, depth_reviews, sector_reviews,
                      deep_refuted, vr_by_url, regular_by_url, native_links, extra_bag_url):
    """Summarize exact-file evidence for fine-grid source triage, not habitat."""
    fine_leads, coarse_audited, fine_elsewhere, unresolved = [], [], [], []
    depth_refutations, deep_refutations, sector_refutations = [], [], []
    evidence_by_survey = {}
    deep_path = "dist/data/central-deep-original-300-refutation.json"
    for sid in original_bag:
        # A filename is a triage hint, not proof of native spacing or coverage.
        candidates = {url for url in surveyed[sid]["products"]["bag"] if fine_bag_hint(url)}
        depth_paths = depth_reviews.get(sid, {})
        sector_paths = sector_reviews.get((sid, sector_id), {})
        deep = deep_refuted.get(sid)
        deep_paths = {deep["source_url"]: deep_path} if deep else {}
        negative_depth_paths = {**deep_paths, **depth_paths}
        files = {}
        outside = []
        for url in sorted(candidates | negative_depth_paths.keys() | sector_paths.keys()):
            file = {"status": "unknown"}
            if url in negative_depth_paths:
                file.update(status="inspected-negative", depth_refutation_path=negative_depth_paths[url])
            elif "_VR_" in url:
                sectors = vr_by_url.get(url, {}).get("sectors")
                overview = native_links.get(url, {})
                if sectors is not None:
                    fine = sectors.get(sector_id, {}).get("fine_native_grids", 0) > 0
                    file["status"] = "inspected-positive" if fine else "inspected-negative"
                    if not fine and overview.get("fine_refinement_grids", 0) > 0:
                        outside.append(url)
                elif (url == extra_bag_url
                      or (overview.get("fine_refinement_grids") == 0
                          and overview.get("resolution_m") and max(overview["resolution_m"]) > 4)):
                    file["status"] = "inspected-negative"  # Reviewed file has no fine native grids.
            elif (review := regular_by_url.get(url)) and review.get("sectors") is not None:
                fine = (max(review["native_resolution_m"]) <= 4
                        and review["sectors"].get(sector_id, {}).get("measured_native_cells", 0) > 0)
                file["status"] = "inspected-positive" if fine else "inspected-negative"
            if url in sector_paths:
                file["sector_200_300ft_refutation_path"] = sector_paths[url]
            files[url] = file
        if files:
            evidence_by_survey[sid] = files

        # Aggregate only evidence for the same claim. A sector screen is not a
        # survey-wide depth review, and an older binding is not a catalog snapshot.
        depth_complete = bool(depth_paths) and candidates.issubset(depth_paths)
        deep_complete = bool(deep_paths) and candidates.issubset(deep_paths)
        if depth_complete:
            depth_refutations.append({"survey_id": sid, "review_paths": list(depth_paths.values())})
        if deep_complete:
            deep_refutations.append({
                "survey_id": sid, "review_path": deep_path,
                "shallowest_native_depth_m_mllw": deep["native_refinements"]["shallowest_depth_m_mllw"],
            })
        if sector_paths and candidates.issubset(sector_paths):
            sector_refutations.append({"survey_id": sid, "review_paths": list(sector_paths.values())})

        statuses = {file["status"] for file in files.values()}
        if "inspected-positive" in statuses:
            fine_leads.append(sid)
        elif not (depth_complete or deep_complete):
            unresolved.append(sid)
            if candidates and statuses == {"inspected-negative"}:
                coarse_audited.append(sid)
            if outside:
                fine_elsewhere.append({
                    "survey_id": sid, "fine_grids_outside_sector_urls": outside,
                    "uninspected_candidate_urls": [url for url, file in files.items() if file["status"] == "unknown"],
                    "claim": "reviewed fine native grids have no centers in this browse sector; other files remain separate leads",
                })
    return {
        "noaa_bag_evidence_by_survey_and_url": evidence_by_survey,
        "noaa_filename_fine_grid_leads": fine_leads,
        "noaa_native_audit_refuted_fine_hint": coarse_audited,
        "noaa_reviewed_vr_fine_grids_outside_sector": fine_elsewhere,
        "noaa_original_300ft_depth_refutations": depth_refutations,
        "noaa_original_deepwater_300ft_refutations": deep_refutations,
        "noaa_original_200_300ft_sector_refutations": sector_refutations,
        "noaa_coarse_or_unresolved_leads": unresolved,
    }


def build(root):
    root = Path(root)
    discovery = read(root / "dist/data/noaa-survey-discovery.json")
    products = read(root / "research/receipts/noaa-survey-products.json")
    native = read(root / "research/receipts/noaa-region-bag-envelope-review.json")
    usgs = read(root / "catalog/usgs-ds781-source-leads.json")
    metadata = read(root / "catalog/usgs-ds781-metadata-review.json")
    ledger = read(root / "dist/data/central-coverage-ledger-v1.json")
    bindings = read(root / "research/catalog/central-native-depth-review-bindings.json")
    monterey_bindings = read(root / "catalog/monterey-original-bag-overlap-bindings.json")
    monterey_merge_assets = read(root / "research/receipts/monterey-2013-merge-public-asset-access.json")
    if (monterey_merge_assets.get("scope") != "noaa-2013-merge-m2612-public-distribution-access"
            or len(monterey_merge_assets.get("listings", [])) != 2
            or monterey_merge_assets.get("full_archive", {}).get("objects", 0) < 8000
            or monterey_merge_assets["full_archive"].get("requested_accuracy_inventory_or_acoustic_assets_found")
            or monterey_merge_assets.get("dem_archive", {}).get("objects", 0) < 8000
            or monterey_merge_assets["dem_archive"].get("requested_accuracy_inventory_or_acoustic_assets_found")
            or monterey_merge_assets.get("candidate_accuracy_layer_obtained") is not False
            or monterey_merge_assets.get("candidate_acoustic_source_extent_obtained") is not False
            or monterey_merge_assets.get("fishing_target") is not False):
        raise ValueError("NOAA 2013 merge asset-access gate changed")
    bluetopo = read(root / "research/receipts/central-bluetopo-upstream-source-leads.json")
    bluetopo_manifest = read(root / "research/catalog/bluetopo-statewide-sample.json")
    multibeam = read(root / "research/receipts/noaa-central-multibeam-footprint-leads.json")
    csumb = read(root / "research/receipts/csumb-bss-native-source-review.json")
    bigcreek = read(root / "research/receipts/bigcreek-lopez-original-300-research.json")
    if (bigcreek.get("scope") != "original-bigcreek-lopez-300ft-dem-habitat-research"
            or bigcreek.get("source_grid_vertical_datum") != "NAVD88 Geoid09"
            or bigcreek.get("fishing_target") is not False
            or bigcreek.get("exportable") is not False
            or bigcreek.get("cdfw_mpa_names") != ["Big Creek SMCA", "Big Creek SMR"]
            or {area["survey_area"] for area in bigcreek.get("areas", [])}
            != {"BigCreekN", "BigCreekS", "LopezPt"}):
        raise ValueError("Big Creek original DEM/class research receipt changed")
    vr_native = read(root / "dist/data/noaa-vr-native-depth-review.json")
    regular_native = read(root / "dist/data/noaa-regular-native-depth-review.json")
    conception_two_bag_gap = read(root / "dist/data/point-conception-original-bag-200-300ft-gap.json")
    conception_ladder = read(root / "dist/data/point-conception-original-bag-depth-ladder.json")
    conception_rugged = read(root / "dist/data/point-conception-original-4m-rugged-overlap.json")
    conception_8m = read(root / "dist/data/point-conception-original-8m-hard-overlap.json")
    conception_access = read(root / "dist/data/point-conception-original-4m-access-screen.json")
    conception_enc_seabed = read(root / "research/receipts/point-conception-original-4m-enc-seabed-gap.json")
    if (conception_enc_seabed.get("scope") != "point-conception-two-original-4m-patches-enc-seabed-feature-gap"
            or {key: row.get("charted_seabed_features_in_100m_envelope")
                for key, row in conception_enc_seabed.get("by_survey", {}).items()}
            != {"H11952": 0, "H11953": 0}
            or conception_enc_seabed.get("fishing_target") is not False
            or conception_enc_seabed.get("exportable") is not False):
        raise ValueError("Point Conception bounded ENC seabed status changed")
    if (conception_two_bag_gap.get("scope") != "point-conception-two-original-noaa-bags-200-300ft-exact-file-gap"
            or conception_two_bag_gap.get("combined_200_to_300ft_cells") != 0
            or {row.get("survey_id") for row in conception_two_bag_gap.get("sources", [])} != {"H11952", "H11953"}
            or [row.get("valid_depth_m_range", [None, None])[1]
                for row in conception_two_bag_gap["sources"]] != [40.0, 20.0]
            or conception_two_bag_gap.get("fishing_target") is not False):
        raise ValueError("Point Conception original BAG deep-band status changed")
    if (conception_ladder.get("scope") != "point-conception-h11952-h11953-eight-original-mllw-bag-depth-tiers"
            or len(conception_ladder.get("sources", [])) != 8
            or conception_ladder.get("nominal_200_to_300ft_cells") != 3990509
            or conception_ladder.get("nominal_200_to_300ft_4m_cells") != 3318707
            or conception_ladder.get("fishing_target") is not False):
        raise ValueError("Point Conception original BAG deep-cell lead changed")
    if (conception_rugged.get("scope") != "point-conception-original-4m-mllw-usgs-class3-aggregate-overlap"
            or conception_rugged.get("total_inset_components_at_least_2500m2") != 2
            or conception_rugged.get("fishing_target") is not False):
        raise ValueError("Point Conception 4 m rugged overlap changed")
    if (conception_8m.get("scope") != "point-conception-original-8m-mllw-usgs-class2-class3-aggregate-overlap"
            or [row["requested_region_class3_inset_cells"] for row in conception_8m.get("rows", [])] != [41, 0]
            or sum(row["class2_hard_flat_two_cell_inset"]["retained_components_intersecting_requested_region"]
                   for row in conception_8m["rows"]) != 0
            or conception_8m.get("fishing_target") is not False):
        raise ValueError("Point Conception 8 m deeper class scope changed")
    if (conception_access.get("scope") != "point-conception-two-original-4m-components-current-gis-screen"
            or len(conception_access.get("components", [])) != 2
            or conception_access.get("fishing_target") is not False):
        raise ValueError("Point Conception point-in-time access screen changed")
    extra_bag_pin = read(root / "research/catalog/central-extra-bag-pin.json")
    extra_bag = read(root / "research/receipts/f00844-original-fifth-bag-review.json")
    estero_depth = read(root / "research/receipts/usgs-estero-bay-2012-original-200-300ft-review.json")
    estero_overlap = read(root / "research/receipts/estero-independent-2012-depth-2008-character-overlap.json")
    scc_estero = read(root / "research/receipts/csumb-scc-2010-estero-original-block-coverage.json")
    estero_vdatum_spatial = read(root / "research/receipts/estero-2012-vdatum-spatial-diagnostic.json")
    estero_direct = read(root / "research/receipts/estero-wgs84-direct-vdatum-review.json")
    estero_direct_character = read(root / "research/receipts/estero-wgs84-2008-character-sensitivity.json")
    estero_bag_gap = read(root / "research/receipts/estero-noaa-bag-catalog-gap.json")
    if (estero_bag_gap.get("scope") != "estero-60-research-block-noaa-nos-bag-catalog-gap"
            or estero_bag_gap.get("bag_survey_count") != 0
            or estero_bag_gap.get("fishing_target") is not False
            or estero_bag_gap.get("exportable") is not False):
        raise ValueError("Estero bounded NOAA BAG catalog gap changed")
    if (estero_direct_character.get("scope") != "estero-wgs84-direct-vdatum-2008-independent-character-sensitivity"
            or estero_direct_character.get("fishing_target") is not False
            or estero_direct_character.get("exportable") is not False
            or estero_direct_character.get("qualified_waypoints") != 0
            or estero_direct_character.get("full_cellwise_mllw_surface_verified") is not False):
        raise ValueError("Estero direct-frame independent-class screen changed")
    deep_binding = read(root / "research/catalog/central-deep-original-300-bindings.json")
    deep_refutation = read(root / "research/receipts/central-deep-original-300-refutation.json")
    buchon_catalog_gap = read(root / "research/receipts/point-buchon-noaa-catalog-envelope-gap.json")
    buchon_original = read(root / "research/receipts/point-buchon-original-paired-200-300ft-review.json")
    buchon_datum_leads = read(root / "research/receipts/point-buchon-datum-provenance-leads.json")
    if (buchon_datum_leads.get("scope") != "point-buchon-datum-and-original-grid-provenance-leads"
            or buchon_datum_leads.get("usgs_published_raster", {}).get("output_vertical_datum") != "unresolved"
            or buchon_datum_leads.get("related_csmp_mbes_product", {}).get("same_bytes_or_processing_lineage_as_usgs_release_proven") is not False
            or buchon_datum_leads.get("qualified_waypoints") != 0
            or buchon_datum_leads.get("fishing_target") is not False):
        raise ValueError("Point Buchon datum provenance lead changed")
    buchon_bluetopo = read(root / "research/receipts/point-buchon-bluetopo-hard-cell-overlap.json")
    hard_buchon = buchon_original.get("paired_nominal_band_by_character", {}).get("hard_rugose", {})
    if (buchon_original.get("bathymetry_metadata_sha256")
            != "67f5bd344c133d44fdabc3893f15dc7da6f0c69a30017d62ccfcfed60b4eec63"
            or buchon_original.get("published_grid_resolution_m") != 2
            or buchon_original.get("source_gridding_resolution_m", {}).get("deeper_than_80m") != 5
            or hard_buchon.get("cells") != 804337
            or hard_buchon.get("cells_from_at_or_over_80m_5m_source") != 70158
            or max(row["observed_depth_range_m"][1] for row in
                   buchon_original.get("open_reference_rov_at_nominal_centers", [])) != 66.37
            or buchon_original.get("qualified_waypoints") != 0
            or buchon_original.get("fishing_target") is not False):
        raise ValueError("Point Buchon USGS source-gridding resolution review changed")
    buchon_access = read(root / "research/receipts/point-buchon-rov-access-triage.json")
    if (buchon_access.get("scope") != "point-buchon-open-reference-rov-100m-access-triage"
            or buchon_access.get("totals", {}).get("blocks") != 26
            or buchon_access.get("totals", {}).get("subunits") != 183
            or buchon_access.get("totals", {}).get("hard_rugose_subunits") != 58
            or buchon_access.get("totals", {}).get("centers_on_at_or_over_80m_5m_source") != 0
            or buchon_access.get("noaa_enc_query_layers") != 18
            or buchon_access.get("qualified_waypoints") != 0
            or buchon_access.get("fishing_target") is not False
            or buchon_access.get("exportable") is not False):
        raise ValueError("Point Buchon ROV access triage changed")
    if (buchon_bluetopo.get("scope") != "point-buchon-original-hard-cells-bluetopo-contributor-overlap"
            or buchon_bluetopo.get("scheme_sha256") != bluetopo_manifest["scheme_sha256"]
            or buchon_bluetopo.get("usgs_bathymetry_archive_sha256") != buchon_catalog_gap.get("usgs_bathymetry_archive_sha256")
            or buchon_bluetopo.get("source_envelope_receipt") != "dist/data/point-buchon-noaa-catalog-envelope-gap.json"
            or buchon_bluetopo.get("original_usgs_hard_rugose_cell_centers") != 804337
            or buchon_bluetopo.get("bluetopo_measured_survey_contributor_centers") != 16
            or buchon_bluetopo.get("qualified_waypoints") != 0
            or buchon_bluetopo.get("fishing_target") is not False
            or buchon_bluetopo.get("exportable") is not False):
        raise ValueError("Point Buchon original-cell BlueTopo source review changed")
    if (buchon_catalog_gap.get("scope") != "point-buchon-noaa-survey-catalog-envelope-gap"
            or buchon_catalog_gap.get("usgs_bathymetry_archive_sha256") != "c825293fc999ad757b32ee2acefcae590690d451d12fd367b2f8b3e9e6d731d4"
            or buchon_catalog_gap.get("original_hard_rugose_cells") != 804337
            or buchon_catalog_gap.get("bag_survey_ids_returned") != ["W00479"]
            or buchon_catalog_gap.get("only_returned_survey_original_depth_receipt") != "dist/data/central-deep-original-300-refutation.json"
            or buchon_catalog_gap.get("fishing_target") is not False
            or buchon_catalog_gap.get("exportable") is not False):
        raise ValueError("Original Point Buchon NOAA catalog gap changed")
    if (deep_binding.get("scope") != deep_refutation.get("scope")
            or deep_refutation.get("fishing_target") is not False
            or deep_refutation.get("exportable") is not False
            or deep_refutation.get("qualified_waypoints") != 0):
        raise ValueError("Original Central deepwater refutation changed")
    deep_refuted = {}
    for binding in deep_binding["sources"]:
        sid = binding["survey_id"]
        match = next((row for row in deep_refutation["sources"] if row["survey_id"] == sid), None)
        if (sid in deep_refuted or not match or match["source_url"] != binding["source_url"]
                or match["source_sha256"] != binding["source_sha256"]
                or match["vertical_datum"] != "MLLW"
                or match["native_refinements"]["cells_at_or_shallower_than_300ft"] != 0
                or match["overview"]["cells_at_or_shallower_than_300ft"] != 0):
            raise ValueError(f"Original Central deepwater refutation invalid for {sid}")
        deep_refuted[sid] = match
    if len(deep_refuted) != len(deep_refutation["sources"]):
        raise ValueError("Original Central deepwater source set changed")
    if (buchon_catalog_gap["only_returned_survey_shallowest_measured_depth_m_mllw"]
            != deep_refuted["W00479"]["native_refinements"]["shallowest_depth_m_mllw"]):
        raise ValueError("Point Buchon catalog gap and original W00479 depth disagree")
    if (estero_vdatum_spatial.get("scope") != "estero-2012-vdatum-spatial-offset-diagnostic"
            or estero_vdatum_spatial.get("sample_lattice", {}).get("points") != 28
            or estero_vdatum_spatial.get("converted_source_raster") is not False
            or estero_vdatum_spatial.get("full_error_budget_resolved") is not False
            or estero_vdatum_spatial.get("qualified_waypoints") != 0
            or estero_vdatum_spatial.get("fishing_target") is not False):
        raise ValueError("Estero VDatum spatial diagnostic changed or was promoted")
    if (estero_direct.get("scope") != "estero-2012-original-wgs84-direct-vdatum-research"
            or estero_direct.get("source_archive_sha256")
            != estero_depth.get("source_archives_sha256", {}).get("WGS84_utm10_EsteroBay.zip")
            or estero_direct.get("sample_count") != 60
            or estero_direct.get("source_product_upper_uncertainty_verified") is not False
            or estero_direct.get("qualified_waypoints") != 0
            or estero_direct.get("fishing_target") is not False):
        raise ValueError("Original Estero direct WGS84 datum diagnostic changed or was promoted")
    pigeon_class = read(root / "research/receipts/w00614-pigeon-original-character-overlap.json")
    pigeon_binding = read(root / "catalog/pigeon-w00614-original-class-binding.json")
    if (pigeon_class.get("scope") != pigeon_binding.get("scope")
            or pigeon_class.get("depth_source_sha256") != pigeon_binding.get("bag_sha256")
            or pigeon_class.get("character_source_sha256") != pigeon_binding.get("character_sha256")
            or pigeon_class.get("counts", {}).get("qualified_depth_cells") != 141331
            or pigeon_class.get("counts", {}).get("classified") != 0
            or pigeon_class.get("fishing_target") is not False
            or pigeon_class.get("exportable") is not False):
        raise ValueError("Original Pigeon Point character-overlap refutation changed")
    if (estero_depth.get("scope") != "usgs-estero-bay-2012-original-200-300ft-research"
            or estero_overlap.get("scope") != "estero-independent-2012-depth-2008-character-nominal-overlap"
            or estero_depth.get("fishing_target") is not False
            or estero_overlap.get("fishing_target") is not False
            or estero_depth.get("exportable") is not False
            or estero_overlap.get("exportable") is not False
            or estero_depth.get("source_report") != estero_overlap.get("source_2012")
            or estero_depth.get("source_archives_sha256", {}).get("NAD83_utm10_EsteroBay.zip")
            != estero_overlap.get("depth_archive_sha256")
            or not estero_depth.get("nominal_depth_bands")
            or not estero_overlap.get("depth_bands")):
        raise ValueError("Original Estero independent source audits missing or changed")
    if (scc_estero.get("scope") != "csumb-scc-2010-estero-original-research-block-coverage"
            or scc_estero.get("fishing_target") is not False
            or scc_estero.get("exportable") is not False
            or scc_estero.get("qualified_waypoints") != 0
            or {row["survey_id"] for row in scc_estero.get("source_results", [])}
            != {"SCC_Block12", "SCC_Block13"}
            or any(row["bands"]["250-300ft"]["measured_2010_cells"] != 0
                   for row in scc_estero["source_results"])):
        raise ValueError("Original 2010 SCC Estero coverage review missing or changed")
    if (csumb.get("scope") != "original-csumb-bss-native-grid-review"
            or csumb.get("publication_status") != "source-evidence-only"
            or any(s.get("status") != "held-from-fishing-targets"
                   or s.get("native_depth_screen", {}).get("comparison_band_200_300ft_navd88_cells") is None
                   or s.get("archive_product_inventory", {}).get("named_uncertainty_or_cube_surface_products") != []
                   for s in csumb.get("sources", []))):
        raise ValueError("CSUMB native 300 ft source audit missing or changed")
    if (vr_native.get("scope") != "california-original-vr-native-depth-review"
            or vr_native.get("status") != "ok"):
        raise ValueError("Original NOAA VR native-sector audit missing or changed")
    vr_by_url = {item["bag_url"]: item for item in vr_native["files"] if item.get("status") == "ok"}
    if (regular_native.get("scope") != "california-original-regular-native-depth-review"
            or regular_native.get("status") != "ok"):
        raise ValueError("Original NOAA regular native-sector audit missing or changed")
    regular_by_url = {item["bag_url"]: item for item in regular_native["files"] if item.get("status") == "ok"}
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
    if any(row["source_url"] not in surveyed[sid]["products"]["bag"]
           for sid, row in deep_refuted.items()):
        raise ValueError("Original Central deepwater BAG not in NOAA product catalog")
    if (extra_bag_pin.get("schema_version") != 1 or extra_bag.get("schema_version") != 1
            or extra_bag.get("scope") != "original-noaa-f00844-fifth-bag-coverage-audit"
            or any(extra_bag.get(field) != extra_bag_pin.get(field)
                   for field in ("survey_id", "source_url", "source_sha256", "source_bytes"))
            or extra_bag["source_url"] not in surveyed[extra_bag["survey_id"]]["products"]["bag"]
            or extra_bag.get("fishing_target") is not False
            or extra_bag.get("exportable") is not False
            or extra_bag.get("native", {}).get("refinement_grids_at_most_4m") != 0):
        raise ValueError("Original F00844 fifth BAG source audit missing or changed")
    if (monterey_bindings.get("scope") != "original-noaa-mllw-bag-overlap-with-17-monterey-research-outlines"
            or monterey_bindings.get("claim") != "no-measured-native-cells-inside-these-17-outlines"):
        raise ValueError("Unreviewed original Monterey BAG overlap claim")
    original_pixel = read(root / "research/receipts/monterey-original-300-pixel-review.json")
    w00614_300 = read(root / "research/receipts/w00614-original-300-pigeon-monterey-review.json")
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
        (root / "research/receipts/usgs-offshore-monterey-hard-context.geojson").read_bytes()).hexdigest()
    original_pixel_sha = hashlib.sha256(
        (root / "research/receipts/monterey-original-300-pixel-review.json").read_bytes()).hexdigest()
    monterey_no_overlap = {}
    for binding in monterey_bindings["bindings"]:
        sid = binding["survey_id"]
        path = binding["review_path"]
        report = read(locate(path, root))
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
    depth_reviews, sector_reviews = depth_review_paths(root, bindings["bindings"], surveyed)
    native_links = {lead["bag_url"]: lead for region in native["regions"]
                    for lead in region.get("leads", [])}
    source_rows = []
    for sector_id in SECTORS:
        area = discovery_rows[sector_id]
        west, south, east, north = map(float, parse_qs(urlsplit(area["request_url"]).query)["geometry"][0].split(","))
        csumb_leads = []
        for source in csumb["sources"]:
            sw, ss, se, sn = source["bathymetry"]["valid_cell_envelope_wgs84"]
            if se < west or sw > east or sn < south or ss > north:
                continue
            band = source["native_depth_screen"]
            if band["comparison_band_200_300ft_navd88_cells"]:
                csumb_leads.append({
                    "source_id": source["source_id"],
                    "native_grid_resolution_m": source["bathymetry"]["resolution_m"],
                    "measured_200_300ft_navd88_comparison_cells": band["comparison_band_200_300ft_navd88_cells"],
                    "derived_rough_class_cells_in_comparison_band": band["derived_rough_class_cells_in_comparison_band"],
                    "rights_status": source["rights_status"],
                    "release_status": "datum-uncertainty-rights-hold",
                })
        # The discovery service is broad-track geometry; counts are leads only.
        survey_ids = sorted({s["id"] for s in area.get("surveys", [])})
        original_bag = [sid for sid in survey_ids if surveyed.get(sid, {}).get("products", {}).get("bag")]
        bag_evidence = noaa_bag_evidence(original_bag, surveyed, sector_id, depth_reviews, sector_reviews,
                                         deep_refuted, vr_by_url, regular_by_url, native_links, extra_bag["source_url"])
        fine_leads = bag_evidence["noaa_filename_fine_grid_leads"]
        has_unknown_bags = any(file["status"] == "unknown"
                               for files in bag_evidence["noaa_bag_evidence_by_survey_and_url"].values()
                               for file in files.values())
        usgs_areas = [m for m in usgs["map_areas"] if sector_id in m.get("planning_sector_ids", [])]
        paired = [m for m in usgs_areas if
                  {"bathymetry", "seafloor-character"}.issubset({p["kind"] for p in m.get("products", [])})]
        upstream_ids = {sid for row in bluetopo_by_sector[sector_id]
                        for sid in row["rat_measured_survey_ids"]}
        historical_hydrography = sorted(sid for sid in upstream_ids if re.fullmatch(r"[BHW]\d{5}(?:_.*)?", sid))
        coastal_dem = sorted(upstream_ids - set(historical_hydrography))
        # Priority is a *source-review* queue, not a predicted fish-density map.
        tier = 1 if paired else 2 if fine_leads or sector_id == "big-sur" else 3
        source_rows.append({
            "sector_id": sector_id,
            "priority_tier": tier,
            "noaa_catalog_lead_count": len(survey_ids),
            "noaa_catalog_leads_with_bag_links": len(original_bag),
            "noaa_survey_ids": original_bag,
            **bag_evidence,
            "point_buchon_noaa_catalog_gap": ({
                "receipt": "dist/data/point-buchon-noaa-catalog-envelope-gap.json",
                "catalog_bag_survey_ids": buchon_catalog_gap["bag_survey_ids_returned"],
                "claim": "The catalog envelope query returned only W00479. The exact reviewed original BAG had no measured MLLW cells at or shallower than 300 ft; other files and archives remain possible.",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_buchon_bluetopo_contributor_overlap": ({
                "receipt": "dist/data/point-buchon-bluetopo-hard-cell-overlap.json",
                "original_usgs_hard_rugose_cell_centers": buchon_bluetopo["original_usgs_hard_rugose_cell_centers"],
                "measured_survey_contributor_centers": buchon_bluetopo["bluetopo_measured_survey_contributor_centers"],
                "claim": "Nominal original USGS hard-cell center overlay finds only 16 BlueTopo pixels attributed to measured survey IDs; most use interpolated historical contributors.",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_buchon_rov_access_triage": ({
                "receipt": "dist/data/point-buchon-rov-access-triage.json",
                "private_research_blocks": buchon_access["totals"]["blocks"],
                "historic_open_reference_subunits": buchon_access["totals"]["subunits"],
                "claim": "A bounded current MPA, NOAA GEA and ENC danger screen clears 26 historical ROV research blocks with a 100 m review margin; no complete route, security, depth or rules clearance.",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_buchon_source_gridding_resolution": ({
                "receipt": "dist/data/point-buchon-original-paired-200-300ft-review.json",
                "published_grid_m": 2,
                "source_grid_m_deeper_than_80m": 5,
                "nominal_hard_rugose_published_cells_from_5m_source": hard_buchon["cells_from_at_or_over_80m_5m_source"],
                "deepest_published_open_reference_rov_observed_depth_m": 66.37,
                "claim": "The 2 m published mosaic includes 5 m source-gridded bathymetry deeper than 80 m; fine pixel spacing does not imply 2 m independent bottom detail there.",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_buchon_datum_provenance_lead": ({
                "receipt": "dist/data/point-buchon-datum-provenance-leads.json",
                "related_product_reported_datum": buchon_datum_leads["related_csmp_mbes_product"]["reported_vertical_datum"],
                "usgs_published_raster_output_datum": "unresolved",
                "claim": "A PG&E technical appendix reports NAVD88 for a related CSMP MBES product, but its processing lineage to the USGS release is not established; CSUMB lists two older Point Buchon grid archives as acquisition leads.",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_conception_original_bag_deep_gap": ({
                "receipt": "dist/data/point-conception-original-bag-200-300ft-gap.json",
                "exact_files_checked": [row["file_name"] for row in conception_two_bag_gap["sources"]],
                "populated_200_300ft_cells": 0,
                "claim": "These two specific original MLLW BAG files reach only 40 m and 20 m; seek different original cells for deeper Point Conception targets.",
                "fishing_target": False, "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_conception_original_bag_deep_lead": ({
                "receipt": "dist/data/point-conception-original-bag-depth-ladder.json",
                "survey_ids": ["H11952", "H11953"],
                "native_4m_nominal_200_300ft_cells": conception_ladder["nominal_200_to_300ft_4m_cells"],
                "native_8m_nominal_200_300ft_cells": (
                    conception_ladder["nominal_200_to_300ft_cells"]
                    - conception_ladder["nominal_200_to_300ft_4m_cells"]),
                "next_gate": "Map whole measured cell patches with product uncertainty and independent substrate; then full legal/chart/route screens",
                "fishing_target": False, "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_conception_original_4m_rugged_overlap": ({
                "receipt": "dist/data/point-conception-original-4m-rugged-overlap.json",
                "inset_components_at_least_2500m2": 2,
                "next_gate": "Resolve USGS/NOAA registration and class accuracy at these components, then independent fish and full access evidence",
                "fishing_target": False, "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_conception_original_8m_hard_overlap": ({
                "receipt": "dist/data/point-conception-original-8m-hard-overlap.json",
                "requested_region_rugged_inset_cells": 41,
                "retained_rugged_patches_at_least_2500m2": 0,
                "retained_flat_patches_inside_requested_region": 0,
                "next_gate": "Seek measured finer-resolution depth and independent bottom observations; 8 m cells cannot validate small reef",
                "fishing_target": False, "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_conception_original_4m_access_screen": ({
                "receipt": "dist/data/point-conception-original-4m-access-screen.json",
                "mapped_gis_held_components_at_review": conception_access["components_held_by_mapped_gis"],
                "source_checked_at": conception_access["source_checked_at"],
                "status": "point-in-time research screen; no legal or route clearance",
                "fishing_target": False, "exportable": False,
            } if sector_id == "morro-conception" else None),
            "point_conception_original_4m_enc_seabed_gap": ({
                "receipt": "dist/data/point-conception-original-4m-enc-seabed-gap.json",
                "charted_seabed_features_in_100m_envelope": 0,
                "scope": "Three ENC scale bands, eight seabed point/line/area layers at each of two private original-cell patches",
                "next_gate": "Obtain source survey SBDARE/S57 or independently positioned camera/grab observations; current ENC has no seabed feature in these bounded envelopes",
                "fishing_target": False, "exportable": False,
            } if sector_id == "morro-conception" else None),
            "noaa_no_measured_cells_in_17_monterey_outlines": [
                {"survey_id": sid, "review_path": monterey_no_overlap[sid]}
                for sid in original_bag if sid in monterey_no_overlap
                and sector_id in ("pigeon-monterey", "monterey-sur")],
            "monterey_2013_merge_source_acquisition": ({
                "receipt": "dist/data/monterey-2013-merge-public-asset-access.json",
                "source_id_to_resolve": "12241",
                "public_supplemental_objects_checked": sum(len(row["objects"]) for row in monterey_merge_assets["listings"]),
                "public_full_distribution_objects_checked": monterey_merge_assets["full_archive"]["objects"],
                "public_dem_distribution_objects_checked": monterey_merge_assets["dem_archive"]["objects"],
                "requested_accuracy_inventory_or_acoustic_assets_found": monterey_merge_assets["requested_accuracy_inventory_or_acoustic_assets_found"],
                "next_gate": "Obtain NOAA's source-ID crosswalk, original source extents and accuracy/void products; then resolve survey datum and upper error on full research footprints",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "monterey-sur" else None),
            "noaa_original_300ft_depth_leads": ([{
                "survey_id": "W00614", "review_path": "dist/data/w00614-original-300-pigeon-monterey-review.json",
                "qualified_200_300ft_native_cells": w00614_300["counts"]["depth_uncertainty_qualified_200_300ft_cells"],
                "eligible_supergrid_center_bounds": w00614_300["eligible_supergrid_center_bounds"],
                "coverage_note": "Native measured cells cluster near Pigeon Point, north of Monterey Bay; no substrate or fishable target qualified."}]
                if sector_id == "pigeon-monterey" else []),
            "noaa_usgs_original_character_overlap": ({
                "receipt": "dist/data/w00614-pigeon-original-character-overlap.json",
                "depth_qualified_cells": pigeon_class["counts"]["qualified_depth_cells"],
                "classified_cells_on_those_depth_cells": pigeon_class["counts"]["classified"],
                "claim": "The USGS Offshore Pigeon Point 2 m class raster has no valid pixels over these W00614 200–300 ft cells; seek a different independent substrate source.",
                "fishing_target": False,
            } if sector_id == "pigeon-monterey" else None),
            "bluetopo_rat_tile_count": len(bluetopo_by_sector[sector_id]),
            "bluetopo_rat_historical_hydrography_ids": historical_hydrography,
            "bluetopo_rat_coastal_dem_ids": coastal_dem,
            "bluetopo_rat_receipt": "dist/data/central-bluetopo-upstream-source-leads.json",
            "ncei_multibeam_footprint_lead_count": footprint_by_sector[sector_id]["footprint_lead_count"],
            "ncei_multibeam_distinct_survey_id_count": len({item["survey_id"] for item in footprint_by_sector[sector_id]["footprints"]
                                                             if item["survey_id"]}),
            "ncei_multibeam_footprint_receipt": "dist/data/noaa-central-multibeam-footprint-leads.json",
            "csumb_native_band_leads": csumb_leads,
            "csumb_native_band_receipt": "dist/data/csumb-bss-native-source-review.json",
            "bigcreek_lopez_original_grids": ({
                "receipt": "dist/data/bigcreek-lopez-original-300-research.json",
                "archive_sha256": bigcreek["source_archive_sha256"],
                "source_datum": "NAVD88 Geoid09",
                "lopez_rough_dem_cells_outside_current_mpa_plus_75m": sum(
                    tier["derived_rough_cells_outside_mpa_plus_75m"]
                    for area in bigcreek["areas"] if area["survey_area"] == "LopezPt"
                    for tier in area["tiers"]),
                "release_status": "full-grid-chart-datum-total-uncertainty-independent-bottom-rights-hold",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "big-sur" else None),
            "estero_independent_depth_character_lead": ({
                "depth_source": estero_depth["source_report"],
                "depth_receipt": "dist/data/usgs-estero-bay-2012-original-200-300ft-review.json",
                "character_source": estero_overlap["source_2008"],
                "overlap_receipt": "dist/data/estero-independent-2012-depth-2008-character-overlap.json",
                "nominal_200_300ft_depth_cells": sum(
                    band["depth_cells"] for band in estero_depth["nominal_depth_bands"].values()),
                "nominal_200_300ft_independent_hard_rugose_overlap_cells": sum(
                    band["classified_cells_by_type"]["hard_rugose"]
                    for band in estero_overlap["depth_bands"].values()),
                "release_status": "datum-registration-uncertainty-legal-chart-biology-hold",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "cambria-morro" else None),
            "csumb_scc_estero_2010_crosscheck": ({
                "receipt": "dist/data/csumb-scc-2010-estero-original-block-coverage.json",
                "survey_ids": [row["survey_id"] for row in scc_estero["source_results"]],
                "shallower_research_blocks_with_measured_2010_cells": max(
                    row["bands"]["200-250ft"]["blocks_with_measured_2010_cells"]
                    for row in scc_estero["source_results"]),
                "deeper_research_blocks_with_measured_2010_cells": 0,
                "release_status": "source-coverage-only",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "cambria-morro" else None),
            "estero_vdatum_spatial_diagnostic": ({
                "receipt": "dist/data/estero-2012-vdatum-spatial-diagnostic.json",
                "sample_points": estero_vdatum_spatial["sample_lattice"]["points"],
                "offset_range_m": estero_vdatum_spatial["offset_m"]["range"],
                "release_status": "CORS96-registration-and-total-uncertainty-hold",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "cambria-morro" else None),
            "estero_wgs84_direct_diagnostic": ({
                "receipt": "dist/data/estero-wgs84-direct-vdatum-review.json",
                "sample_points": estero_direct["sample_count"],
                "nominal_center_offset_200_300ft_cells": sum(
                    row["nominal_center_offset_200_300ft_cells"]
                    for row in estero_direct["by_prior_nominal_band"].values()),
                "release_status": "direct-ellipsoid-datum-available-product-uncertainty-and-registration-hold",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "cambria-morro" else None),
            "estero_wgs84_independent_character_sensitivity": ({
                "receipt": "dist/data/estero-wgs84-2008-character-sensitivity.json",
                "nominal_class3_cells": sum(band["hard_rugose_cells"] for band in
                                            estero_direct_character["by_prior_research_band"].values()),
                "class3_cells_stable_within_25m": sum(
                    band["rugose_class_stable_within_25m_cell_centers"] for band in
                    estero_direct_character["by_prior_research_band"].values()),
                "largest_within_block_25m_stable_component_cells": max(
                    band["largest_within_block_25m_stable_component_cells"] for band in
                    estero_direct_character["by_prior_research_band"].values()),
                "release_status": "nominal-block-center-datum-and-unbounded-registration-hold",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "cambria-morro" else None),
            "estero_noaa_bag_catalog_gap": ({
                "receipt": "dist/data/estero-noaa-bag-catalog-gap.json",
                "bag_survey_count": estero_bag_gap["bag_survey_count"],
                "scope": "NOS BAG catalog over 60 original research blocks only",
                "fishing_target": False,
                "exportable": False,
            } if sector_id == "cambria-morro" else None),
            "usgs_map_areas": [{"name": m["name"], "catalog_url": m["resolved_url"],
                                "paired_original_products": m in paired} for m in usgs_areas],
            "next_action": "Resolve registration/independence of two H11952/H11953 4 m rugged-class research components and source fish observations; repeat dated GIS checks and screen security, rules and full routes before promotion" if sector_id == "morro-conception"
                           else "Acquire NOAA 2013 merge source-ID 12241 crosswalk, original survey datum and vertical-accuracy/source-extent deliverables for the paired Monterey research cells; then test independent substrate and full-area clearance" if sector_id == "monterey-sur"
                           else "Resolve Lopez Point original CUBE-source uncertainty and full-grid NAVD88-to-MLLW conversion, obtain independent rock observations and source-specific use permission; then review full access/chart geometry" if sector_id == "big-sur"
                           else "Acquire 2012 Estero CARIS TPU and source coordinate epoch; convert every WGS84 source cell to MLLW, bound its uncertainty, and validate 2008 class registration plus independent bottom/fish observations before full-route review" if sector_id == "cambria-morro"
                           else "Open original native BAG and paired substrate pixels; document measured-cell footprint, MLLW datum, uncertainty, source age and rights before any target screen" if fine_leads or paired or has_unknown_bags
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
        "region_gaps": regions_without_qualified_targets(ledger["regions"]),
        "sectors": source_rows,
        "method_note": "Catalog intersections, BAG links, BlueTopo contributor-table IDs, multibeam swath-footprint intersections and filename spacing hints are not measured 25–300 ft raster coverage or evidence of fish. The legacy fine-grid-leads field now requires reviewed native cells in the browse sector; it is still a source lead, not a fishing spot. CSUMB BSS native-band pixel counts are nominal NAVD88 source evidence, but lack chart-datum conversion, source uncertainty, independent rock confirmation and redistribution rights. Big Creek/Lopez Point counts are interpolated processed DEM output cells, not independent soundings or rock observations; they remain on chart-datum, uncertainty and rights hold. The Estero WGS84 direct-frame/2008 class join uses 100 m block-center VDatum offsets and tests class stability, not a cellwise chart-MLLW/error surface or exact fishable geometry; its registration, uncertainty, legal, chart and biological gates remain open. The 2010 SCC grids check only four of seven shallower Estero research blocks and none of the 53 deeper blocks. Re-run discovery and inspect original pixels before promotion.",
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
