# Local charter and commercial AIS follow-up — 2026-09-21

## What was actually obtained

**No verified sportfishing-charter lingering grounds.** Expanded the NOAA sample from eight to eleven complete national daily files, including a continuous June 24–30, 2026 block. In total: 106,892,412 national broadcasts scanned, 37,202 retained in the Avila–Cambria region, and 65 distinct reported MMSIs. None matches the researched local sportfishing fleet names. These are selected dates and incomplete reception, not proof that boats do not use AIS or do not fish a place. The broad existing Morro Bay outline is an editorial interpretation of a regional catch-report label; it must not be called an AIS footprint or precise charter ground.

**Yes, public commercial AIS-derived fishing effort.** Obtained Global Fishing Watch's official v3 2024 archive from its openly accessible [Zenodo deposit](https://doi.org/10.5281/zenodo.14982712), without an account or payment. Selected July and September 2024 to cover two local summer/autumn months. Verified HTTP byte ranges avoid a 3.35 GB full download; every extracted daily member is decompressed and CRC/size checked before retaining the local subset. The manifest records individual source members, timestamps, counts and hashes. Metadata gives the exact final completed coverage.

The layer contains original **0.01° cells**, about 0.9 km east–west by 1.1 km north–south here. It uses GFW modeled *apparent fishing hours*, not vessel presence hours or arbitrary low speed. These are commercial activity context, not precise stops, reef footprints, catch reports, current boats, or sportfishing-charter identity. No target species is inferred from the gear class.

## Published layer

- `dist/data/commercial-ais-effort.geojson` and its metadata back an **opt-in “Commercial AIS · 2024” overlay**, separate from habitat and charter reports. No habitat/bite score bonus.
- Show the period, gear category, original grid resolution, number of distinct activity days, apparent hours, low recreational-targeting confidence, and direct GFW source link in each card. Do not call the regions "verified hotspots." The two unspecified-gear records must not be renamed crab or rockfish grounds.
- These cells are outside the nearshore ≤200-foot habitat qualification; **depth remains unknown**. They are not “fish here” pins. Harbor radii and all eight current CDFW MPA polygons were tested; an intersecting whole cell is withheld rather than clipped and falsely reallocating effort. Reapply current restrictions at app load.
- Selection: ≥1 apparent fishing hour total per original cell, with ≥15 apparent minutes on each of at least two distinct dates. This is a transparent display filter, not a validated hotspot detector. Adjacent retained cells of equal gear type may be exactly unioned; gaps are never filled.
- `dist/data/ais-evidence.json` records the expanded eleven-date audit. The broad Morro Bay outline is removed from the map.

## Commercial raw-AIS leads that were withheld

A NOAA broadcast name, KAI HONI II, is consistent with the commercial boat described by its seafood supplier in a [2022 first-party profile](https://gethookedseafood.com/blogs/fishermen-pages/california-king-salmon-david-and-garret-rose-trawler). The data show repeated offshore slow travel June 26–29. No 500 m cell meets a three-date/15-min-per-date dwell gate. One 1 km cell does, but native surveyed portions are about 231–245 ft MLLW with incomplete survey coverage. Identity is only a name/type/local-presence match; a successful independent MMSI-to-owner registry lookup was not obtained. It is **not published** as a charter stop or a depth-qualified recreational target. This is why speed alone should not be treated as fishing proof.

## Access and source limits

- [NOAA/MarineCadastre official access documentation](https://github.com/ocm-marinecadastre/ais-vessel-traffic) supplies the current archive URLs and licensing. The inspected 2026 daily index still ends June 30, 2026. A file's modification date is not a vessel broadcast date.
- Previous NOAA PMEL ERDDAP inventory data retained at most one position per vessel/day; it cannot reconstruct lingering. Monthly GeoParquet name inventories were obtained earlier, but geographic scans did not finish; no new monthly-track result is claimed here.
- [GFW data documentation](https://globalfishingwatch.org/dataset-and-code-fishing-effort/) describes fleet coverage and classes. Read the saved `README-fleet-v3.txt` and `README-known-issues-v3.txt`: 2024 classification is provisional, reception is uneven, multi-gear assignment can be wrong, and slow transits can be false positives. Zero rows is no detected activity in that source, not no fishing.
- USCG [VIVS](https://www.navcen.uscg.gov/ais-vivs-home) form reads succeeded, but query results did not provide usable independent identity verification. No verified registry hit is claimed.
- [USCG AIS requirements](https://www.navcen.uscg.gov/ais-requirements) depend on vessel class/length and other criteria; smaller operators need not all appear in an AIS sample. Do not infer that any named operator is violating requirements or intentionally hiding because its name was absent.

## Redistribution and refresh

**GFW files are separately licensed CC BY-NC 4.0**, verified in the official Zenodo metadata and GFW README. Non-commercial redistribution and adaptation are permitted with attribution, license/source links, and a changes notice. Preserve these terms for the dataset instead of applying the app's personal-use license to it. Credit: “© Global Fishing Watch. 2025. Global AIS-based Apparent Fishing Effort Dataset, Version 3.0. https://doi.org/10.5281/zenodo.14982712. Regional extraction and aggregation by SkipperCast.” Commercial use needs separate permission from GFW. NOAA's inspected official repository provides CC0 products; raw trajectories are not published in the repository.

A daily app job may check upstream metadata/index changes, but these historical products cannot turn into a live fleet feed through repeated downloads. Store version/checksum/source period and skip unchanged archives. Rebuild only when a source version/date coverage changes. The public GFW API's current-data service ordinarily requires free registration/token; none was requested or created in this research. A larger NOAA date sample or an operator-authorized track log could improve charter evidence, with identity validation and trip/gap analysis before any stop claim.

