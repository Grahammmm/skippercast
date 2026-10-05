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
wrong, fix this section in the same PR.

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
  lines) contain 377 distinct hex colours and 245 `var(--…)` uses. No
  webfont is loaded; the CSP has `font-src 'self'`. Icons are unicode
  glyphs (922 arrow, target and dot characters across `dist/*.js` and
  `index.html`).
- **Overlays.** Weather is drawn as translucent `L.circle`s
  (`dist/weather-ui.js` line 363) with "↑" characters rotated for direction
  (line 383); currents reuse the same marker style. Charts are hand-built SVG
  in `dist/meteogram-core.js` (265 lines) drawn by `meteogram-ui.js` into a
  Preact card.
- **Preact.** `web/islands.tsx` mounts seven components (`web/components/`)
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
  advisory link, footer. `src/ui/icons.ts`: 31 stroke icons (the brief said 34; the file has 31 entries).
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

### Module layout

```
web/
  tokens.css            the visual system (§ 5); loaded first by every v2 page
  fonts/                DM Sans and JetBrains Mono woff2 + OFL licences
  ui/                   icons.tsx, Button, Tile, Chip, Sheet, Rail, Dock (§ 6)
  state.ts              existing store, extended: profile, day, layers, area (§ 8)
  profile.ts            Boat / Shore / Spear semantics (§ 8)
  map/
    engine.ts           MapLibre init, PMTiles protocol, controls, resize, errors
    style.ts            basemap style built from tokens (§ 4)
    layers.ts           layer registry: id, order, sources, basis, legend, time
    relief.ts  flow.ts  field.ts  marks.ts  mpa.ts  swell.ts  clouds.ts  fleet.ts
    surface-field.ts    ported from fish (interpolation, contours, ramps)
    frames.ts           ported from fish map-sources.ts (frame selection, age gates)
  brief/
    daily.ts            ported from fish daily.ts (headline, tiles, windows, caveats)
    Brief.tsx  Tiles.tsx  WhereToLook.tsx  TideSpark.tsx
  charts/
    series.tsx          ported from fish series.ts as a Preact component
    Conditions.tsx  History.tsx
  app/
    App.tsx  Masthead.tsx  CommandBar.tsx  Desktop.tsx  Mobile.tsx  TimeDock.tsx
    LayerRail.tsx  Legend.tsx  MarkCard.tsx  views/{Coast,Conditions,History,Fleet}.tsx
  landing/
    Landing.tsx  Readout.tsx  PortInput.tsx  ProfilePills.tsx  LayerDots.tsx
dist/
  app.html              the v2 app shell entry (/map)
  landing.html          the v2 landing entry (/)
  index.html            the v1 shell, untouched until FE-61
```

Rules: product code never imports `research/`; `web/` modules import
`dist/*.js` only through typed wrappers during the migration (the Node
tests import `dist/*.js` directly, so those modules keep their exports until
FE-61 deletes them); every new component reads colour, type, spacing and
radius from `var(--…)`; no `innerHTML` in `web/` (Preact renders).

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
open-questions Q4.

## 4. Basemap strategy (cost near zero)

The map needs a quiet vector basemap: coastline, land, harbor and town
labels, roads at high zoom only, no points of interest. Options, best first:

1. **Self-hosted Protomaps extract on R2, served through `/feeds/`
   (recommended, D10).** Build on Hermes with `pmtiles extract` against
   the latest Protomaps planet build, which reads only the needed byte
   ranges (no planet download), for a bounding box per active and preview
   region clipped to the coast, merged into one archive
   `tiles/basemap/ca-coast-<build-date>.pmtiles`. Style: a Protomaps
   "basemaps" style recoloured from the tokens in `web/map/style.ts`; glyphs
   and sprites self-hosted under `dist/basemap/`. Attribution:
   "© OpenStreetMap contributors, © Protomaps" in the legend's attribution
   row (ODbL; the data is used as a map, never redistributed as data).
   - Size, estimated from the Protomaps planet build (about 110–120 GB at
     zoom 15 for the whole planet, concentrated on populated land): a
     California statewide bbox at zoom 15 is in the order of 1–2 GB; the
     fifteen coastal region bboxes at maximum zoom 14 plus a statewide
     overview at maximum zoom 10 are in the order of 300–600 MB. FE-10
     measures the real numbers and records them in its PR and here.
   - Cost at R2 list prices: storage $0.015 per GB-month, so 2 GB is $0.03
     a month; egress is free; Class B reads $0.36 per million after the
     first 10 million a month. A map session fetches 50–150 tiles; the
     Worker's `/feeds/` route already serves PMTiles ranges through the
     edge cache (`server/feeds.ts`), so origin reads are a fraction of tile
     requests. Estimate: under $1 a month at 100,000 sessions.
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
| `--mpa-fill` / `--mpa-line` | `#e8a877` at 0.08 / `#e8b584` dashed | protected areas |
| `--fleet` | `--amber` | fleet events, tracks, heat |
| `--focus` | `--mint` | focus ring (2 px outside) |

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
  `web/map/palette.ts`, which is the one allowed bridge from CSS to JS.
  A baseline file lists nothing: `web/` has few literals today and FE-02
  removes them.
