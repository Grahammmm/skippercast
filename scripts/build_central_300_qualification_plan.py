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
        "lead": "CSUMB BSS 2 m NAVD88 cells and historical Big Creek ROV reference observations",
        "next": "Get original uncertainty and reference-frame bridge, then pair surveyed substrate and position-audited fish transects at the same patch.",
        "hold": "ROV area counts and terrain roughness do not define a precise fishing patch.",
    },
    "cambria-morro": {
        "lead": "Independent 2012 Estero depth and 2008 video-supervised character overlap",
        "next": "Resolve the CORS96 epoch bridge and NAVD88-to-MLLW surface; obtain 2012 CARIS TPU, then rescreen the full 100 m blocks and approaches.",
        "hold": "The 2010 independent cross-check reaches four shallow blocks and no deeper blocks; total depth error remains unknown.",
    },
    "morro-conception": {
        "lead": "Original Point Buchon 2 m USGS depth/character pair and open-reference ROV context; H11951/52/53 deep cells do not cover the needed rock patches",
        "next": "Establish Point Buchon output datum and upper uncertainty; acquire an original MLLW survey over deep hard cells and current Diablo/Vandenberg access and ENC screens.",
        "hold": "Historical class and fish observations cannot replace chart-datum depth, safe access or current legal review.",
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
    queue, ledger = load(root, queue_path), load(root, ledger_path)
    buchon, estero = load(root, buchon_path), load(root, estero_path)
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
        if csumb:
            receipts.append(row["csumb_native_band_receipt"])
        if estero_lead:
            receipts.extend((estero_lead["depth_receipt"], estero_lead["overlap_receipt"]))
            spatial = row.get("estero_vdatum_spatial_diagnostic")
            if (not spatial or spatial["sample_points"] != 28
                    or spatial["fishing_target"] is not False
                    or spatial["exportable"] is not False):
                raise ValueError("Estero VDatum spatial evidence changed")
            receipts.append(spatial["receipt"])
        if sector_id == "morro-conception":
            receipts.append(buchon_path)
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
        "source_sha256": {p: digest(root, p) for p in (queue_path, ledger_path, buchon_path, estero_path)},
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
