# Front-end rebuild: design

The engineering design for the Bridge app shell, the Open water landing, the
move from Leaflet to MapLibre GL, and the merge of the `fish` repository into
SkipperCast, written for an implementing agent that has not seen the
conversation that produced it. [dev-plan.md](dev-plan.md) is the task list;
this document is the reference each task points to. Decisions D1–D16 are
recorded in [README.md § Decisions already made](README.md#decisions-already-made-d1d16)
and are not reopened here; choices with ranked options are in
[open-questions.md](open-questions.md). Steps that need the owner are marked
**Owner**.

Three wording rules apply in code, copy and docs:

- A reading is shown with its **source and age**; a reading past its
  freshness limit is shown as stale, never as current.
- Habitat fit is a **physical match** ("fits lingcod habitat: 3 of 3");
  it is never written as a chance of catching anything.
- Fleet activity derived from AIS is **"inferred from movement"**
  ([charter-fleet/design.md](../charter-fleet/design.md)).

## 1. Overview and goals

SkipperCast's public app today is a Leaflet map with about a dozen floating
panels and an Options dialog, styled by 22 stylesheets that mostly predate
the token file. The owner's `fish` repository (SLOFishReport.com) built a
second product on SkipperCast's data exports with a MapLibre map, a
server-rendered brief, profile-aware filtering and several data sources
SkipperCast lacks; it is a single-county prototype with a crude basemap and
a 2,942-line stylesheet. The rebuild takes the best of both: SkipperCast's
regions, pipelines, accounts, Worker and tests; `fish`'s map rendering,
brief, charts, profiles and sources; and one new visual system.

Goals, in order:

1. A first-time visitor understands the value of the data within seconds
   (D4): the landing shows live, sourced readings on a real map.
2. One visual system (D1, D5, D6) in a token file that every component uses,
   enforced by a lint, with contrast checked in CI.
3. A map that reads like an instrument: relief, streamlines, fields and
   marks on a quiet self-hosted basemap, with one legend and one time dock.
4. Boat / Shore / Spear as state that shapes the map, the brief, the species
   list and the search plans (D12).
5. Every `fish` capability live in SkipperCast, with its data flowing through
   SkipperCast's collectors and workflows, so that `fish` can be retired (D2).
6. Nothing changes for the public until the owner flips `UI_V2` (D14).

Non-goals: a light theme in this plan (tokens define it; the switch is
backlog), a redesign of `web/admin`, new paid services, changes to the data
pipelines beyond the new collectors in § 11, and any change to what the
charter fleet shows the public.

## 2. Research findings (verified 2026-10-05)

Each claim names the file it was checked in. When a task finds a claim is
wrong, fix this section in the same PR. The findings below describe the two
code bases on 2026-10-05; what Codex merged into SkipperCast afterwards
(`packages/coast/`, the coastal bridge and the v1 coastal modules) is in
[§ 3A.1](#3a1-what-is-on-main-verified-2026-10-07-at-668c2cb), which wins
where the two disagree.

### SkipperCast today

- **Map.** Leaflet 1.9.4 vendored with SRI (`dist/vendor/leaflet.js`,
  `dist/index.html` lines 39 and 56) over OpenStreetMap raster tiles and the
  NOAA ENC chart WMS (`server/security-headers.ts` `CONNECT_ORIGINS`).
  MapLibre GL 5.24.0 and PMTiles 4.5.0 are vendored too but used only by
  `dist/map-test.html` / `dist/map-test.js` and by `dist/seafloor-layer.js`,
  which loads the PMTiles reader to read the seafloor archive on R2
  (`/feeds/tiles/seafloor/seafloor-<region>.pmtiles`, `server/feeds.ts`).
  ADR 0005 (Proposed) measured one dense layer both ways: 58 KB and
  responsive with MapLibre + PMTiles against 1.5 MB and about 50 s per move
  with Leaflet.
- **Shell.** `dist/index.html` is 605 lines with 15 `<details>` disclosures,
  three `<dialog>`s and 41 inputs, selects and buttons inside `#map-options`.
  Twelve `position: absolute` rules in `styles.css` and `map-first.css` place
  the floating panels (locate button, phone-GPS card, regulations card,
  charter chip, species select, time dock, legend, loading, empty state and
  the rest).
- **Boot.** `dist/boot.js` awaits `initHomePort()` before the region loads;
  `dist/home-port.js` returns early only for links with area parameters
  (`hasAreaLink`) and otherwise shows the modal scrim until a port is chosen.
  `dist/first-run.js` then runs two steps (boat preset, tomorrow's answer).
- **Styling.** `dist/tokens.css` defines a light palette with an inactive
  dark set (`data-theme`), Inter as the font family and a legacy palette
  "kept so current screens render unchanged". The 22 stylesheets (4,289
  lines) contain 377 distinct hex colours and 275 `var(--` occurrences
  (`grep -o 'var(--' dist/*.css | wc -l`). No webfont is loaded; the CSP
  has `font-src 'self'`. Icons are unicode glyphs (`⌖`, `↓`, `×`, `↗` and
  the like in `dist/index.html` and `dist/*.js`).
- **Overlays.** Weather is drawn as translucent `L.circle`s
  (`dist/weather-ui.js` line 363) with "↑" characters rotated for direction
  (line 383); currents reuse the same marker style. Charts are hand-built SVG
  in `dist/meteogram-core.js` (265 lines) drawn by `meteogram-ui.js` into a
  Preact card.
- **Preact.** `web/islands.tsx` mounts five components (`web/components/`
  holds seven files; two are children)
  into slots of the existing page; `web/state.ts` holds signals with the URL
  as the source of truth for `region`, `coast`, `view`, `target`, `hour`,
  and reloads the page on region change after `lockRegion()`.
- **Build.** `vite.config.mjs` makes every `dist/*.html` (13 pages) an
  entry, merges each page's stylesheets in document order into one
  `NAME.page.css`, and keeps `cssMinify: false` because the minifier once
  dropped an `!important` override. `scripts/check_client.mjs` checks the
  output; `scripts/check_contrast.mjs` checks the documented token pairs at
  4.5:1 in both themes; `scripts/check_copy.mjs` lints copy; `e2e/` runs
  Playwright with axe (`e2e/axe-summary.ts`); `scripts/startup-budget.json`
  caps Morro Bay's startup JSON (2.54 MB measured, 400 KB target).
- **Regions.** One active region (`regions/morro-bay/region.json`), fourteen
  `preview`.
- **Public features** (each needs a home in the new shell, § 6): forecast
  meteogram and outlook (`meteogram*.js`, `tomorrow.js`, `morning-outlook.js`),
  tides and buoys (`live-conditions.js`, `marine-data.js`), HFR and WCOFS
  currents (`habitat-map.js` reads `habitat-tiles/*.json`), seafloor
  candidates (`seafloor-layer.js`), survey habitat (`survey-habitat.js`),
  geology (`geology.js`), MPAs (`protected-areas.js`), regulations
  (`regulations.js`), charter grounds (`charter-grounds.js`), commercial AIS
  2024 (`commercial-ais.js`, off by default), species search plans
  (`search-plans.js`), trip planner and GPX export (`export-*.js`, `gpx.js`,
  `trip-export.js`), offline pack (`offline-pack.js`, `sw.js`), discussions
  and bite evidence (`recent-discussions.js`, `bite-evidence.js`), account and
  alerts (`account.js`, `trip-alerts.js`, `boat-profile.js`).
- **Gated.** Fleet activity (`dist/fleet-activity.js` behind `FLEET_ENABLED`
  and `FLEET_MAP_ENABLED`, admin only), Text Advisor pages and chat
  (`TEXT_ADVISOR_ENABLED`), charter public profiles (`/boats/<slug>`), the
  admin app (`web/admin`).
- **Worker.** Pages are served by `server/routes/assets.ts` from a `SHELLS`
  map built by `scripts/build-worker.mjs`, `no-store`, with a stable `/sw.js`.
  CSP: `script-src 'self'` (no inline scripts), `font-src 'self'`,
  `worker-src 'self'`, `img-src` limited to `IMAGE_ORIGINS`.

### `fish` today (the `fish` repository, read-only checkout)

- One server-rendered page (`src/render.ts`, 21 lines) with the client in
  `src/client.ts`; MapLibre and PMTiles as npm packages; `src/styles.css` of
  2,942 lines, dark only.
- `src/map/coast.ts` (245 long lines, 31 hard-coded hex values): an inline
  style with no vector basemap (background colour, a 0.05° graticule,
  Natural Earth land fill), the NOAA CUSP coastline drawn twice (a blurred
  glow line under a crisp line), optional NAIP raster from the USGS
  ImageServer, bathymetry as PNG PMTiles, habitat polygons, MPAs, shore runs,
  cloud WMS frames, and canvas fields for water temperature and currents.
- `src/map/surface-field.ts` (57 lines): bilinear interpolation inside
  complete adjacent quads only, no filling of gaps; `fieldContours`
  (marching triangles with a centre fan); `temperatureColors` equal to the
  D5 surface temperature ramp. Streamline seeding, integration and the
  dashed animation live in `coast.ts` (`flowPaths`, `animate`), clipped by
  the land mask.
- `src/charts/series.ts` (26 lines): `linePath` breaks the path at gaps
  over `gapMs`; `chart()` stacks rows with independent scales on one time
  axis, shades night from sunrise and sunset, shades quiet windows, draws a
  cursor; used by the brief's tide sparkline (`mini`), the Conditions view
  and History.
- `src/state/experience.ts`: `Mode = boat | shore | spear`;
  `defaultSpecies` (lingcod / surfperch / cabezon-shallow-reef);
  `maxDepth` 60 for spear, 300 otherwise; `quietestHours`; `initialForecastAt`.
  `src/daily.ts` builds the brief with per-profile missing-data lines and
  caveats (shore: "Offshore seas do not measure breakers at your beach").
  `src/opportunity.ts` holds the surfperch and halibut guidance and the
  shore-run priority with source, rule and access review clocks.
- `src/ui/briefing.ts`: kicker, headline rules (alert, night, swell ≥ 5 ft,
  wind ≥ 12 kt, profile defaults), deck sentence, lower-exposure window,
  four tiles (Wind, Nearshore, Water, Tide) with notes, subline, tide
  sparkline with events, "where to investigate" list, fleet brief, beach
  advisory link, footer. `src/ui/icons.ts`: 31 stroke icons.
  `src/ui/history.ts`: 45-day means over monthly p10 / median / p90 bands.
  `src/ui/catches.ts`: up to eight seven-day catch cards.
- `src/bathymetry-proxy.ts` (128 lines): serves a PNG PMTiles archive from
  the asset binding with an approved-source SHA table, a 16 MB archive cap,
  2 MB range cap and a 128 KB manifest cap. `README.md`: 12,044,691 bytes,
  1,987 tiles at zooms 11–16, three USGS grids (Morro Bay, Point Buchon,
  Point Estero), nominal 0–300 ft.
- `src/map-sources.ts`: fixed publisher hosts only; NAIP tile template;
  GOES WMS frames pinned to published acquisition times with a 90-minute
  age gate; `selectCurrentFrame` with the WCOFS (36 h issue, ±90 min) and
  HF-radar (≤ 6 h) gates.
- Data `fish` has that SkipperCast lacks (providers in `src/providers/`,
  importers in `scripts/`): NAIP aerial (live tiles, nothing stored), CDIP
  MOP alongshore nearshore model at five sites (THREDDS), SLO County beach
  health (SurfSafeSLO ArcGIS feature service), NDBC 46215 and 46028 annual
  standard-met history with monthly p10 / median / p90 (`scripts/refresh-history.mjs`),
  Port San Luis tide curve and events in the brief, ESI 2006 sandy-shore runs
  with California Coastal Commission access points and CDFW guidance
  (`scripts/import-shore-habitat.mjs`), GOES observed-frame loop, seven-day
  catch cards from SkipperCast's own landing-reports feed.
- `NOTICE.md`: `fish` reuses SkipperCast data exports; the same owner holds
  both; rights notes per source are carried into § 11.
- Weaknesses to fix in the port: no vector basemap, panels and boxes
  everywhere, disclaimer-heavy microcopy (the sources sheet repeats four
  "is not" sentences), the mobile map buried under the brief, dark only, hex
  hard-coded in `coast.ts`, one monolithic stylesheet.

## 3. Architecture

ADR 0009 adopts ADR 0005's stack and records the flag, routing and basemap
decisions below. The owner accepts both by approving the plan PR; FE-01
flips their status lines.

**Amended 2026-10-07.** Codex merged `fish`'s client into SkipperCast as
`packages/coast/` while this plan was in Phase 0. [§ 3A](#3a-integration-with-packagescoast-2026-10-07)
records how the v2 shell consumes it; the module layout below is the
amended one. Modules this plan meant to port from `fish` (`surface-field`,
`frames`, `daily`, `series`) are imported from `packages/coast/src/`
instead, and the relief pipeline is replaced by the coast renderer's
terrain.

### Module layout

```
web/
  tokens.css            the visual system (§ 5); loaded first by every v2 page
  fonts/                DM Sans and JetBrains Mono woff2 + OFL licences
  ui/                   icons.tsx, Button, Tile, Chip, Sheet, Rail, Dock (§ 6)
  state.ts              the one URL/profile/time store for both shells (§ 8, § 3A.3)
  profile.ts            Boat / Shore / Spear semantics (§ 8)
  fish-links.ts         Fish link aliases (Codex, #379); the only alias table
  coast-context.ts      coast target ids, terrain coverage, presentation, habitat URL helpers
  coast-data.ts         v2 loaders for the coast report, ocean and history snapshots (FE-74)
  map/
    stage.ts            MapStage adapter: one camera, selection and hour over three presentations (FE-71)
    terrain.js  terrain.d.ts  terrain.css   the dynamically imported terrain module: mountCoast and the shadow-root stylesheets (FE-71)
    engine.ts           MapLibre init for the Chart presentation (FE-11)
    style.ts  palette.ts  basemap style and the CSS-to-JS colour bridge (FE-72)
    layers.ts           layer registry: id, order, presentations, sources, basis, legend, time
    flow.ts  field.ts  marks.ts  mpa.ts  swell.ts  clouds.ts  fleet.ts  seafloor.ts
    frames.ts           thin wrapper over packages/coast map-sources.ts and state/current-layer.ts
  brief/
    model.ts            brief adapter: packages/coast daily.ts where a report binds, regional feeds elsewhere (FE-31)
    Brief.tsx  Tiles.tsx  WhereToLook.tsx  TideSpark.tsx
  app/
    App.tsx  Masthead.tsx  CommandBar.tsx  Desktop.tsx  Mobile.tsx  TimeDock.tsx
    MapStage.tsx  CoastMarkup.tsx (shadow-root host for packages/coast markup, FE-75)
    LayerRail.tsx  Legend.tsx  MarkCard.tsx  views/{Coast,Conditions,History,Fleet,Reports}.tsx
  landing/
    Landing.tsx  Readout.tsx  PortInput.tsx  ProfilePills.tsx  LayerDots.tsx
    Shoreline.tsx (static SVG, FE-07)  NightMap.tsx (live map, FE-25)
packages/coast/         fish's client (Codex, #385): renderer, report model, charts, ui markup
  tokens-bridge.css     --coast-* properties mapped to web/tokens.css under an opt-in (FE-76)
  src/palette.ts        the renderer's colours as data, defaults = today's values (FE-76)
  src/embed.ts          the typed mount API v2 and v1 share (FE-70)
  src/embed-types.ts    its types, renderer-free, so web/tsconfig.json never loads three or the viewer (FE-71)
dist/
  app.html              the v2 app shell entry (/map)
  landing.html          the v2 landing entry (/)
  index.html            the v1 shell, untouched until FE-61
  coast.html            the standalone /coast page, retired by FE-61
```

Rules: product code never imports `research/`; `web/` modules import
`dist/*.js` only through typed wrappers during the migration (the Node
tests import `dist/*.js` directly, so those modules keep their exports until
FE-61 deletes them); every new component reads colour, type, spacing and
radius from `var(--…)`; no `innerHTML` in `web/` (Preact renders), with
one audited exception: `web/app/CoastMarkup.tsx` assigns, inside its own
shadow root, only strings returned by `packages/coast/src` renderers, which
escape every value (`esc`, `escapeHTML`) (§ 3A.2).

### Build and serving

- Vite keeps every `dist/*.html` as an entry, so `app.html` and
  `landing.html` join the build with no config change; shared chunks are
  hashed as today. `cssMinify` stays off until FE-61 removes the old sheets,
  then FE-61 turns it on and re-checks the pages.
- MapLibre GL and PMTiles move from `dist/vendor` to npm packages bundled
  by Vite for the v2 pages (typed imports, tree shaking, one version). The
  MapLibre worker is loaded with `setWorkerUrl` from a hashed asset
  (`worker-src 'self'` already allows it). The v1 pages keep the vendored
  copies until FE-61; `scripts/web-vendor-sha256.json` shrinks then.
- Fonts are self-hosted under `web/fonts/` (D6) because `font-src 'self'`;
  `font-display: swap`; subset to Latin.
- `scripts/build-worker.mjs` adds `app.html` and `landing.html` to `SHELLS`.
  `server/routes/assets.ts` decides which shell answers `/` and `/map`
  (§ 7, flag rules in § 14).
- The service worker's precache gains the v2 entries; the offline pack
  (FE-51) precaches the basemap tiles for the saved region's bounds at
  zooms 8–12 only (budget in § 13).

### Keeping Leaflet alive during the migration

The v1 shell (`index.html`, `boot.js`, the Leaflet modules) is untouched
until FE-61. v2 pages import no Leaflet. Modules shared by both shells
(`search-plans.js`, `gpx.js`, `offline-core.js`, `regulations.js`,
`species-fit.js`, `spot-ranking.js`) are wrapped, not edited, except where a
task says so. When a task must change a shared module, it keeps v1
behaviour and adds a test for the v2 call path. Ranked alternatives are in
open-questions Q4. The v1 coastal modules Codex added (`dist/coast-*.js`,
`dist/coastal-*.js`, `dist/coast.html`) are v1 shell code under the same
rule: v2 never imports them, and FE-61 deletes them with the rest of v1.

## 3A. Integration with `packages/coast` (2026-10-07)

This section amends § 3, § 5, § 8, § 9, § 10, § 11, § 13 and § 15 and
takes precedence over them where they disagree. ADR 0009's 2026-10-07
addendum records the decision.

### 3A.1 What is on `main` (verified 2026-10-07 at `668c2cb`)

Read in the code, not the commit titles. PR numbers are Codex's.

- **`packages/coast/` (#385, extended by #392, #393, #395, #396, #399,
  #402, #405).** Strictly typed TypeScript from `fish` `4ac5e0c`, its own
  `tsconfig.json` in `pnpm typecheck`. Renderer: `src/coast3d/viewer.ts`
  `CoastViewer` on `three` 0.180 (npm, with `OrbitControls`); its 2D is a
  camera-only top-down view of the same Three scene
  (`setPerspective('2d' | '3d')`). There is **no MapLibre in
  `packages/coast`**: `fish`'s MapLibre `src/map/coast.ts` was not ported.
  The viewer's public methods are `load`, `setPerspective`, `setPlace`,
  `setLocation`, `setSpecies`, `setHour`, `setDepthLimit`,
  `setCurrentLayer`, `selectHabitat`, `setVisible`, `destroy`, with the
  `CoastViewerOptions` callbacks `onSelection`, `onRestoredSelection`,
  `onSelectionInvalidated`, `onCurrentStatus`, `onPlace`, `onView`,
  `onPerspective` and `managed: true` for a host that owns region, target,
  location and hour. It reads about forty element ids of `fish`'s page
  template (`relief`, `water`, `contours`, `depth-limit`, `reading`,
  `target-detail`, `sources-open` and the rest), so it cannot mount without
  that markup today. `src/coast3d/regional.ts` streams SHA-verified terrain
  and imagery with byte bounds; `src/coast3d/report.ts` `CoastReport` reads
  the report and history snapshots.
- **Models and markup in `packages/coast/src`.** `daily.ts` (`buildDaily`,
  `availableDays`), `state/experience.ts` (`defaultSpecies`, `maxDepth` 60
  for spear and 300 otherwise, `quietestHours`, `initialForecastAt`),
  `presentation.ts` (`freshNearshore`, `nearshoreAt`, `hourReadout`,
  `reportPanel`), `charts/series.ts` (`chart`, `linePath`, returning SVG
  strings), `ui/briefing.ts`, `ui/history.ts` (`historyView`),
  `ui/catches.ts` (`catchSheet`, `fleetBrief`), `ui/icons.ts`, all
  returning escaped HTML strings; `map/surface-field.ts` (interpolation,
  contours, `temperatureColors`); `map-sources.ts` (`selectCurrentFrame`,
  `cloudSource`, `naipSource`; the last two are unused by any client
  today); `state/current-layer.ts` (`selectedCurrent`,
  `validCurrentField`); `state/habitat-selection.ts`;
  `state/report-binding.ts` (`resolveReportBinding`: exact reviewed
  bounds, no nearest package); `links.ts`; `transport.ts` (`coastFetch`
  reaches only `/api/coast/*` and `/coast-data/*`). `fish`'s
  `opportunity.ts` (shore-run priority and guidance) was not ported.
- **Styling.** Counts use `scripts/check_tokens.mjs`'s own `HEX` regex
  (`/#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/g`) over
  each file, counting every match, distinct lower-cased values and lines
  with a match. `packages/coast/coast.css` is the terrain chrome in a light
  scheme (ground `#dce8eb`): 148 hex literals, 122 distinct, on 15
  minified lines. `panel.css` (2,944 lines; 315 hex literals, 288 distinct,
  on 285 lines) is `fish`'s dark report panel with its own `:root`
  variables whose names shadow `web/tokens.css` (`--bg: #091521` against
  `#07131d`, `--panel2` against `--panel-2`, a system `--mono`); it also
  keeps `.maplibregl-*` rules (lines 912–962) from `fish`'s MapLibre map,
  though nothing in `packages/coast` imports MapLibre. `viewer.ts` holds 14
  hex literals (10 distinct) and `charts/series.ts` 7 (4 distinct).
  `scripts/check_tokens.mjs` lints `web/**` only, so none of this is
  linted.
- **v1 mounts.** `/coast` serves `dist/coast.html` + `coast-entry.js`, a
  standalone page with its own controller and home settings.
  `dist/coast-workspace.js` (#392) mounts `CoastViewer` `managed` in a
  shadow root inside the Leaflet page as the presentations
  `chart | 2d | 3d` (`?presentation=`), syncing the chart centre with the
  span-to-zoom rule `zoom = 12 − log2(span / 7300)` clamped to 7–18.
  `dist/coastal-discovery.js` is the continuous Central Coast overview
  (`coast=central`); `coast-conditions.js` adds the local report and
  history to v1 Conditions (#393); `coastal-clock.js` is one UTC clock
  across Map and Conditions; `coastal-current-control.js` is one explicit
  surface-current choice `?current=off|wcofs|hfr-1|hfr-6` (#402);
  `coastal-offline*.js` saves the three public snapshots (#405). These v1
  modules import `web/state.ts` directly.
- **Server.** `server/coast-data.ts` + `server/routes/coast.ts` (#381) are
  a bounded read-only bridge to the owner's Fish Worker:
  `/api/coast/{report,ocean,history}` (SLO only: `morro-bay`,
  `cambria-san-simeon`), `/api/coast/habitat/{release,tiles}` and an
  enumerated list under `/coast-data/data/` (habitat, shore habitat,
  shoreline, terrain model). `server/coast-pages.ts` (#395) serves `/report`,
  `/feed.xml`, `/methodology` and `/about`. `server/app.ts` registers both
  routers before the private gate.
- **State.** `web/fish-links.ts` (#379) translates `place`, `mode`,
  `species`, `layer` and full ISO hours; `web/state.ts` applies it only
  under `configureStore({v2: true})`. `web/fish-entry.ts` (#396) normalises
  v1 startup links; `web/coast-context.ts` maps targets, terrain coverage,
  `presentation` and `habitat`; `web/overview-context.ts` binds a report
  only on exact identity and bounds. `presentation`, `current` and
  `habitat` are read ad hoc from `location`, not owned by the store.
- **Data.** No collector moved. Report, ocean and history snapshots, the
  habitat release and the terrain assets still come from the Fish Worker
  through the bridge (`docs/coastal-service.md`). Phase 3 (FE-40 … FE-45)
  has not started.
- **Status.** `docs/FISH-MERGE-STATUS.md` keeps the acceptance matrix and
  states that the v2 shell, the homepage default and Fish retirement are
  unchanged; `docs/FISH-MERGE-REVIEW.md` requires one public map shell and
  one profile, location and time controller.

### 3A.2 Decision: one shell, one map stage, three presentations

The v2 Bridge shell (`web/app/`) becomes the single public shell at FE-60.
The v1 chart, the v1 coastal overview and the standalone `/coast` page are
retired by FE-61 once the parity matrix passes; until then each stays
reachable.

**MapStage.** The shell's map area is one `MapStage` (`web/app/MapStage.tsx`
over `web/map/stage.ts`) with one camera, one selection and one hour, and
three presentations of the same place:

| Presentation | Renderer | Where | Notes |
| --- | --- | --- | --- |
| Chart | MapLibre GL + PMTiles (ADR 0005), self-hosted basemap (§ 4) | every region | the registry layers of § 9; atlas marks, GPX, regulations, fleet |
| Terrain 2D | `packages/coast` `CoastViewer`, top-down camera | regions where `hasCoastTerrain(region)` | the same scene as 3D; the toggle moves only the camera |
| Terrain 3D | `CoastViewer`, orbit camera | same | measured versus modelled labels, native masks and source inspection kept |

This corrects the plan's 2026-10-05 picture in one respect: the 2D view the
owner saw in `fish` is SkipperCast's to build in MapLibre (the Chart
presentation), while the terrain is Three in both perspectives. The
surface-field mathematics is shared: the Chart presentation imports
`packages/coast/src/map/surface-field.ts`, and the terrain draws currents
with the same field.

`?presentation=chart|2d|3d` is the key (already written by v1). The
perspective toggle sits in the map chrome beside the zoom controls; it is
disabled with a one-line reason where no terrain exists. Default: Chart
(open-questions Q15).

**Adapter.** `web/map/stage.ts` owns the renderers; Preact components
never touch them. The terrain side goes through `packages/coast/src/embed.ts`
(FE-70), a typed `mountCoast(host, options)` returning a `CoastHandle`
that wraps today's `CoastViewer` and its template, so v1's
`coast-workspace.js` and v2 share one mount. State flows:

| Store → renderer | Renderer → store |
| --- | --- |
| `profile` → `setDepthLimit(60 or 300)` (the values `web/profile.ts` and `experience.ts` both hold) | `onSelection` → `?habitat=` and the mark card |
| `target` → `coastTarget()` → `setSpecies` | `onView` → the shared camera (span-to-zoom rule of § 3A.1) |
| `hour` → `setHour` | `onPerspective` → `?presentation=` |
| shared camera → `setLocation({latitude, longitude, span})` | `onCurrentStatus` → the Currents rail entry's status line |
| `current` → `setCurrentLayer` | `onSelectionInvalidated` → clear selection |
| `habitat` → `selectHabitat` | `onRestoredSelection` → mark card |
| visible = view is Coast, page visible, presentation is terrain → `setVisible` | |

Three and the viewer load by dynamic import on the first terrain
presentation, so the app's 350 KB first-paint budget (§ 13) is unchanged and
`check_client.mjs` asserts `three` is absent from the app entry's static
imports. A WebGL or asset failure returns the stage to Chart with "Coastal
graphics are unavailable. The chart, forecasts and trip tools remain
usable." (v1's wording).

As built (FE-71): the dynamic import is `web/map/terrain.js` with its types in
`terrain.d.ts`, and `stage.ts` takes the handle types from
`packages/coast/src/embed-types.ts`. `packages/coast`'s renderer sources do not
type-check under `web/tsconfig.json`'s `noUncheckedIndexedAccess`, so the web
program must never load them; `embed.ts` re-exports every type, so v1 and the
tests are unchanged. Choosing Chart hides the renderer (`setVisible(false)`)
and keeps it, so returning to terrain is immediate; the layout's unmount
destroys it. A failure is sticky until a reload, as in v1, and the link keeps
`?presentation=`. While the terrain loads, the renderer's own `#loading`
status speaks; the stage's status line carries only why the terrain choices
are disabled. A terrain camera move writes `?view=` (span-to-zoom rule) once it
settles, without a history entry; a selection writes `?habitat=` with one, so
Back restores the previous selection. `onSelectionInvalidated` clears the
mark card but keeps `?habitat=` in the link (v1 parity: the renderer may
restore it when its data admits the id again); only the scene's close button
removes it. Without `?hour=` the terrain takes the current whole UTC hour and
the stage's own clock moves it on at each hour boundary.

**Layers.** Every registry entry (§ 9) declares the presentations it draws
in. Terrain-native layers (relief, water, contours, ranked habitat pins,
shore features) are options of the Seafloor rail entry in terrain (FE-80,
on Codex's host-chrome mode FE-79). SkipperCast layers the renderer lacks
(MPAs, atlas marks, charter grounds, fleet) draw in Chart; in terrain their
rail entries read "Chart only" until Codex's overlay API (FE-81) lets the
registry drape them (FE-82). No layer has two rail entries.

**Brief, Conditions, History, Reports.** v2 reuses `packages/coast` code,
never a fork:

- *Data*: `web/coast-data.ts` (FE-74) loads the report, ocean and history
  snapshots through `coastFetch`, admits them only when
  `resolveReportBinding` / `overviewReportContext` bind the selected place
  (Morro Bay and Cambria today), aborts on change and exposes signals that
  are `null` outside a binding.
- *Models*: the brief adapter (FE-31) calls `buildDaily` where a report
  binds and SkipperCast's regional feeds elsewhere, saying in one line that
  the local report is unavailable for this area. SkipperCast's seven-day
  dual-model forecast stays the forecast; `fish`'s report adds local rows
  and never shortens or fills that horizon.
- *Markup*: `ui/*.ts` and `charts/series.ts` return escaped HTML strings.
  `web/app/CoastMarkup.tsx` (FE-75) mounts such a string in a shadow root
  with `panel.css` and the token bridge (§ 3A.4). When v2 needs another
  structure, the change is made in `packages/coast` with a comment on the
  coordination issue first, so both shells keep one implementation.

### 3A.3 One state controller

`web/state.ts` is the one store for both shells; v1's coastal modules
already import it. FE-73 adds the keys v1 reads ad hoc:

| Key | Values | Stored | Notes |
| --- | --- | --- | --- |
| `presentation` | `chart`, `2d`, `3d` | v2 only (`skippercast-presentation-v1`); v1 writes chart by removing the key, so a v1 store neither reads nor writes it, and v2 writes `presentation=chart` | terrain values fall back to `chart` where `hasCoastTerrain` is false, without rewriting the URL (`stagePresentation`) |
| `current` | `off`, `wcofs`, `hfr-1`, `hfr-6` | no | default `off`; an unknown value stays in the URL and shows as unsupported (v1 rule, #402) |
| `habitat` | coast habitat id (`[A-Za-z0-9._:-]{1,160}`) | no | independent of the atlas `spot` |

Rules:

- `web/fish-links.ts` stays the only alias table (`place`, `mode`,
  `species`, `layer`, `area` → place). New aliases go there, with a test.
- `web/profile.ts` stays the profile table; a test asserts its depth limits
  and default targets equal `experience.ts` `maxDepth` and
  `defaultSpecies`, so the two cannot drift.
- One home memory: v2's port and profile save and forget go through the
  same path as `dist/home-port.js`, which #396 synchronised with
  `packages/coast` preferences (FE-83). A shared link never changes home.
- Region change keeps no reload in v2 (§ 8); the terrain handle receives
  the new place, and a region without terrain returns to Chart.
- `server/routes/assets.ts` `AREA_PARAMS` gains the coast and Fish keys so
  a shared Fish link opens the app, and `/coast` serves the app at
  `presentation=3d` once v2 is on (FE-78).

### 3A.4 Visual system: a token bridge for `packages/coast`

One visual system (D1) means the terrain chrome, the report panel and the
renderer read `web/tokens.css`. v1 pages use the same files today, so the
bridge must leave them unchanged:

1. **`packages/coast/tokens-bridge.css`** declares `--coast-*` properties
   (ground, panel, panel-2, line, text, muted, mint, blue, coral, amber,
   violet, water, land, label, mono and sans font) **only** under an
   opt-in: `[data-coast-theme="tokens"]` and
   `:host([data-coast-theme="tokens"])`, each mapped to a `web/tokens.css`
   variable. Custom properties inherit into shadow roots, so a v2 host
   element with the attribute themes everything inside.
2. **Literals become fallbacks.** In `coast.css` and `panel.css` each
   literal becomes `var(--coast-<name>, <today's literal>)`. Without the
   opt-in the fallback applies, so v1 computes the same values. `panel.css`'s
   local `:root` aliases are renamed to `--coast-*` so they never collide
   with `web/tokens.css` names in a v2 document. FE-76 converts `coast.css`;
   FE-77 converts `panel.css`.
3. **Renderer colours as data.** `packages/coast/src/palette.ts` exports
   `CoastPalette` and `DEFAULT_COAST_PALETTE` (today's ten distinct values); the
   embed takes an optional `palette`; v2 passes values read through
   `web/map/palette.ts`; v1 passes none.
4. **Lint.** `check_tokens.mjs` adds `packages/coast/**` with its own
   shrink-only baseline seeded from today's findings; a literal is allowed
   only as the fallback of a `var(--coast-…, …)` or in
   `packages/coast/src/palette.ts` until FE-61, which removes the fallbacks
   once no v1 page loads these files. SVG strings from `series.ts` carry
   colours in `style` properties, because presentation attributes do not
   resolve `var()`.
5. **Proof.** A Playwright check reads computed colours of fixed elements on
   `/coast` and the v1 terrain presentation before and after; they must be
   equal. A unit test pins `DEFAULT_COAST_PALETTE` to today's values.
   `check_contrast.mjs` covers the bridged text pairs under the opt-in.

### 3A.5 Ownership boundary (proposal; the owner decides)

Ranked options are in open-questions Q14. The plan assumes option 1:
Codex owns `packages/coast` renderer internals, the coast data adapters and
bridge, the terrain and mapping pipeline, the collectors (FE-40 … FE-45,
FE-84, FE-85) and the v1 coastal modules until FE-61; Claude owns the v2
shell, the visual system including the token bridge files, the landing, the
layer registry and MapStage adapter, `web/state.ts`, the flag flip and the
v1 deletion. The `packages/coast` exports v2 consumes (§ 3A.2) are a public
API: changing one needs a comment on the
[coordination issue](#3a6-hot-spots-shared-with-codex) first. Changing
AGENTS.md's division of work is the owner's call; open-questions Q14 holds
the proposed text.

### 3A.6 Hot spots shared with Codex

Coordination happens on GitHub issue
[#413 "Front-end v2 and packages/coast: one shell, ownership boundary"](https://github.com/Grahammmm/skippercast/issues/413).
Before a PR edits one of these, check open PRs and comment on the issue.

| File | Why it is hot | Rule |
| --- | --- | --- |
| `packages/coast/**` | Codex's renderer and models; FE-70, FE-76, FE-77, FE-79, FE-81 touch it | renderer internals: Codex; bridge files (`tokens-bridge.css`, `src/palette.ts`): Claude with Codex review |
| `dist/coast-*.js`, `dist/coastal-*.js`, `dist/coast.html` | v1 coastal glue that imports the shared store | Codex until FE-61; v2 never imports them |
| `web/state.ts`, `web/fish-links.ts`, `web/coast-context.ts` | read by both shells | append keys and aliases; renames need an issue comment and both shells' tests |
| `server/app.ts`, `server/routes/assets.ts`, `server/coast-data.ts`, `server/coast-pages.ts` | route order and the bridge; owner-approved paths | one router line per PR; Codex owns the bridge |
| `dist/sw.js`, `dist/offline-core.js` | v1 offline packs plus coastal snapshots | FE-51 and Codex's offline work rebase on each other |
| `scripts/check_tokens.mjs`, token baseline | FE-76 adds `packages/coast` | shrink-only |
| `package.json`, `pnpm-lock.yaml` | `three`, `suncalc`, later `maplibre-gl`, `pmtiles` | one dependency change per PR |
| `docs/FISH-MERGE-STATUS.md` | Codex's acceptance log | Codex writes; Claude links |
| `CHANGELOG.md` | both agents add lines | rebase, never reorder |

## 4. Basemap strategy (cost near zero)

The map needs a quiet vector basemap: coastline, land, harbor and town
labels, roads at high zoom only, no points of interest. Options, best first:

1. **Self-hosted Protomaps extract on R2, served through `/feeds/`
   (recommended, D10).** Build on Hermes with `pmtiles extract` against
   the latest Protomaps planet build, which reads only the needed byte
   ranges (no planet download), for a bounding box per active and preview
   region clipped to the coast, merged into one archive
   `tiles/basemap/ca-coast-<build-date>.pmtiles`. Style: a Protomaps
   "basemaps" style recoloured from the tokens in `web/map/style.ts`; label
   glyphs self-hosted under `dist/basemap/glyphs/` (DM Sans Medium SDF,
   ranges 0–255 and 8192–8447, about 86 KB, built by
   `scripts/basemap/build_glyphs.py`). The style draws no icons, so it has
   no sprite sheet (FE-72). Attribution:
   "© OpenStreetMap contributors, © Protomaps" in the Chart's attribution
   control, always expanded on both layouts (ODbL; FE-11 moved it from the
   legend because the mobile legend sits in the closed layers sheet). The archive is publicly downloadable from `/feeds/`, so
   it is redistributed as an ODbL derivative database: attribution and
   share-alike apply to the extract itself.
   Rights: `docs/legal/data-rights-register.md` row B6 marks OpenStreetMap
   commercial use **unknown** (the tile-service policy, not ODbL); a
   self-hosted extract removes the tile-service question but still needs
   its own register row (`protomaps-basemap`, ODbL, attribution yes,
   commercial use: owner to confirm), an **Owner** ask on FE-10.
   - Size, **measured by FE-10** (2026-10-08, `scripts/basemap/build_basemap.sh`
     against Protomaps build 20261008, a 138.7 GB planet): zooms 0–10 over
     the overview box `[-125.3, 32.0, -116.55, 42.5]` (every active and
     preview region padded by 0.5°) are 17 MB in 1,133 tiles; zooms 11–14
     inside the fifteen region `bounds` are 172 MB in 22,244 tiles. The
     merged `ca-coast-20261008.pmtiles` is 189,085,436 bytes (180.3 MiB)
     and took 16–36 s to extract and merge in two runs, the second with
     the pinned go-pmtiles v1.31.2 and the same bytes (198 MB of range
     reads in 168 requests). The earlier estimate of 300–600 MB was high.
   - Cost at R2 list prices: storage $0.015 per GB-month, so 0.19 GB is
     under $0.01 a month; egress is free; Class B reads $0.36 per million
     after the first 10 million a month. A map session fetches 50–150
     tiles. The Worker's `/feeds/` route keeps whole objects only up to
     32 MiB in the edge cache (`EDGE_CACHE_MAX_BYTES`, `server/feeds.ts`),
     so every basemap range read that reaches the Worker is an R2 read:
     100,000 sessions are up to 5–15 million reads, $0–1.80 a month. Splitting the archive by region below
     32 MiB would put it in the edge cache if reads grow.
   - Manifest: `tiles/basemap/manifest.json` (served at
     `/feeds/tiles/basemap/manifest.json`) names the current archive with
     its bytes, SHA-256, source build and boxes; the publish step uploads
     the archive, reads its size and hash back, and only then writes the
     manifest. Older archives are never deleted by the job.
   - Refresh: quarterly, by `workflow_dispatch` on `vars.DATA_RUNNER`; the
     archive name carries the build date so the style can pin it.
2. **A hosted vector tile service (MapTiler Cloud, Stadia, Protomaps API).**
   Free tiers exist with attribution and request caps; the terms and caps
   change and a key lives in the client. Rejected for the default; kept as
   the fallback if the extract proves larger than 5 GB.
3. **Keep OpenStreetMap raster and the NOAA ENC WMS.** Zero work, but the
   raster labels and colours fight the dark instrument look, the ENC WMS
   is slow and outside our control, and OSM's tile policy discourages heavy
   production use. Rejected for v2; v1 keeps it until FE-61.

The ENC chart stays available as an optional raster base at zoom ≥ 10 for
people who want chart symbols (the existing "Chart detail" control), off by
default.

## 5. The visual system (tokens)

`web/tokens.css` replaces `dist/tokens.css` for v2 pages (v1 keeps its file
until FE-61). Dark is the default theme; a light set is defined under
`:root[data-theme="light"]` so that the contrast check covers both from day
one and the switch is a backlog task (open-questions Q3).

### Colour

| Token | Dark | Use |
| --- | --- | --- |
| `--bg` | `#07131d` | page ground (app) |
| `--bg-deep` | `#020b12` | landing ground, night map ocean |
| `--panel` | `#0e1d2b` | brief column, sheet, cards |
| `--panel-2` | `#122535` | tiles, rail, dock, hover |
| `--line` | `#223849` | borders, dividers, axis lines |
| `--text` | `#e6eff4` | body text, readings |
| `--muted` | `#8ba5b7` | labels, units, ages, axis text |
| `--mint` | `#69e0bc` | wind, primary action, freshness ok |
| `--blue` | `#73bfff` | swell and waves, links |
| `--coral` | `#ff9c86` | water temperature, warnings |
| `--amber` | `#eabd76` | tide, fleet layers, caution |
| `--depth-0 … --depth-3` | `#7fd9c8`, `#2b9c9c`, `#1f5f8f`, `#1d2f6e` | depth ramp shallow → deep |
| `--sst-0 … --sst-5` | `#244f9d`, `#188eb5`, `#39c6c2`, `#a6dda0`, `#efd477`, `#f18a65` | surface temperature ramp |
| `--flow` / `--flow-fast` | `#dffcf6` / `#fff0bf` | streamlines |
| `--mpa-fill` / `--mpa-fill-opacity` / `--mpa-line` | `#e8a877` / 0.08 / `#e8b584` dashed | protected areas |
| `--fleet` | `--amber` | fleet events, tracks, heat |
| `--focus` | `--mint` | focus ring (2 px outside) |

The light set keeps the cartography tokens and redefines the UI colours
(`#f4f8f9` ground, white panels, `#0b2530` text) so that the same pairs pass.
Text pairs checked at 4.5:1 by `scripts/check_contrast.mjs` (extended to
read `web/tokens.css` and the new pairs): `--text` and `--muted` on `--bg`,
`--bg-deep`, `--panel` and `--panel-2`; `--mint`, `--blue`, `--coral` and
`--amber` on `--panel` and `--panel-2` (reading text); `--bg` on `--mint`
(button text). Ramps are decorative and carry a legend; they are exempt.

### Type

DM Sans (400, 500, 600) for text and labels; JetBrains Mono (400, 500) for
readings, coordinates, times and ages. Scale: `--text-11` (eyebrow, mono
ages), `--text-13` (labels), `--text-15` (body), `--text-18` (tile reading),
`--text-22` (headline mobile), `--text-28` (headline desktop), `--text-40`
and `--text-56` (landing display). Line height 1.25 headings, 1.5 body;
eyebrow tracking 0.08em; readings use `font-variant-numeric: tabular-nums`.

### Spacing, radii, elevation, motion, z

Spacing 4, 8, 12, 16, 24, 32, 48 (`--space-1 … --space-7`); radii 6, 10,
14 and pill (`--radius-sm/md/lg/pill`); elevation three shadows on
`rgb(0 0 0 / …)` tuned for the dark ground; motion `--motion-state` 120 ms
and `--motion-sheet` 220 ms, zero under `prefers-reduced-motion`; z-scale
map 0, chrome 10, dock 20, sheet 30, modal 40, toast 50; `--touch-min` 44 px.

### Enforcement

- `scripts/check_tokens.mjs` (new, FE-02) fails on any hex colour, `rgb(`,
  `hsl(` or named colour literal in `web/**/*.{css,ts,tsx}` outside
  `web/tokens.css`, and on `font-family` outside the tokens file. Map
  style and canvas code read tokens with `getComputedStyle` through
  `web/map/palette.ts`, which is the one allowed bridge from CSS to JS
  (named colours are checked in CSS only: "black rockfish" is copy).
  The baseline (`scripts/token-lint-baseline.json`) lists nothing, since
  `web/` had no literals when the lint landed; like the copy lint's, it can
  only shrink (`--base` compares it with the base branch in CI).
- `scripts/check_contrast.mjs` covers both token files until FE-61.
- `node scripts/check_copy.mjs` already lints `web/`.
- `packages/coast` joins the system through the token bridge of § 3A.4
  (FE-76, FE-77); the lint covers it with its own shrink-only baseline.

## 6. The app shell (concept A · Bridge)

### Desktop (≥ 1,024 px)

```
┌ masthead ───────────────────────────────────────────────────────────────┐
│ SkipperCast  MORRO BAY 35.37N 120.86W   Coast Conditions History Fleet  ● 4 min  Sign in │
├ command bar ────────────────────────────────────────────────────────────┤
│ [Boat][Shore][Spear]  Target: Lingcod ▾   Area: Estero Bay ▾   Window: Today ▾ │
├ brief 332 px ───────────┬ map ────────────────────────────────────────┤
│ Headline sentence       │                               ┌ layer rail ┐ │
│ ┌wind┐┌swell┐┌water┐┌tide┐│                               │ Seafloor   │ │
│ tide sparkline          │       (MapLibre)              │ Currents   │ │
│ Where to look  1 2 3 4  │                               │ Water temp │ │
│ One caveat              │  ┌ selected mark card ┐       │ Swell      │ │
│                         │  └────────────────────┘       │ Fleet      │ │
│                         │ ┌ legend ┐                    │ Clouds     │ │
│                         │ └────────┘                    └────────────┘ │
│                         │ ┌ time dock: Today Tue Wed  ▶ ──●──── 2 pm ┐  │
└─────────────────────────┴──────────────────────────────────────────────┘
```

- **Masthead** (`Masthead.tsx`): brand, location in mono (port name and
  coordinates from the region), view links (Coast, Conditions, History,
  Fleet) as `?view=`, the freshness dot (mint when every tile's source is
  within its limit, amber when any is stale, muted when offline) with the
  oldest age in mono, sign in (existing passkey flow).
- **Command bar** (`CommandBar.tsx`): profile switch (§ 8), target species
  (the region's species for the profile), area (the region's coasts and
  focus areas from `coasts.json`), time window (Today, the next two days,
  or "Now" when observations only).
- **Brief column** (`Brief.tsx`, § 10): headline, four tiles, tide
  sparkline, "where to look", one caveat, a footer with the sources link.
- **Map chrome** is exactly: the selected-mark card (`MarkCard.tsx`), the
  layer rail (`LayerRail.tsx`, § 9), one legend (`Legend.tsx`) and one time
  dock (`TimeDock.tsx`). Zoom buttons and the nautical scale are MapLibre
  controls restyled with tokens. Locate-me is a button in the command bar's
  area menu, not a floating control.

### Mobile (< 1,024 px)

The map fills the viewport; a top strip holds the brand and the profile
switch; a bottom sheet (`Sheet` in `web/ui`) with three detents (peek: the
headline and freshness; half: the four tiles and the top pick; full: the
whole brief, with the day, target and area menus at its end and sign in in
its footer) and the hour slider pinned at the sheet's top edge; a four-tab
nav (Coast, Conditions, History, Fleet) under the sheet. The layer rail
collapses to a single button in the top strip that swaps the sheet's content
for the rail with the legend under it. The mark card replaces the sheet's
peek content while a mark is selected. The sheet moves by drag on its
handle and by keyboard (FE-03's keys); focus entering the sheet's body at
peek lifts it to half.

### Where today's features live in the shell

| Today | In v2 |
| --- | --- |
| Species select, filters disclosure, "Find a spot" search | Command bar target menu (search field inside the menu) |
| Options dialog: region, coast, base map, layer checkboxes, seafloor view, drift options, fleet filters | Layer rail; region and area in the command bar; fleet filters in the Fleet view; drift guides folded into the Seafloor entry's options |
| Forecast panel (meteogram, outlook, morning outlook, bite evidence) | Conditions view (chart, § 10); outlook sentence is the brief headline; bite evidence is the brief's fleet line and the Reports page |
| Guide panel (seasonal watch, discussions, coverage, species guide, grade guide, charter evidence, downloads, offline pack, about) | Reports page (`?view=reports`, Phase 4) for discussions, seasonal watch and charter evidence; coverage and grade guide in the sources page; downloads and offline pack in the account menu |
| Export panel, spot dialog, GPX | Mark card actions ("Add to trip", "GPX"); trip list in the account menu |
| Home-port modal, first-run steps | Landing input and profile choice (§ 7) |
| Boat position card, regulations card, charter chip | Command bar area menu (locate), mark card (regulations line), Fleet view |

Every control removed without a home is listed in the task's PR with the
reason.

## 7. The landing (concept D · Open water) and the entry flow

### Layout

Full-viewport night map on `--bg-deep`. FE-07 ships it as the static
shoreline: the region's CUSP coastline GeoJSON drawn as an inline SVG with
the glow treatment, which is also the WebGL fallback (§ 13). FE-25 replaces
it with the live night map (the basemap style's night variant: land
`--panel`, no labels below zoom 9, coastline glow, animated streamlines
from the latest fresh current frame; the PNG relief layer was dropped on
2026-10-07, § 3A.2) and keeps the SVG as the fallback. The landing never
loads `three`. Over it, left-aligned, DM Sans display: the headline "Know the
water before you leave the dock.", the input "Where are you launching?"
with "Use my location", the profile pills; along the bottom the live readout
strip (wind, swell, water, tide, fleet line, freshness) in the same tiles as
the brief at a smaller size; on the right edge the layer dots (one per rail
entry, hover shows the name, click toggles the preview); a minimal nav
(Fleet, Reports, How it's built, Sign in). One footer line (§ 12).

The readings come from the same feeds the app uses for the default region
(Morro Bay while it is the only active region; the landing's region follows
the port input once typed). Each tile links to the app at that reading.

As built by FE-07 (2026-10-07): the eyebrow, headline, paragraph and footer
line are static in `dist/landing.html`, so the largest paint waits for no
module; `web/landing/main.tsx` renders the shoreline, nav, readout, pills,
port input and layer dots into hosts around them. The readout sits right
under the paragraph rather than along the bottom, because the port list
pushes a bottom strip below the fold and D4 asks for sourced readings
before any choice. Wind, swell and water come from the live conditions
feed (NDBC 46028 and 46215), tide from the CO-OPS water level at Port San
Luis, each stale past its source's own limit (a source that gives none
shows its age without a stale threshold). These are fixed stations, not
the visitor's launch: each buoy's basis gives its distance and bearing
from the harbor (the wind buoy is about 56 nm WNW, offshore, not a harbor
reading), and the tide basis carries the region's `tide_note`. One link
under the strip opens the app's Conditions view instead of a link per tile
(a tile holds its basis disclosure, which cannot sit inside a link). The
shoreline is FE-10's CUSP import, `catalog/shoreline/morro-bay.geojson`,
projected into one SVG path by `scripts/build_landing_shoreline.mjs`; the
footer credit is rendered from that generated module. The fleet line
renders only when the page is given one; no public fleet summary exists
yet, so it stays hidden.

### URL structure

Ranked in open-questions Q2; the plan assumes:

- `/` is the landing for a visitor with no saved port and no area
  parameters. With area parameters (`region`, `coast`, `view`, `spot`,
  `target`, `focus`, or a hash the v1 shell used), the Worker serves the app
  shell at `/` so that every shared link keeps working. With a saved port
  and no parameters, the landing's first module replaces the location with
  `/map?region=…&profile=…` (CSP forbids inline scripts; the hero renders
  for the few milliseconds before the module runs).
- `/map` is the app. `/map` without `region` uses the saved port or
  redirects to `/`.
- `/boats`, `/boats/<slug>`, `/sources`, `/privacy`, `/terms`, `/admin`
  are unchanged.

### Port chooser and first run

- The landing input lists the ports of `catalog/home-ports.json`, served
  as `data/home-ports.json` (name, region, match position); "Use my location" calls `navigator.geolocation` and
  `closestPort` (ported from `home-port.js`) with the 75 nm rule; both
  save `skippercast-home-port-v1` exactly as today so v1 and v2 share the
  preference.
- First run is the profile choice only (D11). The boat preset step from
  `first-run.js` moves to the account menu's boat profile; "tomorrow's
  answer" is the brief headline.
- The app's command bar always offers the port and the profile, so a wrong
  first choice costs one click.

## 8. State and profiles

`web/state.ts` keeps the URL as the source of truth and adds:

| Key | Values | Stored | Notes |
| --- | --- | --- | --- |
| `profile` | `boat`, `shore`, `spear` | yes (`skippercast-profile-v1`) | default `boat` |
| `view` | `coast`, `conditions`, `history`, `fleet`, `reports` | no | masthead and mobile tabs |
| `day` | `YYYY-MM-DD` | no | time dock day chips; `hour` stays ISO UTC |
| `layers` | comma list of rail ids | yes (`skippercast-layers-v1`) | default per profile |
| `area` | coast or focus id | no | replaces `focus` for the command bar; `focus` still read |
| `base` | `night`, `chart`, `aerial` | yes | aerial only where NAIP is configured |
| `presentation`, `current`, `habitat` | see § 3A.3 | see § 3A.3 | added by FE-73; already written by v1 |

Fish links (`place`, `mode`, `species`, `layer`) are translated by
`web/fish-links.ts` before the store reads them (Codex, #379); explicit
SkipperCast keys win.

`?view=` is shared with v1, which writes the map position as
`lat,lng,zoom`. The store keeps the raw value in `view` for v1 and sets
`appView` only when the value names a masthead view (otherwise `coast`), so
one parameter serves both shells; FE-11 picks the v2 key for the map
position. `?layers=none` is an empty rail; an absent key restores the stored
list, then the profile's defaults. A key the URL names is persisted, so a
link that omits it next time restores the last choice (FE-04).

Region change no longer reloads: `lockRegion()` is a no-op under
`configureStore({v2: true})` (ADR 0005 item 3); the engine swaps
region-bound sources and the brief rebuilds from the new region's feeds. v1
keeps the reload until FE-61.

### Profile semantics (ported from `fish` `experience.ts`, `daily.ts`, `opportunity.ts`)

| | Boat | Shore | Spear |
| --- | --- | --- | --- |
| Default target | lingcod | surfperch | cabezon (shallow reef) |
| Depth limit | 300 ft | none (shore runs) | 60 ft |
| Species list | region species whose plans have a boat method | surfperch, halibut and region species with a shore method | region species with a dive method within 60 ft |
| "Where to look" | reef marks and seafloor candidates by habitat fit within the limit | ESI sandy-shore runs ranked by access, rules and conditions clocks (`opportunity.ts` priority 0–3) | reef marks within 60 ft, nearest fresh nearshore site first |
| Swell tile | offshore buoy / forecast | nearest fresh nearshore model site | nearest fresh nearshore model site |
| Default layers | Seafloor, Currents | Swell, Water temp | Seafloor, Swell |
| Caveat | "Habitat describes a place to look; fish presence is unverified." | "Offshore seas do not measure breakers at your beach; check surf, access and water quality." | "In-water visibility is unverified; surface currents cannot clear a dive." |
| Search plans | plans with boat methods | plans with shore methods | plans with dive methods |

`web/profile.ts` exports these as data so that tests cover them without the
DOM. Species search plans (`search-plans.js`) are filtered by method in the
wrapper, not edited.

## 9. Map layers

`web/map/layers.ts` registers each layer with: id, rail entry (or base, or
always-on), the presentations it draws in (`chart`, `terrain`, or both;
§ 3A.2), draw order, sources, time behaviour (`static`, `hour`,
`observed`), legend entries, the **basis** sentence (one sentence naming the
product, its resolution and its age rule, shown in the rail's info popover
and the legend), gating, and the `fish` module it ports. Draw order, bottom
to top: basemap, aerial, ENC chart, relief, water temperature field, contours, swell
field, MPAs, habitat polygons, shore runs, seafloor candidates, charter
grounds, commercial AIS, fleet heat, fleet tracks, fleet events, currents
streamlines (canvas), clouds (raster, above fields so the loop reads as
sky), marks, selection, coastline glow.

| Layer | Rail | Source | Rendering | Time | Basis (shape) | Task |
| --- | --- | --- | --- | --- | --- | --- |
| Basemap | base | Protomaps extract on R2 (§ 4) | token style; night variant on the landing | static | "OpenStreetMap data, Protomaps build <date>." | FE-10 |
| Coastline glow | always | NOAA CUSP extract per region (GeoJSON, § 11 row) | blurred line under a crisp line, as `fish` | static | "NOAA NGS CUSP shoreline, 1994–2010 sources." | FE-11 |
| Terrain relief (2D and 3D) | Seafloor (terrain options) | `packages/coast` regional terrain and imagery, SHA-256-verified in the browser (`regional.ts`), size- and range-bounded (no hashing) by `server/coast-data.ts` from the Fish Worker until FE-85 moves them to R2 and adds server-side manifest verification | the Three scene of the Terrain presentations; relief, water and contour controls move to the rail in FE-80 | static | the renderer's existing source and coverage lines | #385, #392 (on `main`); FE-71, FE-79, FE-80. The PNG relief raster (FE-13, FE-26) is dropped |
| Seafloor candidates and cells | Seafloor (option) | existing `tiles/seafloor/seafloor-<region>.pmtiles` | vector fill by terrain grade or species fit (existing views) | static | existing seafloor sentence | FE-14 |
| Currents | Currents (source choice `?current=`) | `/api/coast/ocean` current fields where a report binds; `habitat-tiles/wcofs-surface-forecast-*.json` and HFR frames elsewhere; gates from `packages/coast` `selectCurrentFrame` and `selectedCurrent` through `frames.ts`; Terrain: `setCurrentLayer` | canvas streamlines from `packages/coast/src/map/surface-field.ts`: screen-spaced seeds, bounded midpoint integration through the interpolated field, dashed `--flow`, `--flow-fast` above the 80th percentile speed, clipped by the land mask; faint source dots; click reading | hour (forecast) / observed (radar) | "WCOFS surface forecast, about 4 km, issued <age>." or "HF radar, 6 km, observed <age>." | FE-15 |
| Water temp | Water temp | `/api/coast/report` `spatial.surfaceTemperature` where a report binds, named by the report's status for its source id (NASA JPL MUR in Fish's report; NOAA Geo-Polar Blended in SkipperCast's own, FE-87); `habitat-tiles/sst-analysis-*.json` (MUR) elsewhere ([#491](https://github.com/Grahammmm/skippercast/issues/491)) | image source texture ≤ 1,024 px from `packages/coast` `surfaceField`, filled with pixels (no request), feathered inward at gaps; `fieldContours` every 0.5 °F, labelled at whole degrees with the unit; click reading with analysis time and error | observed (daily analysis, 72 h limit) | "<product> daily analysis on a 0.01° grid sampled every 0.02°, for <date> (<age> old), with an analysis error of <low> °F to <high> °F." | FE-16 |
| Swell | Swell | forecast matrix grid (`forecast-matrix.js` data); nearshore model sites from the coast report where one binds (`presentation.ts` `freshNearshore`), from FE-40 after FE-84 | field texture of significant height with period isolines; direction as short strokes at low density, never per-cell arrows; nearshore sites as rings sized by height | hour | "Model wave forecast on the region grid, issued <age>; nearshore sites from the CDIP MOP model." | FE-17 (field), FE-27 (nearshore rings) |
| Habitat and marks | always (zoom ≥ 10) | existing survey habitat, geology, reef marks (GeoJSON from the region's `assets`) | habitat as fills at 0.25 with token hue by class; geology as dashed outline; marks as rings with a fit badge on a 44 px target; selected mark highlighted | static | existing sentences per source; a terrain selection keeps the renderer's evidence lines | FE-18 (atlas `?spot=` and coast `?habitat=` in one mark card, one selected at a time) |
| MPAs | always | CDFW ds582 (existing) | `--mpa-fill` 0.08, dashed `--mpa-line`; name label at zoom ≥ 11 | static | "CDFW marine protected areas, ds582; boundaries are context, rules are in the regulations page." | FE-19 |
| Shore runs | with `profile=shore` | ESI runs and access points: `slo-shore-habitat.geojson` through the bridge today, FE-43's import later; in Terrain the renderer draws its own shore features | run as a wide soft line in `--amber` 0.6 with priority tint; access points as pins | static | "ESI 2006 sandy-shore runs; access points from the Coastal Commission inventory, checked <date>." | FE-36 |
| Charter grounds | Fleet | `charter-grounds.json` | hatched polygons, label on hover | static | existing sentence | FE-21 |
| Commercial AIS 2024 | Fleet (option) | `commercial-ais-effort.geojson` | heat fill in `--amber` | static | existing sentence (`commercial-ais.html`) | FE-21 |
| Charter fleet activity | Fleet (admin) | `/api/fleet/map/*` | events sized by dwell, tracks by segment, heat cells, all `--amber` family | static (filters) | "Inferred from movement; filters in the Fleet view." | FE-24 |
| Clouds | Clouds | nowCOAST GOES longwave WMS through `packages/coast` `cloudSource`; frame times from `/api/coast/ocean` `cloud.availableTimes` where a report binds, the FE-44 index elsewhere | raster 512 px tiles, monochrome contrast, loop over observed frames only, 90-minute age gate, withheld on future days | observed | "GOES infrared, observed <time>; a loop of real frames, never a forecast." | FE-22 |
| Aerial | base (Chart) | USGS NAIP ImageServer (live tiles) through `packages/coast` `naipSource`; the terrain drapes its own reviewed imagery | raster at 0.92 opacity, desaturated | static | "USGS/USDA NAIP natural-colour mosaic, dated imagery." | FE-23 |
| Chart | base | NOAA ENC WMS (existing) | raster, zoom ≥ 10 | static | existing sentence | FE-11 |

Rules for every layer:

- Missing data stays blank. No nearest-neighbour fill, no extrapolation
  past the grid, no bridging of gaps (`surface-field.ts` rule).
- A frame outside its age gate is withheld and the rail entry shows "no
  fresh frame" with the last valid time.
- Every rendering reads colours through `web/map/palette.ts`.
- Each layer has a Node test for its data-to-feature step and an e2e
  check that toggling it adds and removes its MapLibre layers.
- Animation (streamlines, cloud loop, play) pauses when the page is hidden
  and under `prefers-reduced-motion`.

### Selected-mark card

One card for every selectable thing (reef mark, seafloor candidate,
habitat polygon, shore run, charter ground, fleet event, field reading):
name, kind, the reading or fit line, the source and age line, one action
row (Add to trip, GPX, Regulations) and a "basis" link. Renders in the map
corner on desktop and as the sheet's peek on mobile.

## 10. Brief and charts

**Amended 2026-10-07 (§ 3A.2).** The brief model is
`packages/coast/src/daily.ts` (`buildDaily`) behind the adapter
`web/brief/model.ts`, used where a coast report binds (Morro Bay and
Cambria today); elsewhere the adapter builds the same fields from
SkipperCast's regional feeds, and `fish`'s report never fills or shortens
the seven-day forecast. Charts are `packages/coast/src/charts/series.ts`
(`chart`, SVG strings) mounted through `CoastMarkup`; History is
`ui/history.ts` `historyView` over `/api/coast/history`; catch cards are
`ui/catches.ts`. The contracts below stand; only "ported" becomes
"imported".

### The daily brief (`web/brief/model.ts` over `packages/coast/src/daily.ts`)

Inputs: the region's forecast hours (wind, gust, seas, period, air, rain,
cloud), alerts, sunrise and sunset, tides (curve and events), the latest
buoy observation, the nearest fresh nearshore site, beach notices, the
profile. Outputs:

- **Headline** by the first matching rule: active marine alert → its event
  name; after sunset today → "One last look. Plan the morning."; max seas
  ≥ 5 ft → "Swell sets the terms today."; max wind ≥ 12 kt → "Find your
  water before the wind."; spear → "Read the swell. Check the visibility.";
  otherwise "A clearer picture of your coast." Rules are data in
  `daily.ts` with a table test.
- **Deck** sentence: wind range, seas range and period, plus the
  provisional note when the forecast is an outlook.
- **Four tiles** (`Tiles.tsx`): Wind (kt, direction, gust; source NWS
  forecast hour or station observation), Swell (ft and period; offshore
  forecast for boat, nearest nearshore site for shore and spear), Water
  (°F; buoy observation with its time, or "no fresh buoy"), Tide (ft and
  trend from the station curve; the reference level sits in the tile's
  basis popover). Each tile carries the source and age in mono and a
  stale state past its limit.
- **Tide sparkline** (`TideSpark.tsx`): `series` in `mini` mode with night
  shading and the high and low events listed under it.
- **Where to look** (`WhereToLook.tsx`): the top four from the profile's
  ranking (§ 8) with name, distance from the port, depth band, fit badge
  (`SpotConfidence` reused), one reason line; clicking selects the mark.
- **Lower-exposure window**: the quietest two hours (`quietestHours`),
  labelled "lower exposure", never "best bite".
- **One caveat** from the profile table, plus a beach notice link when the
  county feed reports one for the area.
- **Fleet line**: "3 boats reported from Morro Bay in the last 7 days" from
  the landing-reports feed, linking to the Reports page; absent when no
  report is within seven days.

### Series chart (`packages/coast/src/charts/series.ts`, mounted by `CoastMarkup`)

A Preact component with the same contract: rows with label, unit, colour
token, points, optional min and max and `gapMs`; one time axis; night
shading; quiet-window shading; a cursor bound to the `hour` signal that
also moves the map; independent row scales with their extremes on the right;
"No supported samples" for an empty row; paths break at gaps; `mini` mode
for sparklines; `role="img"` with a label listing rows and units.
Colours come from tokens through the `--coast-*` bridge (§ 3A.4); the
hard-coded values in `series.ts` are mapped (`#64e4c0` → `--mint`,
`#60b9ff` → `--blue`, `#eabd76` → `--amber`, `#ff9580` → `--coral`, the
rest to `--muted` tints) as `var(--coast-…, literal)` so v1 keeps its look.
The cursor follows `hour`; the host listens for the chart's pointer events
and writes `hour`, so the renderer stays a pure function.

### Conditions view

Heading, a summary row for the selected hour, the stacked chart (Wind,
Gusts, Offshore, Nearshore, Tide, Air, Cloud) in a horizontally scrollable
region on mobile, a caption line, tide events, and the profile's
"before you go" notes with the CDFW rules link. The time dock stays
visible and drives the cursor. The existing `meteogram-core.js` chart stays
for v1 until FE-61. Rows come from SkipperCast's seven-day dual-model
forecast for every region, plus the coast report's local rows (nearshore,
tide events, beach notices) only where a report binds, each with its own
clock, as v1's `coast-conditions.js` does since #393. The surface-current
choice (`?current=`) is the same control as the map's.

### History view

Station and metric pickers (46028, 46215 and the region's other stations
once the history collector covers them), a day range (7, 14, 45, the
 ranges FE-42 publishes), the
recent hourly means line over the monthly p10 / median / p90 bands from
the history feed (§ 11), with sample counts, years with data and missing
coverage shown as text. Copy: "recorded history", never "climatology".
Since #385 and #393 this is `packages/coast` `historyView` over
`/api/coast/history` (46028 and 46215 today); a region without a history
binding shows the unavailable state.

## 11. Data ingest for the `fish`-only sources

**Amended 2026-10-07.** The v2 shell no longer waits for these collectors:
until they exist, the coast report, ocean and history snapshots, the
habitat release and the terrain assets reach SkipperCast through Codex's
bounded bridge to the Fish Worker (`server/coast-data.ts`,
`docs/coastal-service.md`), SLO only. The collectors below are still
required to retire `fish`, and each now has one more acceptance rule: its
output matches the `packages/coast` type the client already reads
(`Enrichment` nearshore and water quality, `HistoryBundle`, `CloudImage`,
the shore-habitat GeoJSON), so FE-84 can switch the bridge's upstream to
SkipperCast feeds without a client change. FE-85 moves the terrain,
imagery and habitat assets. Under the ownership proposal (§ 3A.5) these are
Codex's tasks; the bathymetry row's PNG relief (FE-13, FE-26) is dropped in
favour of the renderer's terrain.

Each source becomes a SkipperCast collector under
`src/skippercast/pipeline/`, runs in an existing workflow on the owner's
runner (`vars.DATA_RUNNER`), publishes to the `conditions` or `data`
branch through the existing atomic snapshot step, and reads from the client
through `/feeds/`. Each gets a `catalog/sources.json` entry with
`rights.license`, `rights.commercial_use`, `rights.attribution_required` and
`commercial_note` (the contract test rejects entries without them), and a
row in `docs/legal/data-rights-register.md` that the **Owner** adds (D16).
Rights notes are carried from `fish/NOTICE.md`.

| Source | Collector | Workflow | Feed | Rights note (from `fish`) | Register row to add | Task |
| --- | --- | --- | --- | --- | --- | --- |
| CDIP MOP alongshore nearshore model, five SLO sites (THREDDS OPeNDAP) | `pipeline/cdip_nearshore.py`: per-site identity and coordinate checks, three-hour series, quality masks | `live-conditions.yml` (hourly) | `conditions/regions/<id>/nearshore.json` | Scripps / UCSD metadata permits redistribution with producer credit; keep native clocks and masks; modelled height is not breakers | `cdip-mop` · redistributable with credit · commercial: allowed (verify terms page) · attribution yes | FE-40 |
| SLO County beach health (SurfSafeSLO ArcGIS feature service, county page) | `pipeline/beach_health.py`: full-count check, WGS84 check, in-county geometry, status text only | `live-conditions.yml` (about hourly; the coast report treats statuses older than 3 h as unavailable, so the daily job alone would be too slow) | `conditions/regions/<id>/beach-health.json` | factual statuses and links only; no sample dates in the feed, none invented; no dashboard design copied | `slo-beach-water-quality` (the id `packages/coast` reads) · public facts · commercial: facts only (owner to confirm) · attribution yes | FE-41 |
| NDBC standard-met annual archives, 46028 (1983–2025) and 46215 (2004–2025) | `pipeline/ndbc_history.py`: SHA-checked annual checkpoints under `var/`, monthly p10 / median / p90 per metric with counts and coverage, recent 45-day means | new `buoy-history.yml` (monthly full, weekly recent) | `data/regions/<id>/history.json` | NOAA public data; aggregations are SkipperCast's; retain counts and missing coverage | `ndbc-history` · public domain · commercial: allowed · attribution yes | FE-42 |
| ESI 2006 Central California sandy-shore runs (NOAA ORR, ArcGIS) and California Coastal Commission access points | `scripts/collect_shore_habitat.py` (reviewed import, not hourly): run geometry with source year, access points with ids and links, review dates in the asset | manual, like `import-shore-habitat.mjs` | `catalog/shore-habitat/<region>.geojson` → `dist/regions/<id>/shore-habitat.geojson` | ESI: no constraints stated beyond mapping limits, attribution encouraged; CCC: facts only, no photos or descriptions; access point is not a current-access certification; rule and access reviews are dated and expire | `noaa-esi-2006` · public · commercial: allowed · attribution yes; `ccc-access-points` · facts only · commercial: owner to confirm · attribution yes | FE-43 |
| GOES longwave imagery (nowCOAST WMS) | `pipeline/goes_frames.py`: GetCapabilities time list only; frames are fetched live by the browser as WMS tiles pinned to listed times | `live-conditions.yml` | `conditions/goes-times.json` | NOAA public; brightness is not cloud fraction; frames pinned to acquisition times, never `current` | `noaa-goes-nowcoast` · public domain · commercial: allowed · attribution yes | FE-44 |
| NOAA NGS CUSP shoreline (Continually Updated Shoreline Product, NOAA Shoreline Data Explorer vector tiles at zoom 12) | `scripts/shoreline/import_cusp.py`: per-region bbox extract, lines clipped to their own tile and the region, zoom-12 display quantisation (about 2 m at 35° N) recorded, source dates kept per feature, only NOAA-created features kept (others counted) | manual, re-run when a region is added | `catalog/shoreline/<region>.geojson` → `dist/regions/<id>/shoreline.geojson` | NOAA public domain; source dates 1994–2010 kept, display quantisation is separate from source accuracy, some tiles unavailable; NOAA policy does not cover unreviewed outside contributors in other regions, so each new region's extract is reviewed | `noaa-cusp-shoreline` · public domain · commercial: allowed (per-region review) · attribution yes | FE-10 |
| NAIP natural-colour mosaic (USGS ImageServer) | none (live tiles); `regions/<id>/region.json` gains `basemap.aerial` (`source`, `checked_at`, the `acquired` window from the publisher's catalog, `note`) where coverage was checked; `validate_region` checks it against the catalog | — | — | USGS/USDA attribution; dated land imagery, not live or underwater; only the fixed USGS service | `usgs-naip` · public domain · commercial: allowed · attribution yes | FE-45 |
| **Dropped 2026-10-07 (FE-13, FE-26; § 3A.2):** USGS bathymetry grids as PNG PMTiles | `seafloor/relief.py` (ported `import-bathymetry.py`): approved ZIP/COG hashes, nearest sampling, transparent gaps | `seafloor.yml` dispatch | `tiles/relief/relief-<region>.pmtiles` + manifest on R2 | public domain; credit USGS, CSUMB Seafloor Mapping Lab, UC CISR; no exact-depth or navigation claim | existing USGS rows; add the credit line | FE-13, FE-26 |

Already in SkipperCast, so no ingest task: Port San Luis tides (`noaa-tides`),
HFR and WCOFS currents, MUR surface temperature, MPAs, NWS forecast and
alerts, landing reports (the catch cards use the existing feed with the
same facts-only review), Natural Earth is replaced by the basemap.
Corrected 2026-10-08 (FE-87): the report's NWS gridpoint forecasts, the active
alerts it filters by area and the 6-minute tide curve had no SkipperCast
collector, so `coast_report.py` ports them from `fish`; Morro Bay's
sea-surface temperature is NOAA Geo-Polar Blended (`noaa-blended-sst`), not MUR.

CSP changes (each in the task that needs it, with
`tests/test_security_headers.mjs` updated): `IMAGE_ORIGINS` gains
`https://imagery.nationalmap.gov` (FE-23/45) and `https://nowcoast.noaa.gov`
(FE-22); `CONNECT_ORIGINS` gains nothing new, because every feed is read
through `/feeds/` or an existing origin.

## 12. Copy, voice and claims

### Voice guide (D3)

Write as the analyst who fishes: specific, sourced, aged, calm.

- Lead with the reading, then the source and age: "12 kt NW, gusting 18.
  NWS forecast, issued 2 h ago."
- Name the product once, in the basis sentence, never in every label.
- Say what a thing is, not what it is not, except in the one caveat.
- Habitat is a place to look. "Fits lingcod habitat 3 of 3" is the
  strongest wording; no word that claims fish will be there (chance,
  catch rate, "productive", "best spot").
- Prefer verbs the reader does: "Scrub the hour", "Add to trip".
- Numbers in mono with units; ages as "4 min", "2 h", "3 d"; times in the
  region's zone with the zone shown once in the dock.
- Headlines are short sentences with a full stop: "Swell sets the terms
  today."
- Never promise fish, clearance, safety or a bite.

### Disclaimer policy (D13)

- One footer line per page: "Forecasts, observations and habitat carry
  separate clocks; check the rules before you fish."
- One basis sentence per layer and per tile, in a popover or `<details>`,
  naming product, resolution and age rule.
- One caveat in the brief, from the profile table.
- Method names and reference levels live in the basis popovers (the copy
  lint's disclosure rule); the legal pages hold the full wording.
- Nothing else repeats a limitation. `fish`'s four-sentence "is not" block
  in its sources sheet becomes one sentence on the sources page.

### Passing the copy lint

`scripts/check_copy.mjs` lints `dist/*.html`, `dist/*.js` and `web/`:
no two consecutive sentences with "not"; model and reference-level names
only inside disclosures. Every basis sentence renders inside a `<details>`
or the confidence badge's why. The baseline only shrinks; FE-61 removes the
v1 entries it deletes.

## 13. Accessibility, performance and testing

- **Contrast** 4.5:1 for every text pair (§ 5); focus rings on every
  control; the rail, dock, sheet and card are keyboard operable; axe in
  e2e stays clean on the landing and app.
- **Motion** respects `prefers-reduced-motion`; the play button still
  steps frames.
- **Budgets** (checked by `scripts/check_client.mjs` and
  `e2e/startup.spec.ts`): landing JavaScript ≤ 180 KB gzipped on first
  paint (MapLibre loads after first paint); app initial JavaScript ≤ 350 KB
  gzipped; startup JSON for Morro Bay keeps the existing budget file and
  lowers `max_bytes` toward the 400 KB target as layers move to tiles;
  Largest Contentful Paint ≤ 2.5 s on Playwright's throttled mobile profile
  against the built site; basemap tile fetch per session ≤ 150 tiles at the
  default view. `three` and `CoastViewer` load only by dynamic import when a
  Terrain presentation is first chosen; `check_client.mjs` fails if the app
  entry's static imports reach `three`. Terrain streaming keeps the
  renderer's own byte bounds.
- **Tests**: Node tests for every ported module (`surface-field`,
  `frames`, `series`, `daily`, `profile`, `layers` registry, `palette`);
  table tests from `fish`'s test suite ported with their fixtures where
  synthetic; e2e specs for the landing (readings render, input, location
  refusal), the app shell at both widths, each rail toggle, the time dock,
  profile switching, and the flag routing; Python tests for each collector
  with offline fixtures; contract tests for the new catalog entries.
- **Browsers**: current Chrome, Safari (iOS 16+), Firefox; MapLibre needs
  WebGL, so the landing shows a static shoreline SVG and the readings when
  WebGL is unavailable, and the app shows the brief with a "map unavailable"
  panel.

## 14. Feature flag, routing and rollback

- `UI_V2` is a runtime Worker variable copied by `scripts/wrangler_config.mjs`
  and passed by `deploy-cloudflare.yml`, default off, parsed in `server/env.ts`
  like `FLEET_ENABLED`.
- `server/routes/assets.ts`: `/` serves `landing.html` and `/map` serves
  `app.html` when the flag is on or the request has `?ui=v2`; `?ui=v1` forces
  the v1 shell; with the flag off and no switch, `/map` answers 404 and `/`
  serves `index.html` byte-identical to today. The switch is a query
  parameter only (no cookie; the site is cookie-less for visitors), so a
  preview link is shareable and the choice never persists silently.
- Rollback: unset the variable (the deploy workflow's variable step), or
  `?ui=v1` per request. After FE-60 the variable defaults on; FE-61 removes
  the v1 shell and the switch; the release is tagged so the rollback
  runbook applies.

## 15. Retiring `fish`

Before the owner archives and deletes the repository (FE-62), verify live
on skippercast.com with `UI_V2` on, and link each item in the PR:

1. Landing and app render at `/` and `/map` for Morro Bay with every rail
   layer toggling (basemap, currents, water temperature, swell, MPAs,
   marks, clouds, aerial where configured) and the Terrain 2D and 3D
   presentations preserving place, target, profile, hour and selection;
   `/coast` and every Fish link open the same app (FE-78). No second map,
   picker or timeline is offered for the same context.
2. Boat, Shore and Spear each change the species list, depth limit,
   "where to look" and caveat as § 8 says.
3. The brief shows the four tiles with sources and ages, the tide curve
   with events, the lower-exposure window and the fleet line.
4. Conditions and History views render; History shows 46028 and 46215
   bands from the SkipperCast history feed.
5. Shore runs and access points render with their review dates; beach
   notices show when the county feed reports one.
6. The cloud loop plays real frames within the age gate and is withheld
   on future days.
7. Every `fish` data source in § 11 has a catalog entry, a register row
   (**Owner**) and a collector run visible in the workflow logs.
8. The terrain, imagery and habitat assets are served from SkipperCast's
   own storage with their SHA manifest (FE-85), the bridge reads SkipperCast
   feeds instead of the Fish Worker (FE-84 for nearshore, beach, ocean and
   history; FE-87 for the rest of the report), and distinct persisted refresh
   runs are witnessed; `docs/FISH-MERGE-STATUS.md`'s acceptance matrix is
   complete.
9. `docs/archive/fish/` holds: `fish/docs/*.md` (architecture, surface
   layer design, history pipeline, species opportunity, bathymetry
   overlay, independent review, quality review, launch), `fish/research/`
   Markdown and JSON receipts (source registry, spatial review, reviewed
   catch binding, the dated validation and acceptance JSON), `NOTICE.md`
   and `README.md`, each prefixed with a one-paragraph note that it is
   historical and that the live truth is SkipperCast's docs. Screenshots
   (`research/*/**.jpg`) are kept only where a document cites them. Nothing
   under `fish/public/data` is copied: SkipperCast regenerates every feed.
10. `fish`'s Cloudflare Worker, D1 database and R2 buckets are listed
    with their names for the owner to delete after the repository.

**Owner** steps, in order: confirm the checklist, archive the repository on
GitHub, delete the Cloudflare resources, delete the repository, release the
`slofishreport.com` redirect decision (open-questions Q10).

## 16. Costs

| Item | Monthly | Note |
| --- | --- | --- |
| Basemap on R2 | ≤ $1 | § 4; storage cents, reads mostly edge-cached |
| Terrain assets on R2 (FE-85) | cents | sized by the mapping pipeline's receipts; replaces the dropped relief tiles |
| Fonts, icons, bundles | $0 | static assets on Workers |
| New collectors | $0 | run on the owner's runner in existing workflows |
| NAIP, GOES, CDIP, county, NDBC | $0 | public services; NAIP and GOES tiles are fetched by the browser |
| Paid options | — | listed only in open-questions (hosted tiles, a CDN for NAIP) |

## 17. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| The basemap extract is larger or slower to build than estimated | FE-10 measures first; fallback to maximum zoom 13 in preview regions, then to a hosted service (Q1 option 2) |
| Two shells drift while both exist | Shared preference keys, shared feeds, FE-60 within two releases of FE-25; the status log records the gap |
| MapLibre memory on older phones with five fields on | Textures capped at 1,024 px; fields rebuild only on frame, camera or viewport change; default layers per profile are two |
| Ported `fish` code carries single-county assumptions (`countyId === 'slo'`) | Every port reads region config; tests run against two region fixtures |
| Copy regressions (claims stronger than evidence) | The wording rules at the top; review checks the basis sentences; copy lint |
| Rights of the Coastal Commission inventory and the county feed for a paid product | Facts only, owner rows in the register before FE-60, open-questions Q8 |
| Startup JSON budget grows with new feeds | Feeds are lazy per rail entry; the budget file's `max_bytes` only decreases |
| The owner's `fish` deletion loses receipts | § 15 item 9 copies them first; FE-62 is blocked until the copy PR merges |
| v2 and Codex's v1 coastal work change the same files in parallel | § 3A.6 hot-spot rules; the coordination issue; the `packages/coast` exports v2 uses are a public API |
| The renderer's ~40 template ids make a host-chrome mount a large refactor | FE-70 keeps the template inside the embed first; FE-79 moves controls one group at a time |
| Three plus terrain on older phones | Chart is the default presentation; terrain is lazy, bounded and stops rendering when hidden (`setVisible`) |
| Restyling `packages/coast` changes v1's look | fallbacks equal today's literals and the computed-style check of § 3A.4 |
| The Fish Worker bridge is a live dependency | FE-84, FE-85 and FE-87 before FE-62; the bridge refuses non-SLO regions, so nothing else depends on it |

## 18. Phasing

See [dev-plan.md](dev-plan.md). In short: Phase 0 makes the system and
shells behind the flag; Phase 1 gives the shell its map; Phase 2 makes it
profile-aware with the brief and charts; Phase 3 brings the `fish` sources
into the pipelines; Phase 4 moves the remaining features in; Phase 5 flips
the flag, deletes the old shell and retires `fish`.