- `scripts/check_contrast.mjs` covers both token files until FE-61.
- `node scripts/check_copy.mjs` already lints `web/`.

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
whole brief) and the hour slider pinned at the sheet's top edge; a four-tab
nav (Coast, Conditions, History, Fleet) under the sheet. The layer rail
collapses to a single button that opens the rail as a sheet. The mark card
replaces the sheet's peek content while a mark is selected.

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

Full-viewport night map on `--bg-deep` (the basemap style's night variant:
land `--panel`, no labels below zoom 9, coastline glow, relief tiles for the
region at 0.5 opacity, animated streamlines from the latest fresh current
frame); over it, left-aligned, DM Sans display: the headline "Know the
water before you leave the dock.", the input "Where are you launching?"
with "Use my location", the profile pills; along the bottom the live readout
strip (wind, swell, water, tide, fleet line, freshness) in the same tiles as
the brief at a smaller size; on the right edge the layer dots (one per rail
entry, hover shows the name, click toggles the preview); a minimal nav
(Fleet, Reports, How it's built, Sign in). One footer line (§ 12).

The readings come from the same feeds the app uses for the default region
(Morro Bay while it is the only active region; the landing's region follows
the port input once typed). Each tile links to the app at that reading.

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

- The landing input lists `data/home-ports.json` (name, region, match
  position); "Use my location" calls `navigator.geolocation` and
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

Region change no longer reloads: `lockRegion()` is removed for v2 (ADR
0005 item 3); the engine swaps region-bound sources and the brief rebuilds
from the new region's feeds. v1 keeps the reload until FE-61.

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
always-on), draw order, sources, time behaviour (`static`, `hour`,
`observed`), legend entries, the **basis** sentence (one sentence naming the
product, its resolution and its age rule, shown in the rail's info popover
and the legend), gating, and the `fish` module it ports. Draw order, bottom
to top: basemap, aerial, relief, water temperature field, contours, swell
field, MPAs, habitat polygons, shore runs, seafloor candidates, charter
grounds, commercial AIS, fleet heat, fleet tracks, fleet events, currents
streamlines (canvas), clouds (raster, above fields so the loop reads as
sky), marks, selection, coastline glow.

