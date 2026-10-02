# SCC seafloor-character enrichment — October 2, 2026

This batch applies the already reviewed USGS Point Estero and Morro Bay
categorical seafloor products to thirteen overlapping SCC native depth products.
It changes two existing bindings only. Source bathymetry rows, class definitions,
native resolution, depth limits, terrain thresholds and spatial exclusions are
unchanged. No new measured geography is claimed.

## Evidence and interpretation

- [USGS Point Estero metadata](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9ZSTUK1/0f75d175cc2046f38c45b6ac26a9be92/SeafloorCharacter_OffshorePointEstero_metadata.xml)
  and [Morro Bay metadata](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9HEZNRO/99111880d0194352899672cd4d7690ac/SeafloorCharacter_OffshoreMorroBay_metadata.xml)
  are pinned in the existing rules. Original archives and every actual class
  code were rechecked. The source-only receipt is
  `research/receipts/seafloor-scc-character-bindings-review.json`.
- Point Estero binds SCC07 2 m and SCC08–11 2 m/5 m. SCC07 5 m has no measured
  class overlap and remains unbound. Morro binds SCC12–15 2 m. The existing
  USGS depth bindings remain intact; the larger supported Morro footprint is
  selected for SCC15 rather than assigning two ambiguous class sources.
- Classes stay 1: interpreted soft/flat sediment; 2: coarse sediment or flat
  bedrock; 3: interpreted rugose boulder/bedrock. Missing classes remain unknown.
  Class 2 is not automatically a boulder field. Actual 2 m raster spacing does
  not establish 2 m classification accuracy. Point Estero's 2 m/5 m processing
  mosaic and scalar 10 m metadata conflict remain explicit.
- Bathymetry and interpretation are conservatively treated as the same evidence
  family. Exact survey-line equivalence remains unresolved. Video-supervised
  accuracy tables reuse training observations and cannot become independent
  per-pixel confidence or fish-presence probability. The repeated Point Estero
  and Morro accuracy tables are retained as a metadata limitation.
- Fresh Point Estero metadata reads failed with HTTP 522 twice; archive HEAD
  returned 403. The review uses checksum-pinned original metadata and archives,
  not a claim of a successful fresh download. Original USGS data are public
  domain; acknowledge USGS, CSUMB SFML and UC Center for Integrated Spatial
  Research, and preserve the not-for-navigation notice.

## Current-parent before/after proof

Normal processing, without `--force`, was run before and after the two binding
changes. All 6,414 selected depth cells are exactly identical. Selected valid
measured support stays **281.124714913 km²** and Tier 1 reference-cell area stays
**294.113125 km²**.

| Reach | Physical before → after | Passing before → after | Passing habitat km² before → after |
| --- | ---: | ---: | ---: |
| morro-bay-r04 | 287 → 56 | 278 → 56 | 2.315563 → 0.798399 |
| morro-bay-r03 | 333 → 215 | 305 → 203 | 5.417559 → 4.110427 |
| morro-bay-r05 | 339 → 130 | 318 → 128 | 3.373913 → 0.888706 |
| morro-bay-r02 | 803 → 801 | 756 → 754 | 10.912568 → 10.885796 |
| morro-bay-r06 | 415 → 415 | 383 → 383 | 8.931421 → 8.931421 |
| morro-bay-r01 | 461 → 460 | 378 → 377 | 4.850465 → 4.846300 |
| cambria-san-simeon-r02 | 296 → 290 | 225 → 220 | 3.548911 → 3.452826 |

Totals: **2,934 → 2,367 physical candidates**, **2,643 → 2,121 spatially
passing polygons**, and **39.350400741 → 33.913874881 km²** passing habitat.
The decrease removes or reshapes terrain candidates using the existing
sediment-exclusion rule. It is a quality correction, not lost measured coverage.
246 candidates remain held; no passing polygon touches a CDFW MPA, NOAA federal
exclusion or security exclusion.

Physical candidates with some interpreted substrate support increase from
416 to 2,088; those with at least half of their sampled patch classified increase
from 416 to 2,084. These are patch counts, not independent confidence estimates
or newly surveyed areas. Independent-confirmation counts remain zero.

## Validation and handoff

Original source and metadata hashes, preserved definitions, unambiguous binding
resolution and identical selected depth cells were checked. Existing numeric
substrate, tiled habitat, ordinary habitat, screen, manifest and source-rights
checks passed: **54 tests / 3,598 subtests**. Platform regeneration, repository
and web checks passed. Independent review and current-head CI precede merge.

The ledger remains production-workflow owned. Local polygons are not a live
publication claim. The existing locked workflow must rebuild the affected
regional archives and verify their current public manifests and byte ranges.
PGE South native coverage is a separate batch; its producer rough/smooth
terrain derivatives are not these USGS rock/sediment classes.
