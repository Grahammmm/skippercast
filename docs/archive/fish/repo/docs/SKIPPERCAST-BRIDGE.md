> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/SKIPPERCAST-BRIDGE.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# SkipperCast habitat bridge

**Parallel upgrades:** the current integration supports data publication independent of the website code. Compatible feeds use existing collectors; completed government habitat builds use immutable private consumer assets and a conditional release switch. See [the update pipeline](SKIPPERCAST-UPDATES.md) for commands, semantic-review boundaries and unconfigured cloud activation.

Imported and verified October 1, 2026. Owner authorized reuse of SkipperCast data. Original producer terms still apply to a sponsored Fish site. This import does not modify SkipperCast, rebuild surveys, infer catches, or grant fishing permission.

**Operational update, October 3, 01:40 UTC:** Fish now serves a separately rebuilt government-only release from its own private local R2 binding. All 12 reaches were processed with original USGS inputs selected before terrain, precedence and calibration; both regions passed full original geometry, source-rights, hash and screening checks. The reviewed engine capability merged through [SkipperCast PR 209](https://github.com/Grahammmm/skippercast/pull/209). The actual Fish Worker returns exact 206 ranges for both regions and withdraws both together when the selected control is held. The release has 2,868 polygons, 12,453 coverage cells and 45 exact curated details. Cloud R2 publication remains unverified; actual local browser rendering and interactions are documented in [browser acceptance](../research/visual-acceptance-2026-10-03.json). See [government release setup and evidence](GOVERNMENT-HABITAT.md). The original mutable upstream integration and prior 43-detail import below are historical evidence; the old mixed release remains ineligible for the sponsored site.

## Current evidence replaces older atlas holds

The reviewed SkipperCast main commit is `b4f4eff2f6f04895331430cbad58abc31342f759`. Its current [seafloor publication contract](https://github.com/Grahammmm/skippercast/blob/b4f4eff2f6f04895331430cbad58abc31342f759/docs/seafloor.md) separates physical habitat mapping from navigation-grade datum qualification. The older regional atlas's research-only fishing targets do not disable the newer, screened survey-derived habitat product.

Live ready publications inspected:

| Region | Whole screened habitat polygons | Reference/coverage cells | Publication | Screen expiry |
| --- | ---: | ---: | --- | --- |
| Morro Bay | 2,821 | 10,101 | Oct 1, 2026, 17:20:27 UTC | Nov 3, 2026, 00:00 UTC |
| Cambria–San Simeon | 47 | 2,352 | Oct 1, 2026, 17:20:00 UTC | Nov 3, 2026, 00:00 UTC |

Those names are pipeline regions. The actual admissible habitat footprint spans approximately 35.131–35.541° N, predominantly Point Buchon/Port San Luis through Morro Bay and Point Estero. **This is partial SLO County coverage, not surveyed habitat throughout San Simeon or Pismo.** Exact imported bounds are stored per region.

All 2,868 canonical features passed the upstream whole-polygon permanent spatial screen and their depth/substrate contributors matched the pinned catalog's reviewed `public-domain-us-gov` terms. The six contributors are USGS Offshore Morro Bay, Point Estero and Point Buchon bathymetry and paired seafloor-character releases. Source URLs, native transport checksums, acquisition years, resolution profiles, datum limitations and rights links are retained in `public/data/skippercast-manifest.json`.

The nearby South Big Sur–San Simeon live publication contains 603 features and credits original CSUMB Seafloor Mapping Lab data. That bundle is excluded: its producer policy requires express permission for for-profit use. NOAA hosting does not convert its rights to public domain. See the current [producer-rights implementation](https://github.com/Grahammmm/skippercast/blob/b4f4eff2f6f04895331430cbad58abc31342f759/src/skippercast/seafloor/rights.py) and [CSUMB policy](https://csumb.edu/undersea/sfml-data-library/).

## Delivered files

- `scripts/import-skippercast.mjs`: reusable bounded importer. Pins main; downloads published exports; checks compressed/decoded size and SHA-256; validates whole-polygon screen, contributor rights and species fields; verifies the complete PMTiles archive and range transport; checks the manifest again before writing data.
- `public/data/skippercast-manifest.json`: UI/proxy contract, source records, proof, current screening expiry and per-region archive metadata.
- `public/data/skippercast-species.json`: four physical habitat planning profiles, original agency citations, score meanings and explicit unsupported targets.
- `public/data/skippercast-habitat.geojson`: 43 complementary detail polygons, 1,978,797 bytes. Every selected original coordinate, hole and polygon part is retained. There is no new simplification, rounding, clipping, centroid replacement or invented fishing point. The disclosed subset uses spatial bins and combined lingcod/reef-rockfish fit/terrain order within a 1.98 MB budget; it does not represent complete habitat coverage. Use the complete PMTiles layer for full display.
- `tests/import-skippercast.test.mjs`: five offline checks for contributor rights including substrate, missing/expired screens, required species scores, unknown datum retention and exact geometry/holes within the byte budget.

Run from Fish:

```sh
node scripts/import-skippercast.mjs
node --test tests/import-skippercast.test.mjs
```

Raw downloaded reviews are in ignored `artifacts/skippercast-import-inputs/`; no large archive needs to be committed. The importer does not copy raw restricted data or old atlas coordinates.

## Map integration contract

The manifest has top-level default-region fields plus `regions[]` for additional approved archives:

```text
ready, status, regionId, builtAt, expiresAt, importedAt, sourceCommit
sourceManifestUrl, archiveUrl, archiveETag, archiveSha256, archiveBytes
featureCount, coverageCount, layerNames, bounds
license, commercialUse, commercialArchivePermitted, rightsReview
allowedSpeciesScores[], propertySchema, sources[], proxyContract
geojsonUrl, geojsonFeatureCount, geojsonBytes, geojsonSha256, selectionNotice
```

Use MapLibre + PMTiles through the Fish same-origin proxy, with source layers `habitat` and `cells`. The full Morro archive is 15,285,168 bytes; its SHA-256 is `c426a9bce40eea6d0af465dbc8b6e21e7f44c836dd1405d0ba5e24e2361f55d6`. The Cambria archive is separately pinned in `regions[1]`.

PMTiles scalar filters are:

| Species filter | Tile field | Interpretation |
| --- | --- | --- |
| Lingcod | `fit_lingcod` | General rocky-reef depth planning proxy transferred from agency species guidance |
| Reef rockfish | `fit_rockfish_reef` | Copper-rockfish Central California habitat/depth observation proxy; other rockfish differ |
| Gopher rockfish | `fit_gopher_rockfish` | Adult nearshore reef/kelp depth planning band |
| Cabezon | `fit_cabezon_shallow_reef` | Broad hard-bottom occurrence envelope; cannot rank shallow versus deep preference |

Scores 1–3 describe physical planning fit, with 3 strongest. A/B/C terrain grade is a distinct ruggedness assessment. Neither is a catch probability or fish abundance score. Halibut, surfperch, salmon and tuna have no imported reef fit: leave these scores unavailable instead of treating rocky habitat as a universal fishing target.

Useful popup fields: `id`, `terrain_grade`, `terrain_score`, `depth_min_ft`, `depth_max_ft`, `depth_basis`, `vertical_datum`, `resolution_m`, `source_year`, `metric_support_fraction`, and species fit scalars. `source_ids`, `source_rights`, `terrain`, `fit`, `substrate`, `screen` and other nested evidence are JSON **strings in MVT**; parse them only with bounded/error-aware handling. They are objects/arrays in the upstream canonical GeoJSON. Paired USGS depth and character are the same survey evidence family.

Keep these labels visible in the layer legend/popup: **Survey-derived habitat candidate; fish presence unverified. Nominal depth; verify on your sounder.** The published source may have unknown vertical datum or interpolation masks, which remain unknown. Grid spacing is not rock size or positioning accuracy.

`cells` is a separate coverage/context overlay. Tier 0 cells belong to the provisional NOAA BlueTopo-derived planning reference; tier 1 cells have qualifying native survey support (at least 25% of a 250 m planning cell). Do not color every cell as measured terrain, draw them as depth contours, or imply that all cell area was surveyed. The present PMTiles product does **not** supply a continuous bathymetry raster, native depth contours, or a local surf/dive model. Those require a separate reviewed display export; old 132-target bottom views are not silently promoted by this bridge.

## Mutable archive safeguards

The exact public manifest URL is:

`https://skippercast.g4651.workers.dev/feeds/tiles/seafloor/manifest-morro-bay.json`

The public archive URL is:

`https://skippercast.g4651.workers.dev/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles`

Both are supported by SkipperCast's [documented Cloudflare feeds](https://github.com/Grahammmm/skippercast/blob/b4f4eff2f6f04895331430cbad58abc31342f759/docs/cloudflare.md). The URL is a **mutable alias**, not an immutable archive version. The importer verified full bytes and captured the strong Morro ETag `"42414130ae880e6ba8b4705a4ac9fcfd"`.

`Range: bytes=0-126` with that `If-Match` returned HTTP 206, 127 matching header bytes and `Content-Range: bytes 0-126/15285168`. The response exposes ETag, range, length and Accept-Ranges with CORS `*`. A deliberately wrong `If-Match` returned HTTP **304 with an empty body**, rather than conventional 412. Therefore the Fish proxy must require 206 for ranged requests and exact ETag equality; accepting any nominally successful/cache status would be unsafe.

For every archive request: allow only configured safe source URLs, verify a current ready source manifest, require its archive hash to equal the imported approved hash, enforce screening expiry, send the pinned `If-Match`, and reject wrong status/ETag/range/length. Do not serve retained bytes after expiry or a changed publication. The importer must review every contributor again before updating its approved hash. The upstream Worker also gates the archive against its current screen and R2 checksum metadata. Recheck locally at least once per minute while a habitat layer is visible, and withhold stale geometry.

The same source guards apply to Cambria's manifest/archive URLs in `regions[1]`. A government-only current manifest does not authorize an arbitrary future mixed-rights archive.

## Remaining limits

Permanent spatial screening excludes whole candidate polygons overlapping reviewed MPAs, federal conservation areas and security restrictions. It does not authorize a trip, open a species season, resolve gear rules, or certify current harbor/shore/dive conditions. The displayed map must continue linking current official rules and retaining the method-specific report limitations.

A successful daily upstream refresh may change the archive hash even without geographic expansion. An importer refresh is a rights/byte check, not additional surveying. Report current manifest state and actual polygon/count deltas separately. New counties require exact producer rights, coverage and screening review rather than copying SLO's approved archive list.
