<!-- Generated from 07-subsurface-depth-ladder/spec.md, plan.md, tasks.md. Edit those, not this file. -->

# 07 · Subsurface depth ladder: temperature at depth, thermocline, mixed layer, salinity

Status: proposed, 2026-11-19 · Priority 7 · Effort estimate: L · Depends on: 05 (shared WCOFS read path), 01 (readings). **Owner question first:** confirm this is what "subsea weather" means (see Open questions).
Source: SkipperCast competitor analysis, recommendation 7 (Fishare subsurface temperature at depth, Salty Offshore Elite subsurface temp, MLD and salinity, SiriusXM thermocline and salinity, RipCharts sub-surface SST).

## Intended goal

The angler can slide a depth control (surface, 10, 20, 30, 50, 100 m) and see the forecast water temperature at that depth, plus two summary maps: **thermocline depth** and **mixed-layer depth**. A **salinity** field is also available. All of it follows the time dock across the WCOFS forecast.

## Purpose

SkipperCast's Water temp layer is satellite surface temperature. Its basis sentence says it is "neither bottom temperature nor a forecast". The repo has no salinity, subsurface temperature, thermocline or mixed-layer product. The WCOFS model that SkipperCast already reads for currents publishes `temp` and `salt` on 41 depth levels (0, 1, 2, 4 … 100, 125 … 5000 m), verified in the OPeNDAP DDS on 2026-11-19. SkipperCast reads only depth index 0 today. Bottomfish and water-column anglers care where the cold water sits. Offshore competitors charge their top tier for this.

## User journey

1. Kai turns on **Below surface** in the rail. A vertical depth ladder appears on the map's right edge: `0 · 10 · 20 · 30 · 50 · 100 m`, with feet shown as well when feet units are chosen.
2. He picks 30 m. The field redraws as forecast temperature at 30 m for the dock hour: "WCOFS 03z +9 h · model, not observed · 0.04° grid".
3. He switches the ladder's top chip to **Thermocline**. The map shows the depth of the sharpest temperature drop per cell, for example 18–35 m, with a note that it's estimated from model levels.
4. **Mixed layer** shows how deep the surface water is stirred (a temperature drop of 0.2 °C from 10 m).
5. **Salinity** is its own rail entry: surface salinity in PSU on a haline ramp.
6. Tapping a point (spec 01) shows a mini profile: temperature against depth from 0–100 m at that cell and hour, with the thermocline marked.

## Use cases

- **Find where 50–52 °F water sits at 30 m over a reef** for rockfish or lingcod.
- **Check whether a surface warm break extends below the surface** or is a thin skin.
- **Spot fresh-water plumes** (low salinity) after rain off river mouths.

## Requirements

1. **R1** The pipeline reads WCOFS `temp` at depth indexes for 0, 10, 20, 30, 50 and 100 m, and `salt` at 0 m, on the same regional subset, frames and contract checks as `wcofs_surface`. Frames are f000–f072 every 6 h, to keep within budget. Total cells per frame are capped by a new `WCOFS_DEPTH_BUDGET` (for example 6 levels × ≤ 15,000 cells).
2. **R2** Derived per cell and frame:
   - Thermocline depth is the mid-depth of the level pair with the maximum −dT/dz across levels 0–100 m (1, 2, 4 … 100 m available), but only where max −dT/dz ≥ 0.05 °C/m. Otherwise it is `none` ("well mixed").
   - Mixed-layer depth is the shallowest depth where T < T(10 m) − 0.2 °C (de Boyer Montégut criterion), interpolating linearly between levels. It is labelled "estimated from model levels".
