# Original nested ArcInfo adapter proof — September 30, 2026

## Reproducible blocker and fix

The original [NOAA BigCreek archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/BigCreek/multibeam/data/version2/products/BigCreek_additional_products.tar.gz) is available (HTTP 200, 364,945,509 bytes, SHA256 `5e688dae2eca47844cf9727f70d212b0492e0d28e0aa5b261acbd8911dd2ada1`). Its native bathymetry grids are inside three original ZIP members, not direct tar directories. The former shared adapter could not select them, and the fetcher excluded this reviewed NOAA ship archive. Existing research records were consequently unusable by the scheduled mapping runner.

The shared `arcgrid` adapter now selects exactly `ZIP_MEMBER/GRID_DIRECTORY` inside an original gzip tar. It supports one nested ZIP, spools the selected container to bounded scratch, validates all tar and ZIP entries, applies aggregate member/uncompressed-byte limits before extracting grid files, rejects traversal/absolute paths, duplicates, links and encryption, and preserves the original archive as the recovery object. Cached extracted files still require exact checksums. Only the reviewed NOAA `ventresca` archive prefix is added; no arbitrary hosts or data mirrors are enabled.

The original [publisher record](https://www.ngdc.noaa.gov/ships/ventresca/BigCreek_mb.html) and embedded grid metadata identify the six 2 m/5 m products inspected in `bigcreek-nested-native-proof-2026-09-30.json`. Source dates are May/August 2010; native depth is NAVD88 Geoid09, not charted MLLW. Uncertainty and per-cell interpolation masks remain unknown. Shared resolutions are not independent surveys. Native footprints span 36.00996–36.12722 N, and the actual reference intersection is measured separately below. No hillshade, slope, 5 m all-depth composite or rendered map was ingested.

## Native and mapping proof

The synthetic AIG test reproduces the previous direct-container result through the new nested path: exact native values, mask, grid, normalized raster identity and depth counts. Malicious containers fail before grid extraction. Thirteen ArcInfo tests pass, including four new nested/fetch cases. Eight already-qualified original ArcInfo products (six BSS and the two USGS 1998 grids) were reingested: every reviewed normalized COG SHA and scientific raster identity is unchanged. The adapter key pin is updated only after this real parity proof. Future source normalization cache keys change once with the adapter revision; extraction and original-download caches remain reusable.

The ordinary private runner processed two previously empty Big Sur reference intersections using six hash-checked draft products:

| Reach | Selected valid km² | Tier 1 planning-cell km² | Physical candidates | Lingcod fit 2 / 3 / unknown | Rockfish fit 1 / 2 / 3 / unknown |
| --- | --- | --- | --- | --- | --- |
| big-sur-coast-r03 | 1.972780706 | 2.183125 | 28 | 21 / 1 / 6 | 0 / 22 / 0 / 6 |
| big-sur-coast-r04 | 15.061897453 | 16.37375 | 138 | 97 / 19 / 22 | 12 / 87 / 17 / 22 |

Combined: 17.034678159 km² selected-valid original depth and 166 physical candidates. Of these, 138 have supported lingcod/reef-rockfish ranks; 28 retain unknown ranks because support is incomplete. One reported maximum is 300.000008 feet, within one Float32 ULP of the nominal 91.44 m threshold; no navigation-grade or exact chart-depth claim is made. The depth mask and ranking rules are unchanged.

All candidates remain private and export/publication prohibited. This adapter PR grants no producer rights, changes no source status in the committed catalog, adds no legal scope and changes no public ledger. Separate source qualification and whole-polygon MPA/security screening are still required. The earlier empty run before draft qualification is retained only as a private diagnostic and is not counted as surveyed area or a genuine data gap.

The [CSUMB producer policy](https://csumb.edu/undersea/sfml-data-library/) remains the applicable source-rights reference; NOAA hosting is not a public-domain grant. The proposed skill documents exact nested-member selection and the source-review/private-processing/release sequence.

Validation: full Python suite after the reviewed adapter key update: 1,050 passed, 14 allowed private-cache skips, 3,775 subtests passed. Native source and private processing receipts are saved under `var/seafloor/bigcreek-nested-native/`; private source/candidate geometry and the generated ledger are excluded. Repository, web, platform regeneration, 431 Node tests, copy checks, type checks and production client build pass. Local temporary client builds on macOS required a canonical TMPDIR rather than the /var symlink; the same unchanged tests then pass, with no app/test weakening. Exact-head hosted checks and independent review remain required before merge. No additional fishing locations are claimed live.