| Layer | Rail | Source | Rendering | Time | Basis (shape) | Task |
| --- | --- | --- | --- | --- | --- | --- |
| Basemap | base | Protomaps extract on R2 (§ 4) | token style; night variant on the landing | static | "OpenStreetMap data, Protomaps build <date>." | FE-10 |
| Coastline glow | always | NOAA CUSP extract per region (GeoJSON, built by FE-10 from the same bbox) | blurred line under a crisp line, as `fish` | static | "NOAA NGS CUSP shoreline, 1994–2010 sources." | FE-11 |
| Seafloor relief | Seafloor | PNG PMTiles of USGS grids built by `src/skippercast/seafloor/relief.py` (ported from `fish/scripts/import-bathymetry.py`), on R2 at `tiles/relief/relief-<region>.pmtiles`, served by `server/relief.ts` (ported proxy: approved-source SHA table, 16 MB and 2 MB caps, range checks) | raster with the depth ramp; transparent gaps; nearest sampling | static | "USGS survey relief, nominal 0–300 ft; gaps are unsurveyed." | FE-12 |
| Seafloor candidates and cells | Seafloor (option) | existing `tiles/seafloor/seafloor-<region>.pmtiles` | vector fill by terrain grade or species fit (existing views) | static | existing seafloor sentence | FE-12 |
| Currents | Currents | `habitat-tiles/wcofs-surface-forecast-*.json` and HFR frames, through `frames.ts` gates | canvas streamlines: screen-spaced seeds, bounded midpoint integration through the interpolated field, dashed `--flow`, `--flow-fast` above the 80th percentile speed, clipped by the land mask; faint source dots; click reading | hour (forecast) / observed (radar) | "WCOFS surface forecast, about 4 km, issued <age>." or "HF radar, 6 km, observed <age>." | FE-13 |
| Water temp | Water temp | `habitat-tiles/sst-analysis-*.json` (MUR) | `ImageSource` texture ≤ 1,024 px from `surfaceField`, feathered inward at gaps; 0.5 °F contours with sparse labels; click reading with analysis time and error | observed (daily analysis) | "MUR daily analysis, 0.01°, sampled at 0.02°, <age>." | FE-14 |
| Swell | Swell | forecast matrix grid (`forecast-matrix.js` data) and nearshore model sites (§ 11) | field texture of significant height with period isolines; direction as short strokes at low density, never per-cell arrows; nearshore sites as rings sized by height | hour | "Model wave forecast on the region grid, issued <age>; nearshore sites from the CDIP MOP model." | FE-17 |
| Habitat and marks | always (zoom ≥ 10) | existing survey habitat, geology, reef marks (GeoJSON / PMTiles) | habitat as fills at 0.25 with token hue by class; geology as hatched outline; marks as rings with a fit badge; selected mark highlighted | static | existing sentences per source | FE-15 |
| MPAs | always | CDFW ds582 (existing) | `--mpa-fill` 0.08, dashed `--mpa-line`; name label at zoom ≥ 11 | static | "CDFW marine protected areas, ds582; boundaries are context, rules are in the regulations page." | FE-16 |
| Shore runs | with `profile=shore` | ESI runs and access points (§ 11) | run as a wide soft line in `--amber` 0.6 with priority tint; access points as pins | static | "ESI 2006 sandy-shore runs; access points from the Coastal Commission inventory, checked <date>." | FE-36 |
| Charter grounds | Fleet | `charter-grounds.json` | hatched polygons, label on hover | static | existing sentence | FE-20 |
| Commercial AIS 2024 | Fleet (option) | `commercial-ais-effort.geojson` | heat fill in `--amber` | static | existing sentence (`commercial-ais.html`) | FE-20 |
| Charter fleet activity | Fleet (admin) | `/api/fleet/map/*` | events sized by dwell, tracks by segment, heat cells, all `--amber` family | static (filters) | "Inferred from movement; filters in the Fleet view." | FE-23 |
| Clouds | Clouds | nowCOAST GOES longwave WMS, frames from the times index (§ 11) | raster 512 px tiles, monochrome contrast, loop over observed frames only, 90-minute age gate, withheld on future days | observed | "GOES infrared, observed <time>; a loop of real frames, never a forecast." | FE-21 |
| Aerial | base | USGS NAIP ImageServer (live tiles) | raster at 0.92 opacity, desaturated | static | "USGS/USDA NAIP natural-colour mosaic, dated imagery." | FE-22 |
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

### The daily brief (`web/brief/daily.ts`, ported from `fish/src/daily.ts`)

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

### Series chart (`web/charts/series.tsx`, ported from `fish/src/charts/series.ts`)

A Preact component with the same contract: rows with label, unit, colour
token, points, optional min and max and `gapMs`; one time axis; night
shading; quiet-window shading; a cursor bound to the `hour` signal that
also moves the map; independent row scales with their extremes on the right;
"No supported samples" for an empty row; paths break at gaps; `mini` mode
for sparklines; `role="img"` with a label listing rows and units.
Colours come from tokens via `palette.ts`; the hard-coded values in
`fish` are mapped (`#64e4c0` → `--mint`, `#60b9ff` → `--blue`, `#eabd76` →
`--amber`, `#ff9580` → `--coral`, the rest to `--muted` tints).

### Conditions view

Heading, a summary row for the selected hour, the stacked chart (Wind,
Gusts, Offshore, Nearshore, Tide, Air, Cloud) in a horizontally scrollable
region on mobile, a caption line, tide events, and the profile's
"before you go" notes with the CDFW rules link. The time dock stays
visible and drives the cursor. The existing `meteogram-core.js` chart stays
for v1 until FE-61.

### History view

Station and metric pickers (46028, 46215 and the region's other stations
once the history collector covers them), a day range (14, 45, 90), the
recent hourly means line over the monthly p10 / median / p90 bands from
the history feed (§ 11), with sample counts, years with data and missing
coverage shown as text. Copy: "recorded history", never "climatology".

