# Web app

The app is a mobile-first map workspace written in TypeScript and Preact. It has two pages: a landing page at `/` and the map app at `/map`. The map app has five views (Coast, Conditions, History, Fleet and Reports), a brief beside or under the map, a layer rail, and a time dock. This page describes what the code does today (package version 0.8). The older Leaflet "classic" shell is removed.

## Run it locally

```bash
pnpm install --frozen-lockfile && pnpm build
node scripts/wrangler_config.mjs 00000000-0000-0000-0000-000000000000 skippercast-feeds wrangler.local.jsonc
npx --yes wrangler@4.142.0 dev --config wrangler.local.jsonc
```

Open `http://localhost:8787/`. `pnpm build` (`scripts/build-worker.mjs`, `vite.config.mjs`) builds the pages in `dist/*.html` with Vite into `dist/client` (hashed scripts and styles in `assets/`, one stylesheet per page, pages renamed with the build id, static data copied unchanged) and bundles the Worker into `dist/server`; see [Cloudflare](cloudflare.md). `scripts/check_client.mjs` checks the output, including that the heavy map and terrain libraries stay out of the first-paint imports. `wrangler dev` serves both, including the Worker's `/feeds/` and `/api/` routes. On an iPad, use the deployed HTTPS site.

## Pages and routes

- `/` serves `dist/landing.html` (entry `web/landing/main.tsx`; components in `web/landing/`). With an area parameter (`region`, `spot`, `place` and the other keys in `server/routes/assets.ts` `AREA_PARAMS`) it opens the map app instead, so shared links keep working.
- `/map` serves `dist/app.html` (entry `web/app/main.tsx`).
- `/coast` moves to `/map?presentation=3d`.
- Other pages in `dist/*.html` are static: sources, licenses, privacy, terms, the species-research page, `coast-readable.html`, `commercial-ais.html`, and the advisor and admin pages (`chat.html`, `my-data.html`, `upload.html`, `admin.html`).
- The deploy's smoke test opens `/`, `/map` and `/coast` (`scripts/smoke_test.sh`).

## State and the URL

`region`, `coast`, `view`, `target`, `hour`, `profile`, `day`, `layers`, `area` and `base` in the address are the source of truth (`URL_KEYS` in `web/state.ts`, which also lists the History and coast keys). Choosing a port, changing a view, picking a target or moving the time dock updates the address without a reload, and a shared link opens the same state. Region changes never reload the page in the map app (`configureStore({v2: true})` in `web/app/main.tsx`); `navigate()` in `web/state.ts` is the one place that decides. `?view=` names a masthead view (`coast`, `conditions`, `history`, `fleet`, `reports`); any other value is read as a map position `lat,lng,zoom`.

## Code layout

