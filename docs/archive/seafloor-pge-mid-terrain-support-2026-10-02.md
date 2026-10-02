# PGE Mid native terrain support — October 2, 2026

Bind four original rough/smooth products to their exact original depth grids using the reviewed native-terrain method. Preserve source status, rights, quality holds, depth limits and the habitat formula. This batch adds **zero new measured coverage**.

## Original evidence

The source-only receipt `research/receipts/seafloor-pge-mid-native-terrain-review.json` records publisher URLs, original/member hashes, exact alignment, class counts, datum and acquisition limitations. The combined `seafloor-pge-mid-terrain-binding-review.json` records checked before/after outputs. Logical receipt references were renamed during integration; the original raster and metadata evidence was not altered.

The class interpretation derives from the same DEM. It supports rough terrain, not independently measured substrate, sounding accuracy or fish presence. Manual smooth/artifact exclusions are not a comprehensive artifact mask. Unknown accuracy and interpolation remain unknown. Original bytes and normalized scientific identities were checked against existing caches; no archive was downloaded again.

C2, E2, C5 and E5 retain usable status and credited noncommercial terms. C1/D1 have no matching native 1 m class product; D2 contains unexplained +1 class codes and remains unbound. No nearest-neighbor substitution, legend relaxation or resampling is used. C2/C5 metadata report a 0.0005 VRM threshold and 93% agreement, but the sample design and reference independence are not established; this is not a calibrated habitat-confidence percentage.

The comparison includes all shared-calibration contributors, including unbound sources. Eligible outlines change by −111 and habitat area by −3.423584457 km². These are refinements of existing support, not lost or gained measured geography. All 1,298 eligible polygons pass the current whole-polygon CDFW/NOAA/security check; 1–3 ranks and nominal 25–300 ft product depths were validated.

## Measured comparison

Normal runs used retained caches without `--force`. Coverage-cell records, native source selection and measured area are identical before and after. Changed support appropriately invalidates affected terrain calculations. The unchanged public ledger remains workflow-owned.

| Reach | Selected valid km², unchanged | Physical before → after | Screened before → after | Habitat km² before → after |
| --- | ---: | ---: | ---: | ---: |
| morro-bay-r07 | 55.921421631 | 702 → 558 | 436 → 314 | 3.37061201 → 1.906556289 |
| morro-bay-r08 | 60.95992344 | 1011 → 1022 | 973 → 984 | 7.875940858 → 5.916412122 |

## Native review

All 531 direct bound-source features received native numeric checks; 18 deterministic samples on six pages show localized outcrops, ridges and margins. Some linear terrain remains ambiguous without independent corroboration. Sampling does not establish exhaustive artifact absence, substrate accuracy or fish presence; no stronger source-quality claim is made.

All selected native centers have valid class data. Minimum rough-support fraction is 0.989170; projected polygon edges and native centers differ slightly. Numeric depth diagnostics span 18.21–88.87 m. Diagnostic rasters, candidate coordinates and held geometry remain private.

The existing research-only `research/scripts/audit_native_terrain_support.py` creates these diagnostics without resampling or changing ranks/holds. It is an audit utility, not a production dependency. Hashes bind the review to exact saved outputs. Production runs must retain current source/rights and whole-polygon screens before any eligible output is called live.
