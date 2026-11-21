# Implementation plan · 02 observed look-back

## Evidence in the repository (observed 2026-11-19, commit fa9c358)

- `src/skippercast/pipeline/habitat_dynamics.py` `run()` (L373+) builds the layers `sst-analysis` and `chlorophyll-observation` from the reviewed adapters (`noaa-ncss-sst` → `pipeline/noaa_sst.py` `latest_file`/`fetch`; `noaa-ncss-chlorophyll` → `pipeline/noaa_chlorophyll.py`), each with a single `times = {grid["sample_at"]}`. `publish_tiles` writes `habitat-tiles/<layer>-…-<sha16>.json`. `_copy_previous_tiles` already re-uses prior tiles from `previous_root`. `_cleanup_tiles` deletes unreferenced tiles; history references must keep them alive.
- `src/skippercast/pipeline/sst_fronts.py` `publish_region` writes one `sst-fronts.json` beside `habitat-dynamics.json`. The feed is in `catalog/feed-health.json` (`sst-fronts`, path `conditions/regions/{region}/sst-fronts.json`, `max_age_hours` 48).
- `scripts/publish_r2.py` treats `latest|index|manifest|status|health…json` as pointers (L45). Dated history files are immutable objects. `scripts/r2_lifecycle.py` governs retention: add an 8-day rule for `habitat-history/`.
- Browser: `web/map/habitat-feed.ts` verifies tiles (`TILE_PATH`, SHA-256, `MAX_TILES` 64, `MAX_TILE_BYTES` 5 MB). `web/map/sst.ts`, `chlorophyll.ts` and `fronts.ts` gate on age against `now`. `web/map/layers.ts` already has `TimeBehaviour = 'static' | 'hour' | 'observed'`. `web/app/TimeDock.tsx` and `web/hour.ts` build the 169-hour horizon. `web/dock-selection.ts` handles selection, and `web/state.ts` parses `day`.
- Layer-card rules (basis sentence naming product, grid, age; attribution; time tag) come from `docs/plans/pelagic-context/design.md` §2.1 and `web/map/layers.ts`.

## Data inputs

- The same reviewed sources: NOAA CoastWatch Geo-Polar Blended Night SST (THREDDS `Blended/SST5km/Night/GHRSSTOSPO`, file pattern in `noaa_sst.py`) and NOAA VIIRS merged OCI chlorophyll (`noaa_chlorophyll.py`). Backfill (R9) needs a `fetch_for_date(client, bounds, date)` that selects the dated file from the same catalog instead of `latest_file`. **Checked 2026-11-19:** the SST catalog has year folders from 2014 (2026 folder: 322 daily files), and the chlorophyll catalog `chlociVIIRSnpp-n20GlobalDailyWW00` lists 2,945 daily files from `V2018221`. A 7-day backfill from the same reviewed sources is possible. `noaa_chlorophyll.py` caps `MAX_FILES = 3` for the newest-file search; the dated fetch must pick the exact file by name instead.
- If `docs/research/data-sources/` (a separate inventory) lists a longer archive for these products, use it only after the source's review status is `approved` in the catalog.

## Data model

`habitat-dynamics.json` (schema_version stays 1; additive optional field):

```json
"layers": {"sst-analysis": {"...": "current fields unchanged",
  "history": [{"sample_at": "2026-11-18T00:00:00Z", "tiles": [{"path": "habitat-history/sst-analysis-2026-11-18-<sha16>.json", "sha256": "…", "bytes": 123}]}]}}
```

Fronts: `conditions/regions/{region}/sst-fronts/index.json` = `[{date, path, sha256}]` (pointer), plus the immutable `sst-fronts/{date}.json` in the existing document shape.

## Architecture choices

- History is append-and-trim in the pipeline. Each run reads the previous manifest's history and adds today's frame if `sample_at` is new. It trims to 7 days, copies the referenced tiles forward (extending `_copy_previous_tiles`), and excludes them from `_cleanup_tiles`.
- History tiles live under `habitat-history/` so the live `TILE_PATH` regex and the budgets stay unchanged. The client adds `HISTORY_TILE_PATH`.
- The client loads a past day lazily, only when selected. It caches per (region, layer, date) for the session.
- Dock: a `past` segment in `web/hour.ts` (`pastDays(now, tz, available)`). `TimeDock.tsx` renders the chips before Today. Hour selection is disabled on past days because observations are daily.

## Files to create or modify

| File | Change |
| --- | --- |
| `src/skippercast/pipeline/habitat_dynamics.py` | history append/trim, tile retention, optional backfill hook |
| `src/skippercast/pipeline/noaa_sst.py`, `noaa_chlorophyll.py` | `fetch_for_date` (R9) |
| `src/skippercast/pipeline/sst_fronts.py` | dated output + index |
| `catalog/feed-health.json`, `catalog/layer-inventory.json` | history feed entries |
| `scripts/r2_lifecycle.py` | retention for `habitat-history/` and `sst-fronts/` dated files |
| `web/map/habitat-feed.ts` | `history` parsing and verification, `loadHistoryDay` |
| `web/map/sst.ts`, `chlorophyll.ts`, `fronts.ts`, `contrast.ts` | draw the selected past frame; past-day gate (R6) |
| `web/map/swell.ts`, `wind.ts`, `currents.ts`, `web/map/layers.ts` | hide on past days with a rail note (R5) |
| `web/hour.ts`, `web/app/TimeDock.tsx`, `web/dock-selection.ts`, `web/state.ts`, `web/share-link.ts` | past chips, `day=-N` |
| `catalog/app/strings.json` | `dock.past.*`, `map.status.*.pastOnly`, en+es |
| `tests/test_habitat_history.py` (new), `tests/test_habitat_feed_history.mjs` (new), `tests/test_dock_past.mjs` (new) | |

## UX details

- The past chips are a muted style, visually separated from Today by a thin divider. The selected past chip shows the date ("Fri 14"). A small "Past · observed" tag sits above the map while a past day is shown.
- Visual reference: `docs/research/inspiration/skippercast_inspiration.json` → `salinity` example ("haline ramp + running date stamp"). Show a running date stamp in the map corner during play.

## Edge cases

- DST: past days are computed in the region zone with `Intl`, as `windowInstants` does in `server/alert-policy.ts`.
- Mixed products across days, for example a product switch: each day's legend and basis use that frame's own product.
- The manifest's bounds changed: discard history (it is already reset when `previous` doesn't match).
- Offline: history days aren't in the offline pack. A past day offline says "not saved for offline".

## Dependencies

- Spec 01 is optional: readings on past days reuse its `readingsAt`.
- Spec 05 (chlorophyll edges, eddies) will publish its derived layers per day into the same history structure.
