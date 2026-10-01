# Original Avila–Pismo and southern Arguello shelf batch

The NOAA-hosted original PGE Avila Bay archive (938,065,756 bytes) supplies
BlockI/BlockJ native 2 m grids. SCC25 (173,430,719 bytes) supplies a native
2 m southern Arguello shelf grid. These are measured producer-gridded surfaces,
not rendered hillshade, slope, interpolated regional DEM or invented fill.
Exact members, native footprints, mask counts and archive hashes are in
`catalog/csumb-morro-avila-native-sources.json`.

[NOAA PGE Avila Bay](https://www.ngdc.noaa.gov/ships/ventresca/PGE_AvilaBay_mb.html)
and [SCC25](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block25_mb.html)
original product links were observed on official listings and fetched with the
existing checked downloader. Native bounded inspection and standard ingestion
preserve 2 m spacing; spacing is not sounding accuracy. No per-cell uncertainty
or interpolation mask is supplied; unknown remains unknown.

## Metadata and geographic corrections

* BlockI's embedded FGDC metadata names May 2–5, May 31 and June 1–9, 2009;
  NAVD88/Geoid03. Its footprint is 35.11362–35.17798 N.
* BlockJ's native 2 m XML contains only an Esri metadata creation timestamp.
  Survey date and datum remain **unknown** in its qualified row. A companion
  BlockJ 5 m-all product states 2009/NAVD88 Geoid03; that is recorded as a lead,
  not silently assigned to this native grid. Footprint: 35.03882–35.11788 N.
* SCC25 processing metadata specifies NAVD88/Geoid09. Its abstract names
  September 30, October 1–3 and 13–14, 2010, but structured calendar dates repeat
  adjacent Block24 dates. Both are retained, with an explicit conflict; no
  day-level chronology claim. Its native footprint is 34.66362–34.71409 N.
* NOAA **CC_BlockA02** actually contains **CC_Block02 near Pacifica** at
  37.63145–37.70181 N. It is not the similarly named 2009 Morro–Avila CC_BlkA2.
  The archive was inspected but excluded from this goal/catalog promotion.
  This corrects the prior batch's unverified acquisition lead, not its results.

The BlockI/BlockJ grids inspected here are shallower than about 35 m; they
fill real coastal gaps but do not establish full 200–300 ft coverage.
Companion products and compiled USGS surfaces sharing these acquisitions are
not independent evidence. Substrate is not inferred solely from terrain.

## Measured before and after

| Reach | Selected valid native km² | Physical candidates |
| --- | ---: | ---: |
| point-arguello-conception-r05 | 2.143088 → 28.122020 | 14 → 767 |
| point-arguello-conception-r04 | 66.881588 → 69.353978 | 104 → 100 |
| morro-bay-r08 | 19.712855 → 27.123197 | 477 → 426 |
| morro-bay-r09 | 0.000000 → 31.704285 | 0 → 196 |
| point-arguello-conception-r01 | 37.988570 → 39.202650 | 846 → 915 |
| morro-bay-r10 | 0.000000 → 35.428616 | 0 → 1042 |

Across these six affected reaches: selected valid coverage
**126.726100387 → 230.934744728 km² (+104.208644341)**; planning Tier1
**131.163125 → 240.476875 km² (+109.313750000)**; physical candidates
**1,441 → 3,446 (+2,005 net)**. Morro r09/r10 had no prior measured coverage
and now contain 31.704285477/35.428615683 km² and 196/1,042 candidates.
Necessary adjacent reach updates retain finest/newest per-cell selection;
changed outlines or overlapping acquisitions are not independent new grounds.

All six runs completed without incomplete terrain. Of 3,446 physical polygons,
3,266 have supported lingcod/reef-rockfish fit values and 180 remain unknown.
The existing species-specific 1–3 scale is unchanged; **3 is strongest**.
Candidate masks, depth limits and non-exportability were checked. Exact rank
counts, source ownership, before/after and input hashes are in
`docs/archive/morro-avila-private-proof-2026-10-01.json`; original geometry,
archives and cache receipts remain private. These are candidate habitat, not
fish-presence claims or whole-coast completion.

## Release and validation

**Zero new public or exportable locations.** All three sources are explicitly
physical-only. Reviewed producer use rights, hash-checked retained-physics
transfer, current whole-polygon MPA/security screens, regional publication and
actual live-map/export verification remain separate release requirements.
[CSUMB producer policy](https://csumb.edu/undersea/sfml-data-library/) does not
become federal public-domain permission merely because NOAA hosts the data.
All prior 413 source rows remain unchanged; the catalog now has 416 records.

1,050 Python tests passed, 14 allowlisted skips, 3,929 subtests; strict skip
report, platform regeneration, repository/web and diff checks passed. App and
scientific thresholds are unchanged. This source batch depends on #166; reconcile
onto fresh main, independent review and exact-head hosted checks before merge.

Next: qualify native remaining Morro–Avila blocks by actual footprint, inspect
whether original outer-band products support 200–300 ft without treating a
combined display grid as uniformly fine data, and investigate BlockJ's missing
native metadata. SCC26–28 are original acquisition leads for remaining southern
Arguello coverage. The full Monterey–Point Conception goal remains active.
