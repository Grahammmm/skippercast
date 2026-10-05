# Front-end rebuild: development plan

One task = one builder = one branch `claude/fe-<id>` (for example
`claude/fe-02`) = one PR. Every task stays at or under about 400 changed
lines, not counting generated files (`dist/client`, `dist/server`,
`dist/regions/*`, migrations). Sizes: **S** under 150 lines, **M** 150–300,
**L** 300–400. Section numbers (§) refer to [design.md](design.md); re-read
the section before starting a task. There are 46 tasks in six phases.

Rules for every task:

- Start from a fresh `main`, depend only on merged tasks, rebase before
  review. Run the checks in `AGENTS.md` § "Before opening a PR", plus
  `node scripts/check_copy.mjs --base origin/main`, `node scripts/check_contrast.mjs`
  and (from FE-02) `node scripts/check_tokens.mjs`.
- Independent review against `AGENTS.md`'s checklist and the task's
  acceptance criteria; merge only on green CI at the current head.
- v2 pages render only with `UI_V2=true` or `?ui=v2` until FE-60. A task
  that touches a v1 file keeps v1 byte-identical unless the task says so;
  `e2e/app.spec.ts` and the Node tests that import `dist/*.js` stay green.
- Every new colour, font, radius and spacing is a `var(--…)` (§ 5);
  `check_tokens.mjs` fails otherwise.
- Copy follows § 12. No word that claims fish will be there and no promise
  of a bite; basis sentences inside disclosures.
- `.github/CODEOWNERS` gives the owner `server/`, `.github/workflows/`,
  `deployments/`, `docs/legal/` and `wrangler.jsonc`; a PR touching them
  waits for the **Owner**'s approval and says so with the link.
- Material user-facing changes add a line under `## Unreleased` in
  `CHANGELOG.md` (say "behind `UI_V2`" until FE-60). Append a dated line to
  [README.md](README.md)'s status log when a phase starts or ends.

## Phase 0: foundations behind `UI_V2`

### FE-01 · `UI_V2` flag, shell routing, ADR status · M
- Depends: —
- Files: `server/env.ts`, `server/routes/assets.ts`, `scripts/build-worker.mjs`, `scripts/wrangler_config.mjs`, `.github/workflows/deploy-cloudflare.yml`, `deployments/production.json`, `dist/app.html`, `dist/landing.html` (placeholders: title, tokens link, one `<main>`), `tests/test_worker_routes.mjs`, `tests/test_wrangler_config.mjs`, `docs/engineering/adr/0005-*.md`, `0009-*.md`, `adr/README.md`.
- Build: § 14 routing (`/` landing or app by parameters, `/map`, `?ui=v2`, `?ui=v1`, 404 for `/map` when off); `SHELLS` gains both pages; ADR 0005 and 0009 status lines become Accepted citing the plan PR.
- Accept: 1. With the flag unset and no switch, `/` is byte-identical to today and `/map` is 404. 2. `?ui=v2` on `/` serves `landing.html`; `/?region=morro-bay&ui=v2` serves `app.html`. 3. With `UI_V2=true`, `?ui=v1` serves `index.html`. 4. Wrangler config copies `UI_V2`.
- **Owner**: approve (`server/`, workflows, `deployments/`); accept the ADRs.

### FE-02 · Token system, fonts, contrast, token lint · M
- Depends: —
- Files: `web/tokens.css`, `web/fonts/*.woff2` + licences, `scripts/check_contrast.mjs`, `scripts/check_tokens.mjs`, `tests/test_check_tokens.mjs`, `package.json` (script), `.github/workflows/ci.yml` (one step), `NOTICE.md` (font rows).
- Build: § 5 tokens (dark default, light set defined), type scale, `@font-face` subsets; contrast pairs; the lint over `web/**` with `web/map/palette.ts` as the only CSS-to-JS bridge.
- Accept: 1. `check_contrast.mjs` passes for both token files and both themes. 2. `check_tokens.mjs` fails on a fixture with a hex literal and passes on `web/`. 3. No Google Fonts request; CSP unchanged. 4. Fonts load with `font-display: swap`.

### FE-03 · Icons and UI primitives · M
- Depends: FE-02
- Files: `web/ui/icons.tsx` (31 stroke icons ported from `fish/src/ui/icons.ts`), `web/ui/{Button,Tile,Chip,Rail,Sheet,Dock,Popover}.tsx`, `web/ui/ui.css`, `tests/test_ui_icons.mjs`.
- Build: `Icon` with `name`, `size`, `aria-hidden` by default; primitives with token styling, focus rings, 44 px targets; `Sheet` with three detents and keyboard operation; `Popover` for basis sentences rendering a `<details>`.
- Accept: 1. Every icon name renders a single `<svg>` with `stroke="currentColor"`. 2. Primitives have no colour literal. 3. Snapshot test of each primitive at both themes.

