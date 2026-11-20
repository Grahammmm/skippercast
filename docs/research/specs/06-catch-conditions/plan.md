# Implementation plan · 06 catch conditions

## Evidence in the repository (observed 2026-11-19, commit fa9c358)

- `db/schema.ts` `catchLog` fields: id, owner, trip_id, started_at, ended_at, method, species, outcome, count, lat, lon, note, created_at. The comment says coordinates are private and never leave the owner's routes.
- `server/routes/catch-log.ts`: `validateLogEntry`, POST (L102), PATCH (L114, coordinate pairing rule), `LIST_LIMIT 200`, cursor paging.
- `dist/account.js`: the catch-log UI and CSV (`Download log (CSV)`: started_at, outcome, count, species, method, lat/lon, linked trip date, note; at most 10 pages / 2,000 entries).
- Tide data: `scripts/build_tide_layer.py`, `web/tides.ts`, and the region's tide station in `regions/<id>/region.json`. Forecast hours: the regional conditions feed read by `server/trips.ts` (`tripInputs`).
- Feed tiles: `habitat-dynamics.json` (spec 02 adds history). Fronts: `sst-fronts.json`.

## Architecture choices

- `server/catch-conditions.ts` (new): `snapshot(env, region, lat, lon, startedAt) → ConditionsV1`. It reads via `FEEDS` with a per-request cache and respects `cost-ceiling` (degraded mode stores `{v:1, pending:true}`, and a later cron fills it in).
- Front distance: minimum haversine distance from the point to the front polylines of that day's `sst-fronts`, in nautical miles. It is null if there are no fronts.
- Region resolution: the entry has no region column, so derive it from position (the region whose bounds contain it) or the trip link's region. Without either, only `{v:1, missing:'no region'}` is stored.
- The aggregation for **My patterns** is pure client-side in `dist/account.js` (or a new `web/catch-patterns.ts` it imports).

## Files to create or modify

| File | Change |
| --- | --- |
| `db/schema.ts`, `drizzle/0021_catch_conditions.sql` (generated) | `conditions` column |
| `server/catch-conditions.ts` (new) | snapshot |
| `server/routes/catch-log.ts` | compute on create/patch; include in list for owner |
| `server/index.ts` (cron) | fill `pending` snapshots, bounded per run |
| `dist/account.js`, `web/catch-patterns.ts` (new) | Conditions line, My patterns, CSV columns |
| `server/routes/account.ts` | export includes conditions |
| `catalog/app/strings.json` | `catch.conditions.*`, `catch.patterns.*` en+es |
| `tests/test_catch_conditions.mjs`, `tests/test_catch_patterns.mjs` (new); extend the privacy sweep test | |

## Edge cases

- `started_at` in the future: no snapshot ("future time").
- A position on land or outside every region: `missing:'outside coverage'`.
- Very old entries (before history): observed layers `not archived`.
- An entry edited many times: recompute only when position or time changes.

## Dependencies

- 02: history frames for entries logged after the day.
- 03: shared native-cell sampler (build it once, in whichever spec lands first).
- 01: the same value formatting as the point readout.
