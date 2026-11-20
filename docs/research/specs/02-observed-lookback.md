<!-- Generated from 02-observed-lookback/spec.md, plan.md, tasks.md. Edit those, not this file. -->

# 02 · Look-back playback for observed ocean layers

Status: proposed, 2026-11-19 · Priority 2 · Effort estimate: M (weeks) · Depends on: 01 (readings plug-in, optional)
Source: SkipperCast competitor analysis, recommendation 2 (Fishare 7-day look-back, Salty Offshore "Water Playback", SatFish v2 history).

## Intended goal

The angler can step back through the last 7 days of observed water temperature, temperature fronts and chlorophyll on the same time dock they already use for the forecast, and watch a break move, stall or fade before they choose where to run.

## Purpose

Today the time dock (`web/app/TimeDock.tsx`) covers the 169-hour forecast horizon from the current hour forward. The observed layers each publish only their newest frame (`src/skippercast/pipeline/habitat_dynamics.py` collects one `sample_at` per layer; `sst_fronts.py` writes one `sst-fronts.json`). The History view covers station readings only. Offshore anglers judge a front by its persistence and drift, not by one snapshot. Every leading SST competitor ships a look-back. SkipperCast's honesty rules still hold: past days show real dated observations, clouds stay as gaps, and nothing is interpolated between days.

## User journey

1. Luis opens the Chart with Water temp and Fronts on. The dock shows **Today** selected, as now.
2. A new **Past** chip group sits to the left of Today: `−7d … −1d`. He taps `−5d`.
3. The Chart redraws the SST analysis dated five days ago, with its own legend range and its age stated ("analysis Nov 14, 5 days old, past view"). Fronts redraw from the same day. Forecast-only layers (swell, wind, WCOFS currents) hide, and their rail entries say "forecast only, not shown for past days".
4. He presses **Play**. The dock steps one observed day per second from −7d to Today, then stops. Reduced-motion users step one day per press.
5. A day with no published frame, for example one lost to clouds or an outage, shows "no analysis for Nov 16". That day is skipped during play, never filled.
6. He taps a point while on −3d. The reading (spec 01) shows that day's values.
7. **Today** returns to the live forecast dock. A shared link with `day=-3` reopens on that past day.

## Use cases

- **Decide whether a break is persistent** (three days in the same place) **or transient**.
- **See which way a warm tongue is pushing** before planning tomorrow's run.
- **Explain a slow day after the fact** by checking whether the water changed.
- **Check chlorophyll before and after an upwelling event.**

## Requirements

1. **R1** The pipeline keeps the last 7 daily frames of `sst-analysis`, `chlorophyll-observation` and `sst-fronts` per region, each with its own observation time, SHA-256, product and resolution. Each frame is immutable once published.
2. **R2** `habitat-dynamics.json` gains an optional `history` array per layer, `[{sample_at, tiles:[{path, sha256, bytes}]}]`, newest first, at most 7 entries. `sst-fronts` gains `conditions/regions/{region}/sst-fronts/{YYYY-MM-DD}.json` plus an index.
3. **R3** The browser loader (`web/map/habitat-feed.ts`) verifies history tiles with the same checks as current tiles (region, path pattern, length, SHA-256, fields, grid, bounds). One failing tile refuses that day only.
4. **R4** The dock offers past days only for regions whose manifest carries history. Past days are local days in the region's zone.
5. **R5** On a past day: layers with time behaviour `observed` draw that day's frame. Layers that are `hour`-only (forecasts) do not draw, and their rail entries state why. `static` layers are unchanged.
6. **R6** The age gate for a past frame is "observation date equals the selected day". The live `max_age_hours` gate applies only to Today. The legend and basis always print the frame's own date.
7. **R7** Play over past days skips missing days, stops at Today, pauses when the page is hidden, and honours reduced motion.
8. **R8** `day` accepts `-1`…`-7` in links and state. Values out of range or unsupported fall back to Today, keeping today's rule that a kept-but-unshowable value is reported, not silently reset.
9. **R9** An optional backfill job may populate the 7 days for a new region from the same reviewed source (no new source), so the feature works on day one.

## Acceptance

- With two or more archived days, the past chips appear, each draws its dated frame, and the legend shows the right date and range.
- A corrupted tile for one day shows "no analysis" for that day only.
- Swell and wind hide on past days with the stated reason.
- `pytest -m "not gis"` (pipeline tests), `node --test tests/test_*.mjs`, `pnpm typecheck` and `pnpm build` pass. R2 publication size stays within `scripts/perf-budget.json` / `startup-budget.json` limits, because history loads only when a past day is selected.

## Non-goals

- No hindcast of forecast models, no reanalysis products, no blending between days, no animation between frames.
- No history for WCOFS currents, swell or wind in this increment.
- No change to the History view (stations).


---

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


---

# Tasks · 02 observed look-back

- [ ] T1 Pipeline history append/trim for `sst-analysis` and `chlorophyll-observation`, tile retention, manifest `history`. Offline pytest with fixture tiles covering 0, 1 and 8 days (R1, R2).
- [ ] T2 Dated `sst-fronts` output plus index, with a test (R2).
- [ ] T3 Add `fetch_for_date` (exact dated file from the same catalogs; depth verified 2026-11-19) and a `--backfill-days 7` flag (R9).
- [ ] T4 R2 lifecycle rule and feed-health/layer-inventory entries. Run `python scripts/check_repository.py` (R1).
- [ ] T5 `habitat-feed.ts` history parse and verify, plus `loadHistoryDay`. Test a tampered tile, a wrong region and a path escape (R3).
- [ ] T6 Dock past segment (`hour.ts`, `TimeDock.tsx`, `dock-selection.ts`, `state.ts`, `share-link.ts`). Tests for DST, missing days and the link round-trip (R4, R7, R8).
- [ ] T7 Layer gates: observed layers draw the past frame, forecast layers hide with a reason (R5, R6).
- [ ] T8 Strings en+es, then run `node scripts/check_copy.mjs`.
- [ ] T9 e2e: select −2d, the legend date changes and swell hides. Play skips a missing day.
- [ ] T10 Update `docs/web-app.md` (time dock) and `docs/data-feed-readme.md` (history fields) in the same PR series.

## Verification

Record dated results here (pipeline run on a real region, R2 object count and bytes, phone check).
