<!-- Generated from 05-chlorophyll-edges-eddies-ssh/spec.md, plan.md, tasks.md. Edit those, not this file. -->

# 05 · Chlorophyll edges, eddies and sea-surface height

Status: proposed, 2026-11-19 · Priority 5 · Effort estimate: M · Depends on: 01 (readings), 02 (optional: per-day history)
Source: SkipperCast competitor analysis, recommendation 5 (Fishare eddies and SSH, BlueFronts chlorophyll-edge and shear detection, SiriusXM Fish Mapping altimetry, Salty Offshore eddies and FSLE fronts).

## Intended goal

Beside the existing SST fronts, the Chart can draw **colour edges** (sharp changes in chlorophyll), **eddy outlines** (rotating water from the WCOFS current forecast) and a **sea-surface-height** field. Each one is dated and sourced, and each carries its uncertainty.

## Purpose

SkipperCast already publishes SST fronts as edges with an uncertainty band (`src/skippercast/pipeline/sst_fronts.py`, `web/map/fronts.ts`) and an SST contrast field (`web/map/contrast.ts`). Offshore anglers also read colour breaks and eddies. Both can be derived from data SkipperCast already pulls: the chlorophyll-observation tiles, and the WCOFS regular grid. That grid also carries `zeta` (sea-surface elevation, metres), verified on 2026-11-19 in the OPeNDAP DDS. No new source is needed.

## User journey

1. Ana turns on **Edges** in the rail. A sub-toggle chooses SST fronts (existing), Colour edges and Eddies.
2. Colour edges draw as dashed green lines where chlorophyll changes sharply across clean (cloud-free) cells. Each line carries its sample date and a band showing position uncertainty.
3. Eddies draw as closed outlines with a rotation arrow (clockwise or counter-clockwise), labelled with the WCOFS run and forecast hour. They move with the dock hour across the WCOFS 0–72 h frames.
4. **Sea height** is a separate rail entry: a diverging field in centimetres about the regional mean, from WCOFS, following the dock hour.
5. Tapping an edge or eddy (spec 01 readout) shows, for example, "Colour edge · chlorophyll 0.6 → 2.1 mg/m³ across 3 km · sample Nov 18" or "Eddy (counter-clockwise) · ~22 km across · WCOFS 03z +12 h · model, not observed".

## Use cases

- **Find where blue offshore water meets green coastal water** (colour edge) near the SST break.
- **See an eddy pulling warm water toward the coast** over the next 3 days.
- **Cross-check an SST front against a colour edge**: two independent signals in the same place.

## Requirements

1. **R1** A pipeline step `chl_edges.py` derives edges from the `chlorophyll-observation` tiles. It applies the `sst_fronts.py` method to log10(chl), keeps only cells whose log-change across neighbours exceeds a documented threshold, takes the ridge, and links it into lines of at least 5 cells. Its uncertainty band is half a cell. Its age and status rules match `sst_fronts.py`, with a new `chl-edges` feed in `catalog/feed-health.json`.
2. **R2** Extend `wcofs_surface` (or add `wcofs_derived`) to also read `zeta[0]` on the same subset and frames. Publish it as layer `wcofs-ssh` (cm, minus the regional mean per frame) in `habitat-dynamics.json`, with the same SHA-256 tile rules.
3. **R3** Eddy detection runs per WCOFS frame using Okubo–Weiss (W = s_n² + s_s² − ω²) on the surface currents. A connected region with W < −0.2·σ_W is a candidate, kept if it is at least 4 cells across and its outline closes. The outline is the boundary polygon, the sense is the sign of ω, and the size is its equivalent diameter. Each eddy is labelled "model (WCOFS), not observed". It is published as `wcofs-eddies`.
4. **R4** The client adds layer-registry entries following the existing card rules (legend, basis sentence naming product, grid and age, attribution, time tag, age limit): `chl-edges` (observed), `ssh` (hour), `eddies` (hour). Each has a `reading(at)`.
5. **R5** Edges are drawn under the MPA fill and above the fields, consistent with `fronts.ts`. Colours come from palette tokens.
6. **R6** If spec 02 has landed, `chl-edges` publishes per-day history like `sst-fronts`.

## Acceptance

- Pipeline tests with synthetic tiles: a step change in chlorophyll gives one edge line. Pure noise gives none. A cloud gap breaks a line rather than bridging it.
- A synthetic WCOFS vortex field gives one eddy with the right sense and an approximate diameter within 20%.
- SSH tiles verify in the browser. A tampered tile refuses the layer.
- `pytest -m "not gis"`, `node --test tests/test_*.mjs`, `pnpm typecheck` and `pnpm build` pass. `python scripts/check_repository.py` passes with the new catalog entries.

## Non-goals

- No satellite altimetry (CMEMS/AVISO) in this increment. That needs a source review and is listed in the data-source inventory if available.
- No FSLE or Lagrangian products. No "fish here" scoring.


---

# Implementation plan · 05 chlorophyll edges, eddies, SSH

## Evidence in the repository and sources (observed 2026-11-19)

