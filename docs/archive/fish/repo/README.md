> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `README.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../README.md) and [front-end design § 15](../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Fish

**SLOFishReport.com** is the first county in a shared coastal fishing-report platform. The current rebuild is a Cloudflare-ready, mobile-oriented map workspace with **boat, shore and spearfishing** filters, target species, linked day/hour selection, conditions charts and recorded buoy history. One codebase serves reviewed county domains; Monterey and Santa Barbara are future regional configurations, not copied repositories.

## What is implemented

- **Coast / Conditions / History views:** MapLibre + PMTiles, server-rendered briefing, three representative SLO areas, target species and nominal habitat-depth filters, a supported three-calendar-day outlook, and a shared hourly clock. Charts preserve gaps, source units and independent scales; mobile charts scroll instead of compressing labels.
- **Forecast and observation:** NWS wind/gust/seas/period/air/rain/sky-cover and alerts; NOAA NDBC 46215/46028 observations; Port San Luis 9412110 tide curve/events in MLLW; five native three-hour CDIP nearshore model sites; official county beach-health status. Health sample dates remain unknown in the public feed.
- **Temperature / boundaries:** NASA JPL MUR daily surface analysis, native 0.01° sampled at 0.02° with masks and uncertainty; CDFW DS582 protected-area polygons with verified query completeness and CC BY 4.0 attribution. Analysis is neither bottom temperature nor a future buoy forecast.
- **Actual current fields:** public SkipperCast NOAA WCOFS native ~4 km surface forecast frames and available HF-radar observation frames. Selected times use native frames and explicit age gates; unavailable wet cells remain blank. Arrows follow actual toward bearings; their motion is illustrative. These products do **not** resolve an exact reef, dive entry, Morro Bay bar or entrance current.
- **Actual cloud imagery / sharp context:** acquired NOAA GOES longwave imagery with an observed-frame loop, dated USGS/USDA NAIP aerial imagery, and a NOAA CUSP shoreline extract. Natural Earth remains an overview land mask. No satellite image is projected into tomorrow or converted to dive visibility.
- **Native bottom imagery:** three reviewed original USGS bathymetry grids, nominal 0–300 ft only, transparent gaps, nearest display sampling and source-qualified relief. The 12,044,691-byte PNG PMTiles archive has 1,987 populated tiles at zooms 11–16. The same-origin `/api/bathymetry/tiles` verifies its SHA and supplies bounded 206 ranges; actual local Worker/production-reader decoding was verified.
- **Reef habitat:** a separately rebuilt government-only SkipperCast release in Fish private R2, with 2,868 complete habitat polygons and 45 exact curated details. Lingcod, reef-rockfish, gopher-rockfish and cabezon selectors use ordinal physical fit, separate from terrain grade, depth color and catch probability. Expiring ready/version/rights screens gate habitat transport independently of static physical bathymetry.
- **Shore species:** actual NOAA ESI 2006 sandy-shore runs for Hearst Memorial Beach, Morro Strand, Cayucos, Pismo and Oceano, factual California Coastal Commission public-approach references, surfperch/halibut guidance and dated conditions windows. Whole shoreline/approach geometry, current source/rule/access clocks and applicable hazards govern priority. This does not measure today's troughs, breakers or fish.
- **Recorded history:** all 65 advertised annual standard-met archives from the two station catalogs were collected: 46215, 2004–2025; 46028, 1983–2025. Recent 45-day hourly means and recorded seasonal p10/median/p90 distributions retain per-variable counts and missing coverage. This is descriptive history, not a standard climatology or calibrated fishing/forecast model.
- **Reviewed local catch facts:** a small linked factual-count binding from the public SkipperCast Morro/Avila feed, under its pinned September 21 facts-only source review. The boat briefing and dated trip modal show eligible reports from the past seven local calendar days (up to eight cards). Original boat/port/trip/angler/species labels and reported/retained/released distinctions remain intact; independent original-publisher receipt clocks must be fresh. No publisher prose/photos, licensed bulk operator feed, catch coordinates, AIS locations, probability or shore/dive outcome is imported. See [reviewed catch evidence](research/reviewed-catch-binding.md).
- **Parallel SkipperCast upgrades:** reviewed currents/catches flow through existing collectors; complete government habitat releases can be promoted atomically from private R2 without another website build. Species semantics, original clocks, rights and whole-set compatibility remain gated. Open maps detect and recover new release IDs. See [update commands and activation status](docs/SKIPPERCAST-UPDATES.md).
- **Operations code:** bounded collectors, publication gates that retain useful prior data with original clocks, hourly Cron handler, D1 report/run/auxiliary adapters, optional R2 normalized archives, strict hostname registry, RSS and information pages. Email signup remains disabled.

Coverage is partial and source-specific. The habitat/bottom footprint mainly spans Point Buchon/Port San Luis through Morro Bay/Point Estero; region labels do not establish all-county coverage. Source retrieval times never replace original measurement, analysis, issue or validity times. Unknown underwater visibility stays unknown. Conditions windows are low-confidence exposure screening, **not bite predictions or trip/dive clearance**. Moon and tide are not automatic catch multipliers; tide stage does not identify slack horizontal current. Commercial harvest recommendations require a separate rules review.

**Cloud deployment:** the Worker, dedicated D1 database and private government habitat release are deployed and verified at the Cloudflare preview hostname. Custom-domain activation and automatic Git publishing are pending; see [production publishing](docs/PRODUCTION.md). **Not yet established:** witnessed unattended scheduled refreshes, email delivery, automated social publication or sponsorship sales. Actual desktop/mobile visual and interaction checks now pass for the reviewed local build; see [browser acceptance](research/visual-acceptance-2026-10-03.json). No formal accessibility certification or controlled performance benchmark is claimed. Bundled data is dated and ages normally. Licensed bulk catch-feed reuse, charter AIS identity/activity classification, exact entrance currents, measured dive visibility and a complete current legal engine remain future work. The reviewed small catch-fact display does not establish those capabilities.

## Local commands

Node 22+:

```sh
npm ci
npm run refresh
npm run refresh:ocean -- --county=slo
npm run refresh:history -- --max-files=80 --concurrency=2
npm run dev
```

Open `http://localhost:8787`. `refresh` collects the SLO report and `refresh:ocean` collects currents/GOES. Use `npm run refresh:history:recent` for routine buoy updates: it preserves every annual baseline, catalog and original annual receipt. `refresh:history` is the initial backfill command and includes `--all-years`, reusing SHA-verified annual checkpoints. All publish **local assets**, not cloud data or a running schedule. Failed attempts are recorded separately and do not replace a useful public snapshot with an outage; retained layers keep their own clocks.