## 11. Data ingest for the `fish`-only sources

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
| SLO County beach health (SurfSafeSLO ArcGIS feature service, county page) | `pipeline/beach_health.py`: full-count check, WGS84 check, in-county geometry, status text only | `daily-data.yml` and `live-conditions.yml` | `conditions/regions/<id>/beach-health.json` | factual statuses and links only; no sample dates in the feed, none invented; no dashboard design copied | `slo-beach-health` · public facts · commercial: facts only (owner to confirm) · attribution yes | FE-41 |
| NDBC standard-met annual archives, 46028 (1983–2025) and 46215 (2004–2025) | `pipeline/ndbc_history.py`: SHA-checked annual checkpoints under `var/`, monthly p10 / median / p90 per metric with counts and coverage, recent 45-day means | new `buoy-history.yml` (monthly full, weekly recent) | `data/regions/<id>/history.json` | NOAA public data; aggregations are SkipperCast's; retain counts and missing coverage | `ndbc-history` · public domain · commercial: allowed · attribution yes | FE-42 |
| ESI 2006 Central California sandy-shore runs (NOAA ORR, ArcGIS) and California Coastal Commission access points | `scripts/import_shore_habitat.py` (reviewed import, not hourly): run geometry with source year, access points with ids and links, review dates in the asset | manual, like `import-shore-habitat.mjs` | `catalog/shore-habitat/<region>.geojson` → `dist/regions/<id>/shore-habitat.geojson` | ESI: no constraints stated beyond mapping limits, attribution encouraged; CCC: facts only, no photos or descriptions; access point is not a current-access certification; rule and access reviews are dated and expire | `noaa-esi-2006` · public · commercial: allowed · attribution yes; `ccc-access-points` · facts only · commercial: owner to confirm · attribution yes | FE-43 |
| GOES longwave imagery (nowCOAST WMS) | `pipeline/goes_frames.py`: GetCapabilities time list only; frames are fetched live by the browser as WMS tiles pinned to listed times | `live-conditions.yml` | `conditions/goes-times.json` | NOAA public; brightness is not cloud fraction; frames pinned to acquisition times, never `current` | `noaa-goes-nowcoast` · public domain · commercial: allowed · attribution yes | FE-44 |
| NAIP natural-colour mosaic (USGS ImageServer) | none (live tiles); `regions/<id>/region.json` gains `basemap.aerial: true` where coverage was checked | — | — | USGS/USDA attribution; dated land imagery, not live or underwater; only the fixed USGS service | `usgs-naip` · public domain · commercial: allowed · attribution yes | FE-45 |
| USGS bathymetry grids as PNG PMTiles | `seafloor/relief.py` (ported `import-bathymetry.py`): approved ZIP/COG hashes, nearest sampling, transparent gaps | `seafloor.yml` dispatch | `tiles/relief/relief-<region>.pmtiles` + manifest on R2 | public domain; credit USGS, CSUMB Seafloor Mapping Lab, UC CISR; no exact-depth or navigation claim | existing USGS rows; add the credit line | FE-12 |

Already in SkipperCast, so no ingest task: Port San Luis tides (`noaa-tides`),
HFR and WCOFS currents, MUR surface temperature, MPAs, NWS forecast and
alerts, landing reports (the catch cards use the existing feed with the
same facts-only review), Natural Earth is replaced by the basemap.

CSP changes (each in the task that needs it, with
`tests/test_security_headers.mjs` updated): `IMAGE_ORIGINS` gains
`https://imagery.nationalmap.gov` (FE-22/45) and `https://nowcoast.noaa.gov`
(FE-21); `CONNECT_ORIGINS` gains nothing new, because every feed is read
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
  default view.
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
   layer toggling (basemap, relief, currents, water temperature, swell,
   MPAs, marks, clouds, aerial where configured).
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
8. The relief archive on R2 matches an approved SHA and the proxy refuses
   an altered manifest (test and a live check).
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
| Relief tiles on R2 | < $0.01 | about 12 MB per region today |
| Fonts, icons, bundles | $0 | static assets on Workers |
| New collectors | $0 | run on the owner's runner in existing workflows |
| NAIP, GOES, CDIP, county, NDBC | $0 | public services; NAIP and GOES tiles are fetched by the browser |
| Paid options | — | listed only in open-questions (hosted tiles, a CDN for NAIP) |

## 17. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| The basemap extract is larger or slower to build than estimated | FE-10 measures first; fallback to maximum zoom 13 in preview regions, then to a hosted service (Q1 option 2) |
| Two shells drift while both exist | Shared preference keys, shared feeds, FE-60 within two releases of FE-07; the status log records the gap |
| MapLibre memory on older phones with five fields on | Textures capped at 1,024 px; fields rebuild only on frame, camera or viewport change; default layers per profile are two |
| Ported `fish` code carries single-county assumptions (`countyId === 'slo'`) | Every port reads region config; tests run against two region fixtures |
| Copy regressions (claims stronger than evidence) | The wording rules at the top; review checks the basis sentences; copy lint |
| Rights of the Coastal Commission inventory and the county feed for a paid product | Facts only, owner rows in the register before FE-60, open-questions Q8 |
| Startup JSON budget grows with new feeds | Feeds are lazy per rail entry; the budget file's `max_bytes` only decreases |
| The owner's `fish` deletion loses receipts | § 15 item 9 copies them first; FE-62 is blocked until the copy PR merges |

## 18. Phasing

See [dev-plan.md](dev-plan.md). In short: Phase 0 makes the system and
shells behind the flag; Phase 1 gives the shell its map; Phase 2 makes it
profile-aware with the brief and charts; Phase 3 brings the `fish` sources
into the pipelines; Phase 4 moves the remaining features in; Phase 5 flips
the flag, deletes the old shell and retires `fish`.
