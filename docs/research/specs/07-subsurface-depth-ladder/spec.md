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