```sh
npm run check
npm test
npm run build
```

CI uses Node 22 and runs these checks/build. Scientific raster tests require the existing GIS Python separately:

```sh
../skippercast-seafloor-rollout/.venv/bin/python tests/bathymetry.test.py
```

Reviewed imports are separate jobs, not hourly web requests:

```sh
node scripts/import-shore-habitat.mjs
node scripts/import-government-habitat.mjs artifacts/government-engine --stage-local
../skippercast-seafloor-rollout/.venv/bin/python scripts/import-bathymetry.py --skipper-root ../skippercast-seafloor-rollout
```

The government habitat job requires an owned, reviewed engine with complete government-scoped outputs for both regions; see [private R2 setup and acceptance](docs/GOVERNMENT-HABITAT.md). The original `import-skippercast.mjs` remains a separately gated upstream importer and must not replace this release with an unreviewed mixed archive. These jobs require source/version review. The shore importer does not independently renew its explicitly dated legal review; do not extend rule/access expiry because an endpoint still responds. The bottom importer reads approved SkipperCast caches without editing that project. Raw history receipts, GIS intermediates and failed-attempt receipts are ignored local evidence, not public assets.

## Cloudflare prerequisites

1. Use the intended account and provision a **dedicated Fish D1 database**, bound as `DB` in `wrangler.jsonc` with its actual ID.
2. Apply **both** `migrations/0001_initial.sql` (reports, run audits, subscription/delivery scaffolding) and `migrations/0002_auxiliary.sql` (history/ocean snapshots): `npm run db:local` for local testing; `npm run db:remote` only against the configured Fish cloud database.
3. Set the exact preview hostname as `PREVIEW_HOST`; unknown hosts intentionally return 404. Configure Namecheap → Cloudflare DNS and the approved custom domain.
4. Provision the dedicated private `fish-habitat` R2 bucket as `HABITAT` and explicitly stage the reviewed government release with SHA metadata and complete byte read-back. Local R2 objects are not uploaded by deployment; without them habitat stays unavailable. See [the storage contract](docs/GOVERNMENT-HABITAT.md). Optionally bind another dedicated R2 bucket as `EVIDENCE`. Run `npm run deploy` only with authorized account access; witness two distinct scheduled runs before claiming ongoing collection.