- `src/skippercast/pipeline/sst_fronts.py`: method (gradient vs summed analysis error, ridge thinning, `MIN_FRONT_CELLS = 5`, uncertainty = error/gradient), `publish_region`, refusal rules (`SstFrontError`). This is the template for chlorophyll edges.
- `src/skippercast/pipeline/habitat_dynamics.py` `wcofs_surface` (L247+): reads `temp`, `u_eastward` and `v_northward` at `Depth` index 0 on a ≤ 15,000-cell regional subset of the 0.04° regular grid, for frames f000–f072 every 3 h, with unit and mask contract checks.
- WCOFS regular-grid DDS (fetched 2026-11-19, `https://opendap.co-ops.nos.noaa.gov/thredds/dodsC/NOAA/WCOFS/MODELS/2026/11/19/wcofs.t03z.20261119.regulargrid.f003.nc.dds`): `zeta[time][ny][nx]` "free-surface referenced to mean sea level", units metres. Also `salt`, `temp`, `u_eastward` and `v_northward` over 41 depths.
- `web/map/currents-layer.js` (map-style test page) already computes relative vorticity / f with central differences on a current grid (`VORT_RANGE`, cmocean balance). Reuse the maths in Python for Okubo–Weiss.
- Client: `web/map/fronts.ts` (draw and reading pattern), `web/map/habitat-feed.ts` (tile verification), `web/map/layers.ts` (registry), `web/map/palette.ts` (tokens; add `edgeChl`, `eddyCw`, `eddyCcw`, and an SSH diverging ramp).

## Data model

`habitat-dynamics.json` layers gain `wcofs-ssh` (fields: latitude, longitude, ssh_cm) and `wcofs-eddies` (GeoJSON-like features in a tile: `{frame_time, features:[{outline:[[lon,lat]…], sense:'cw'|'ccw', diameter_km, ow_min}]}`). New feed `conditions/regions/{region}/chl-edges.json` in the `sst-fronts.json` shape with `product` = the chlorophyll product.

## Architecture choices

- Chlorophyll edges use log10 space, because chlorophyll is log-normal. The threshold is documented (start: Δlog10 ≥ 0.3 per cell across both neighbours) and tuned by checking real regional fixtures before release.
- Eddies come from the model, so the label says "model". They follow the dock hour like currents (`TimeBehaviour 'hour'`).
- The Edges rail entry groups SST fronts, colour edges and eddies with sub-toggles, so the rail doesn't grow by three rows. Confirm this against `web/app/LayerRail.tsx` patterns.

## Files to create or modify

| File | Change |
| --- | --- |
| `src/skippercast/pipeline/chl_edges.py` (new) | edges |
| `src/skippercast/pipeline/habitat_dynamics.py` | zeta read, `wcofs-ssh` and `wcofs-eddies` layers |
| `src/skippercast/pipeline/eddies.py` (new) | Okubo–Weiss detection, pure numpy |
| `scripts/refresh_regions.py` | call the new steps in the habitat stage |
| `catalog/feed-health.json`, `catalog/layer-inventory.json` | entries |
| `web/map/habitat-feed.ts` | parse the new layers |
| `web/map/chl-edges.ts`, `web/map/ssh.ts`, `web/map/eddies.ts` (new) | draw and reading |
| `web/map/layers.ts`, `web/map/chart.ts`, `web/app/LayerRail.tsx`, `web/app/Legend.tsx`, `web/map/palette.ts` + tokens | registry, rail and legend |
| `catalog/app/strings.json` | labels, basis, status en+es |
| `tests/test_chl_edges.py`, `tests/test_eddies.py`, `tests/test_habitat_ssh.mjs` (new) | |

## UX details

- Colour edges are dashed lines (`line-dasharray [2,1]`) in a green token, 1.5 px, with a translucent band for uncertainty. Eddies are a 1 px outline with a small arrowhead marking the sense. SSH uses the cmocean `balance` ramp, centred at 0, in ±cm.
- Visual reference: `docs/research/inspiration/skippercast_inspiration.json` per_layer "Sea surface temperature" ("make fronts and eddies the subject", examples `sst_japan`, `helene_sst`) and "Chlorophyll / ocean colour" (`olci_chl`: log-scale green ramp over a dark base).

## Edge cases

- Heavy cloud: no colour edges, and the rail says "too little clear water for edges (N% observed)".
- WCOFS missing or stale: SSH and eddies withheld with the existing WCOFS status.
- Eddies touching the subset boundary are dropped (their outline isn't closed).

## Related data-source inventory

`docs/research/data-sources/` records the 2026-11-19 sample pulls that matter here: `nesdisSSH1day_sla_centralcoast.nc` and `nesdisSSH1day_ugos_centralcoast.nc` (NOAA satellite sea-level anomaly and geostrophic currents, a possible observed alternative to WCOFS `zeta`), `erdMBchla1day_chlorophyll_centralcoast.nc`, and `hycom_espc_uv_surface_centralcoast.nc` and `rtofs_20261118_f024_diag_centralcoast.nc` (other ocean models). Those sample files are not in the repository. Download steps are in `docs/research/data-sources/sources/`. Use an alternative only after a catalog entry is `approved`. This spec does not depend on them.

## Dependencies

- 01: readings at a tap.
- 02 (optional): daily history of `chl-edges`.
- 07 shares the WCOFS read path. Implement the zeta read so 07 can add depth levels on the same request code.


---

# Tasks · 05 chlorophyll edges, eddies, SSH

- [ ] T1 `chl_edges.py` with synthetic and real-fixture tests, plus the feed-health entry (R1).
- [ ] T2 WCOFS zeta read and the `wcofs-ssh` layer, with contract checks for zeta units (R2).
- [ ] T3 `eddies.py` Okubo–Weiss with a synthetic vortex test, plus the `wcofs-eddies` layer (R3).
- [ ] T4 Wire both into `refresh_regions.py`. Run `python scripts/check_repository.py`.
- [ ] T5 Client parse, layers and readings. Tamper tests (R4, R5).
- [ ] T6 Rail grouping and legend, strings en+es.
- [ ] T7 Optional history (R6) if spec 02 has landed.
- [ ] T8 Update `docs/web-app.md`, `docs/data-feed-readme.md` and `catalog/layer-inventory.json` notes.

## Verification

Record a dated run on Morro Bay: count of edges and eddies, a visual check against the SST fronts, and timings.