### FE-04 · State v2: profile, view, day, layers, area · S
- Depends: —
- Files: `web/state.ts`, `web/profile.ts`, `tests/test_state.mjs`, `tests/test_profile.mjs`.
- Build: § 8 keys and storage; `profile.ts` exports the semantics table as data (defaults, depth limits, layer defaults, caveats, species method filters); `lockRegion()` kept for v1, bypassed by a `v2` option.
- Accept: 1. Round-trip of every key through `withParams` and `syncFromURL`. 2. Stored profile and layers restore when the URL omits them. 3. Table test of `profile.ts` against § 8.

### FE-05 · Desktop app shell · L
- Depends: FE-02, FE-03, FE-04
- Files: `dist/app.html`, `web/app/{App,Masthead,CommandBar,Desktop,TimeDock,LayerRail,Legend,MarkCard}.tsx`, `web/app/app.css`, `web/app/main.tsx`, `e2e/v2-shell.spec.ts`.
- Build: § 6 desktop layout with a map placeholder, the brief column with placeholder tiles bound to signals, masthead views as `?view=`, command bar bound to state; freshness dot from a `freshness` signal.
- Accept: 1. `pnpm typecheck && pnpm build && node scripts/check_client.mjs` pass. 2. At 1,280 px the brief column is 332 px and the map fills the rest. 3. Keyboard reaches every control; axe clean. 4. View links update `?view=` without reload.

### FE-06 · Mobile app shell · M
- Depends: FE-05
- Files: `web/app/Mobile.tsx`, `web/app/app.css`, `e2e/v2-shell.spec.ts`.
- Build: § 6 mobile: top strip, sheet detents (peek, half, full), hour slider at the sheet edge, four-tab nav, rail as a sheet, mark card as peek content.
- Accept: 1. At 390 × 844 the map fills the viewport and the sheet peeks. 2. Detents work by drag and keyboard. 3. No horizontal page scroll; axe clean.

### FE-07 · Landing page · L
- Depends: FE-05, FE-11, FE-13, FE-15 (night map); FE-08
- Files: `dist/landing.html`, `web/landing/{Landing,Readout,ProfilePills,LayerDots}.tsx`, `web/landing/landing.css`, `web/landing/main.tsx`, `e2e/v2-landing.spec.ts`, `scripts/startup-budget.json` (landing entry).
- Build: § 7 layout; readings from the default region's feeds with source and age; night style variant; saved-port redirect; WebGL fallback (shoreline SVG and readings).
- Accept: 1. LCP ≤ 2.5 s on the throttled mobile profile against the built site. 2. Every readout tile shows a source and age; a stale feed shows stale. 3. With a saved port and no parameters the page navigates to `/map?region=…&profile=…`. 4. Landing JavaScript before first paint ≤ 180 KB gzipped. 5. axe clean.

### FE-08 · Port chooser and first-run profile · M
- Depends: FE-04, FE-05
- Files: `web/landing/PortInput.tsx`, `web/ports.ts` (ported `closestPort`, `portURL`, storage key shared with `dist/home-port.js`), `web/app/FirstRun.tsx`, `tests/test_ports.mjs`, `e2e/v2-landing.spec.ts`.
- Build: § 7 chooser and location flow; first run is the profile choice once; the command bar's area menu holds port and locate.
- Accept: 1. Typing matches ports by name; Enter navigates. 2. Location refused → message and the input focused. 3. v1 reads the port v2 saved (shared key). 4. First run shows once and never when `?profile=` is in the URL.

### FE-09 · v2 test harness and budgets · S
- Depends: FE-05
- Files: `e2e/serve.mjs`, `e2e/fixtures.ts`, `scripts/check_client.mjs`, `scripts/startup-budget.json`, `docs/engineering/testing.md`.
- Build: serve `app.html` and `landing.html` with `?ui=v2`; bundle-size and LCP checks per § 13; feed stubs for v2 pages.
- Accept: 1. A v2 e2e spec runs in CI. 2. `check_client.mjs` fails when a v2 bundle exceeds its budget. 3. Docs list the v2 layers.

## Phase 1: map engine and core layers

