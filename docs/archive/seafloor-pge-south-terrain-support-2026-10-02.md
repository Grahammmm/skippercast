# PGE South native terrain support — October 2, 2026

Bind four original rough/smooth products to their exact original depth grids using the reviewed native-terrain method. Preserve source status, rights, quality holds, depth limits and the habitat formula. This batch adds **zero new measured coverage**.

## Original evidence

The source-only receipt `research/receipts/seafloor-pge-south-native-terrain-review.json` records publisher URLs, original/member hashes, exact alignment, class counts, datum and acquisition limitations. The combined `seafloor-pge-south-terrain-binding-review.json` records checked before/after outputs. Logical receipt references were renamed during integration; the original raster and metadata evidence was not altered.

The class interpretation derives from the same DEM. It supports rough terrain, not independently measured substrate, sounding accuracy or fish presence. Manual smooth/artifact exclusions are not a comprehensive artifact mask. Unknown accuracy and interpolation remain unknown. Original bytes and normalized scientific identities were checked against existing caches; no archive was downloaded again.

F2, G2, H2 and G5 retain physical-only status. G5 contains original rough cells only below the nominal 300 ft ceiling; G2 has one shallow rough cell and H2 has none. Class NoData remains unsupported for habitat, while valid measured depth is retained. The four processed reaches are maintenance of previously processed private coverage, not four new reaches.

The comparison includes every contributing source because the unchanged shared calibration can alter neighboring-source candidates. The combined physical count changes from 4,255 to 3,127; this is filtering and component refinement, not geographic expansion. Further original-evidence review of two isolated Block F features is pending; no source is promoted by this change.

## Measured comparison

Normal runs used retained caches without `--force`. Coverage-cell records, native source selection and measured area are identical before and after. Changed support appropriately invalidates affected terrain calculations. The unchanged public ledger remains workflow-owned.

| Reach | Selected valid km², unchanged | Physical before → after | Screened before → after | Habitat km² before → after |
| --- | ---: | ---: | ---: | ---: |
| morro-bay-r08 | 112.082476716 | 726 → 1046 | 0 → 0 | 0.0 → 0.0 |
| morro-bay-r09 | 35.781702324 | 192 → 201 | 0 → 0 | 0.0 → 0.0 |
| morro-bay-r10 | 59.241373997 | 1639 → 1003 | 0 → 0 | 0.0 → 0.0 |
| point-arguello-conception-r01 | 71.241712598 | 1698 → 877 | 0 → 0 | 0.0 → 0.0 |

## Native review

All 38 direct Block F features received native numeric checks and visual review on 13 pages. Most show localized ridges, edges and outcrops. Two isolated relief features need additional corroboration; source quality is not cleared. All other southern bound sources yield no direct candidates in these runs. The current spatial-only diagnostic finds all 38 Block F polygons clear of the configured restrictions; this does not remove source-quality or publication holds.

All selected native centers have valid class data. Minimum rough-support fraction is 0.997006; projected polygon edges and native centers differ slightly. Numeric depth diagnostics span 7.93–44.72 m. Diagnostic rasters, candidate coordinates and held geometry remain private.

The existing research-only `research/scripts/audit_native_terrain_support.py` creates these diagnostics without resampling or changing ranks/holds. It is an audit utility, not a production dependency. Hashes bind the review to exact saved outputs. Production runs must retain current source/rights and whole-polygon screens before any eligible output is called live.
