# Changelog

## Unreleased

- Seafloor: process the remaining two qualified Monterey native intersections; add 27.72 km² of measured coverage and 62 ranked habitat candidates, held privately until spatial screening.

- Seafloor: qualify the original Monterey 2 m producer product and paired substrate; add three measured physical reaches with 672 ranked habitat candidates, held privately until Monterey spatial screening.

- Seafloor: process oversized native habitat windows in bounded tiles without downsampling; join habitat across tile edges and preserve reach-wide thresholds. Morro Bay r01 has measured coverage and private ranked candidates pending its spatial screen.

- Add a daily seafloor rollout planner, reusable physical-stage cache, explicit survey promotion and per-reach failure recovery; keep legal screening as the final publication stage.

- Map startup ([P4-05], first slice): with production's live MPA check, Morro Bay's map downloads 3.6 MB of JSON at startup instead of 7.3 MB (`scripts/measure_startup.mjs --stub-mpa`). The uncertainty feed and the daily fishing evidence now load when Conditions opens, and the map reads only the regulation checks (and, when the live MPA query fails, the MPA record) of the daily feed through the new `/api/daily?region=&part=` endpoint (per-IP limited, saved in offline packs), falling back to the full feed. The map, atlas and protected-area screen load in parallel behind a loading skeleton, and a bottom-left **Legend** chip explains the visible layers and marker meanings. CI budgets the committed static startup JSON (`scripts/startup-budget.json`).
- Operations: the research inventory workflow keeps its carried state after a degraded run, and NOAA BAG HEAD checks retry `429 Too Many Requests` (honouring `Retry-After`, four workers) instead of reporting a rate-limited rescan as degraded.
- Operations ([P4-11]): cookie-less client telemetry. The app counts a fixed set of funnel steps (port selected, map viewed, forecast viewed, spot saved, offline pack saved, installed) and reports uncaught errors with the page build and last request id, batched through `navigator.sendBeacon` to `POST /api/telemetry` and written to Workers Analytics Engine when `ENABLE_ANALYTICS` is on. Nothing is sent under Do Not Track or Global Privacy Control; no ids, cookies, IPs or query strings. The daily Operations report shows the funnel and top client errors ([docs/engineering/telemetry.md](docs/engineering/telemetry.md)).
- Testing ([P4-09a]): browser tests with Playwright and axe (`pnpm e2e`, CI job `e2e`) run eight flows at phone and laptop size against the built site under `wrangler dev`; serious or critical accessibility violations fail the build.
- Front end ([P4-01b]): TypeScript and Preact foundation. A signals store (`web/state.ts`) owns region, coast, view, target and hour in the URL: opening the site with a saved port, choosing the first port, and choosing a port in the region already shown no longer reload the page (the forecast hour and target are kept), and `?hour=` links open that forecast hour. The header outlook badge, the meteogram card and the offline freshness banner are Preact components; `pnpm typecheck` covers `web/`.
- Build ([P4-01a]): Vite 8 bundles the client (`vite.config.mjs`); first load of the map drops from 84 script and stylesheet requests (242 KB gzip) to 22 (169 KB). Hashed files live in `/assets/` with a year's immutable caching; pages, `/sw.js`, vendored libraries (with SRI), data and the offline precache keep their contract. `scripts/fingerprint.mjs` is retired and `check_client.mjs` checks the Vite manifest.
- Operations: optional Workers Analytics Engine metrics (repository variable `ENABLE_ANALYTICS=true`): one data point per request (route pattern, status, latency, cache), LLM call, queue batch and cron run, with no personal data; a daily **Operations report** workflow summarises the last 24 hours. A failed cron step now fails the cron invocation.
- Operations: saved-trip checks can run on Cloudflare Queues (repository variable `ENABLE_QUEUES=true`): the Worker cron queues one message per owner after each live publication, with retries and a dead-letter queue, removing the 2,500-trip ceiling. Off by default; `/api/jobs/check` stays as the manual trigger and fallback.
- Development: Python tests run under pytest in layers (`tests/unit`, `tests/contract`, `tests/integration`, `tests/gis`; claims pins in `research/tests`) with `gis`/`claims`/`network` markers, JUnit and slowest-test summaries in CI, and the full survey-science run fails on any skip outside the private-cache allowlist.
- Docs: the README is rewritten as a short product page with a screenshot, coverage list and three-command start; datum and withdrawn-claim details now live in `docs/product/data-confidence.md`. The architecture doc no longer describes ChatGPT Sites hosting.
- Docs: `docs/product/data-confidence.md` is the single reference for grades, coverage states, freshness, depth datums and withdrawn claims.
- Docs: 39 dated rollout, source-request and research logs moved to `docs/archive/` (indexed in `docs/archive/README.md`); `docs/README.md` now links the engineering, operations and legal documents.
- Worker in TypeScript with Hono ([P3-01]): `server/` is strict TypeScript (`pnpm typecheck` in CI) routed by Hono (`server/app.ts`, `server/routes/`, `server/middleware/`). Routes, statuses, headers and cookies are unchanged; every response now carries `X-Request-Id`, JSON errors repeat it as `request_id`, and `HEAD` is answered like `GET` without a body.
- Operations: the daily data job now runs and publishes product feeds only; its NOAA BAG/ENC and USGS catalog research inventories moved to `research-daily.yml` (artifacts only), the monthly research workflows are renamed `research-substrate.yml` / `research-fish-survey.yml`, and 22 research-only catalog pins moved to `research/catalog/`.
- Smaller deploy: 206 audit receipts (3.1 MB) moved from `dist/data/` to `research/receipts/` with a sha256 manifest; the app never loaded them, and they are no longer uploaded with the site.
- Repository: the ~240 dated audit, screening, triage, discovery and one-off builder scripts moved from `scripts/` to `research/scripts/` (history kept); `scripts/` now holds only the product tools that workflows, the build and deploy run.
- Docs: architecture decision records 0002 (own NOAA/ECMWF forecasts), 0003 (R2 as feed system of record), 0005 (front-end direction, proposed) and 0006 (passkey accounts; billing proposed).
- Trip alerts use your saved boat: the form's wind, gust and sea limits start from it, the boat is saved with the trip (D1 migration 0003 adds four nullable columns), and the evening-before and morning-of checks judge wind chop against that boat and name it in the alert.
- First run: harbor, then boat (four quick choices, exact boat or skip), then tomorrow's one-word answer for that harbor and boat, with the reasoning and caveats behind a "Why?" tap.
- Seafloor habitat layer (Map options → Map layers): screened Morro Bay habitat candidates from original surveys, colored by terrain grade or by lingcod / rockfish-reef physical fit, with optional survey coverage cells. Shown only while the screening publication is current; the service worker never caches it.
- Accounts: create a SkipperCast account and sign in with a passkey (Face ID, Touch ID or device PIN; no password or email) from Guide → Your account. Saved trip alerts, comfort feedback and AI boat lookup use it; you can add or remove passkeys, sign out, export your records and delete the account.
- Contracts: feeds and generated region files are validated against `schemas/` before they are written (`ContractError`, `SKIPPERCAST_VALIDATE=off` emergency switch), and region validation uses the region schema plus cross-reference checks.
- Operations: `refresh_regions.py --run-manifest` records each regional refresh (per-region and per-source status, input/output sha256, exit status) at `var/runs/refresh-<kind>/<run_id>.json`; `skippercast.report` renders a region table and `publish_r2.py var/runs runs` uploads manifests to R2 `runs/`.
- Pipeline: every source request in `src/` goes through one HTTP client (`skippercast.http.Session`: host allowlist, DNS-pinned public addresses, bounded bodies, jittered retries honouring Retry-After, receipts, optional ETag cache); the `/usr/bin/curl` TLS fallbacks are replaced by the optional `tls` extra (`truststore`).
- Offline: a service worker now keeps the app shell and the latest public data, and "Save for offline" (Guide → Offline trip pack) stores a region's data, rules, forecast and NOAA chart tiles; saved data shows an "Offline — showing data saved …" banner. Install prompt and a one-time iOS Add to Home Screen hint.
- Fixed: every Cloudflare deploy since the gated workflow was rolled back by a false smoke-test failure (curl | grep -q under pipefail).
- Operations: the `conditions` and `data` feed branches, like `forecasts`, are now one parentless commit replaced on each publish (with a lease against concurrent publishers), and each deploy sets R2 lifecycle rules (run manifests 7 days, history backstops after the pipeline's own 90/30-day retention).
- Security: the live workflow is split into `refresh` (contents write), `notify` (OIDC identity for saved-trip checks, runs beside it and cannot fail a cycle) and `next` (dispatch only) jobs, and data workflows prefer an R2-only `R2_PUBLISH_TOKEN` over the deploy token.
- Tomorrow card on the Conditions tab: for the next three days, go / marginal / no-go per two-hour window for your saved boat, the one factor that limits the day in words, GFS–ECMWF agreement as confidence and the latest comfortable back-at-dock time. Caveats sit behind a "Why?" tap.
- Performance and abuse protection: the model API, forecast/intelligence/habitat endpoints and R2 feeds are edge-cached (`X-SC-Cache`), and `/api/om` (60/min) and `/feeds/` (300/min) are rate-limited per IP on Cloudflare.
- Security: every Worker response now carries HSTS, an enumerated Content-Security-Policy (moved from the page meta tag), frame-ancestors 'none', Permissions-Policy and COOP; vendored scripts and styles are pinned with SRI.
- Operations: data retention now runs on the Cloudflare cron as well as the trip-check job; `request_limits.expires_at` is indexed (migration 0001).
- AI boat lookup: a global daily cap (`BOAT_LOOKUP_GLOBAL_DAILY_LIMIT`, default 500), a `BOAT_LOOKUP_ENABLED` kill switch, and one usage log line per lookup with billed tokens and searches.
- Worker hardening: request errors are typed (only validation failures return their message), `/api/events/ack` validates the event id, and public `/api/health` no longer discloses which bindings and secrets exist.
- Development: shared `skippercast.util` time and file-hash helpers replace duplicated copies; CI runs `ruff check src` for syntax errors and undefined names.
- Development: `pip install -e ".[survey]"` (and `ocean`, `sst`, `publish`, `test`, `seafloor`, `dev`) installs pinned optional tools; `SKIPPERCAST_ROOT` points installed code at a checkout.
- Operations: R2 upload failures now fail the live and daily jobs, each `latest.json` records `published_at` and `run_id`, publishes are verified on the public `/feeds/` route, and the freshness monitor checks that route first.
- Operations: one region's refresh error no longer blocks the others; it is recorded as `status: failed` in the regional index, and the job fails only for the default region or a majority.
- Contracts: JSON Schemas in `schemas/` for regions, catalogs, jurisdictions, the daily, live and intelligence feeds, region indexes, coverage and forecast tiles, with `python -m skippercast validate` and CI validation of every committed file.
- Operations: structured JSON logging (`skippercast.log`), run manifests (`skippercast.runs`) and `python -m skippercast.report` step summaries; the forecast tile builder logs structured records and can write a run manifest.
- Conditions: surface currents and drift guides now use NOAA WCOFS samples from the regional pipeline (about 4 km, first 72 hours) instead of the browser's Open-Meteo request; the hourly sea-temperature weather layer is removed until an own source exists, and the legacy monitor requests SkipperCast's /api/om.
- Forecast range & uncertainty: the 31-member GEFS wind ensemble is now read directly from NOAA's GEFS open data on AWS once per cycle instead of Open-Meteo's non-commercial ensemble API.
- Web app: installable icons (PNG, maskable, Apple touch), faster startup via module preloading, a friendly retry card when the app fails to start, one combined notice when several optional layers fail, and neutral boat wording instead of the owner's boat name.

- Internal: removed duplicate and unused client files (including the unused 2.3 MB og.png), renamed -vN modules to canonical names, and made check_web.py reject -vN names in dist/.
- Internal: design tokens (colour, type, spacing, radius, elevation, z-scale, motion; light and inactive dark) in dist/tokens.css with a CI contrast check; screens are unchanged.

- Legal: a data-rights register records, for every source and runtime service, whether a paid product may use it; a CI gate fails if a new asset depends on a source not cleared for commercial use. See [data-rights register](docs/legal/data-rights-register.md).
- Draft terms of use, privacy notice and licences pages (pending review by counsel), linked from About, the Guide and Sources.
- Contributing: outside contributors must sign off commits (Developer Certificate of Origin), checked on every pull request; licensing options are laid out for the owner in [ADR 0004](docs/engineering/adr/0004-licensing.md).
- Governance: issue templates, CODEOWNERS, weekly Dependabot updates, a security policy, a production dependency audit in CI, and CI actions pinned to commit SHAs.
- CI: scheduled data and survey workflows run third-party actions pinned to commit SHAs.
- Operations: runbooks for a stale feed, an R2 outage, a D1 restore and secret rotation, plus an incident-response process; the stale-feed issue now links its runbook. See [incident response](docs/operations/incident-response.md).
- Conditions: a 7-day meteogram (wind and gust, seas, tide, hourly score band, model disagreement, now marker, provisional hatch after 72 h) opens the view; tap, drag or arrow keys pick the hour shared with the scrubber.
- Rules card: a first row now shows Open/Closed (or Check rules), bag, size, depth where the reviewed rules state it, the verified date and one official link; the full detail stays below.
- Security: the Cloudflare Worker no longer trusts ChatGPT identity headers; private features there return 401 until SkipperCast has its own sign-in.
- Fixed: trip-alert push notifications could never be enabled because the build renamed the service worker away from `/sw.js`.
- Seafloor runner setup now installs the schema validator and checks the manifest before processing or publishing.

- Tuna search overlays use the regional offshore footprint, reject uniform water and stale frames, support uncertainty-screened satellite fronts, and explain species-aware 1–3 search priorities separately from boat comfort.
- Boat profile: enter your boat (optionally looked up with AI and confirmed) and comfort and drift-control ratings scale to its length, weight, hull and layout. See [boat profile](docs/boat-profile.md).
- Search plans for five Central Coast preview regions now include their surveyed habitat footprints (575 in total); they had been built before those inputs existed.
- Map engine test pages (`/map-test.html`, `/map-test-leaflet.html`) compare MapLibre with PMTiles vector tiles against today's Leaflet map on one layer. See [map engine test](docs/archive/map-engine-test.md).

### Internal

- Release process: version tags publish GitHub Releases whose notes are the matching CHANGELOG section; see [release process](docs/operations/release-process.md).
- Seafloor runner setup now installs the schema validator and checks the manifest before processing or publishing.
- Seafloor publication: regional PMTiles, private survey recovery and a scheduled main-only workflow with checksum, restriction-expiry and public HTTP Range checks. The first Morro Bay archive contains 1,006 screened candidates; live acceptance follows a successful post-merge dispatch.
- Seafloor spatial screening: current CDFW, NOAA federal-area and reviewed security boundaries now qualify whole habitat polygons for tier 2. Missing, stale, changed or overlapping evidence stays held; publication follows separately.
- Seafloor habitat: reusable original-substrate joins, rough-bottom extraction, A/B/C terrain grades and source-cited 1–3 species planning fits. Three Morro Bay reaches now have private review outputs, including a real survey seam; legal screening still gates publication and export.
- Seafloor coverage: original-survey footprints now qualify planning cells and produce mask-aware terrain summaries for the first Morro Bay reaches. The ledger separates classified-cell area from actual selected survey area; habitat publication remains pending.
- Seafloor ingestion: reusable USGS GeoTIFF and regular NOAA BAG adapters, hash-verified private caching and native-resolution drafts. Two survey windows are qualified for processing; habitat coverage totals remain unchanged.
- Seafloor pipeline: reproducible Central Coast reach/grid baseline and a coverage-ledger CLI. All new tiers remain unprocessed until original surveys are ingested; the reference band is explicitly provisional. See [seafloor pipeline](docs/seafloor.md).
- Published feeds (live conditions, daily data, forecast tiles) now load through the site's `/feeds/` route, ready to be served from Cloudflare R2; the site can deploy to its own Cloudflare account. See [Cloudflare](docs/cloudflare.md).
- The live conditions feed is monitored hourly and reports when it stops refreshing.
- Hosting: SkipperCast runs only on its own Cloudflare Worker; ChatGPT Sites packaging, its origin and its identity headers are gone, `CUSTOM_DOMAINS` attaches skippercast.com and www.skippercast.com as custom domains (www redirects to the apex), and workers.dev stays on as staging.

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
