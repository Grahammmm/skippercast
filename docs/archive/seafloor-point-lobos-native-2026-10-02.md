# Point Lobos native survey qualification — October 2, 2026

This batch adds the original 2 m CSUMB Point Lobos bathymetry to the measured
habitat pipeline. It processes Monterey–Point Sur r02 with the existing source
priority, nominal depth band, terrain rules and whole-polygon spatial screen.
No threshold, reference ownership, class binding or exclusion geometry changes.

## Original evidence

- [NOAA original cruise report](https://www.ngdc.noaa.gov/ships/macginitie/PointLobos_mb.html)
  and [original product archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/macginitie/PointLobos/multibeam/data/version2/products/PointLobos_additional_products.tar.gz).
- Exact native member: `PointLobos/PtLobos_2mbathy_hill_slope.zip/ArcViewGrids/pl_2mbathy`.
  The archive is 267,635,311 bytes; SHA-256
  `6ecad4d5f58cb459fa2b45abd46c386e095dcbc4817d736b703305b7bf220384`.
- The native grid has 3,216,643 valid depth pixels and 2,180,800 nominal shallow
  pixels. Normalized COG SHA-256 is
  `558878a051d62be6b3d2b9cea7f00611fe1a45d25f94f538f75a865e256717bf`.
- Acquisition dates span 2000, 2001, 2005 and 2006. The catalog year is the latest
  acquisition, not a claim that every pixel was surveyed in 2006. Native depth
  processing describes MLLW while another derivative describes NAVD88; the
  unresolved datum remains `unknown`. No datum conversion is invented.
- Producer metadata describes approximately ±2 m horizontal and ±0.20 m
  vertical accuracy, varying with depth and without a specified confidence level.
  These are producer statements, not a navigation certification. Gridding used
  shoal-biased 1 m XYZ and a 2 m average grid; no per-cell interpolation mask or
  uncertainty raster is supplied. Unknown masks stay unknown.
- [CSUMB source terms](https://csumb.edu/undersea/sfml-data-library/) remain
  credited noncommercial use, not for navigation, with express permission
  required for for-profit use. NOAA distribution does not make the source
  federal public-domain data. The public source-only review is
  `research/receipts/seafloor-point-lobos-native-review.json`.

## Reproduced before/after measurements

The baseline was run on the current parent catalog, including Yankee Point and
the previously merged Monterey sources. Both sides use the same fresh screen.
The existing pipeline was invoked normally, without `--force`.

| Monterey–Point Sur r02 measure | Before | After | Net change |
| --- | ---: | ---: | ---: |
| Selected valid measured support, km² | 9.384424435 | 13.403177239 | +4.018752804 |
| Tier 1 reference-cell area, km² | 9.785625 | 14.018125 | +4.232500 |
| Physical habitat candidates | 154 | 245 | +91 |
| Spatially passing candidates | 12 | 21 | +9 |
| Held candidates | 142 | 224 | +82 |
| Spatially passing habitat, km² | 0.148995285 | 0.135691459 | −0.013303826 |

The final 21 polygons comprise 2 terrain-A, 18 terrain-B and 1 terrain-C
candidate. Species suitability retains the existing 1–3 rules. Ten passing
polygons use the Point Lobos source and retain its unknown datum. Source
replacement and reach-wide terrain thresholds can shrink total habitat area
while increasing the number of smaller passing patches; neither metric is
forced to increase.

The source-level shallow union gap of 4.225095 km² and native-cell-center proxy
of 4.179688 km² are diagnostic comparisons, not the pipeline coverage gain.
The selected-support gain above is the reported mapping result. No additional
independent acquisition count or fish-presence claim is made.

Of the 224 held polygons, 222 overlap a CDFW MPA; metric and contract holds can
overlap those reasons. Held geometry remains private. Every passing polygon
was checked against the complete current CDFW, NOAA and security geometries:
zero intersections, valid nominal 25–300 ft habitat depths and fit values 1–3.
The screen snapshot is from October 2 at 06:59:08 UTC. Season, gear, dynamic
closures and current conditions remain trip-time checks.

## Validation and continuation

Pinned original/normalized files and all run output hashes were reopened and
checked. Source-rights, manifest, whole-polygon screen and tiled-habitat tests
passed: 43 tests and 3,605 subtests. Platform regeneration, repository and web
validation passed. Independent review and required CI remain before merge.

The committed ledger remains workflow-owned. This local result is not live
publication. The existing production workflow must process the merged catalog,
publish a ready regional manifest and pass public PMTiles byte-range verification.
The next useful batch is the separately qualified PGE South source family or
the reviewed SCC substrate bindings; neither is counted here.
