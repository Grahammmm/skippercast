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
