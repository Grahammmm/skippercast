# Point Conception substrate evidence — October 1, 2026

Join the original USGS Point Conception seafloor-character grid to seven
reviewed H11952/H11953 depth products. This refines habitat selection over
existing measured depth; it creates **no new bathymetric coverage**. The native
2 m categorical grid is interpreted substrate from bathymetry, backscatter and
supervised training, not fish observations or direct sampling at every pixel.

## Original evidence and limits

- [Original USGS archive](https://cmgds.marine.usgs.gov/data/csmp/OffshorePointConception/data/SeafloorCharacter_OffshorePointConception.zip): 1,232,378 bytes; SHA-256 `c5faa08e5162cf09401fa07976333487626a0e2d8732b4e112255b3a8c5733fb`.
- [Original metadata](https://cmgds.marine.usgs.gov/data/csmp/OffshorePointConception/metadata/SeafloorCharacter_OffshorePointConception_metadata.xml): current retrieval October 2 UTC, metadata date May 7, 2026. It declares USGS public-domain/CC0 redistribution, attribution and no navigation use. Preserve the metadata and credit USGS.
- Actual raster bounds: W -120.568412, S 34.388644, E -120.371431, N 34.542708. The native valid mask controls support; the XML eastern envelope is materially broader and is not used as measured coverage.
- Native GeoTIFF declares WGS84 / UTM10N (EPSG:32610). An XML geodetic subsection instead says NAD83. Keep this conflict explicit; 2 m spacing is not a positional-accuracy guarantee. No raster classification confusion matrix or per-cell uncertainty was verified.
- Acquisition/year descriptions conflict. The character layer was classified in 2016 and published in 2017; no single acquisition year is assigned. Category depth zones are not measured depth or the 300 ft cutoff. Existing NOAA native MLLW measurements continue to determine the nominal depth band.
- Treat the character/depth pairing as shared sonar lineage, with `independent_confirmation=false`. Exact pixel-to-survey-line correspondence remains unresolved. [Parent bathymetry metadata](https://cmgds.marine.usgs.gov/data/csmp/OffshorePointConception/metadata/Bathymetry_OffshorePointConception_metadata.xml) describes the sonar/lidar compilation; the compilation is not newly admitted as native depth.

The public, source-only review receipt is
[seafloor-conception-substrate-review.json](../../research/receipts/seafloor-conception-substrate-review.json).
Native raster/VAT counts agree for all 19 codes and 32,277,243 valid cells.
Only the existing nearest-neighbor categorical adapter is used.

## Class semantics

| Original family | Meaning | Existing normalized behavior |
| --- | --- | --- |
| 1 | Fine/medium smooth sediment | Soft; excluded from reef extraction |
| 2 | Mixed sediment, coarse material and rock | Hard-flat/mixed; not proof of rugose rock |
| 3 | Rugose boulder/bedrock | Hard-rugose evidence |
| 4 | Sediment/shell hash in scour depressions | Conservatively treated as excluded sediment |
| 5 | Hard anthropogenic material | Hard-flat; never relabeled natural rugose reef |
| NoData | Unknown | Unknown, not sand |

All slope/depth variants are explicitly enumerated. Existing output retains a
generic habitat-candidate label, not a natural-reef claim. The binding retains
the original anthropogenic description; the current feature summary does not
separately quantify artificial material. Terrain thresholds and 1–3 species
suitability rules are unchanged. Adding this reviewed binding activates its
seven depth products even though the categorical catalog row remains `candidate`;
this is an intentional reviewed binding, not an implicit bathymetry promotion.

## Overlap and local processing

Exact polygon intersections of native masks give 57.198 km² of classified
substrate over 57.400 km² of unioned nominal shallow NOAA depth in the source
envelope. Approximately 4.974 km² is interpreted rugose rock, 2.438 km² mixed,
49.646 km² fine sediment, 0.068 km² coarse/scour sediment and 0.072 km²
anthropogenic. These are evidence-overlap areas, not added survey coverage,
selected habitat or legal clearance. H11953 8 m is unbound because actual
shallow overlap is zero.

| Reach | Selected valid km² (unchanged) | Physical before → after | Screened before → after | Screened habitat km² before → after |
| --- | ---: | ---: | ---: | ---: |
| Conception r06 | 56.900909 | 947 → 947 | 452 → 452 | 2.838982 → 2.838982 |
| Conception r07 | 56.089513 | 270 → 225 | 219 → 187 | 3.662677 → 3.238532 |
| Conception r08 | 41.780301 | 309 → 264 | 172 → 149 | 2.848408 → 2.530394 |

This removes 90 physical candidates and 55 screened candidates, with a
0.742158 km² reduction in screened habitat. Fewer areas reflects better
substrate discrimination, not a relaxed threshold or data failure. The 788
passing areas have zero full-polygon intersections or boundary touches with
the current CDFW, NOAA and security exclusions. Of them, 12 in r07 and all
149 in r08 have some classified substrate support; none in r06 do. No feature
claims independent confirmation. The 648 remaining candidates stay held.

## Validation and publication

The existing physical pipeline processed the three reaches using checked local
source bytes. GIS habitat/tile and inventory checks pass: 34 tests and 3,413
subtests. Platform regeneration and repository/web checks pass. The new original
receipt is included in the inventory's existing receipt-alias convention.
Private before/after and overlap verification are retained under
`var/seafloor/overnight-conception-substrate/`.

Full current-head CI and independent review precede protected merge. Production
must recompute affected source/rule identities, screen complete polygons and
verify ready public manifests and PMTiles range reads before any live claim.
MPA screening does not grant season, gear, launch-notice or current-access
permission. No terrain or rights gate is weakened to increase map density.