| Path | What it holds |
| --- | --- |
| `dist/*.html`, `dist/landing.html`, `dist/app.html` | Page shells that Vite builds; no hand-written bundles or hashes |
| `web/landing/` | The landing page: port input, profile pills, a readout of current readings |
| `web/app/` | The map app shell: `App.tsx`, `Masthead.tsx`, `CommandBar.tsx`, `Desktop.tsx` (wide layout), `Mobile.tsx` (under 1,024 px: map plus a three-detent bottom sheet and a four-tab nav), `LayerRail.tsx`, `Legend.tsx`, `TimeDock.tsx`, `MapStage.tsx`, `MarkCard.tsx`, `LimitsPanel.tsx`, `FirstRun.tsx`, `AccountMenu.tsx`, `Trip.tsx` |
| `web/app/views/` | `Conditions.tsx`, `History.tsx`, `Fleet.tsx`, `Reports.tsx` |
| `web/brief/` | The brief: `model.ts` builds it, `Brief.tsx`, `Tiles.tsx`, `WhereToLook.tsx`, `TideSpark.tsx` render it, `run.ts` / `Run.tsx` give the run time and return window |
| `web/map/` | The map: `chart.ts` (MapLibre Chart), `layers.ts` (layer registry), `stage.ts` (shared camera, Chart / 2D / 3D), `terrain.js` (terrain loader), `style.ts` (basemap style), plus one module per layer (seafloor, MPAs, currents, swell, SST, clouds, marks, charter grounds, commercial AIS, fleet) |
| `web/ui/` | Shared primitives: `Button`, `Chip`, `Dock`, `Popover`, `Rail`, `Sheet`, `Tile`, `icons` |
| `web/*.ts` | State and models: `state.ts` (URL store), `views.ts`, `conditions.ts`, `score.ts`, `limits.ts`, `ranking.ts`, `species.ts`, `trip.ts`, `tides.ts`, `regs.ts`, `reports.ts`, `coast-data.ts`, `telemetry.ts` |
| `web/advisor/` | The Text Advisor's chat and pages (dark unless `TEXT_ADVISOR_ENABLED` is set; see `server/advisor/gate.ts`) |
| `packages/coast/` | The terrain renderer (2D and 3D), coast report logic, history and catch views; also shared types and limits |
| `dist/sw.js`, `offline-pack.js`, `offline-core.js`, `coastal-offline-core.js` | Service worker and the offline trip pack (below) |
| `dist/*.js` (feed, region, protected-area, GPX and other modules) | Plain-JavaScript modules that `web/` imports or the pages load; the new code is TypeScript in `web/` |
| `dist/data/`, `dist/downloads/`, `dist/tiles/`, `dist/basemap/` | Reviewed public atlas and exports (including 132 single-target GPX files), PMTiles, self-hosted glyphs |
| `dist/vendor/` | Licence files for MapLibre, PMTiles, SunCalc and three, plus the passkey browser library; no Leaflet. Hashes: `scripts/web-vendor-sha256.json` |
| `research/scripts/export_web_targets.mjs` | Generates the direct single-target GPX files in `dist/downloads/targets/` |

## What the app does

