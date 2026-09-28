# Changelog

## Unreleased

- Seafloor habitat: reusable original-substrate joins, rough-bottom extraction, A/B/C terrain grades and source-cited 1–3 species planning fits. Three Morro Bay reaches now have private review outputs, including a real survey seam; legal screening still gates publication and export.

- Seafloor coverage: original-survey footprints now qualify planning cells and produce mask-aware terrain summaries for the first Morro Bay reaches. The ledger separates classified-cell area from actual selected survey area; habitat publication remains pending.

- Seafloor ingestion: reusable USGS GeoTIFF and regular NOAA BAG adapters, hash-verified private caching and native-resolution drafts. Two survey windows are qualified for processing; habitat coverage totals remain unchanged.

- Seafloor pipeline: reproducible Central Coast reach/grid baseline and a coverage-ledger CLI. All new tiers remain unprocessed until original surveys are ingested; the reference band is explicitly provisional. See [seafloor pipeline](docs/seafloor.md).
- Map engine test pages (`/map-test.html`, `/map-test-leaflet.html`) compare MapLibre with PMTiles vector tiles against today's Leaflet map on one layer. See [map engine test](docs/map-engine-test.md).
- Published feeds (live conditions, daily data, forecast tiles) now load through the site's `/feeds/` route, ready to be served from Cloudflare R2; the site can deploy to its own Cloudflare account. See [Cloudflare](docs/cloudflare.md).
- Boat profile: enter your boat (optionally looked up with AI and confirmed) and comfort and drift-control ratings scale to its length, weight, hull and layout. See [boat profile](docs/boat-profile.md).
- Search plans for five Central Coast preview regions now include their surveyed habitat footprints (575 in total); they had been built before those inputs existed.
- The live conditions feed is monitored hourly and reports when it stops refreshing.

## 0.3.0 — 2026-09-20

- Mobile-first map with Map, Spots, Forecast, and Guide navigation; no long page scroll to reach the map or weather.
- Compact spot cards expand into accessible detail sheets with persistent map and GPX actions; wide screens retain a docked list and detail panel.
- Collapsible filters, a reset action, 44-pixel map-marker hit areas, safe-area spacing, and readable mobile forecast comparisons.
- Direct single-spot GPX downloads for mobile and embedded browsers, with reproducible generation and checks for all 132 files.

## 0.2.1 — 2026-09-20

- Visible A/B/C terrain-grade definitions and practical context for points, reef outlines, and drift alignments.
- Per-target explanations of all four grading factors, weighted points, and capped contributions.
- Dated AIS evidence summary with eight sampled archive dates, source URLs, counts, hashes, and explicit lack of verified local sportfishing-charter tracks.

## 0.2.0 — 2026-09-20

- Public browser map with target search, habitat grades, depth filters, reef outlines, and optional drift alignments.
- Notes and GPX export for each selected target, plus the complete reviewed atlas downloads.
- On-demand ECMWF and NOAA wind/wave comparisons at three offshore samples, with missing-data, disagreement, coverage, and freshness notices.
- Model metadata, NWS advisory lookup, source attribution, and links to current rules and entrance information.
- Browser forecast and GPX tests, asset consistency checks, and vendored Leaflet with its license.

The app displays evidence for review; automated trip qualification and alert delivery remain separate integrations.

## 0.1.0 — 2026-09-20

Initial public research release:

- Portable forecast collector and alert lifecycle logic, with explicit operator-review boundaries.
- Public USGS-derived atlas: 132 habitat candidates, 107 outlines, 31 optional drift alignments.
- Reproducible GPX, GeoJSON, and offline notes from the included public data.
- Personal-use source license and separate third-party source notices.
- Offline tests, CI, contributor guide, and onboarding documentation.

The existing personal forecast deployment and full private research atlas are not migrated or replaced by this release. This initial research release did not include a hosted application.
