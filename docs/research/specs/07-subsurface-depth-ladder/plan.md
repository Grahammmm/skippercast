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