- **Chart.** The Chart is MapLibre GL over a self-hosted Protomaps (PMTiles) basemap, recoloured from the app's tokens (`web/map/style.ts`, `web/map/chart.ts`). MapLibre and PMTiles load by dynamic import on the first Chart view (`web/map/maplibre.js`). Bases are Night, Chart detail (NOAA ENC display, planning only) and, where a region offers it, Aerial (`baseOptions` in `web/app/LayerRail.tsx`).
- **Terrain, 2D and 3D.** The Chart / 2D / 3D toggle in the map chrome loads `packages/coast` on the first terrain choice, by dynamic import from `web/map/stage.ts` (`web/map/terrain.js`). The Chart and the terrain share one camera. Seafloor relief is nominal, with its survey and datum named in the legend.
- **Layers.** The registry in `web/map/layers.ts` lists them: basemap, aerial, ENC chart, terrain relief, water temperature, swell, protected areas (always drawn), habitat (from zoom 10), shore runs (Shore profile), seafloor, charter grounds, commercial AIS 2024, currents, clouds, marks, the selection and ranked trip spots. Fleet heat, tracks and events are admin only. Each entry shows its basis sentence.
- **Profiles.** Boat, Shore, Spear and Kayak change the default target, depth limit, layers and caveat (`PROFILE_TABLE` in `web/profile.ts`). Kayak uses the boat ranking within a 120 ft screen and reads wind, drift and launch surf first; a forecast cannot clear a paddle. Habitat is described as a place to look; fish presence stays unverified.
- **Brief.** The brief (`web/brief/`) shows a headline, wind, swell, water and tide tiles, the lower-exposure window, where to look, and the profile's caveat. Without a forecast the tiles read unavailable; an old run reads stale with its age.
- **Run time and return window.** For a Boat brief, `web/brief/run.ts` works out the run from the harbor to the chosen place at your own cruise speed, the latest turn-back time to be in by the end of the window, and the fishing time left. The distance is straight-line, not a charted route. No window means no return time.
- **Time dock.** `TimeDock.tsx` scrubs or plays 169 hourly samples (`web/hour.ts`) in the region's time zone. A `?hour=` outside that range is kept and the slider turns off.
- **Conditions.** The view shows the selected hour, a forecast chart, source clocks, tide events and the profile's notes (`web/app/views/Conditions.tsx`). It compares NOAA (GFS, GFS-Wave) with ECMWF (IFS, WAM) (`web/conditions.ts`).
- **History.** Recorded station history, shown only where a local coast report binds the region; elsewhere the view says history is unavailable (`web/app/views/History.tsx`).
- **Fleet.** The charter-grounds layer with dates and a basis sentence (approximate search outlines from published trip records, not AIS-confirmed positions), the Commercial AIS 2024 option (apparent fishing effort is not proof of fishing or catches) where a region has it, and an admin-only part (`web/app/views/Fleet.tsx`).
- **Reports.** Dated catch cards, recent fishing evidence and discussions, and charter evidence, each with its source link. Nothing ranks places or scores a catch (`web/app/views/Reports.tsx`).
- **Limits.** Comfort limits and cruise speed are yours, kept on the device (`web/limits.ts`).
- **Trip plan and GPX.** The trip plan dialog ranks screened reef spots (Best available) or takes the marks you add, re-checks protected areas and the reef publication when you export, and downloads GPX, a share-sheet file or offline notes. The plan is saved per region in this browser. State is `web/planner.ts`, the view `web/app/Planner.tsx`, the dialog `web/app/Trip.tsx` and the wiring `web/trip.ts`, all loaded on first open. GPX polygons are separate track rings; they are not navigable routes.
- **Saved-trip alerts.** Signed-in people save a date, area and comfort limits and get material changes and a day-before assessment from saved-trip alerts in the account menu (`web/app/TripAlerts.tsx`, `web/alerts.ts`). They do not certify navigation or entrance clearance.
- **Account.** Passkey sign-in, the boat profile, comfort feedback and saved trips sit behind the account menu (`web/account.ts`, `web/app/AccountMenu.tsx`). Anonymous map browsing needs no account.

## Data, storage and offline

Shared cloud jobs publish regional environmental evidence. A Worker serves cached public feeds, with direct-provider recovery in the browser for a few live sources. Private records (accounts, saved trips, alerts, comfort feedback) live in D1; public assets contain no credentials or private records. See [production operations](production-operations.md) for isolation and retention. Hosting providers and external map/weather services process ordinary network requests. NOAA ENC chart tiles are fetched only for the visible map.

The service worker `dist/sw.js` precaches the landing page's first paint but none of the map app's files (listed in `/precache.json`, written by `scripts/precache.mjs`); the map app opens offline only after Save for offline. It keeps the latest public data it has seen, and answers from a saved trip pack when the network fails. Anything served from a save is marked `X-SC-Offline: <saved-at>` and the page shows an offline banner; saved data is never shown as live.

The offline pack is saved only when asked (account menu, Save for offline; `web/trip.ts`, `dist/offline-pack.js`, `dist/offline-core.js`). It holds NOAA ENC chart tiles for the selected region at zoom 8–12 (at most 1,500), the app's page and files (about 2.2 MB), and the self-hosted base map's tiles for the region at zoom 8–12 under the same cap, stored as the byte ranges the map reads (95 base-map tiles for Morro Bay; `tests/test_trip.mjs`). A separate coastal snapshot is handled by `dist/coastal-offline-core.js`. The app is a mobile website; installing it to the home screen is optional (iPhone and iPad need it for push alerts).

## Evidence limits

The Morro Bay atlas is a dated research layer, with no AIS-confirmed charter hotspots or verified catch success. It shows official MPA boundaries and screens all fishing geometries against them at load; this is not a complete live closure service. It has no nautical navigation route or harbor-current model. Saved-trip threshold alerts do not certify navigation or entrance clearance. Central Coast qualified targets end at Point Estero; Cambria–San Simeon adds geological context. Southern California adds 410 historical island habitat outlines and 84 source-grid terrain views with explicit datum and coverage limits. The excluded source products remain excluded. Weather/search-reference coverage extends offshore. Search references are constructed samples, not species detections or charted routes.

