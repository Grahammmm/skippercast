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
