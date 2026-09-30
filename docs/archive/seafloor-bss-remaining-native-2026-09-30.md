# Remaining BSS native shelf grids — September 30, 2026

Seven original CSUMB SFML survey archives supply fourteen distinct native bathymetry grids. This source batch fills gaps between the previously qualified blocks. It qualifies original depth; measured reach expansion and current whole-polygon publication screening are separate stages.

Original metadata identifies September–November 2011 acquisitions, NAVD88 Geoid09 depth, 2 m CUBE surfaces for approximately 0–85 m, and 5 m surfaces for approximately 80–250 m. Both native resolutions are retained. The 91.44 m ceiling is nominal in the source datum; horizontal/vertical sounding accuracy and interpolation masks remain unknown. Depth grids are not rendered hillshades or explicitly interpolated display products. Shared acquisition is not independent evidence.

The [NOAA acquisition archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/) lists the original products. The [CSUMB producer policy](https://csumb.edu/undersea/sfml-data-library/) permits public noncommercial use with acknowledgment and requires express for-profit permission. Every qualified row binds a dated producer review to its original SHA, retains attribution and prohibits navigation use. No commercial permission is inferred.

| Block | Native grids | Nominal shallow source pixels: 2 m / 5 m | Original archive |
| --- | --- | --- | --- |
| BSS_Block04 | 2 m / 5 m | 3817786 / 222479 | [Download](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block04/multibeam/data/version2/products/BSS_Block04_additional_products.tar.gz) |
| BSS_Block05 | 2 m / 5 m | 2341080 / 77221 | [Download](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block05/multibeam/data/version2/products/BSS_Block05_additional_products.tar.gz) |
| BSS_Block06 | 2 m / 5 m | 2868986 / 65594 | [Download](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block06/multibeam/data/version2/products/BSS_Block06_additional_products.tar.gz) |
| BSS_Block07 | 2 m / 5 m | 2675258 / 39908 | [Download](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block07/multibeam/data/version2/products/BSS_Block07_additional_products.tar.gz) |
| BSS_Block09 | 2 m / 5 m | 1314976 / 27168 | [Download](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block09/multibeam/data/version2/products/BSS_Block09_additional_products.tar.gz) |
| BSS_Block10 | 2 m / 5 m | 2748607 / 73320 | [Download](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block10/multibeam/data/version2/products/BSS_Block10_additional_products.tar.gz) |
| BSS_Block11 | 2 m / 5 m | 2984386 / 48637 | [Download](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block11/multibeam/data/version2/products/BSS_Block11_additional_products.tar.gz) |

Exact native geographic envelopes, acquisition-date metadata, grid members, archive hashes and sizes are in `catalog/csumb-bss-remaining-native-sources.json`. Schema-qualified normalized native-window receipts are in `catalog/surveys.json`. Pixel counts are original-source counts, never additive/deduplicated reach area. Source overlap is resolved by the shared native-resolution selection rules; finer cells do not manufacture precision in 5 m data.

All fourteen grids were opened through the existing bounded ArcInfo adapter and normalized without resampling. Existing source rows remain unchanged. This PR does not edit the public ledger, change ranking thresholds, add MPA clearances or claim new live fishing locations. The next deterministic batch reruns the intersecting saved reaches, retains previous caches, reports selected-valid footprint/ranked-candidate deltas and screens before publication.

## Deterministic local measurement proof

The ordinary runner processed four existing reaches after source qualification. Previous caches are preserved privately. No scoring threshold or numerical implementation changed. These results are local evidence, not a public ledger or live-location claim.

| Reach | Selected valid km²: before → after | Physical candidates: before → after | Screened candidates: before → after |
| --- | --- | --- | --- |
| south-big-sur-san-simeon-r01 | 0.727169 → 35.825691 | 19 → 352 | 9 → 313 |
| big-sur-coast-r06 | 6.246063 → 22.423225 | 95 → 259 | 81 → 237 |
| big-sur-coast-r05 | 2.634517 → 23.739810 | 19 → 201 | 13 → 162 |
| south-big-sur-san-simeon-r02 | 53.116324 → 53.117068 | 592 → 592 | 543 → 543 |

The combined selected valid footprint increases by 72.381721136 km². Physical candidate count increases by 679; the net screened-candidate change is 609. These are net changes after shared source selection, not sums of overlapping input grids. Morphological rankings may change as source support changes. Spatial restrictions apply to complete candidate polygons; incomplete metric support remains held.

Validation: full Python suite: 1,046 passed, 14 allowed private-cache skips, 3,823 subtests passed. Manifest, original-byte/normalized-raster verification, repository and website checks pass. Local PMTiles encoding awaits the pinned tippecanoe executable; production uses the existing pinned Linux tool. Publication and live/export verification remain required.