Forecasts are regional model values, not observations at individual targets. The browser checks units, timestamps, populated fields, published end times, model disagreements, and inconsistent gust/component values. It never assigns a go/no-go or a qualified trip recommendation. The lower-exposure windows and comfort words come from one disclosed conditions model ([conditions model](conditions-model.md), `web/score.ts`); bite potential stays unknown. The qualitative hourly comfort screen uses disclosed wind/sea preferences and does not calculate transit, verify four fishing hours, or certify an entrance. Days four through seven are provisional. Active alerts are a retrieval-time snapshot, not future clearance. Provider metadata are not guaranteed run attribution for every value in a rolling timeseries. Stale evidence cannot earn a calmer label.

NOAA chart images follow the service's portrayal units. Wave, tide, and habitat cards use feet; wind uses knots. Wave/wind directions are from; current direction is toward. All timestamps render in Pacific time. NOAA tides are astronomical predictions for Port San Luis, not Morro Bay bar currents. Dated buoy observations come through the public conditions feed. Harbor pages remain external references, not live entrance clearance.

## Hosting

The site is served by SkipperCast's Cloudflare Worker (`wrangler.jsonc`), which publishes the built `dist/client` and `dist/server`; see [Cloudflare](cloudflare.md). Source credentials, generated archives, DNS receipts, and personal monitor state are not committed. Deploys come only from `main` through `.github/workflows/deploy-cloudflare.yml`; a failed deploy is rolled back, never repaired by hand in the dashboard.

The private personal Telegram monitor is not wired into the public web app. The portable Python collector and alert lifecycle stay available for a later authenticated integration.

## Live measurements

Dated NOAA buoy readings, airport weather and measured water level come through the public conditions feed. The brief uses measured buoy seas when fresh and labels a forecast fallback. The brief reuses a loaded regional forecast for up to 30 minutes before it asks again (`FORECAST_MAX_AGE_MS` in `web/brief/Brief.tsx`). Refresh intervals for observations are not verified here; see [Sources and the cloud refresh](live-conditions.md).

## Link previews

The initial HTML contains Open Graph and X large-image metadata for
`https://skippercast.com/`. Crawlers can read the title, description and absolute
image URL without running JavaScript.

The [published share image](../dist/skippercast-parker-preview.jpg) is a 1736 × 906
JPEG, 493,062 bytes. It preserves the composition and dimensions of the
original generated PNG (from this [prompt](social-preview-prompt.txt)), which is no
longer shipped; recover it from git history if needed. The original 2.3 MB PNG exceeded [Signal Desktop's 1 MiB image download limit](https://github.com/signalapp/Signal-Desktop/blob/main/ts/linkPreviews/linkPreviewFetch.preload.ts),
so Signal displayed the title and description without the boat image. The JPEG
uses a new URL and is less than half that limit. Keep social-preview images below
1,048,576 bytes, publicly accessible as JPEG or PNG, and declared in the initial
HTML. This is separate from ordinary in-app attachment size limits.

The image hash is recorded in `scripts/web-vendor-sha256.json`. Keep image
dimensions, media type and hashes in sync when replacing the card. To check a
change, remove the existing unsent link and paste it into Signal again; an already
sent preview is embedded in its message and is not updated by redeploying the site.


## Source documents

The 132-target atlas, charter-ground, species and habitat methods are in [atlas methodology](atlas-methodology.md), [charter grounds](charter-grounds.md) and [species research](species-research.md). Older release notes are in [the archive](archive/map-and-forecast.md); [product research](archive/product-research.md) records possible additions and is not a claim that they ship. `scripts/check_web.py` checks the deployed copies of the atlas, licences and vendor hashes. JavaScript checks run with `node --test tests/test_*.mjs`.
