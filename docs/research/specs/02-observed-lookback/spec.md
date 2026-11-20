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