The configured Cron is hourly at UTC minute 17. Without `DB`, it skips collection and APIs serve dated bundled assets. With provisioned storage, report and auxiliary jobs store current snapshots; recent-history refresh preserves the reviewed annual reference instead of downloading decades hourly. The optional evidence R2 binding does not establish a raw-receipt upload pipeline; habitat uses its separate required private binding. No public refresh/admin endpoint is exposed. Subscription tables and env variables do not activate confirmation, unsubscribe or sending.

## Design, data and rollout documents

| Document | Contents |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) / [Launch](docs/LAUNCH.md) | Source contracts, refresh/storage paths, county replication and launch gates |
| [Product design research](docs/PRODUCT-DESIGN-RESEARCH.md) | Primary application references and actual NOAA/USGS source probes |
| [Independent review](docs/INDEPENDENT-REVIEW.md) | Concrete source-reviewed corrections, transport evidence and actual browser acceptance |
| [History pipeline](docs/HISTORY-PIPELINE.md) | Actual backfill, checkpoint commands, gaps and seasonal aggregation |
| [Species opportunity](docs/SPECIES-OPPORTUNITY.md) | Shore guidance, exact source geometry, access/rule/condition gates |
| [Bottom overlay](docs/BATHYMETRY-OVERLAY.md) | Reviewed native sources, masks/datum, PNG rendering and verified HTTP transport |
| [SkipperCast bridge](docs/SKIPPERCAST-BRIDGE.md) / [Government release](docs/GOVERNMENT-HABITAT.md) | Original source evidence, reviewed government rebuild, private R2 setup and live archive gates |
| [Source registry](research/source-registry.md) / [Spatial review](research/spatial-review.md) | Authoritative products, masks, precision, rights and uncertainty |
| [Reviewed catch binding](research/reviewed-catch-binding.md) / [Charter intelligence](docs/CHARTER-INTELLIGENCE.md) | Implemented linked trip facts and the separate planned licensed bulk/AIS pipeline |
| [Distribution research](research/domain-distribution.md) | Domain acquisition, email, Instagram, iMessage and sponsor strategy |

County rollout uses `src/counties.ts`, approved hostname mappings and `src/experience-config.ts` regional assets. New counties need independently reviewed source coverage, rights, stations, species/method/access/legal context and data/visual acceptance. Never reuse SLO data as another county's evidence.

Keep the report free, with future clearly labeled sponsorship independent of grades, habitat priority and editorial selection. Email requires opt-in/preferences/unsubscribe provisioning; weekly Instagram starts as approved editorial drafts. No general iMessage broadcast is promised. Asset/source notices are in [NOTICE.md](NOTICE.md) and `public/licenses/`; private repository status grants no application-code license.