### FE-10 · Basemap build, publish and style · L
- Depends: FE-02
- Files: `scripts/basemap/build_basemap.sh`, `scripts/basemap/regions.py` (bboxes from `regions/*/region.json`), `.github/workflows/basemap.yml` (dispatch, `DATA_RUNNER`), `web/map/style.ts`, `dist/basemap/{glyphs,sprites}`, `catalog/sources.json` (`protomaps-basemap`), `docs/data-sources.md`, `tests/unit/test_basemap_regions.py`, `tests/test_map_style.mjs`.
- Build: § 4 option 1: `pmtiles extract` per region bbox merged into `tiles/basemap/ca-coast-<date>.pmtiles`, uploaded to R2 by the workflow; a token-coloured style (day and night variants) with labels from zoom 9; CUSP coastline GeoJSON per region from the same bboxes.
- Accept: 1. The style test asserts every colour comes from `palette.ts`. 2. The workflow has no `pull_request` trigger and pinned actions. 3. The PR records the measured archive size and build time and updates § 4. 4. Attribution renders "© OpenStreetMap contributors, © Protomaps".
- **Owner**: dispatch the first build; confirm the R2 object.

### FE-11 · Map engine, layer registry, coastline, chart base, mark card · L
- Depends: FE-05, FE-10
- Files: `web/map/{engine,layers,palette}.ts`, `web/map/coastline.ts`, `web/map/chart.ts`, `web/app/MarkCard.tsx`, `package.json` (maplibre-gl, pmtiles), `tests/test_map_layers.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 3 engine (PMTiles protocol, worker URL, nautical scale, no rotate, resize, error routing); § 9 registry with order, basis, legend, time behaviour; coastline glow; ENC chart as an optional base; `view` round-trip to `?view=`.
- Accept: 1. The map renders the basemap and coastline for Morro Bay. 2. Registry order matches § 9 (test). 3. A source error marks its layer unavailable without breaking others. 4. `?view=` round-trips. 5. `dist/map-test.html` is removed and its budget entry with it.

### FE-12 · Time dock and frame selection · M
- Depends: FE-11
- Files: `web/map/frames.ts` (ported `fish/src/map-sources.ts` `selectCurrentFrame` and the cloud gate), `web/app/TimeDock.tsx`, `web/hour.ts`, `tests/test_frames.mjs`, `e2e/v2-map.spec.ts`.
- Build: day chips from the forecast horizon, play (pauses when hidden), hour slider, readout with wind, swell, tide; `hour` and `day` signals drive registered `hour` and `observed` layers.
- Accept: 1. Frame gate table tests pass (forecast ±90 min and 36 h issue; radar ≤ 6 h; clouds 90 min and withheld on future days). 2. Play steps hours and stops at the end. 3. `prefers-reduced-motion` disables auto-play.

### FE-13 · Relief tiles pipeline and proxy · L
- Depends: —
- Files: `src/skippercast/seafloor/relief.py`, `scripts/seafloor/publish_relief.py`, `.github/workflows/seafloor.yml` (dispatch input), `server/relief.ts`, `server/app.ts`, `tests/unit/test_relief.py`, `tests/test_relief_proxy.mjs`, `docs/seafloor.md`.
- Build: port `fish/scripts/import-bathymetry.py` (approved ZIP/COG hashes, nearest sampling, transparent gaps, depth ramp applied at render not bake) to produce `relief-<region>.pmtiles` and a manifest; port `bathymetry-proxy.ts` as `GET /api/relief/<region>/tiles` with the SHA table, size and range caps, reading R2.
- Accept: 1. A fixture grid produces tiles with transparent gaps (test decodes a tile). 2. The proxy refuses a manifest with an unlisted SHA, a range over 2 MB and an archive over 16 MB. 3. Range requests return 206 with correct bytes. 4. Tests are offline.
- **Owner**: approve (`server/`, workflows); run the first publish for `morro-bay`.

### FE-14 · Seafloor layer: relief, candidates, cells · M
- Depends: FE-11, FE-13
- Files: `web/map/relief.ts`, `web/map/seafloor.ts` (wraps `dist/seafloor-data.js`), `web/app/Legend.tsx`, `tests/test_seafloor_layer.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 relief raster with the depth ramp from tokens; candidates and cells from the existing PMTiles with the terrain-grade and species-fit views; legend entries; basis sentences.
- Accept: 1. Toggling Seafloor adds and removes exactly its layers. 2. The legend shows the depth ramp with survey name and year. 3. Expired seafloor publication hides candidates with the existing message.