3. **R3** Publish layers `wcofs-temp-depth` (fields per level), `wcofs-salt-surface`, `wcofs-thermocline` and `wcofs-mld` in `habitat-dynamics.json` with the SHA-256 tile rules, `max_age_hours` 36 like WCOFS today, and `catalog/layer-inventory.json` entries.
4. **R4** Client entries: `subsurface-temp` (hour; depth state `depth=0|10|20|30|50|100|thermocline|mld` in links) and `salinity` (hour). Each follows the card rules and says "model (NOAA WCOFS), not observed".
5. **R5** The ramp for temperature at depth reuses the SST tokens with its own range per depth. Salinity uses a new haline ramp token set.
6. **R6** The point readout includes a 0–100 m profile sparkline at the tapped cell for the dock hour.
7. **R7** Offline packs don't include these layers in this increment, and the rail says so.

## Acceptance

- Pipeline tests with a synthetic stratified column: thermocline found at the right pair, MLD interpolated correctly, and a well-mixed column gives `none`.
- Contract tests: changed units or depth axis values make the step refuse (as `wcofs_surface` does).
- Browser: the depth ladder switches fields within 300 ms on a mid-range phone, without refetching, once the frame is loaded.
- `pytest -m "not gis"`, `node --test tests/test_*.mjs`, `pnpm typecheck` and `pnpm build` pass. The published bytes per region and cycle are documented in the PR and stay inside the R2 and perf budgets.

## Non-goals

- No bottom temperature at the seafloor depth in this increment. It's possible later by sampling the level nearest the bathymetry.
- No observed subsurface data (Argo, gliders). No dissolved oxygen (not in WCOFS).

## Open questions for the owner

- Does "subsea weather" mean this (temperature and salinity below the surface), currents (already shipped), or something else? Build only after confirmation.
- Are 6 depth levels and 6-hourly frames enough, or is 3-hourly needed like currents?


---

# Implementation plan · 07 subsurface depth ladder

## Evidence (observed 2026-11-19)

- `src/skippercast/pipeline/habitat_dynamics.py` `wcofs_surface` (L247–L313): catalog discovery for the newest cycle, DAS unit contract checks (`temp` Celsius, `u_eastward`/`v_northward` m/s, `Depth` m), mask contract, ≤ 15,000-cell subset, 0.04° spacing check, frames f000–f072 every 3 h, query `temp[0][0]{cut}`.
- WCOFS DDS/DAS (fetched 2026-11-19): `Depth[41]` = 0, 1, 2, 4, 6, 8, 10, 12, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 125, 150, 200, … 5000 m. `temp` "potential temperature" in Celsius. `salt` "salinity" in PSU. `zeta` in metres. All on `[time][Depth][ny][nx]` over 935 × 833.
- The Water temp basis in `catalog/app/strings.json` (`layer.water-temp.basis` or similar) says surface only, not a forecast. Keep it, and make the new layer's basis distinct.
- Client patterns: `web/map/sst.ts` (texture, contours, legend range), `web/map/field.ts` (`fieldTexture`), `web/map/habitat-feed.ts` (verification), `web/map/currents.ts` (hour-following frames via `web/map/frames.ts` `forecastTime`).
- Visual reference: `docs/research/inspiration/skippercast_inspiration.json` per_layer "Subsurface temperature / thermocline" (gap: "No strong X example found … thermal + depth slider") and "Salinity" (example `salinity`: NASA SMAP animation; "haline ramp + running date stamp", cmocean haline).

## Data and request plan

- Depth indexes: look them up by value from the `Depth` axis (never hard-code indexes). Refuse if any of {0, 10, 20, 30, 50, 100} is missing.
- One DAP request per frame for levels 0..100 m as a contiguous slab (`temp[0][0:1:20]{cut}`, indexes 0–20 cover 0–100 m) to compute the thermocline and MLD from all 21 levels. Publish only the 6 ladder levels plus the derived fields. Check bytes: 21 levels × 15,000 cells × 4 B ≈ 1.3 MB per frame in transfer. That's acceptable for 13 frames, but measure it, and fall back to 6 separate level requests if the shared HTTP budget (5 MB decompressed in the pipeline client) is exceeded.
- Salinity: `salt[0][0]{cut}` (surface).

## Data model

