# Monterey–Point Conception: 300 ft source and ranking review

Reviewed September 26, 2026. The boat's 300 ft planning ceiling is **not** a promise of mapped or legal fishing coverage to 300 ft. The public Morro Bay–Avila atlas has 132 historical survey-derived rocky targets, all within its original 200 ft source screen. The six adjacent preview packages still have no exportable bottom-fishing targets.

The companion [biological evidence and gap plan](central-biological-evidence-and-gaps.md) adds a reproducible 2007–2024 open-reference CCFRP catch/effort summary and identifies the CDFW ROV observations most relevant to deeper reef validation. Neither source has qualified a new 200–300 ft waypoint.

## What was checked

* [26 pinned NOAA NBS Modeling tiles](../dist/data/nbs-central-300-depth-screen.json) across Monterey–Point Sur, Big Sur, and Point Sur–San Simeon were re-downloaded, SHA-256 checked, and screened at 25–300 ft. A cell needed a measured post-1990 contributor, at most 4 m resolution, no more than 1 m supplied vertical uncertainty, and room for the 2 m planning margin. **Zero cells passed.** One Monterey tile had 6,790 measured post-1990 pixels within the nominal depth band, but none passed all uncertainty and depth-margin gates. The NBS compilation is a test/evaluation product, not a chart or original survey.
* The original NOAA H11952 2 m and H11953 1 m MLLW BAGs were joined to hash-checked original USGS class-3 hard-bottom rasters using fresh CDFW MPA and NOAA GEA polygons and reviewed historical hazards. Their [300 ft summary](../dist/data/point-conception-native-hard-300-review-summary.json) retained 27 and 1 research components respectively, **exactly the same counts as the prior 200 ft screen**. Their deepest retained source cells were 131.2 ft and 45.0 ft. No 200–300 ft area emerged from these two source footprints. These components remain non-exportable because current chart, route and Vandenberg access gates are unresolved.
* The [fresh GIS re-screen](../dist/data/central-atlas-300-current-closure-screen.json) checked all 132 existing Central atlas target centers with a 200 m review buffer and all 107 reef outlines plus 31 drift lines with 100 m buffers. None hit the fresh CDFW MPA or NOAA GEA polygons. The minimum separation was 504 m for a target center, 505 m for an outline and 531 m for a drift line. This does not clear the Diablo security zone, other restrictions, a route, or the controlling legal boundary.

The [complete target ranking inventory](../dist/data/central-rocky-species-rankings.json) uses a deterministic lingcod and broad rockfish physical-habitat fit rule. Rank **1** means stronger mapped fit, **2** intermediate, **3** lower. Lingcod weights local relief more; rockfish weights rough-habitat extent more. A selective rank 1 now requires a fit index of at least 0.90 and at least 70% mapped rough cover; rank 2 starts at 0.70. The updated distribution is 32/60/40 for lingcod and 37/76/19 for rockfish. These are fixed physical thresholds, not catch-calibrated percentiles. The separate survey confidence and source detail still matter; no score is a catch probability or evidence of fish at the coordinate.

| Current higher-scoring historical candidates | Center depth | Terrain score | Lingcod / rockfish fit |
| --- | ---: | ---: | ---: |
| SC26-004 · North Buchon rocky rise | 61 ft | 98/100 | 1 / 1 |
| SC26-012 · West White Rock complex | 96 ft | 93/100 | 1 / 1 |
| SC26-011 · Estero rock high | 137 ft | 89/100 | 1 / 1 |
| SC26-001 · Southern rocky rise | 140 ft | 88/100 | 1 / 1 |
| SC26-002 · Southern reef crest | 146 ft | 86/100 | 1 / 1 |

The current [CDFW Central Management Area table](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary) says recreational nearshore and shelf/slope rockfish and lingcod are open at all depths April 1–December 31, subject to species, area and other rules. Thus 300 ft is the user's equipment/planning limit here, not a fixed Central-area legal depth line. Recheck [in-season changes](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Inseason), the exact MPA and federal boundaries, local access and the day's conditions before fishing. The Southern Management Area on the other side of Point Conception has a different seasonal 50-fathom boundary rule.

## Remaining qualification work

The USGS Offshore Monterey original class and bathymetry pair remains research only: its depth raster is NAVD88 with no paired per-cell uncertainty, and five VDatum point probes cannot convert a full patch or establish the missing survey uncertainty. Big Sur's broader PMEP rocky-reef areas likewise cannot identify a precise 300 ft reef or a safe waypoint. A useful next source must supply original, local MLLW-equivalent depth plus per-cell uncertainty and high-resolution substrate for the exact footprint. Every promoted mark then needs current chart dangers, legal boundary, access, and full approach/drift geometry review. Until those gates pass, displaying the research polygons without a 1–3 fishing rank is the accurate behavior.

To reproduce the bounded 300 ft audit, use `scripts/audit_central_nbs_300.py --fetch` with the pinned tile scheme and `scripts/qualify_regular_bag_hard.py --limit-ft 300` with current complete CDFW/NOAA geometry snapshots. Both source files are checksum checked. Run `scripts/audit_central_atlas_closures.py` against fresh geometry before rebuilding the inventory with `scripts/build-central-rankings.mjs`.