### FE-15 · Currents as animated streamlines · L
- Depends: FE-12
- Files: `web/map/surface-field.ts` (ported, with tests from `fish`), `web/map/flow.ts`, `web/map/currents.ts` (wraps `dist/habitat-data.js` readers), `tests/test_surface_field.mjs`, `tests/test_flow.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 Currents: interpolation inside complete quads only, screen-spaced seeds, bounded midpoint integration, land-mask clip, dashed animation with `--flow` and `--flow-fast`, faint source dots, click reading; product switch (WCOFS, HF radar 1 km, 6 km) in the rail's info.
- Accept: 1. Interpolation tests (linear, vector, missing column, invalid grid) pass. 2. Paths stop at gaps (test with a hole). 3. No fresh frame → rail shows the last valid time and draws nothing. 4. Animation stops when the page is hidden.

### FE-16 · Water temperature field and contours · M
- Depends: FE-15
- Files: `web/map/field.ts` (texture from `surfaceField`, feathered inward), `web/map/sst.ts`, `tests/test_field_texture.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 Water temp: `ImageSource` texture ≤ 1,024 px, 0.5 °F contours with sparse labels, fixed range while panning, click reading with analysis time and error; legend ramp from `--sst-*`.
- Accept: 1. A rejected replacement grid hides the previous texture and contours. 2. Contours use complete quads only (test). 3. The legend range equals the rounded extrema of the accepted analysis.

### FE-17 · Swell as a field · M
- Depends: FE-16, FE-40 (nearshore rings; the field alone can merge first)
- Files: `web/map/swell.ts`, `web/map/forecast-grid.ts` (wraps the forecast matrix reader), `tests/test_swell_layer.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 Swell: height texture through `field.ts`, period isolines, direction strokes at low density, nearshore site rings when the feed exists; no circles, no per-cell arrows.
- Accept: 1. Toggling Swell adds the texture, isolines and strokes only. 2. Hour change replaces the texture within one frame. 3. Nearshore rings appear only within the site's freshness window.

### FE-18 · Habitat, geology and reef marks · M
- Depends: FE-11
- Files: `web/map/marks.ts`, `web/map/habitat.ts` (wraps `survey-habitat.js`, `geology.js`, `reef-trip-data.js` readers), `web/app/MarkCard.tsx`, `tests/test_marks_layer.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 habitat fills, geology hatch, reef marks as rings with the fit badge (`SpotConfidence`), selection highlight, mark card with the § 9 fields and actions.
- Accept: 1. Clicking a mark selects it and sets `?spot=`. 2. The card shows source and age and the regulations line. 3. Fit wording is "fits <species> habitat n of 3" only.

### FE-19 · Protected areas · S
- Depends: FE-11
- Files: `web/map/mpa.ts` (wraps `protected-areas.js`), `tests/test_mpa_layer.mjs`.
- Build: § 9 MPA fill and dashed outline, labels at zoom ≥ 11, the basis sentence.
- Accept: 1. Always on; no rail entry. 2. Labels appear at zoom 11 (e2e). 3. Styling reads `--mpa-fill` and `--mpa-line`.

