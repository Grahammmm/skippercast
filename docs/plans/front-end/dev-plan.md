# Front-end rebuild: development plan

One task = one builder = one branch (`claude/fe-<id>` or `codex/fe-<id>`)
= one PR. Every task stays at or under about 400 changed lines, not counting
generated files (`dist/client`, `dist/server`, `dist/regions/*`,
migrations). Sizes: **S** under 150 lines, **M** 150–300, **L** 300–400.
Section numbers (§) refer to [design.md](design.md); re-read the section
before starting a task.

**Reconciled 2026-10-07** with the ~50 commits Codex merged since
2026-10-06 (`packages/coast/`, the coastal bridge, the v1 coastal modules;
design [§ 3A](design.md#3a-integration-with-packagescoast-2026-10-07)).
Each task now carries a **Status** (DONE, PARTLY on `main`, CHANGED,
STILL NEEDED, DROPPED, NEW) and an **Agent** that follows the ownership
proposal in [open-questions Q14](open-questions.md#q14-ownership-boundary-between-the-v2-shell-and-packagescoast).
Ids of tasks that remain are unchanged; new integration tasks start at
FE-70. Coordination with Codex happens on issue
[#413](https://github.com/Grahammmm/skippercast/issues/413).

Rules for every task:

- Start from a fresh `main`, depend only on merged tasks, rebase before
  review. Run the checks in `AGENTS.md` § "Before opening a PR", plus
  `node scripts/check_copy.mjs --base origin/main`, `node scripts/check_contrast.mjs`
  and `node scripts/check_tokens.mjs`.
- Independent review against `AGENTS.md`'s checklist and the task's
  acceptance criteria; merge only on green CI at the current head. A Claude
  task touching a hot-spot file (design § 3A.6) asks Codex to review, and
  the reverse.
- v2 pages render only with `UI_V2=true` or `?ui=v2` until FE-60. A task
  that touches a v1 file keeps v1 byte-identical unless the task says so;
  `e2e/app.spec.ts`, the `tests/coast/*` suite and the Node tests that
  import `dist/*.js` stay green.
- v2 imports `packages/coast/src` exports; it never copies or forks them,
  and it never imports `dist/coast-*.js` or `dist/coastal-*.js`. A needed
  change to a `packages/coast` export is announced on issue #413 first.
- Every new colour, font, radius and spacing is a `var(--…)` (§ 5, § 3A.4);
  `check_tokens.mjs` fails otherwise.
- Copy follows § 12. No word that claims fish will be there and no promise
  of a bite; basis sentences inside disclosures.
- `.github/CODEOWNERS` gives the owner `server/`, `.github/workflows/`,
  `deployments/`, `docs/legal/` and `wrangler.jsonc`; `NOTICE.md` and
  `LICENSE` are owner territory too (ADR 0004). A PR touching any of them
  waits for the **Owner**'s approval and says so with the link.
- Material user-facing changes add a line under `## Unreleased` in
  `CHANGELOG.md` (say "behind `UI_V2`" until FE-60). Append a dated line to
  [README.md](README.md)'s status log when a phase starts or ends.

## Status summary (2026-10-07)

| Status | Count | Tasks |
| --- | --- | --- |
| DONE (Claude, Phase 0) | 8 | FE-01 … FE-06, FE-08, FE-09 |
| DONE on `main` by Codex | 0 | none whole; Codex's pieces are listed under PARTLY |
| PARTLY on `main` | 5 | FE-31, FE-35, FE-36, FE-51, FE-52 |
| CHANGED (consume `packages/coast` or the bridge) | 27 | FE-10, FE-11, FE-12, FE-14, FE-15, FE-16, FE-18, FE-20, FE-22, FE-23, FE-25, FE-27, FE-30, FE-32, FE-33, FE-34, FE-37, FE-40 … FE-45, FE-54, FE-60, FE-61, FE-62 |
| STILL NEEDED as written | 8 | FE-07, FE-17, FE-19, FE-21, FE-24, FE-50, FE-53, FE-55 |
| DROPPED | 2 | FE-13, FE-26 |
| NEW | 17 | FE-70 … FE-86 |

## Phase 0: foundations behind `UI_V2`

### FE-01 · `UI_V2` flag, shell routing, ADR status · M — DONE
Merged as [#355](https://github.com/Grahammmm/skippercast/pull/355).

### FE-02 · Token system, fonts, contrast, token lint · M — DONE
Merged as [#356](https://github.com/Grahammmm/skippercast/pull/356).

### FE-03 · Icons and UI primitives · M — DONE
Merged as [#357](https://github.com/Grahammmm/skippercast/pull/357).

### FE-04 · State v2: profile, view, day, layers, area · S — DONE
Merged as [#354](https://github.com/Grahammmm/skippercast/pull/354). Codex
extended it with Fish aliases in [#379](https://github.com/Grahammmm/skippercast/pull/379); FE-73 adds the coast keys.

### FE-05 · Desktop app shell · L — DONE
Merged as [#359](https://github.com/Grahammmm/skippercast/pull/359). The map stage is a placeholder until FE-71.

### FE-06 · Mobile app shell · M — DONE
Merged as [#362](https://github.com/Grahammmm/skippercast/pull/362); Codex adjusted its e2e hour test in [#391](https://github.com/Grahammmm/skippercast/pull/391).

### FE-07 · Landing page (static shoreline) · L
- Status: STILL NEEDED. Agent: Claude.
- Depends: — (FE-05, FE-08 merged)
- Files: `dist/landing.html`, `web/landing/{Landing,Readout,ProfilePills,LayerDots,Shoreline}.tsx`, `web/landing/landing.css`, `web/landing/main.tsx`, `e2e/v2-landing.spec.ts`, `scripts/startup-budget.json` (landing entry).
- Build: § 7 layout with the static shoreline SVG (the region's shoreline GeoJSON drawn inline with the glow treatment; FE-25 adds the live map and keeps this as the fallback); readings from the default region's SkipperCast feeds with source and age; saved-port redirect; layer dots bound to the registry ids as links into `/map?layers=`; nav "Reports" links to the existing `/report` page (Codex, #395) until FE-52, "How it's built" to `/sources` (Q16).
- Accept: 1. LCP ≤ 2.5 s on the throttled mobile profile against the built site. 2. Every readout tile shows a source and age; a stale feed shows stale. 3. With a saved port and no parameters the page navigates to `/map?region=…&profile=…`. 4. Landing JavaScript before first paint ≤ 180 KB gzipped; no MapLibre or `three` import. 5. axe clean.

### FE-08 · Port chooser and first-run profile · M — DONE
Merged as [#361](https://github.com/Grahammmm/skippercast/pull/361). Home memory parity with Codex's #396 is FE-83.

### FE-09 · v2 test harness and budgets · S — DONE
Merged as [#360](https://github.com/Grahammmm/skippercast/pull/360).

## Phase 1: one map stage and its layers

### FE-70 · Coast embed API shared by v1 and v2 · M
- Status: NEW. Agent (proposed): Codex (renderer internals); Claude reviews.
- Depends: —
- Files: `packages/coast/src/embed.ts`, `packages/coast/src/embed-template.ts` (the scene markup `dist/coast-workspace.js` takes from `dist/coast.html` today), `dist/coast-workspace.js` (switches to the embed, behaviour unchanged), `tests/coast/coast-embed.test.ts`.
- Build: § 3A.2 adapter: `mountCoast(host, {root?, palette?, onSelection, onRestoredSelection, onSelectionInvalidated, onCurrentStatus, onView, onPerspective})` creates the shadow root, inserts the template, constructs `CoastViewer` `managed`, and returns a `CoastHandle` with `load`, `setPerspective`, `setLocation`, `setSpecies`, `setHour`, `setDepthLimit`, `setCurrentLayer`, `selectHabitat`, `setVisible`, `destroy`; the handle type is exported and documented as the public API v2 uses.
- Accept: 1. `dist/coast-workspace.js` no longer parses `coast.html`; v1 terrain e2e and `tests/coast/*` pass unchanged. 2. A unit test mounts the embed into a DOM fixture and calls every handle method once. 3. `pnpm typecheck` passes for `packages/coast`. 4. No change to `/coast`.

### FE-73 · One state controller: coast keys and profile parity · M
- Status: NEW. Agent: Claude. Hot spot: `web/state.ts` (comment on #413 before merging).
- Depends: —
- Files: `web/state.ts`, `web/profile.ts`, `web/coast-context.ts` (re-exports only), `tests/test_state.mjs`, `tests/test_profile.mjs`, `tests/test_coast_state_keys.mjs`.
- Build: § 3A.3: `presentation`, `current`, `habitat` join `URL_KEYS` as signals with the stored and validation rules of the table; `presentation` stored as `skippercast-presentation-v1`; parsers reuse `presentationFromURL`, `habitatURL` and the `current` choices from `packages/coast/src/state/current-layer.ts`; a table test pins `PROFILE_TABLE` depth limits and default targets to `experience.ts`.
- Accept: 1. Each new key round-trips through `withParams` and `syncFromURL`. 2. An unknown `current` stays in the URL and parses as unsupported; `habitat` rejects ids outside `[A-Za-z0-9._:-]{1,160}`. 3. The parity test fails if `experience.ts` `maxDepth` or `defaultSpecies` changes alone. 4. v1 tests that import `web/state.ts` (`test_web_state`, `test_coast_*`) pass unchanged.

### FE-71 · MapStage hosts the coast renderer · L
- Status: NEW. Agent: Claude.
- Depends: FE-70, FE-73
- Files: `web/map/stage.ts`, `web/app/MapStage.tsx`, `web/app/Desktop.tsx`, `web/app/Mobile.tsx` (placeholder replaced), `web/app/app.css`, `scripts/check_client.mjs` (no `three` in the app entry), `tests/test_map_stage.mjs`, `e2e/v2-map.spec.ts`. As built also: `web/map/terrain.{js,d.ts,css}` (the dynamic module and the terrain's placement), `packages/coast/src/embed-types.ts` (the embed's types without the renderer, re-exported by `embed.ts`; the renderer sources fail `web/tsconfig.json`'s `noUncheckedIndexedAccess`) and one `role="group"` on the embed's pin list (axe), announced on #413; `tests/test_app_shell.mjs`, `tests/test_client_build.mjs`.
- Build: § 3A.2: presentation signal drives Chart (placeholder until FE-11), Terrain 2D, Terrain 3D; the perspective toggle in the map chrome, disabled with a reason where `hasCoastTerrain(region)` is false; dynamic import of the embed on the first terrain choice; the store-to-handle and handle-to-store flows of the table, including the span-to-zoom rule; `setVisible` follows view, page visibility and presentation; graphics failure returns to Chart with v1's message; tokens via the `data-coast-theme="tokens"` opt-in once FE-76 lands.
- Accept: 1. `/map?ui=v2&region=morro-bay&presentation=3d` shows the terrain; switching to 2D keeps place, target, profile, hour and selection (e2e). 2. Profile Spear sets the depth limit to 60 and Boat to 300 (unit test on the flow table). 3. A terrain selection writes `?habitat=`; Back restores the previous selection. 4. The app entry's static imports contain no `three` (check_client) and its JavaScript budget holds. 5. With WebGL disabled the stage shows Chart and the message; axe clean.

### FE-72 · Chart basemap style from tokens · M
- Status: NEW (the style half of the old FE-10). Agent: Claude.
- Depends: —
- Files: `web/map/style.ts`, `web/map/palette.ts`, `dist/basemap/{glyphs,sprites}`, `tests/test_map_style.mjs`, `tests/fixtures/basemap/tiny.pmtiles` (synthetic).
- Build: § 4 token-coloured Protomaps style, day and night variants, labels from zoom 9, attribution row; `palette.ts` is the one CSS-to-JS bridge and also fills the coast embed's `palette`.
- Accept: 1. Every style colour comes from `palette.ts` (test). 2. The night variant has no labels below zoom 9 (test). 3. Attribution reads "© OpenStreetMap contributors, © Protomaps".

### FE-10 · Basemap and shoreline build and publish · L
- Status: CHANGED (pipeline only; the style moved to FE-72). Agent: Claude (owner, issue #413).
- Depends: —
- Files: `scripts/basemap/build_basemap.sh`, `scripts/basemap/regions.py`, `scripts/shoreline/import_cusp.py`, `catalog/shoreline/<region>.geojson`, `.github/workflows/basemap.yml` (dispatch, `DATA_RUNNER`), `catalog/sources.json` (`protomaps-basemap`, `noaa-cusp-shoreline`), `docs/data-sources.md`, `tests/unit/test_basemap_regions.py`.
- Build: § 4 option 1 extract per region bbox merged into `tiles/basemap/ca-coast-<date>.pmtiles` on R2; CUSP shoreline per region with source dates kept, copied by the platform build to `dist/regions/<id>/shoreline.geojson`; reuse the SLO extract the bridge already serves (`/coast-data/data/slo-shoreline.geojson`) as the Morro Bay reference.
- Accept: 1. The workflow has no `pull_request` trigger and pinned actions. 2. The PR records the measured archive size and build time and updates § 4. 3. The shoreline keeps a source date per feature; platform build diff clean.
- **Owner**: approve the new workflow; dispatch the first build and confirm the R2 object; add the register rows for `protomaps-basemap` and `noaa-cusp-shoreline`.

### FE-11 · Chart presentation: MapLibre engine, registry, coastline, mark card · L
- Status: CHANGED (mounted as the Chart presentation inside MapStage). Agent: Claude.
- Depends: FE-71, FE-72, FE-10
- Files: `web/map/{engine,layers}.ts`, `web/map/coastline.ts`, `web/map/chart.ts`, `web/map/stage.ts` (Chart branch), `web/app/MarkCard.tsx`, `package.json` (maplibre-gl, pmtiles), `tests/test_map_layers.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 3 engine (PMTiles protocol, worker URL, nautical scale, no rotate, resize, error routing) as the Chart renderer of `stage.ts`, sharing its camera with the terrain handle; § 9 registry with `presentations`, order, basis, legend, time behaviour; coastline glow; ENC chart as an optional base.
- Accept: 1. The Chart renders basemap and coastline for Morro Bay. 2. Registry order matches § 9 (test) and every entry declares its presentations. 3. A source error marks its layer unavailable without breaking others. 4. Switching Chart → 3D → Chart keeps the centre within one zoom step. 5. `dist/map-test.html` and its budget entry are removed.

### FE-12 · Time dock and frame selection · M
- Status: CHANGED (wrap `packages/coast` gates instead of porting). Agent: Claude.
- Depends: FE-71
- Files: `web/map/frames.ts` (thin wrapper over `packages/coast/src/map-sources.ts` `selectCurrentFrame` and `state/current-layer.ts`), `web/app/TimeDock.tsx`, `web/hour.ts`, `tests/test_frames.mjs`, `e2e/v2-map.spec.ts`.
- Build: day chips from the 169-hour SkipperCast horizon (the coast report never shortens it), play (pauses when hidden), hour slider, readout; `hour` drives registered `hour` and `observed` layers and the terrain `setHour`; model outages never reset the clock (the rule of v1's `coastal-clock.js`).
- Accept: 1. `fish`'s frame-gate table cases pass through the wrapper (forecast ±90 min and 36 h issue; radar ≤ 6 h; clouds 90 min and withheld on future days). 2. Play steps hours and stops at the end. 3. `prefers-reduced-motion` disables auto-play. 4. The terrain receives the dock's hour (e2e).
- As built: `packages/coast`'s `map-sources.ts` and `state/current-layer.ts` type-check under `web/tsconfig.json`, so `frames.ts` imports them directly (no types-only module). The horizon, the dock's time and play live in `web/hour.ts` (plain TypeScript, Node-tested): 169 UTC hours grouped by local day (eight chips; the eighth carries its date), `?hour=` wins over `?day=`, and an hour outside the horizon is kept with the slider off ("outside the forecast"). Under reduced motion the play button becomes "Next hour" (design § 13: the button still steps). The cloud gate applies `cloudSource`'s 90-minute check to each listed time, since `goes-times.json` lists about two hours, and shows no loop off today's local day. Also touched: `web/ui/Dock.tsx` (the step button; a one-hour day no longer disables play), `web/app/{CommandBar,Mobile,MapStage}.tsx`, `web/app/app.css` (the day strip scrolls sideways), `web/map/stage.ts` (the terrain takes the dock's `?day=` in the region's zone and marks the hour it applied as `data-hour`), `tests/test_app_shell.mjs`, `e2e/v2-shell.spec.ts`. The registry wiring for `hour` and `observed` layers arrives with the registry (FE-11) and its layers (FE-15, FE-22), which call `frames.ts` with the dock's hour.

### FE-13 · Relief tiles pipeline — DROPPED
The `packages/coast` renderer's SHA-verified terrain is the relief ([#385](https://github.com/Grahammmm/skippercast/pull/385), [#392](https://github.com/Grahammmm/skippercast/pull/392)); a PNG relief raster would be less capable (`docs/FISH-MERGE-STATUS.md`, product decision 3). Coverage grows through Codex's mapping pipeline.

### FE-26 · Relief proxy and publish workflow — DROPPED
Superseded by Codex's bounded bridge `server/coast-data.ts` ([#381](https://github.com/Grahammmm/skippercast/pull/381)), which already bounds response size, checks range syntax and the returned range, and accepts only a 64-hex `release` id. The bridge computes no hash: SHA-256 is verified only in the browser (`packages/coast/src/coast3d/regional.ts` line 17). FE-85 moves the assets to SkipperCast storage and adds server-side manifest SHA verification.

### FE-14 · Seafloor layer: candidates and cells in Chart · M
- Status: CHANGED (relief removed; terrain options are FE-80). Agent: Claude.
- Depends: FE-11
- Files: `web/map/seafloor.ts` (wraps `dist/seafloor-data.js`), `web/app/Legend.tsx`, `tests/test_seafloor_layer.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 seafloor candidates and cells from the existing PMTiles with the terrain-grade and species-fit views, `presentations: ['chart']`; the rail's Seafloor entry in Terrain is FE-80.
- Accept: 1. Toggling Seafloor adds and removes exactly its layers in Chart. 2. Expired seafloor publication hides candidates with the existing message (the #395 race fix kept). 3. The legend names the survey and year.

### FE-15 · Currents as animated streamlines · L
- Status: CHANGED (import the field mathematics; one source choice). Agent: Claude.
- Depends: FE-12, FE-74
- Files: `web/map/flow.ts`, `web/map/currents.ts`, `web/app/LayerRail.tsx` (Currents source select bound to `?current=`), `tests/test_flow.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 Currents in Chart: streamlines over `packages/coast` `surfaceField` (no local copy), screen-spaced seeds, bounded midpoint integration, land-mask clip, dashed `--flow` / `--flow-fast`, click reading; source from `current` (`off`, `wcofs`, `hfr-1`, `hfr-6`) through `selectedCurrent`, packets from FE-74 where a report binds and the existing habitat tiles elsewhere; Terrain gets `setCurrentLayer`.
- Accept: 1. Paths stop at gaps (test with a hole). 2. `off` clears immediately; a selected source never silently substitutes another (test). 3. No fresh frame → the rail shows the last valid time and draws nothing. 4. Animation stops when the page is hidden.

### FE-16 · Water temperature field and contours · M
- Status: CHANGED (import `surfaceField`, `fieldContours`, `temperatureRange`). Agent: Claude.
- Depends: FE-15
- Files: `web/map/field.ts`, `web/map/sst.ts`, `tests/test_field_texture.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 Water temp: `ImageSource` texture ≤ 1,024 px, contours from `fieldContours`, ramp from `--sst-*` through `palette.ts` (equal to `temperatureColors`, asserted by test).
- Accept: 1. A rejected replacement grid hides the previous texture and contours. 2. The legend range equals the rounded extrema of the accepted analysis. 3. The token ramp equals `packages/coast` `temperatureColors` (test).

### FE-17 · Swell as a field · M
- Status: STILL NEEDED. Agent: Claude.
- Depends: FE-16
- Files: `web/map/swell.ts`, `web/map/forecast-grid.ts` (wraps the forecast matrix reader), `tests/test_swell_layer.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 Swell: height texture through `field.ts`, period isolines, direction strokes at low density; no circles, no per-cell arrows.
- Accept: 1. Toggling Swell adds the texture, isolines and strokes only. 2. Hour change replaces the texture within one frame.

### FE-27 · Nearshore wave rings · S
- Status: CHANGED (data from the coast report, not FE-40). Agent: Claude.
- Depends: FE-17, FE-74
- Files: `web/map/nearshore.ts`, `web/map/swell.ts`, `tests/test_nearshore_layer.mjs`.
- Build: § 9 Swell: nearshore sites from `packages/coast` `freshNearshore` / `nearshoreAt` on the bound report, rings sized by height with site name and sample age in the mark card.
- Accept: 1. Rings appear only within the site's freshness window. 2. Outside a report binding the Swell layer renders as before FE-27.

### FE-18 · Habitat, geology, reef marks and one mark card · M
- Status: CHANGED (atlas marks and coast habitat in one card). Agent: Claude.
- Depends: FE-11, FE-71
- Files: `web/map/marks.ts`, `web/map/habitat.ts` (wraps `survey-habitat.js`, `geology.js`, `reef-trip-data.js`), `web/app/MarkCard.tsx`, `tests/test_marks_layer.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 9 habitat fills, geology hatch, reef marks with the fit badge in Chart (`?spot=`); terrain selections arrive through the handle (`?habitat=`) and render in the same card with the renderer's evidence lines; `resolveHabitatSelection` restores metadata without graphics.
- Accept: 1. Clicking a mark sets `?spot=`; a terrain pin sets `?habitat=`; only one is selected at a time. 2. The card shows source and age and the regulations line. 3. Fit wording is "fits <species> habitat n of 3" only.

### FE-19 · Protected areas · S
- Status: STILL NEEDED. Agent: Claude.
- Depends: FE-11
- Files: `web/map/mpa.ts` (wraps `protected-areas.js`), `tests/test_mpa_layer.mjs`.
- Build: § 9 MPA fill and dashed outline, labels at zoom ≥ 11, the basis sentence.
- Accept: 1. Always on in Chart; no rail entry. 2. Labels appear at zoom 11 (e2e). 3. Styling reads `--mpa-fill` and `--mpa-line`.

### FE-20 · Layer rail, legend, `?layers=`, profile defaults · M
- Status: CHANGED (presentation-aware; Fish layer aliases). Agent: Claude.
- Depends: FE-14, FE-15, FE-16, FE-17, FE-18, FE-71
- Files: `web/app/LayerRail.tsx`, `web/app/Legend.tsx`, `web/landing/LayerDots.tsx`, `tests/test_layer_rail.mjs`, `e2e/v2-map.spec.ts`.
- Build: § 6 rail with info popovers, one legend composed from active layers, `?layers=` and stored defaults per profile (§ 8), entries unavailable in the active presentation read "Chart only"; Fish `layer=` links arrive translated by `fish-links.ts`.
- Accept: 1. `?layers=seafloor,currents` restores both; `?layer=temperature` (Fish) opens Water temp. 2. Switching profile with no `?layers=` applies the profile defaults. 3. The legend never shows an inactive ramp. 4. In Terrain, chart-only entries are marked and never toggle hidden layers.

### FE-21 · Charter grounds and commercial AIS · S
- Status: STILL NEEDED. Agent: Claude.
- Depends: FE-20
- Files: `web/map/charter-grounds.ts`, `web/map/commercial-ais.ts`, `tests/test_fleet_public_layers.mjs`.
- Build: § 9 hatched grounds and heat fill from the existing files under the Fleet rail entry (public part), with the existing basis sentences.
- Accept: 1. Both render from committed data offline. 2. The existing copy for commercial AIS is unchanged.

### FE-22 · Clouds: GOES observed-frame loop · M
- Status: CHANGED (frames from the ocean snapshot; `cloudSource` imported). Agent: Claude.
- Depends: FE-12, FE-74
- Files: `web/map/clouds.ts`, `server/security-headers.ts` (`IMAGE_ORIGINS` + nowCOAST), `tests/test_security_headers.mjs`, `tests/test_clouds_layer.mjs`.
- Build: § 9 Clouds: times from `/api/coast/ocean` `cloud.availableTimes` where a report binds (FE-44's index elsewhere once it exists; until then the rail entry reads "no frames for this area"); tile URLs from `packages/coast` `cloudSource`; loop and pause; withheld on future days.
- Accept: 1. A time not in the list is never requested (test). 2. The loop stops when hidden. 3. CSP test passes with the new origin.
- **Owner**: approve (`server/`).

### FE-23 · Aerial base: NAIP toggle · S
- Status: CHANGED (`naipSource` imported). Agent: Claude.
- Depends: FE-11, FE-45
- Files: `web/map/aerial.ts`, `server/security-headers.ts` (`IMAGE_ORIGINS` + USGS), `tests/test_security_headers.mjs`.
- Build: § 9 Aerial in Chart where the region has `basemap.aerial`, tile template from `packages/coast` `naipSource`; attribution line.
- Accept: 1. Absent in regions without the flag. 2. Only the fixed USGS host from `mapSourceHosts` is requested.
- **Owner**: approve (`server/`).

### FE-24 · Charter fleet activity layers in v2 · M
- Status: STILL NEEDED. Agent: Claude.
- Depends: FE-20
- Files: `web/map/fleet.ts` (ports `dist/fleet-activity.js` drawing; filters move to the Fleet view in FE-53), `tests/test_fleet_layers_v2.mjs`.
- Build: § 9 events, tracks and heat in the `--amber` family, admin gated exactly as today (`/api/fleet/map/filters` answers for an admin with both flags).
- Accept: 1. Rail entry absent for non-admins and with the flags off. 2. Every card says "inferred from movement". 3. v1 `fleet-activity.js` untouched.

### FE-25 · Landing night map · M
- Status: CHANGED (no relief layer). Agent: Claude.
- Depends: FE-07, FE-11, FE-15
- Files: `web/landing/NightMap.tsx`, `web/landing/main.tsx` (lazy MapLibre after first paint), `e2e/v2-landing.spec.ts`.
- Build: § 7 live night map: FE-72's night style, coastline glow, streamlines from the latest fresh frame; the FE-07 SVG stays as the fallback; layer dots preview a layer on hover.
- Accept: 1. LCP and the 180 KB first-paint budget hold. 2. With WebGL disabled the SVG renders and axe stays clean. 3. Motion stops under `prefers-reduced-motion`. 4. No `three` request (e2e network log).

### FE-79 · Host-chrome mode for the coast embed · L
- Status: NEW. Agent (proposed): Codex; Claude reviews the handle API.
- Depends: FE-70
- Files: `packages/coast/src/embed.ts`, `packages/coast/src/embed-template.ts`, `packages/coast/src/coast3d/viewer.ts`, `tests/coast/coast-embed.test.ts`.
- Build: `mountCoast(host, {chrome: 'host'})` renders the scene without the native layers panel, view controls, reading, target detail and sources button; the sources sheet stays in the root, closed, for `openSources()`. The handle gains setters for relief exaggeration, water opacity and visibility, contours, depth display (`setSourceCoverage`, the source-coverage colours; the depth limit keeps `setDepthLimit`), habitat visibility, zoom, reset and top view, and events for readings, target detail and source coverage as typed data. The native controls stay bound outside the root, so each setter runs the same handler as v1's control. `chrome: 'native'` (default) is unchanged. Split by control group if it exceeds 400 lines.
- Built (2026-10-08, Claude per #413): the habitat status line, ranked list and "Explore a ranked reef" button leave the root with the layers panel and have no handle event yet; FE-80 decides whether the rail needs them.
- Accept: 1. v1 and `/coast` unchanged (their e2e and `tests/coast/*`). 2. With `chrome: 'host'` the shadow root contains no native panel, and every setter changes the scene (unit test against the viewer state). 3. Readings arrive with their measured or modelled label and source clock.

### FE-80 · Terrain options in the rail and mark card · M
- Status: NEW. Agent: Claude.
- Depends: FE-79, FE-20
- Files: `web/app/LayerRail.tsx`, `web/app/MarkCard.tsx`, `web/app/Legend.tsx`, `web/map/stage.ts`, `e2e/v2-map.spec.ts`.
- Build: in Terrain, the Seafloor entry's options hold relief, water, contours and source coverage bound to the FE-79 handle; readings and target detail render in the mark card; the renderer's sources sheet opens from the basis link; zoom, reset and top view join the MapLibre-styled zoom controls.
- Accept: 1. Every control `fish` offered on the terrain has a home (table in the PR). 2. Measured and modelled labels and source clocks are preserved verbatim. 3. Keyboard reaches every option; axe clean.

### FE-81 · Overlay API on the terrain · L
- Status: NEW. Agent: Claude (owner decision on #413, 2026-10-07).
- Depends: FE-70
- Files: `packages/coast/src/coast3d/overlays.ts`, `packages/coast/src/embed.ts`, `packages/coast/src/coast3d/viewer.ts` (own the overlays, re-drape after seams and relief, route clicks), `packages/coast/src/palette.ts` (overlay colour roles), `packages/coast/src/embed-types.ts` (the public overlay types, FE-71 split), `tests/coast/coast-overlays.test.ts` (run from `tests/test_coast_renderer.mjs`).
- Build: `handle.setOverlay(id, {kind: 'fill' | 'line' | 'point', features, style, order})` drapes GeoJSON on the terrain in draw order and `handle.removeOverlay(id)` frees it; styles name colour roles (`COAST_OVERLAY_COLORS`, the `web/map/palette.ts` keys) resolved from the mount's `overlayPalette`, never literals; a click on an overlay calls the mount's `onOverlayPick` with the overlay id and feature id instead of showing a terrain reading; an overlay builds at most 100,000 fill triangles and 50,000 line segments (the drape coarsens to fit, else it is refused).
- Accept: 1. A fixture polygon drapes without z-fighting at both perspectives (screenshot test or vertex check). 2. Removing an overlay frees its geometry. 3. Picking returns the overlay id and feature id.

### FE-82 · Registry layers on the terrain · S
- Status: NEW. Agent: Claude.
- Depends: FE-81, FE-20
- Files: `web/map/layers.ts`, `web/map/stage.ts`, `tests/test_map_layers.mjs`.
- Build: registry entries for MPAs, reef marks and charter grounds declare `terrain`; the stage forwards them to `setOverlay`; picks open the mark card.
- Accept: 1. MPAs and reef marks show in Terrain with the same styling tokens. 2. "Chart only" disappears from those rail entries. 3. A pick selects the same mark as in Chart.

## Phase 2: profiles, brief and charts

### FE-74 · Coast data client for v2 · M
- Status: NEW. Agent: Claude.
- Depends: FE-73
- Files: `web/coast-data.ts`, `tests/test_coast_data_client.mjs`, `tests/fixtures/coast/*` (synthetic report, ocean and history snapshots).
- Build: § 3A.2 loaders over `coastFetch('/api/report' | '/api/ocean' | '/api/history')` admitted only when `overviewReportContext` / `resolveReportBinding` bind the selected place; signals `coastReport`, `coastOcean`, `coastHistory` (`null` outside a binding); abort on place change; original clocks kept; expiry hides, never refreshes.
- Accept: 1. Monterey and Point Conception get `null` (test). 2. A response for a superseded place is discarded (test). 3. An expired snapshot yields `null` and the reason (test). 4. No new endpoint or server change.

### FE-75 · CoastMarkup host · S
- Status: NEW. Agent: Claude.
- Depends: FE-76
- Files: `web/app/CoastMarkup.tsx`, `web/app/coast-markup.css`, `tests/test_coast_markup.mjs`, `tests/fixtures/coast-markup/*` (type test), `e2e/coast-markup.spec.ts` (computed style), `scripts/check_web.py` (new rule: an `innerHTML` assignment or other markup sink in `web/` outside this file fails; comments ignored) with its cases in `tests/unit/test_web_runtime_references.py`.
- Build: § 3A.2 Preact component that takes the name of a renderer from `packages/coast/src` and its arguments, mounts the returned string in its own shadow root with `panel.css` and `tokens-bridge.css` under `data-coast-theme="tokens"`, and forwards pointer events as typed callbacks (cursor hour, selection). `coast-markup.css` inherits back the `web/tokens.css` names that `panel.css`'s `:host` block redeclares, until FE-77 renames them (FE-77b deleted it once `panel.css` declared no custom property). The allow-list starts with `chart`: `tideChart`, `historyView`, `catchSheet` and `fleetBrief` join with FE-33, FE-35 and the Reports task, because their modules (with `daily.ts`, `experience.ts`, `presentation.ts`, `assessment.ts`) do not yet type-check under `web/tsconfig.json`'s `noUncheckedIndexedAccess` (50 findings on 2026-10-08), and fixing them is a `packages/coast` change announced on #413.
- Accept: 1. The component accepts only the name of a renderer on an allow-list of `packages/coast` renderers, with that renderer's typed arguments; never a function or raw markup (type test), and a `chart` series colour that is not hex, `rgb()`/`hsl()` or `var(--…)` throws. 2. `check_web.py` fails on a fixture with an `innerHTML` assignment (or `outerHTML`, `insertAdjacentHTML`, an `innerHTML` key, `dangerouslySetInnerHTML`, `document.write`, `setHTMLUnsafe`, `createContextualFragment`, `parseFromString`) elsewhere in `web/` and passes on `main`. 3. A rendered `chart()` inside it reads token colours (computed style test).

### FE-76 · Token bridge for `packages/coast`: chrome and renderer · M
- Status: NEW. Agent: Claude; Codex reviews. Hot spot: `packages/coast/**`.
- Depends: —
- Files: `packages/coast/tokens-bridge.css`, `packages/coast/coast.css`, `packages/coast/src/palette.ts`, `packages/coast/src/coast3d/viewer.ts` (read colours from the palette only), `packages/coast/src/charts/series.ts` (literals → `var(--coast-…, literal)`), `scripts/check_tokens.mjs`, `scripts/token-lint-coast-baseline.json` (the package's own baseline, so `--base` stays a pure growth check), `tests/test_check_tokens.mjs`, `tests/coast/coast-palette.test.ts`, `e2e/coast-computed-style.spec.ts` + `e2e/coast-computed-style.json` (values recorded from `main` before the change).
- Build: § 3A.4 items 1, 3, 4 and 5 for `coast.css`, the viewer and `series.ts`; in `series.ts` colours move from SVG presentation attributes into `style` properties, since attributes do not resolve `var()`; `packages/coast/src/palette.ts` is the package's one allowed literal file (like `web/map/palette.ts`); the lint covers `packages/coast/**` with a seeded shrink-only baseline that excludes the converted files.
- Accept: 1. Computed colours on `/coast` and the v1 terrain presentation are equal before and after (e2e reads fixed elements). 2. `DEFAULT_COAST_PALETTE` equals today's ten distinct values (test). 3. With `data-coast-theme="tokens"` the terrain chrome reads `web/tokens.css` values. 4. The lint fails on a new literal in `packages/coast` and passes on `main`.

### FE-77 · `panel.css` onto the token bridge · L (two PRs, FE-77a and FE-77b)
- Status: NEW. Agent: Claude; Codex reviews. Hot spot: `packages/coast/panel.css`.
- Depends: FE-76
- Files: `packages/coast/panel.css`, `packages/coast/tokens-bridge.css`, `scripts/token-lint-coast-baseline.json`, `e2e/coast-computed-style.spec.ts`, `scripts/check_contrast.mjs` (bridged pairs).
- Build: § 3A.4 item 2: each of the 315 hex literals (288 unique, on 285 lines; counted with `check_tokens.mjs`'s `HEX` regex) becomes `var(--coast-…, literal)`; the local `:root` aliases are renamed `--coast-*`; FE-76 seeds the baseline with these 315 `panel.css` findings and each PR removes the ones it converts. The 288 values map to a few dozen `--coast-*` role names, not one name each; about 285 changed lines plus those role mappings and the e2e additions exceed one PR, so FE-77a converts lines 1–1,472 and FE-77b the rest, each ≤ ~400 lines. FE-77a (done) also renamed the aliases across the whole file, since a half-renamed alias breaks v1 or v2: their definitions in `:root` and `:host` are gone and each use reads `var(--coast-<role>, <today's :host value>)`; the two later lines that this touched (the `:host` one-liner and `.catch-counts dd`) were converted whole, because the lint baseline keys on the line. FE-77a's e2e records every element of each report-dialog tab from a synthetic report (`e2e/coast-report-fixture.ts`) and checks the dialog under the opt-in; FE-77b reuses both. FE-77b (done) converted the last 95 literals onto existing roles, leaving `panel.css` with no baseline entry, and deleted `web/app/coast-markup.css`. The legend ramps without a `web/tokens.css` ramp (reef, reef-fit, shore, current, wave and the seven-stop `bathy` depth legend, which matches none of § 5's four `--depth-*` stops) stay unmapped in the bridge; FE-61 adds tokens for them or drops those legends.
- Accept: 1. Computed colours of the report dialog, history and catch sheet in v1 are unchanged. 2. Under the opt-in, text pairs pass 4.5:1 in `check_contrast.mjs`. 3. `panel.css` defines no unprefixed custom property.

### FE-30 · Profiles applied across the app · M
- Status: CHANGED (targets merge the coast list; parity with `experience.ts` from FE-73). Agent: Claude.
- Depends: FE-20, FE-73
- Files: `web/app/CommandBar.tsx`, `web/species.ts` (wraps `species.js`, `search-plans.js` and `dist/coast-targets.js`' list as data), `web/profile.ts`, `tests/test_species_profile.mjs`, `e2e/v2-profile.spec.ts`.
- Build: § 8 applied: target list (SkipperCast plans plus coast targets, translated by `coastTarget`), depth limit to both presentations, layer defaults, caveat text, search plans filtered by method.
- Accept: 1. Switching to Shore hides reef marks and shows surfperch first in Chart and Terrain. 2. Spear limits marks to 60 ft (fixture test). 3. `?profile=` and Fish `?mode=` win over storage; an unsupported target stays explicit.

### FE-31 · Daily brief model (adapter) · M
- Status: PARTLY on `main`: the model is `packages/coast/src/daily.ts` with `state/experience.ts` and `presentation.ts` ([#385](https://github.com/Grahammmm/skippercast/pull/385), [#393](https://github.com/Grahammmm/skippercast/pull/393)), bound to SLO only. Remaining: the regional adapter. Agent: Claude.
- Depends: FE-30, FE-74, FE-12
- Files: `web/brief/model.ts`, `web/brief/types.ts`, `tests/test_brief_model.mjs`, `tests/fixtures/brief/*` (synthetic regional forecast, tides, buoy).
- Build: § 10 fields: where `coastReport` binds, map `buildDaily` output (headline, deck, tiles, windows, caveats, beach notice) to the brief type; elsewhere build the same fields from SkipperCast's regional forecast, tides and buoy feeds, with the local-report line marked unavailable; fleet line from the landing-reports feed; tile freshness limits.
- Accept: 1. Morro Bay fixture output equals `buildDaily`'s for the same inputs (no reimplementation). 2. A Monterey fixture yields the regional brief and the unavailable line. 3. A tile past its limit is stale. 4. Each profile yields its § 8 caveat.

### FE-37 · Brief column and mobile sheet · M
- Status: CHANGED (renders the adapter). Agent: Claude.
- Depends: FE-31, FE-75
- Files: `web/brief/{Brief,Tiles}.tsx`, `web/app/Desktop.tsx`, `web/app/Mobile.tsx`, `e2e/v2-brief.spec.ts`.
- Build: § 10 rendering of the FE-31 model in tokens: headline, deck, four tiles with basis popovers, lower-exposure window, caveat, notice link, fleet line, footer; the mobile sheet's peek, half and full content.
- Accept: 1. A stale tile renders the stale state and its age. 2. The mobile sheet shows headline, tiles, top pick and slider at the half detent. 3. axe clean at both widths.

### FE-32 · Conditions view from `packages/coast` · L
- Status: CHANGED (no series port; the v1 composition of #393 is the reference). Agent: Claude.
- Depends: FE-37, FE-75, FE-77
- Files: `web/app/views/Conditions.tsx`, `web/conditions.ts` (rows from SkipperCast's dual-model forecast plus `coastReport` local rows), `tests/test_conditions_rows.mjs`, `e2e/v2-conditions.spec.ts`.
- Build: § 10 Conditions: `packages/coast` `chart()` through `CoastMarkup`, cursor bound to `hour`, the `?current=` control shared with the map, per-source clocks, tide events, before-you-go notes.
- Accept: 1. A 2 h hole produces two path segments (fixture through `chart`). 2. The seven-day horizon stays when the coast report covers fewer hours (test). 3. Dragging the cursor moves the map's hour. 4. Scrolls sideways at 390 px.

### FE-33 · Tide sparkline and tide tile · S
- Status: CHANGED (`chart(…, {mini: true})` and `briefing.ts` `tideChart` where bound). Agent: Claude.
- Depends: FE-32
- Files: `web/brief/TideSpark.tsx`, `web/tides.ts` (wraps the existing CO-OPS reader), `tests/test_tides.mjs`.
- Build: § 10 sparkline with events and night shading through `CoastMarkup`; trend from the curve; reference level in the basis popover.
- Accept: 1. Trend is Rising, Falling or Turning per the 15-minute rule. 2. Fewer than two points → "Tide series unavailable".

### FE-34 · "Where to look" ranking · M
- Status: CHANGED (two sources in one list). Agent: Claude.
- Depends: FE-37, FE-18
- Files: `web/brief/WhereToLook.tsx`, `web/ranking.ts` (wraps `spot-ranking.js`, `species-fit.js` and `packages/coast` `rankedHabitat`), `tests/test_ranking.mjs`.
- Build: § 10 top four within the profile limit: coast ranked habitat where terrain exists, atlas spots elsewhere, never mixed scores; distance, depth band, fit badge, reason; selection syncs with both presentations.
- Accept: 1. Items outside the limit never appear. 2. Clicking selects the mark or habitat and opens the card. 3. Wording per § 12; the two rankings are labelled by source.

### FE-35 · History view · S
- Status: PARTLY on `main`: `ui/history.ts` `historyView` over `/api/coast/history` renders in v1 Conditions ([#385](https://github.com/Grahammmm/skippercast/pull/385), [#393](https://github.com/Grahammmm/skippercast/pull/393)). Remaining: the v2 view. Agent: Claude.
- Depends: FE-32, FE-74
- Files: `web/app/views/History.tsx`, `tests/test_history_view.mjs`.
- Build: § 10 History: `historyView` through `CoastMarkup` with station, metric and range pickers bound to the store; the unavailable state outside a binding.
- Accept: 1. A region without a history binding shows the unavailable state (test). 2. Copy says "recorded history". 3. Picker choices survive Back and Forward.

### FE-36 · Shore runs, access points and guidance · M
- Status: PARTLY on `main`: the terrain draws shore features for surfperch and halibut and the bridge serves `slo-shore-habitat.geojson`. Remaining: Chart runs and access pins, and `fish`'s `opportunity.ts` guidance, which was not ported. Agent: Claude.
- Depends: FE-30, FE-74
- Files: `web/map/shore.ts`, `web/brief/shore.ts` (ported `fish/src/opportunity.ts` priority and guidance), `tests/test_shore.mjs`.
- Build: § 8 and § 9 shore profile in Chart: runs with priority tint, access pins, guidance with the source link, review dates shown and expiry honoured; data through `coastFetch` until FE-43.
- Accept: 1. An expired access review drops the run to "Hold" (test). 2. A run inside an MPA is blocked (test). 3. Visible only with `profile=shore`.

## Phase 3: `fish` data sources into SkipperCast (retire the bridge)

Under Q14 option 1 these are Codex's. Each output matches the
`packages/coast` type the client already reads, so FE-84 switches the
bridge without a client change. None blocks the v2 shell; all block FE-62.

### FE-40 · CDIP nearshore model collector · M
- Status: CHANGED (output = `packages/coast` `NearshoreSite`). Agent: Claude (owner decision, #413).
- Depends: —
- Files: `src/skippercast/pipeline/cdip_nearshore.py` (collector, `publish`, CLI), `scripts/live_cycle.sh` (one step after the buoy refresh; replaces the `live.py` hook, so `refresh_regions.py` and its offline tests stay untouched), `regions/morro-bay/region.json` (sites), `catalog/sources.json`, `tests/fixtures/cdip/*`, `tests/unit/test_cdip_nearshore.py`, `docs/data-sources.md`, `docs/live-conditions.md`.
- Build: § 11 row: site identity and coordinate checks, three-hour series with masks, freshness, published in `live-conditions.yml`'s snapshot.
- Accept: 1. A site label or coordinate mismatch raises. 2. Partial arrays are rejected. 3. A fixture validates against the `NearshoreSite` shape. 4. Platform build diff clean.
- **Owner**: add the register row.

### FE-41 · Beach health collector · S
- Status: CHANGED (output = `BeachWaterQuality`). Agent (proposed): Codex.
- Depends: —
- Files: `src/skippercast/pipeline/beach_health.py`, `scripts/live_cycle.sh` (not `live.py`: the collector writes its own file per bound region, so the region refresh and its offline tests stay free of county calls), `catalog/sources.json`, `tests/fixtures/beach-health/*`, `tests/unit/test_beach_health.py`, `docs/data-sources.md`, `docs/live-conditions.md`.
- Build: § 11 row; statuses and links only. Source id `slo-beach-water-quality`, the id `packages/coast` already reads.
- Accept: 1. `exceededTransferLimit` or a count mismatch raises. 2. Out-of-county geometry is rejected. 3. No date is invented. 4. Output validates against `BeachWaterQuality`.
- **Owner**: add the register row.

### FE-42 · NDBC history backfill and seasonal bands · L
- Status: CHANGED (output = `HistoryBundle`). Agent (proposed): Codex.
- Depends: —
- Files: `src/skippercast/pipeline/ndbc_history.py`, `.github/workflows/buoy-history.yml`, `catalog/sources.json`, `tests/fixtures/ndbc-history/*`, `tests/unit/test_ndbc_history.py`, `docs/live-conditions.md`.
- Build: § 11 row: annual checkpoints with SHA under `var/`, monthly p10 / median / p90 with counts, coverage and years; recent hourly means for 7, 14 and 45 days.
- Accept: 1. Quantiles on a fixture match hand-computed values. 2. Unchanged archives download nothing. 3. Missing hours are counted, never filled. 4. Output validates against `HistoryBundle`.
- **Owner**: approve the workflow; run the backfill once.

### FE-43 · ESI shore runs and access points import · M
- Status: CHANGED (schema = the shore-habitat GeoJSON the renderer reads). Agent (proposed): Codex.
- Depends: —
- Files: `scripts/collect_shore_habitat.py` (a `collect_` product collector like `collect_cdfw_mpas.py`; `import_` is a research prefix in `tests/contract/test_research_boundary.py`), `catalog/shore-habitat/morro-bay.geojson`, `schemas/shore-habitat.schema.json`, `src/skippercast/platform/build.py`, `catalog/sources.json`, `tests/contract/test_shore_habitat.py`, `docs/data-sources.md`.
- Build: § 11 row: runs with source year, access points with ids and links, review dates in the asset.
- Accept: 1. Schema validation in the contract test, compatible with `slo-shore-habitat.geojson`. 2. Platform build diff clean. 3. No photo or description text from the inventory.
- **Owner**: add the register rows; confirm the review dates.

### FE-44 · GOES frame times index · S
- Status: CHANGED (output = `CloudImage`). Agent (proposed): Codex.
- Depends: —
- Files: `src/skippercast/pipeline/goes_frames.py`, `scripts/live_cycle.sh` (one call per cycle; the index is region-independent, so it is published beside `latest.json` rather than from the per-region `live.py`), `catalog/sources.json`, `tests/unit/test_goes_frames.py`, `tests/fixtures/goes/capabilities.xml`.
- Build: § 11 row: GetCapabilities time list as a `CloudImage` record with the fetch time.
- Accept: 1. A capabilities fixture yields the list. 2. Times are ISO UTC, sorted, deduplicated.

### FE-45 · NAIP source config and rights · S
- Status: CHANGED (host list shared with `map-sources.ts`). Agent (proposed): Codex.
- Depends: —
- Files: `catalog/sources.json`, `regions/morro-bay/region.json` (`basemap.aerial`), `schemas/region.schema.json` (if needed), `docs/data-sources.md`, rebuilt `dist/regions/*`.
- Build: § 11 row; the region flag (`basemap.aerial` is an object naming the catalog source, the coverage check date and the acquisition window, so the Aerial attribution can carry the imagery date); a test that `catalog/sources.json`'s NAIP host equals `packages/coast` `mapSourceHosts`.
- Accept: 1. Contract tests pass. 2. Platform build diff clean.
- **Owner**: add the register row.

### FE-84 · Snapshots from SkipperCast feeds; bridge upstream switch · L
- Status: NEW, narrowed 2026-10-08. Agent: Claude (#413). Narrowed to the four sources its dependencies publish: the report's forecasts, observations, tides, alerts, catches and spatial layers have no SkipperCast feed in the `Report` shape yet, so they move in FE-87.
- Depends: FE-40, FE-41, FE-42, FE-44
- Files: `src/skippercast/pipeline/coast_snapshots.py` (assembles the ocean packet; the nearshore, beach and history feeds are already `packages/coast` shapes and are read as published), `scripts/live_cycle.sh`, `server/coast-data.ts` (`COAST_FEEDS` per-source switch, Fish Worker as the dated fallback), `server/routes/coast.ts`, `server/env.ts`, `scripts/wrangler_config.mjs` and `.github/workflows/deploy-cloudflare.yml` (the var), `tests/test_coast_data.mjs`, `tests/test_wrangler_config.mjs`, `tests/unit/test_coast_snapshots.py`, `docs/coastal-service.md`, `docs/live-conditions.md`.
- Build: the bridge serves SkipperCast's feeds per source (`nearshore`, `water-quality`, `ocean`, `history`) with the same validation; source clocks and outcomes stay original; the server applies each feed's age limit itself and falls back to Fish for a missing, invalid or stale feed.
- Accept: 1. `/api/coast/{report,ocean,history}` return schema-valid packets with the switched sources from SkipperCast feeds (fixture test). 2. The client tests pass unchanged, and with the switch off every path behaves as before (the bridge tests also run with every source switched and nothing published). 3. Two distinct persisted refresh runs are recorded in the PR.
- **Owner**: approve (`server/`, the deploy workflow line); set `COAST_FEEDS` after the receipts; confirm the run receipts.

### FE-87 · Coast report base from SkipperCast feeds · L
- Status: NEW (split from FE-84), built 2026-10-08. Agent: Claude.
- Depends: FE-84
- Files: `src/skippercast/pipeline/coast_report.py` (report assembly with the NWS and CO-OPS reads ported from `fish`; network reads kept out of the local-only `coast_snapshots.py`), `scripts/live_cycle.sh`, `server/coast-data.ts` (a `report` source in `COAST_FEEDS`, the rights gate and the #422 follow-ups), `server/env.ts` (comment), `tests/unit/test_coast_report.py`, `tests/fixtures/coast/skippercast-report.json`, `tests/test_coast_data.mjs`, `docs/coastal-service.md`, `docs/live-conditions.md`.
- Build: the report's area forecasts (NWS gridpoints per county area), buoy observations, CO-OPS tides and events, NWS alerts with the area-zone filter, catch reports with their context and the spatial layers, assembled in the `Report` shape from SkipperCast collectors (existing ones where they cover the same source, new ones ported from `fish` `src/providers/` where not), each with its own `SourceStatus`; the FE-84 overlays then apply on SkipperCast's own report.
- Accept: 1. A fixture report validates against `Report` and passes `packages/coast` readiness. 2. Each source keeps its own clocks and outcome. 3. With every source switched, `/api/coast/*` snapshots make no Fish request (test).
- **Owner**: rights rows for any new source; confirm the run receipts.

### FE-85 · Terrain, imagery and habitat assets in SkipperCast storage · L
- Status: NEW. Agent: Claude (#413). The first publish waits on rights rows ([coastal-service.md](../../coastal-service.md#assets-in-skippercast-storage-fe-85)).
- Depends: —
- Files: `scripts/coast/publish_assets.py`, `.github/workflows/coast-assets.yml` (dispatch), `server/coast-data.ts` (R2 reads for `/coast-data/data/*` and habitat tiles), `server/routes/coast.ts` (passes the `FEEDS` binding), `tests/test_coast_data.mjs`, `tests/unit/test_coast_assets.py`, `tests/contract/test_coast_assets_workflow.py`, `docs/coastal-service.md`.
- Build: copy the reviewed assets with their SHA-256 manifest to R2; add server-side manifest SHA-256 verification (the bridge has none today; only the browser checks, in `regional.ts`): an object whose digest differs from its manifest entry, or that has no entry, is refused before any byte is served; keep the existing size and range gates and the private-prefix denial. Two groups, `terrain` and `habitat`; the reef context travels with `habitat` (it is derived from the habitat release), every region archive the release lists is copied (the renderer HEADs each one), and the shore files stay on the bridge for FE-10 and FE-43. A source without an approved, commercial-use `catalog/sources.json` row refuses the run. Split by asset group if over ~400 lines.
- Accept: 1. A fixture object with an altered byte, and one missing from the manifest, are both refused by the server (test). 2. Every served asset matches its manifest SHA-256 (live check recorded in the PR). 3. Encoded and traversal paths are refused. 4. The renderer's in-browser verified-asset checks still pass against R2.
- **Owner**: approve the workflow and `server/`; run the first publish.

## Phase 4: the remaining features in the new shell

### FE-50 · Account, boat profile and alerts in the masthead · M
- Status: STILL NEEDED. Agent: Claude.
- Depends: —
- Files: `web/app/AccountMenu.tsx`, `web/account.ts` (wraps `account.js`, `boat-profile.js`, `trip-alerts.js`), `e2e/v2-account.spec.ts`.
- Build: sign in (passkeys), boat presets from `first-run.js`, alerts, downloads and offline pack entry, in tokens.
- Accept: 1. `tests/test_accounts.mjs` unchanged and green. 2. Sign-in flow completes in e2e with the fixture. 3. The menu is keyboard operable.

### FE-51 · Trip planner, GPX export and offline pack · L
- Status: PARTLY on `main`: coastal snapshot save and delete ([#405](https://github.com/Grahammmm/skippercast/pull/405), `dist/coastal-offline-core.js`, `dist/sw.js`). Remaining: the v2 trip, GPX and offline entry. Agent: Claude. Hot spot: `dist/sw.js`.
- Depends: FE-18, FE-50
- Files: `web/app/Trip.tsx`, `web/trip.ts` (wraps `export-ui.js`, `gpx.js`, `trip-export.js`, `offline-pack.js`, `coastal-offline-core.js`), `dist/sw.js` (v2 precache and basemap tiles at zooms 8–12 for the saved region), `e2e/v2-trip.spec.ts`.
- Build: mark card actions, trip list in the account menu, GPX with the existing evidence labels, one offline section holding the chart pack and the coastal snapshots with their saved time and original clocks.
- Accept: 1. `e2e/ranked-export.spec.ts` logic passes against v2. 2. The offline pack size for Morro Bay stays under the documented budget. 3. GPX output is byte-identical to v1 for the same selection. 4. The coastal snapshot tests (`test_coastal_offline.mjs`) pass unchanged.

### FE-52 · Reports view · M
- Status: PARTLY on `main`: `ui/catches.ts` `catchSheet` and `fleetBrief`, the readable `/report` and `/feed.xml` ([#385](https://github.com/Grahammmm/skippercast/pull/385), [#395](https://github.com/Grahammmm/skippercast/pull/395)). Remaining: the v2 view. Agent: Claude.
- Depends: FE-37, FE-75
- Files: `web/app/views/Reports.tsx`, `web/reports.ts` (wraps `recent-discussions.js`, `bite-evidence.js`, `coastal-research-context.js`), `tests/test_reports_view.mjs`.
- Build: § 6 table: discussions, recent evidence, catch cards through `CoastMarkup` (`catchSheet`, eight at most), seasonal watch, charter evidence, with dates and source links; link to `/feed.xml`.
- Accept: 1. Catch cards keep boat, port, trip, species and the reported/retained/released labels. 2. No publisher prose or photos. 3. Reachable from the landing nav and the masthead.

### FE-53 · Fleet view · M
- Status: STILL NEEDED. Agent: Claude.
- Depends: FE-24, FE-21
- Files: `web/app/views/Fleet.tsx`, `web/fleet.ts`, `tests/test_fleet_view.mjs`.
- Build: public part: charter grounds and the boat directory link (`/boats`) when `FLEET_ENABLED`; admin part: the filter form from `fleet-activity.js` driving the FE-24 layers.
- Accept: 1. With the flags off the view shows grounds and the AIS 2024 option only. 2. Admin filters round-trip to the API exactly as `tests/test_fleet_layers.mjs` expects. 3. "Inferred from movement" present.

### FE-54 · Species plans, regulations and the sources page · M
- Status: CHANGED (coast targets in the menu; `/sources` canonical per Q16). Agent: Claude.
- Depends: FE-30, FE-18
- Files: `web/app/CommandBar.tsx` (target menu with search), `web/app/MarkCard.tsx` (regulations line), `dist/sources.html` (tokens restyle), `web/regs.ts` (wraps `regulations.js`), `tests/test_regs_wrapper.mjs`.
- Build: § 6 table rows for species, filters, search, regulations; the menu groups SkipperCast plans and coast targets without merging their scores; the sources page in the visual system with every basis sentence linking into it.
- Accept: 1. The target menu lists plans by profile method. 2. The regulations line matches `regulations.js` output for a fixture species, including the inherited-lookup guard from #396. 3. Copy lint clean on the restyled page.

### FE-55 · Advisor entry and pages in the visual system · S
- Status: STILL NEEDED. Agent: Claude.
- Depends: —
- Files: `web/advisor/copy.ts`, `server/advisor/pages/render.ts` (tokens link), `dist/chat.html`, `e2e/advisor-pages.spec.ts`.
- Build: the chat entry in the masthead when `TEXT_ADVISOR_ENABLED`; advisor pages load `web/tokens.css`.
- Accept: 1. With the advisor off nothing renders. 2. Advisor page snapshots are regenerated with the same text content.
- **Owner**: approve (`server/`).

### FE-78 · Coast and Fish links open the v2 app · S
- Status: NEW. Agent: Claude. Hot spot: `server/routes/assets.ts`.
- Depends: FE-73
- Files: `server/routes/assets.ts` (`AREA_PARAMS` gains `place`, `mode`, `species`, `presentation`, `habitat`, `current`; `/coast` → app with `presentation=3d` when v2 is on), `tests/test_worker_routes.mjs`.
- Build: § 3A.3 routing; with v2 off every path is unchanged.
- Accept: 1. With v2 off `/coast` still serves `coast.html` and `/` is byte-identical. 2. With v2 on `/?place=morro&mode=shore` serves the app and `/coast` serves the app at `presentation=3d`. 3. `/report`, `/feed.xml`, `/methodology`, `/about` unchanged.
- **Owner**: approve (`server/`).

### FE-83 · Home memory parity with the coast preferences · S
- Status: NEW. Agent: Claude.
- Depends: —
- Files: `web/ports.ts`, `web/app/FirstRun.tsx`, `web/landing/PortInput.tsx`, `tests/test_ports.mjs`.
- Build: § 3A.3: v2 save and forget call the same synchronisation `dist/home-port.js` uses since #396 (shared key plus `packages/coast` preferences), through a shared function in `web/ports.ts`; denied storage is supported; a shared link never changes home.
- Accept: 1. A port saved in v2 is read by v1 and by `/coast` (test against both readers). 2. Forget clears both. 3. With storage denied the chooser still navigates.

### FE-86 · Readable and information pages in the visual system · S
- Status: NEW. Agent: Claude. Hot spot: `server/coast-pages.ts` (Codex's).
- Depends: FE-76
- Files: `dist/coast-readable.html`, `dist/coast-readable.css`, `tests/test_coast_pages.mjs`, `tests/fixtures/coast-readable/` (the pre-restyle template), `e2e/coast-readable.spec.ts`.
- Build: the `/report`, `/methodology` and `/about` template loads `web/tokens.css` and its sheet reads only token names (the pages use no `packages/coast` styles, so the `--coast-*` bridge has nothing to theme and is not loaded); `/methodology` and `/about` link to the sources page (Q16) at `/sources` (the Worker route added by #475; `/sources.html` keeps working); text content unchanged apart from that link.
- Accept: 1. Page text is byte-identical (test compares text nodes). 2. Contrast and axe clean. 3. CSP unchanged.

## Phase 5: flip, delete, retire

### FE-60 · Flip `UI_V2` on by default · S
- Status: CHANGED (dependencies and the one-map acceptance). Agent: Claude.
- Depends: FE-07, FE-11, FE-12, FE-14 … FE-25 (not FE-13), FE-27, FE-30 … FE-37, FE-50 … FE-55, FE-71 … FE-83, FE-86
- Files: `deployments/production.json`, `.github/workflows/deploy-cloudflare.yml`, `CHANGELOG.md`, `docs/web-app.md`, `README.md` (status).
- Build: default on; `?ui=v1` stays for one release; release notes.
- Accept: 1. Smoke test in the deploy workflow passes on `/`, `/map` and `/coast`. 2. § 15 items 1–6 and `docs/FISH-MERGE-STATUS.md`'s desktop and mobile matrix verified live and linked. 3. No duplicate map, picker or timeline for one context (e2e). 4. Tag the release.
- **Owner**: approve; confirm the live check.

### FE-61 · Delete the v1 shell and the v1 coastal modules · L (mostly deletions)
- Status: CHANGED (also removes Codex's v1 coastal glue, after Codex confirms on #413). Agent: Claude.
- Depends: FE-60 (one release later)
- Files: `dist/index.html` (becomes the v2 app at `/`), `dist/coast.html`, `dist/coast-entry.js`, `dist/coast-launch.js`, `dist/coast-workspace.js`, `dist/coast-conditions.js`, `dist/coastal-*.js` (the modules no v2 file imports), `dist/*.css` (v1 sheets), `dist/tokens.css`, `dist/vendor/leaflet*`, `dist/vendor/images`, `dist/vendor/maplibre-*`, `dist/vendor/pmtiles-*`, the `dist/*.js` modules fully replaced by `web/` wrappers, `packages/coast/*.css` fallbacks (§ 3A.4 item 4), `scripts/web-vendor-sha256.json`, `scripts/copy-lint-baseline.json`, `vite.config.mjs` (`cssMinify: true`), `server/routes/assets.ts` (remove the switch), tests.
- Build: delete in dependency order (a script lists modules no test or page imports); turn CSS minification on and re-check every page; baselines shrink. Split by group if over 400 changed lines of non-deletion edits.
- Accept: 1. No Leaflet reference remains (grep test). 2. `check_contrast.mjs` reads `web/tokens.css` only. 3. All checks green; the copy-lint and token-lint baselines shrink.
- **Owner**: approve (`server/`).

### FE-62 · Archive `fish` receipts and retire the repository · M
- Status: CHANGED (blocked on the bridge's retirement). Agent: Claude, with Codex for the data receipts.
- Depends: FE-60, FE-84, FE-85, FE-87; FE-40 … FE-45 merged and run
- Files: `docs/archive/fish/README.md`, `docs/archive/fish/**` (the § 15 item 9 list), `docs/plans/front-end/README.md` (status), `docs/data-sources.md`.
- Build: copy the listed docs and receipts with the historical-note prefix; tick § 15's checklist with links; list the Cloudflare resources, including the Fish Worker the bridge used.
- Accept: 1. Every § 15 item has a link or a dated note. 2. No `fish/public/data` file is copied. 3. `server/coast-data.ts` has no Fish Worker origin. 4. `check_repository.py` passes on the archive.
- **Owner**: archive the GitHub repository, delete the Cloudflare resources, delete the repository, decide the domain redirect (Q10).

## Parallelism

Waves (a task starts when its dependencies merge; C = Claude, X = Codex):

| Wave | Claude | Codex |
| --- | --- | --- |
| 1 (now) | FE-07, FE-72, FE-73, FE-76, FE-83, FE-50, FE-55 | FE-70, FE-10, FE-40 … FE-45, FE-85 |
| 2 | FE-71 (FE-70, FE-73), FE-74, FE-75, FE-77, FE-78, FE-86 | FE-79, FE-81 (FE-70) |
| 3 | FE-11 (FE-10, FE-71, FE-72), FE-12 (FE-71) | FE-84 (FE-40, 41, 42, 44) |
| 4 | FE-14, FE-18, FE-19, FE-23 (also FE-45); FE-15 (FE-12, FE-74); FE-22 (FE-12, FE-74) | — |
| 5 | FE-16 → FE-17 → FE-27; FE-25 (FE-07, FE-11, FE-15) | — |
| 6 | FE-20 (FE-14 … FE-18, FE-71) | — |
| 7 | FE-21, FE-24, FE-30, FE-80 (FE-79), FE-82 (FE-81) | — |
| 8 | FE-31 → FE-37 → FE-32 → FE-33, FE-35; FE-34, FE-36, FE-51, FE-52, FE-53, FE-54 | — |
| 9 | FE-60 → FE-61; FE-87 (FE-84); FE-62 (FE-84, FE-85, FE-87) | data receipts for FE-62 |

Critical path: FE-70 → FE-71 → FE-11 → FE-14/FE-18 and FE-12 → FE-15 →
FE-16 → FE-17 → FE-20 → FE-30 → FE-31 → FE-37 → FE-32 → FE-60. FE-10
(Codex) and FE-72 must merge before FE-11.

Conflict hot spots (design § 3A.6 holds the rules):

- **Shared with Codex:** `packages/coast/**` (FE-70, FE-79, FE-81 Codex;
  FE-76, FE-77 Claude), `dist/coast-*.js` and `dist/coastal-*.js` (FE-70
  edits `coast-workspace.js`; FE-61 deletes them), `web/state.ts`,
  `web/fish-links.ts`, `web/coast-context.ts` (FE-73; Codex's v1 work reads
  them), `server/app.ts`, `server/routes/assets.ts` (FE-78, FE-61),
  `server/coast-data.ts` (FE-84, FE-85), `server/coast-pages.ts` and
  `dist/coast-readable.*` (FE-86), `dist/sw.js` (FE-51 and Codex's offline
  work), `scripts/check_tokens.mjs` (FE-76), `package.json` /
  `pnpm-lock.yaml`, `CHANGELOG.md`.
- **Claude only:** `web/app/{MarkCard,Legend,LayerRail,TimeDock}.tsx`
  (MarkCard: FE-11, FE-18, FE-80, FE-54 in that order; Legend: FE-14, FE-20,
  FE-80; LayerRail: FE-15, FE-20, FE-80; TimeDock: FE-12); `web/map/stage.ts`
  (FE-71, FE-11, FE-80, FE-82); `web/app/{Desktop,Mobile}.tsx` (FE-71,
  FE-37); `server/security-headers.ts` (FE-22, FE-23: one line each).
- **Codex only:** `catalog/sources.json` and `live.py` (FE-40 … FE-45:
  append and rebase).

## Dependency graph

```
Done: FE-01 … FE-06, FE-08, FE-09.  Dropped: FE-13, FE-26.
No open dependencies: FE-07, FE-10, FE-50, FE-55, FE-70, FE-72, FE-73, FE-76, FE-83, FE-85, FE-40 … FE-45
FE-70 + FE-73 ─► FE-71;  FE-70 ─► FE-79, FE-81
FE-73 ─► FE-74, FE-78;  FE-76 ─► FE-75, FE-77, FE-86
FE-10 + FE-71 + FE-72 ─► FE-11 ─► FE-14, FE-18 (also FE-71), FE-19;  FE-11 + FE-45 ─► FE-23
FE-71 ─► FE-12;  FE-12 + FE-74 ─► FE-15, FE-22;  FE-15 ─► FE-16 ─► FE-17;  FE-17 + FE-74 ─► FE-27
FE-07 + FE-11 + FE-15 ─► FE-25
FE-14 + FE-15 + FE-16 + FE-17 + FE-18 + FE-71 ─► FE-20 ─► FE-21, FE-24
FE-20 + FE-79 ─► FE-80;  FE-20 + FE-81 ─► FE-82;  FE-20 + FE-73 ─► FE-30
FE-30 + FE-74 + FE-12 ─► FE-31;  FE-31 + FE-75 ─► FE-37;  FE-37 + FE-75 + FE-77 ─► FE-32 ─► FE-33
FE-32 + FE-74 ─► FE-35;  FE-37 + FE-18 ─► FE-34;  FE-30 + FE-74 ─► FE-36
FE-18 + FE-50 ─► FE-51;  FE-37 + FE-75 ─► FE-52;  FE-24 + FE-21 ─► FE-53;  FE-30 + FE-18 ─► FE-54
FE-40 + FE-41 + FE-42 + FE-44 ─► FE-84
Phases 0–4 and FE-71 … FE-83, FE-86 ─► FE-60 ─► FE-61;  FE-84 ─► FE-87;  FE-60 + FE-84 + FE-85 + FE-87 + FE-40 … FE-45 ─► FE-62
```

## Backlog (no task yet)

- **Light theme switch** (US-L1): a `data-theme` toggle in the account menu,
  the light contrast pass, map style day variant on the app; the token
  bridge's opt-in carries it into `packages/coast`.
- **Admin restyle** (US-L3): `web/admin` on `web/tokens.css`.
- **Second active region on the landing** (US-L2): region-aware readings
  once another region leaves preview.
- **Terrain for further regions**: each is a mapping-pipeline task for
  Codex (`skills/skippercast-map-coast`), shown by MapStage with no shell
  change.
- **Landing readings for the typed port** before navigation.
- **`packages/coast` markup as data**: if `CoastMarkup` proves limiting,
  Codex splits a renderer into a model and a template; v2 then renders the
  model in Preact. Announced on #413 first.

## Definition of done

1. `/` and `/map` serve the landing and the Bridge shell by default, in one
   visual system, with the v1 shell, the v1 coastal modules and `/coast`'s
   separate page deleted (FE-60, FE-61).
2. The map stage offers Chart (MapLibre, every § 9 layer) and Terrain 2D /
   3D (`packages/coast`) over one camera, selection and hour (Phase 1).
3. Boat, Shore and Spear shape both presentations, the brief, the species
   list and the plans (Phase 2), from one state controller.
4. Every `fish`-only source flows through a SkipperCast collector with a
   catalog entry and a register row, and the bridge reads SkipperCast
   storage (Phase 3, **Owner** rows).
5. `fish`'s docs and receipts are in `docs/archive/fish/` and the owner
   has archived and deleted the repository (FE-62).
6. Costs stay at the § 16 estimate (**Owner** confirms against the bill).