```json
"wcofs-temp-depth": {"fields": ["latitude","longitude","t0","t10","t20","t30","t50","t100"], "units": "Celsius", "frames": [...], "tiles": [...]},
"wcofs-thermocline": {"fields": ["latitude","longitude","depth_m","gradient_c_per_m"]},
"wcofs-mld": {"fields": ["latitude","longitude","mld_m"]},
"wcofs-salt-surface": {"fields": ["latitude","longitude","psu"]}
```

The client converts to °F and ft for display only.

## Files to create or modify

| File | Change |
| --- | --- |
| `src/skippercast/pipeline/wcofs_depth.py` (new) | read slab, derive, tiles |
| `src/skippercast/pipeline/habitat_dynamics.py` | job wiring, shared WCOFS catalog/cycle discovery (refactor from `wcofs_surface`) |
| `catalog/feed-health.json`, `catalog/layer-inventory.json`, catalog source entry for `noaa-wcofs` needs (add `salinity`, `subsurface-temperature`) | |
| `regions/morro-bay/region.json` (source_bindings for new needs) | then `PYTHONPATH=src python -m skippercast.platform.build` |
| `web/map/habitat-feed.ts` | parse |
| `web/map/subsurface.ts`, `web/map/salinity.ts` (new) | draw, reading, profile |
| `web/app/DepthLadder.tsx` (new), `web/app/LayerRail.tsx`, `web/app/Legend.tsx`, `web/map/layers.ts`, `web/map/palette.ts` + tokens (`--haline-*`) | |
| `web/state.ts`, `web/share-link.ts` | `depth` param |
| `catalog/app/strings.json` | en+es |
| `tests/test_wcofs_depth.py`, `tests/test_subsurface_layer.mjs` (new) | |

## Edge cases

- Shallow cells where deeper levels are masked (land or below the seafloor): those levels are null, the ladder shows "below seafloor here", and the thermocline and MLD are computed from the available levels only, or `none`.
- A WCOFS cycle missing frames: publish what's complete. Never mix cycles in one layer.
- Units toggle: the ladder labels show ft equivalents (33, 66, 98, 164, 328 ft).

## Related data-source inventory

`docs/research/data-sources/` records `coastwatchSMOSv662SSS1day_sss_centralcoast.nc` (satellite surface salinity, SMOS, a possible observed check on WCOFS `salt`) and `rtofs_20261118_f024_diag_centralcoast.nc` / `hycom_espc_uv_surface_centralcoast.nc` (alternative 3D ocean models) from the 2026-11-19 pulls. Those sample files are not in the repository. Download steps are in `docs/research/data-sources/sources/`. Use an alternative only after a catalog entry is `approved`. WCOFS remains the primary source here because SkipperCast already reads and reviews it.

## Dependencies

- 05 refactors the WCOFS read path (zeta). Do 05's refactor first or in the same PR series.
- 01 readings and profile.
- Owner confirmation of the "subsea weather" scope.


---

# Tasks · 07 subsurface depth ladder

- [ ] T0 **Owner confirmation** of scope ("subsea weather") and frame cadence. Stop here until it's answered.
- [ ] T1 Refactor the WCOFS discovery and contract into a shared helper (with spec 05), keeping `wcofs_surface` byte-identical in output (regression test).
- [ ] T2 `wcofs_depth.py` slab read, measure bytes, derive the thermocline and MLD. Synthetic column tests (R1, R2).
- [ ] T3 Publish the layers plus catalog and region bindings, then rebuild the platform output (R3).
- [ ] T4 Client parse, subsurface layer, DepthLadder, salinity layer, `depth` link param (R4, R5).
- [ ] T5 Point-readout profile sparkline (R6).
- [ ] T6 Offline note (R7), strings en+es, docs (`docs/web-app.md`, `docs/data-feed-readme.md`).
- [ ] T7 Full checks plus a performance check on a phone.

## Verification

Record dated bytes per frame and region, timings, and a visual comparison with the surface SST.