### FE-20 · Layer rail, legend, `?layers=`, profile defaults · M
- Depends: FE-14, FE-15, FE-16, FE-17, FE-18
- Files: `web/app/LayerRail.tsx`, `web/app/Legend.tsx`, `web/landing/LayerDots.tsx`, `tests/test_layer_rail.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 6 rail with info popovers, one legend composed from active layers, `?layers=` and stored defaults per profile (§ 8), the landing's dots bound to the same registry.
- Accept: 1. `?layers=seafloor,currents` restores both. 2. Switching profile with no `?layers=` applies the profile defaults. 3. The legend never shows an inactive ramp.

### FE-21 · Charter grounds and commercial AIS · S
- Depends: FE-20
- Files: `web/map/charter-grounds.ts`, `web/map/commercial-ais.ts`, `tests/test_fleet_public_layers.mjs`.
- Build: § 9 hatched grounds and heat fill from the existing files under the Fleet rail entry (public part), with the existing basis sentences.
- Accept: 1. Both render from committed data offline. 2. The existing copy for commercial AIS is unchanged.

### FE-22 · Clouds: GOES observed-frame loop · M
- Depends: FE-12, FE-44
- Files: `web/map/clouds.ts`, `server/security-headers.ts` (`IMAGE_ORIGINS` + nowCOAST), `tests/test_security_headers.mjs`, `tests/test_clouds_layer.mjs`.
- Build: § 9 Clouds from the times index; 512 px WMS tiles pinned to listed times; loop and pause; withheld on future days.
- Accept: 1. A time not in the index is never requested (test). 2. The loop stops when hidden. 3. CSP test passes with the new origin.
- **Owner**: approve (`server/`).

### FE-23 · Aerial base: NAIP toggle · S
- Depends: FE-11, FE-45
- Files: `web/map/aerial.ts`, `server/security-headers.ts` (`IMAGE_ORIGINS` + USGS), `tests/test_security_headers.mjs`.
- Build: § 9 Aerial where the region has `basemap.aerial`; attribution line.
- Accept: 1. Absent in regions without the flag. 2. Only the fixed USGS host is requested.
- **Owner**: approve (`server/`).

### FE-24 · Charter fleet activity layers in v2 · M
- Depends: FE-20
- Files: `web/map/fleet.ts` (ports `dist/fleet-activity.js` drawing; filters move to the Fleet view in FE-53), `tests/test_fleet_layers_v2.mjs`.
- Build: § 9 events, tracks and heat in the `--amber` family, admin gated exactly as today (`/api/fleet/map/filters` answers for an admin with both flags).
- Accept: 1. Rail entry absent for non-admins and with the flags off. 2. Every card says "inferred from movement". 3. v1 `fleet-activity.js` untouched.

## Phase 2: profiles, brief and charts

### FE-30 · Profiles applied across the app · M
- Depends: FE-04, FE-20
- Files: `web/app/CommandBar.tsx`, `web/species.ts` (wraps `species.js`, `search-plans.js` with method filters), `web/profile.ts`, `tests/test_species_profile.mjs`, `e2e/v2-profile.spec.ts`.
- Build: § 8 applied: target list, depth limit, layer defaults, caveat text, search plans filtered by method.
- Accept: 1. Switching to Shore hides reef marks and shows surfperch first. 2. Spear limits marks to 60 ft (fixture test). 3. `?profile=` wins over storage.

### FE-31 · Daily brief and the brief column · L
- Depends: FE-30, FE-12
- Files: `web/brief/daily.ts` (ported `fish/src/daily.ts`), `web/brief/{Brief,Tiles}.tsx`, `web/app/Desktop.tsx`, `web/app/Mobile.tsx`, `tests/test_daily.mjs`.
- Build: § 10 headline rules, deck, four tiles with source and age, lower-exposure window, caveat, beach notice link (reads `beach-health.json` when present), fleet line from the landing-reports feed, footer.
- Accept: 1. Headline table test covers every rule. 2. A tile past its limit renders stale. 3. The fleet line is absent without a report in 7 days. 4. The mobile sheet shows headline, tiles, top pick and slider at the half detent.

### FE-32 · Series chart and Conditions view · L
- Depends: FE-31
- Files: `web/charts/series.tsx` (ported), `web/charts/Conditions.tsx`, `web/app/views/Conditions.tsx`, `tests/test_series.mjs`, `e2e/v2-conditions.spec.ts`.
- Build: § 10 chart contract and Conditions view with the shared cursor.
- Accept: 1. Gap test: a 2 h hole produces two path segments. 2. Rows keep independent scales (test reads the y mapping). 3. The cursor follows `hour` and dragging it moves the map layers. 4. Scrolls sideways at 390 px.

### FE-33 · Tide sparkline and tide tile · S
- Depends: FE-32
- Files: `web/brief/TideSpark.tsx`, `web/tides.ts` (wraps the existing CO-OPS reader), `tests/test_tides.mjs`.
- Build: § 10 sparkline with events and night shading; trend from the curve; reference level in the basis popover.
- Accept: 1. Trend is Rising, Falling or Turning per the 15-minute rule. 2. Fewer than two points → "Tide series unavailable".

### FE-34 · "Where to look" ranking · M
- Depends: FE-31, FE-18
- Files: `web/brief/WhereToLook.tsx`, `web/ranking.ts` (wraps `spot-ranking.js`, `species-fit.js`), `tests/test_ranking.mjs`.
- Build: § 10 top four by habitat fit within the profile limit, with distance, depth band, fit badge and reason; selection syncs with the map.
- Accept: 1. Items outside the limit never appear. 2. Clicking selects the mark and opens the card. 3. Wording per § 12.

### FE-35 · History view · M
- Depends: FE-32, FE-42
- Files: `web/charts/History.tsx`, `web/app/views/History.tsx`, `tests/test_history_view.mjs`.
- Build: § 10 History from `history.json`: pickers, bands, means, counts and coverage text.
- Accept: 1. A month with `count` 0 or inconsistent quantiles is skipped (test). 2. Copy says "recorded history". 3. Station without data → the unavailable state.

### FE-36 · Shore runs, access points and guidance · M
- Depends: FE-30, FE-43
- Files: `web/map/shore.ts`, `web/brief/shore.ts` (ported `fish/src/opportunity.ts` priority and guidance), `tests/test_shore.mjs`.
- Build: § 8 and § 9 shore profile: runs with priority tint, access pins, surfperch and halibut guidance with the source link, review dates shown and expiry honoured.
- Accept: 1. An expired access review drops the run to "Hold" (test). 2. A run inside an MPA is blocked (test). 3. Visible only with `profile=shore`.

## Phase 3: `fish` data sources into the pipelines

### FE-40 · CDIP nearshore model collector · M
- Depends: —
- Files: `src/skippercast/pipeline/cdip_nearshore.py`, `src/skippercast/pipeline/live.py`, `regions/morro-bay/region.json` (sites), `catalog/sources.json`, `tests/fixtures/cdip/*`, `tests/unit/test_cdip_nearshore.py`, `docs/data-sources.md`.
- Build: § 11 row: site identity and coordinate checks, three-hour series with masks, freshness, published in `live-conditions.yml`'s snapshot.
- Accept: 1. A site label or coordinate mismatch raises. 2. Partial arrays are rejected. 3. Offline fixtures; the platform build diff is clean.
- **Owner**: add the register row.

### FE-41 · Beach health collector · S
- Depends: —
- Files: `src/skippercast/pipeline/beach_health.py`, `live.py`, `catalog/sources.json`, `tests/fixtures/beach-health/*`, `tests/unit/test_beach_health.py`.
- Build: § 11 row; statuses and links only.
- Accept: 1. `exceededTransferLimit` or a count mismatch raises. 2. Out-of-county geometry is rejected. 3. No date is invented (feed has `sample_date: null`).
- **Owner**: add the register row.

### FE-42 · NDBC history backfill and seasonal bands · L
- Depends: —
- Files: `src/skippercast/pipeline/ndbc_history.py`, `.github/workflows/buoy-history.yml`, `catalog/sources.json`, `tests/fixtures/ndbc-history/*`, `tests/unit/test_ndbc_history.py`, `docs/live-conditions.md`.
- Build: § 11 row: annual checkpoints with SHA under `var/`, monthly p10 / median / p90 with counts, coverage and years; recent 45-day means; publish `history.json`.
- Accept: 1. Quantiles on a fixture match hand-computed values. 2. A re-run with unchanged archives downloads nothing (conditional GET test). 3. Missing hours are counted, never filled.
- **Owner**: approve the workflow; run the backfill once on Hermes.

### FE-43 · ESI shore runs and access points import · M
- Depends: —
- Files: `scripts/import_shore_habitat.py`, `catalog/shore-habitat/morro-bay.geojson`, `schemas/shore-habitat.schema.json`, `src/skippercast/platform/build.py` (copy to `dist/regions/<id>/`), `catalog/sources.json`, `tests/contract/test_shore_habitat.py`, `docs/data-sources.md`.
- Build: § 11 row: runs with source year, access points with ids and links, review dates (`checked_at`, `review_expires_at`, `legal_reviewed_at`) in the asset.
- Accept: 1. Schema validation in the contract test. 2. The platform build copies the asset and the diff is clean. 3. No photo or description text from the inventory.
- **Owner**: add the register rows; confirm the review dates.

### FE-44 · GOES frame times index · S
- Depends: —
- Files: `src/skippercast/pipeline/goes_frames.py`, `live.py`, `catalog/sources.json`, `tests/unit/test_goes_frames.py`.
- Build: § 11 row: parse GetCapabilities for the layer's time list, publish `goes-times.json` with the fetch time.
- Accept: 1. A capabilities fixture yields the list. 2. Times are ISO UTC, sorted, deduplicated.

### FE-45 · NAIP source config and rights · S
- Depends: —
- Files: `catalog/sources.json`, `regions/morro-bay/region.json` (`basemap.aerial`), `schemas/region.schema.json` (if the key needs it), `docs/data-sources.md`, rebuilt `dist/regions/*`.
- Build: § 11 row; the region flag.
- Accept: 1. Contract tests pass with the new entry. 2. Platform build diff clean.
- **Owner**: add the register row.

## Phase 4: the remaining features in the new shell

### FE-50 · Account, boat profile and alerts in the masthead · M
- Depends: FE-05
- Files: `web/app/AccountMenu.tsx`, `web/account.ts` (wraps `account.js`, `boat-profile.js`, `trip-alerts.js`), `e2e/v2-account.spec.ts`.
- Build: sign in (passkeys), boat presets from `first-run.js`, alerts, downloads and offline pack entry, in tokens.
- Accept: 1. `tests/test_accounts.mjs` unchanged and green. 2. Sign-in flow completes in e2e with the fixture. 3. The menu is keyboard operable.

### FE-51 · Trip planner, GPX export and offline pack · L
- Depends: FE-18, FE-50
- Files: `web/app/Trip.tsx`, `web/trip.ts` (wraps `export-ui.js`, `gpx.js`, `trip-export.js`, `offline-pack.js`), `dist/sw.js` (v2 precache and basemap tiles at zooms 8–12 for the saved region), `e2e/v2-trip.spec.ts`.
- Build: mark card actions, trip list in the account menu, GPX with the existing evidence labels, offline pack with the basemap bounds budget.
- Accept: 1. `e2e/ranked-export.spec.ts` logic passes against v2. 2. The offline pack size for Morro Bay stays under the documented budget. 3. GPX output is byte-identical to v1 for the same selection.

### FE-52 · Reports page · M
- Depends: FE-31
- Files: `web/app/views/Reports.tsx`, `web/reports.ts` (wraps `recent-discussions.js`, `bite-evidence.js`, `coastal-research-context.js`), `tests/test_reports_view.mjs`.
- Build: § 6 table: discussions, bite evidence, seven-day catch cards (facts only, eight at most), seasonal watch, charter evidence, with dates and source links.
- Accept: 1. Catch cards keep boat, port, trip, species and the reported/retained/released labels. 2. No publisher prose or photos. 3. Reachable from the landing nav.

### FE-53 · Fleet view · M
- Depends: FE-24, FE-21
- Files: `web/app/views/Fleet.tsx`, `web/fleet.ts`, `tests/test_fleet_view.mjs`.
- Build: public part: charter grounds and the boat directory link (`/boats`) when `FLEET_ENABLED`; admin part: the filter form from `fleet-activity.js` driving the FE-24 layers.
- Accept: 1. With the flags off the view shows grounds and the AIS 2024 option only. 2. Admin filters round-trip to the API exactly as `tests/test_fleet_layers.mjs` expects. 3. "Inferred from movement" present.

### FE-54 · Species plans, regulations and the sources page · M
- Depends: FE-30, FE-18
- Files: `web/app/CommandBar.tsx` (target menu with search), `web/app/MarkCard.tsx` (regulations line), `dist/sources.html` (tokens restyle), `web/regs.ts` (wraps `regulations.js`), `tests/test_regs_wrapper.mjs`.
- Build: § 6 table rows for species, filters, search, regulations; the sources page in the visual system with every basis sentence linking into it.
- Accept: 1. The target menu lists plans by profile method. 2. The regulations line matches `regulations.js` output for a fixture species. 3. Copy lint clean on the restyled page.

### FE-55 · Advisor entry and pages in the visual system · S
- Depends: FE-05
- Files: `web/advisor/copy.ts`, `server/advisor/pages/render.ts` (tokens link), `dist/chat.html`, `e2e/advisor-pages.spec.ts`.
- Build: the chat entry in the masthead when `TEXT_ADVISOR_ENABLED`; advisor pages load `web/tokens.css`.
- Accept: 1. With the advisor off nothing renders. 2. Advisor page snapshots in `tests/fixtures/boat-page-snapshots/` are regenerated with the same text content.
- **Owner**: approve (`server/`).

## Phase 5: flip, delete, retire

### FE-60 · Flip `UI_V2` on by default · S
- Depends: FE-07, FE-08, FE-09, FE-20 … FE-24, FE-30 … FE-36, FE-50 … FE-55
- Files: `deployments/production.json`, `.github/workflows/deploy-cloudflare.yml`, `CHANGELOG.md`, `docs/web-app.md`, `README.md` (status).
- Build: default on; `?ui=v1` stays for one release; release notes.
- Accept: 1. Smoke test in the deploy workflow passes on `/` and `/map`. 2. § 15 items 1–6 verified live and linked. 3. Tag `v0.4.0`.
- **Owner**: approve; confirm the live check.

### FE-61 · Delete the v1 shell · L (mostly deletions)
- Depends: FE-60 (one release later)
- Files: `dist/index.html` (becomes the v2 app at `/`), `dist/*.css` (v1 sheets), `dist/tokens.css`, `dist/vendor/leaflet*`, `dist/vendor/images`, `dist/vendor/maplibre-*`, `dist/vendor/pmtiles-*`, the `dist/*.js` modules fully replaced by `web/` wrappers, `scripts/web-vendor-sha256.json`, `scripts/copy-lint-baseline.json`, `vite.config.mjs` (`cssMinify: true`), `server/routes/assets.ts` (remove the switch), tests.
- Build: delete in dependency order (a script lists modules no test or page imports); turn CSS minification on and re-check every page; baseline shrinks.
- Accept: 1. No Leaflet reference remains (grep test). 2. `check_contrast.mjs` reads `web/tokens.css` only. 3. All checks green; the copy-lint baseline shrinks.
- **Owner**: approve (`server/`).

### FE-62 · Archive `fish` receipts and retire the repository · M
- Depends: FE-60; FE-40 … FE-45 merged and run once
- Files: `docs/archive/fish/README.md`, `docs/archive/fish/**` (the § 15 item 9 list), `docs/plans/front-end/README.md` (status), `docs/data-sources.md`.
- Build: copy the listed docs and receipts with the historical-note prefix; tick § 15's checklist with links in the PR; list the Cloudflare resources.
- Accept: 1. Every § 15 item has a link or a dated note. 2. No `fish/public/data` file is copied. 3. `check_repository.py` passes on the archive.
- **Owner**: archive the GitHub repository, delete the Cloudflare resources, delete the repository, decide the domain redirect (Q10).

## Parallelism

- Phase 0: FE-01, FE-02, FE-04 in parallel; FE-03 after FE-02; FE-05 after FE-02, FE-03, FE-04; FE-06, FE-08, FE-09 after FE-05; FE-07 last (needs FE-11, FE-13, FE-15 for its map).
- Phase 1: FE-10 and FE-13 can start with Phase 0 (FE-10 after FE-02); FE-11 after FE-05 and FE-10; then FE-12, FE-18, FE-19 in parallel; FE-14 after FE-13; FE-15 after FE-12; FE-16 after FE-15; FE-17 after FE-16; FE-20 after FE-14 … FE-18; FE-21, FE-22, FE-23, FE-24 after FE-20 (FE-22 also FE-44; FE-23 also FE-45).
- Phase 3 is independent of the shell: FE-40 … FE-45 can run any time, in parallel.
- Phase 2: FE-30 after FE-20; FE-31 after FE-30; FE-32, FE-34 after FE-31; FE-33 after FE-32; FE-35 after FE-42; FE-36 after FE-43.
- Phase 4: FE-50 any time after FE-05; FE-52 after FE-31; FE-51, FE-53, FE-54, FE-55 as listed.
- Conflict hot spots: `dist/index.html` (FE-61 only; Phase 0 adds new pages instead); `vite.config.mjs` (FE-61 only); `web/islands.tsx` (untouched: v2 pages have their own `main.tsx`); `web/state.ts` (FE-04 only, later tasks add keys by appending); `server/routes/assets.ts` (FE-01, FE-61); `server/security-headers.ts` (FE-22, FE-23: rebase, one line each); `web/app/MarkCard.tsx` (FE-11, FE-18, FE-54: in that order); `web/app/Legend.tsx` (FE-14, FE-20); `catalog/sources.json` (FE-40 … FE-45: append entries, rebase); `live.py` (FE-40, FE-41, FE-44: register one collector each).

## Dependency graph

```
FE-01, FE-02, FE-04, FE-13, FE-40 … FE-45: no dependencies
FE-02 ─► FE-03 ─► FE-05 (also FE-04) ─► FE-06, FE-08, FE-09, FE-50
FE-02 ─► FE-10 ─► FE-11 (also FE-05) ─► FE-12, FE-18, FE-19
FE-13 + FE-11 ─► FE-14
FE-12 ─► FE-15 ─► FE-16 ─► FE-17 (also FE-40)
FE-14 + FE-15 + FE-16 + FE-17 + FE-18 ─► FE-20 ─► FE-21, FE-24, FE-30
FE-12 + FE-44 ─► FE-22;  FE-11 + FE-45 ─► FE-23
FE-05 + FE-11 + FE-13 + FE-15 + FE-08 ─► FE-07
FE-30 + FE-12 ─► FE-31 ─► FE-32 ─► FE-33;  FE-31 + FE-18 ─► FE-34
FE-32 + FE-42 ─► FE-35;  FE-30 + FE-43 ─► FE-36
FE-18 + FE-50 ─► FE-51;  FE-31 ─► FE-52;  FE-24 + FE-21 ─► FE-53;  FE-30 + FE-18 ─► FE-54;  FE-05 ─► FE-55
Phases 0–4 ─► FE-60 ─► FE-61;  FE-60 + FE-40 … FE-45 ─► FE-62
```

## Backlog (no task yet)

- **Light theme switch** (US-L1): a `data-theme` toggle in the account menu,
  the light contrast pass, map style day variant on the app.
- **Admin restyle** (US-L3): `web/admin` on `web/tokens.css`.
- **Second active region on the landing** (US-L2): region-aware readings
  once another region leaves preview.
- **Relief for preview regions**: FE-13 publishes Morro Bay; each further
  region is a data task with its own approved grids.
- **Landing readings for the typed port** before navigation.

## Definition of done

1. `/` and `/map` serve the landing and the Bridge shell by default, in one
   visual system, with the v1 shell deleted (FE-60, FE-61).
2. The map runs on MapLibre and PMTiles with the self-hosted basemap and
   every layer in § 9 (Phase 1).
3. Boat, Shore and Spear shape the map, brief, species list and plans
   (Phase 2).
4. Every `fish`-only source flows through a SkipperCast collector with a
   catalog entry and a register row (Phase 3, **Owner** rows).
5. `fish`'s docs and receipts are in `docs/archive/fish/` and the owner
   has archived and deleted the repository (FE-62).
6. Costs stay at the § 16 estimate (**Owner** confirms against the bill).
