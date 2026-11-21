# Offshore sample grids for the Swell layer

## R1. What draws today

| Region | Status | Forecast points | Lattice nodes / drawable cells | Field envelope (west, south, east, north) |
|---|---|---:|---:|---|
| `big-sur-coast` | Preview | 3 | No | — |
| `bodega-point-reyes` | Preview | 3 | No | — |
| `cambria-san-simeon` | Preview | 11 | Yes: 8 / 3 | −121.75, 35.45, −121.25, 35.65 |
| `channel-islands-north` | Draft | 4 | No | — |
| `crescent-city` | Preview | 5 | No | — |
| `fort-bragg-point-arena` | Preview | 2 | No | — |
| `humboldt-bay-cape-mendocino` | Preview | 5 | No | — |
| `monterey-point-sur` | Preview | 3 | No | — |
| `morro-bay` | Active | 15 | Yes: 11 / 5 | −121.75, 35.05, −121.00, 35.55 |
| `outer-islands-borderland` | Draft | 5 | No | — |
| `point-arena-bodega` | Preview | 3 | No | — |
| `point-arguello-conception` | Preview | 4 | No | — |
| `point-reyes-pigeon` | Preview | 3 | No | — |
| `san-diego` | Draft | 3 | No | — |
| `san-pedro-orange-county` | Draft | 2 | No | — |
| `santa-barbara-channel` | Draft | 4 | No | — |
| `santa-cruz-monterey-bay` | Preview | 3 | No | — |
| `santa-monica-palos-verdes` | Draft | 2 | No | — |
| `shelter-cove-north-mendocino` | Preview | 3 | No | — |
| `south-big-sur-san-simeon` | Preview | 3 | No | — |
| `southern-california` | Preview | 21 | No | — |
| `trinidad-klamath` | Preview | 6 | No | — |

**Recommendation:** Pilot Big Sur outer coast, then extend to the other previews. Leave Morro Bay's grid and all six draft statuses alone. Of 22 committed configs, only two can draw Swell today; 14 indexed previews and six drafts lack a grid. See the replay below; status comes from `dist/regions/index.json:1` and the source configs (`regions/<id>/region.json:5`). Drafts are excluded by `src/skippercast/platform/build.py:90-95` and by default in `scripts/refresh_regions.py:153-161`.

Source revision: staged `origin/main` at `26c8f4822a503a849507a3aacf3f2b4d75c86d7d` (offline, 2026-11-21). `git ls-tree` at that revision and the planning baseline `c5f07fc5d9516d1d9b0954e7ec47506b343963c8` gives identical objects for `regions`, the index, `web/map/{forecast-grid.ts,surface-field.js,swell.ts}`, `packages/coast/src/map/surface-field.ts`, and `tests/contract/test_forecast_lattice_water.py`. No live forecast was requested.

The parser keeps a point only if another point shares its latitude and another shares its longitude. That filter is not a water check and does not read the `offshore` flag. The resulting points must align on one grid, and **each drawn cell** needs four corners; the whole bounding rectangle need not be filled (`web/map/forecast-grid.ts:65-86`; `packages/coast/src/map/surface-field.ts:14-37`). At any chosen hour, missing model values can remove additional cells (`web/map/forecast-grid.ts:89-101`; `web/map/swell.ts:159-176`). Here are the actual potential footprints, not just their envelopes:

- **Morro Bay:** at 35.05–35.30° N, −121.75 to −121.00°; at 35.30–35.55° N, −121.75 to −121.25°. Step 0.25° × 0.25°. The two shoreward nodes augment the original 3 × 3 (`regions/morro-bay/region.json:162-238`).
- **Cambria:** at 35.45–35.55° N, −121.75 to −121.25°; at 35.55–35.65° N, −121.75 to −121.50°. Step 0.25° × 0.10° (`regions/cambria-san-simeon/region.json:81-159`).

**Replay R1:** Save the following as a scratch `swell-r1.mjs` outside the checkout, then run `node /path/to/swell-r1.mjs` from the repo root on Node 22. It reads the checked-out commit's JSON via Git and imports the actual parser and grid sampler from that checkout. Zeroes establish geometry only, not wave availability.

```js
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const git = (...a) => execFileSync('git', a, {encoding: 'utf8'}).trim();
const read = p => JSON.parse(git('show', `HEAD:${p}`));
const load = p => import(pathToFileURL(resolve(p)));
const {parseForecast} = await load('web/map/forecast-grid.ts');
const {surfaceField} = await load('web/map/surface-field.js');
const statuses = new Map(read('dist/regions/index.json').regions.map(r => [r.id, r.status]));
const round = n => +n.toFixed(5);
for (const p of git('ls-files', 'regions/*/region.json').split('\n')) {
  const r = read(p);
  const requested_points = r.forecast_points.map(p => [p.id, p.latitude, p.longitude]);
  const {lattice} = parseForecast({region_id: r.id, retrieved: 0, requested_points}, r.id);
  const field = surfaceField(lattice.map(({lon, lat}) => ({lon, lat, values: [0]})));
  console.log(r.id, statuses.get(r.id) ?? r.status, requested_points.length, lattice.length,
    field?.bounds.map(round) ?? null, field?.quads.map(q => [q.west, q.south, q.east, q.north].map(round)) ?? []);
}
```

## R2. Candidate offshore rectangles

All coordinates are WGS84 degrees, longitude first. The four corners are `(W,S)`, `(E,S)`, `(W,N)`, `(E,N)`. Fill all rows and columns at the stated spacing, starting at `(W,S)`; append unique `offshore-<row>-<column>` IDs without changing the existing points or their order. These fit the **regional `bounds`**, not necessarily the smaller fishing bounds (`src/skippercast/platform/contracts.py:356-366`; `schemas/region.schema.json:84-98`). They are offshore placement proposals, not a navigation layer or a promise to cover ports, bays or islands. **Only the central-coast corridor had continuous local planning-line evidence in this check.** Elsewhere the geographic placement is a planning estimate, using conservative separation from committed coastal references, not a substitute for shoreline and wet-cell sign-off.

| Region | W, S, E, N | Δlon × Δlat | New points | Regional points before → after | Actual intelligence request before → after | Offshore placement and screen |
|---|---|---|---:|---:|---:|---|
| `big-sur-coast` | −122.18, 35.93, −121.98, 36.23 | .20° × .15° | 2 × 3 = 6 | 3 → 9 | 5 → 11 / 50 | West of the Big Sur shoreline: 11.0 km to planning spine. |
| `bodega-point-reyes` | −123.63, 38.00, −123.23, 38.40 | .20° × .20° | 3 × 3 = 9 | 3 → 12 | 4 → 13 / 50 | Pacific side of Bodega Head and Point Reyes, west of the nearshore references (config:75). |
| `channel-islands-north` | −119.92, 33.85, −119.52, 33.88 | .20° × .03° | 3 × 2 = 6 | 4 → 10 | 6 → 12 / 50 | Thin strip south of Santa Cruz Island, 1.1 km from the nearest island *focus box*. Hold for native shoreline confirmation; the north–south step does not give independent wave resolution. |
| `crescent-city` | −124.71, 41.61, −124.51, 41.93 | .20° × .16° | 2 × 3 = 6 | 5 → 11 | 6 → 12 / 50 | West of Point St George and Smith River, around the outer samples (config:57). |
| `fort-bragg-point-arena` | −124.34, 39.02, −124.14, 39.42 | .20° × .20° | 2 × 3 = 6 | 2 → 8 | 3 → 9 / 50 | West of Noyo and Point Arena (config:56). |
| `humboldt-bay-cape-mendocino` | −124.76, 40.23, −124.56, 40.83 | .20° × .20° | 2 × 4 = 8 | 5 → 13 | 7 → 15 / 50 | West of the cape and outer harbor references, not inside the bay (config:83). |
| `monterey-point-sur` | −122.31, 36.33, −122.11, 36.57 | .20° × .24° | 2 × 2 = 4 | 3 → 7 | 5 → 9 / 50 | West of Carmel and Point Sur: 11.6 km to planning spine. |
| `outer-islands-borderland` | −119.60, 32.78, −119.00, 32.98 | .20° × .20° | 4 × 2 = 8 | 5 → 13 | 7 → 15 / 50 | South of San Nicolas and west of San Clemente; 16.6 km from the nearest island focus box. |
| `point-arena-bodega` | −124.16, 38.45, −123.76, 38.85 | .20° × .20° | 3 × 3 = 9 | 3 → 12 | 5 → 14 / 50 | Pacific side of the Point Arena–Sonoma nearshore references (config:74). |
| `point-arguello-conception` | −121.23, 34.50, −121.03, 34.90 | .20° × .20° | 2 × 3 = 6 | 4 → 10 | 5 → 11 / 50 | West of the headlands: 32.6 km to spine; 34.5 km to the available CUSP extract (which ends before the southern rows). |
| `point-reyes-pigeon` | −123.26, 37.22, −122.86, 37.58 | .20° × .18° | 3 × 3 = 9 | 3 → 12 | 5 → 14 / 50 | West of the Half Moon Bay–Pigeon samples (config:56), kept south of the Farallones; check the islets explicitly. |
| `san-diego` | −117.57, 32.58, −117.37, 32.98 | .20° × .20° | 2 × 3 = 6 | 3 → 9 | 5 → 11 / 50 | West of the La Jolla–border coast (config:102); check the southern edge against the Coronados. |
| `san-pedro-orange-county` | −118.14, 33.36, −117.98, 33.52 | .16° × .16° | 2 × 2 = 4 | 2 → 6 | 4 → 8 / 50 | South of the Newport coast (config:131) and east of Catalina; 8.4 km from the Catalina focus box. |
| `santa-barbara-channel` | −120.26, 34.19, −119.66, 34.27 | .20° × .08° | 4 × 2 = 8 | 4 → 12 | 6 → 14 / 50 | Middle channel, south of the mainland (config:190) and 8.9 km north of the nearest island focus box. |
| `santa-cruz-monterey-bay` | −122.72, 36.65, −122.52, 37.05 | .20° × .20° | 2 × 3 = 6 | 3 → 9 | 5 → 11 / 50 | Outside the mouth of Monterey Bay: 17.8 km to planning spine. |
| `santa-monica-palos-verdes` | −118.92, 33.78, −118.52, 33.94 | .20° × .16° | 3 × 2 = 6 | 2 → 8 | 4 → 10 / 50 | Outer bay, west of Palos Verdes (config:88), outside the island focus boxes by at least 28.1 km. |
| `shelter-cove-north-mendocino` | −124.76, 39.51, −124.36, 40.11 | .20° × .20° | 3 × 4 = 12 | 3 → 15 | 5 → 17 / 50 | Offshore band west of Shelter Cove, Bear Landing and Ten Mile (config:57). |
| `south-big-sur-san-simeon` | −121.97, 35.69, −121.77, 35.89 | .20° × .20° | 2 × 2 = 4 | 3 → 7 | 4 → 8 / 50 | West of Cape San Martin: 23.3 km to planning spine. |
| `southern-california` | −120.98, 32.58, −119.78, 33.48 | .30° × .30° | 5 × 4 = 20 | 21 → 41 | 28 → 48 / 50 | Open Pacific west of the outer islands; 12.1 km from the nearest island focus box. This deliberately does not cover the entire Southern California preview. |
| `trinidad-klamath` | −124.57, 41.04, −124.37, 41.49 | .20° × .15° | 2 × 4 = 8 | 6 → 14 | 9 → 17 / 50 | West of Trinidad and the Klamath coastal samples (config:59). Offset the latitudes from the originals so the current selector accepts only the new grid. |

Here `config:N` means `regions/<row-id>/region.json:N`. Planning distances are the nearest distance from the **rectangle** (not just the nodes) in California Albers EPSG:3310 to the line in `catalog/reaches.json:4-9` or to the coast in `catalog/shoreline/morro-bay.geojson:1`; the planning spine is generalized, not a land mask (`catalog/seafloor-scope.json:14-31`). The island distances use the individual focus boxes in `regions/channel-islands-north/region.json:38-80` and `regions/outer-islands-borderland/region.json:27-69`, not land polygons. The scratch `screen.py` reproduces the distances with PyProj and Shapely. Before adopting any rectangle, check land intersection and setbacks on a regional shoreline/land mask, including any intervening island, then check the actual model's wet cells. The existing Central Coast test is more specific: west of the shoreline and at least 8 km from its vertices (`tests/contract/test_forecast_lattice_water.py:15-47`).

**Replay R2:** From the workspace run `node swell-probe.mjs skippercast candidate-grids.json` (scratch files supplied with the handoff). To reproduce without those files, extend the R1 replay with the table above: for `row < ny`, `col < nx`, append `[id, +(S+row*dy).toFixed(5), +(W+col*dx).toFixed(5)]` before `parseForecast`. Require the same envelope as the table, `nx*ny` lattice nodes and `(nx−1)*(ny−1)` drawable cells; do not discard the existing regional points before testing. Add the length of `r.intelligence.verification_stations` to the enlarged regional count to check the last numeric column. Every listed rectangle passed those structural checks offline. Southern California has only **two** spare positions in the real request; adding a fifth latitude row would add five positions and reach 53.

**Morro Bay / Estero Bay: keep the current edge.** The inshore Estero Bay sample at (−120.94, 35.36) remains available as a point, but not a grid corner (`regions/morro-bay/region.json:137-161`). The missing (−121.00, 35.55) corner would cost one point (15 → 16 regional; 17 → 18 with stations), but the existing water test explicitly rejects it (`tests/contract/test_forecast_lattice_water.py:89-97`; 6.7 km to the CUSP extract in the scratch distance check). A partial new row or isolated nearshore point does not make an adjacent four-corner cell. Do not fill the missing corner, move the bay sample or imply harbor coverage. A separate owner-reviewed, wet-cell design would be needed to reach farther shoreward.

## R3. Request, time and generated files

- **Request size:** The builder sends one position list per model, with an eight-day hourly horizon. Intelligence appends verification stations to that same request; the sampler enforces 50 positions, not 50 regional points (`src/skippercast/pipeline/collect.py:238-259`; `src/skippercast/pipeline/intelligence.py:108-121,158-161,197-201`; `server/model-api.js:229-235`). The 16 indexed packages rise from **93 to 206 regional positions**; with 33 unchanged verification positions they rise from **126 to 239** total positions across the individual requests for each model. That adds **452 point-model samples** per all-region intelligence pass (113 × four), but no additional deterministic model requests. The six draft proposals add another 38 regional points only if separately admitted. `python summarize.py` in the scratch workspace reproduces the totals from the probe and committed configs.
- **Time and bytes (offline estimate, not live timing):** `node timing.mjs` exercised `server/model-api.js:327-367` on one synthetic all-wet tile, eight days, the same four-model variable lists, sequential calls and JSON serialization, reporting the median of ten warmed trials. Four answers together went from **0.130 to 0.285 MB** at 5 → 11 locations (Big Sur; 4.3 → 7.9 ms), and **0.726 to 1.244 MB** at 28 → 48 (Southern California; 20.2 → 35.4 ms). Scaling the measured ~0.7–0.8 ms per extra location to 113 gives **about 0.002 minutes** of added hot in-process sampling/serialization for the indexed set in this synthetic workload. This excludes cold/tile reads, Python and Node process handoff, the separate ensembles, writes, transfers and retries; it is not a live cycle estimate or upper bound. Budget **up to 1 additional minute per due cycle for pilot monitoring** as a planning allowance, not measured capacity; measure before/after `duration_ms` and bytes from the existing regional receipts before widening (`scripts/refresh_regions.py:49-65,83-99`; `src/skippercast/forecast/local.py:42-81`; `src/skippercast/pipeline/intelligence.py:161-169`). The scheduler still uses 30-minute slots and a 55-minute intelligence-age threshold (`.github/workflows/live-conditions.yml:48-58`; `scripts/live_loop.py:25-40,57-83`). Neither cadence nor the sampler's two-minute timeout estimates the incremental spend.
- **Static rebuild (future change):** Regenerate `dist/regions/<id>/region.json` with the platform builder and `web/trip-calendar-regions.generated.json` with `node scripts/build_trip_calendar_regions.mjs` (it snapshots point IDs and names). Rebuild and inspect `dist/regions/<id>/coverage.json`, `dist/regions/<id>/manifest.json` and `dist/regions/index.json`; a point-only change is expected to keep those three byte-identical if coverage and asset files do not change. The manifest hashes listed assets, not the generated region config; the index carries that manifest hash. `dist/region-default.js` changes only for the default Morro Bay config, not for the pilot. Drafts get no static projection while draft. No hand-edits to generated output (`src/skippercast/platform/build.py:90-95,122-129,168-180`; `scripts/build_trip_calendar_regions.mjs:5-20`; `tests/test_trip_ics.mjs:85-87`; `.github/workflows/ci.yml:374-382`).
- **Scheduled rebuild (operator only):** The effective field comes from `var/live/regions/<id>/intelligence.json` and the corresponding published `regions/<id>/intelligence.json`; `/api/forecast` projects its `forecast` member, not a standalone `forecast.json`. The pass also writes `var/live/intelligence-health.json` and maintains `verification-state.json`, `verification-state.previous.json` when applicable, and `verification-archive/{forecasts,observations}/…/*.json.gz`. Do not rewrite history. On a failed first fetch after a point-list change, old deterministic model rows are not reused under the new positions (`scripts/live_cycle.sh:26-50,75`; `scripts/refresh_regions.py:168-171`; `src/skippercast/pipeline/intelligence.py:108-121,197-217`; `src/skippercast/pipeline/verification_archive.py:209,246-292`; `server/routes/public.ts:98-112`).

**Regional-data owner decision:** Approve the pilot's exact coordinates, shoreline source/setback and model coverage review before appending points. Before rollout, approve timing/freshness criteria and which previews go next; separately decide whether any draft or an Estero Bay design should be considered at all. The live-data operator owns any collection rehearsal or publishing decision; this report changes neither that authority nor any hold. Dry arithmetic, rendering fixtures and deterministic rebuild review do not authorize a feed refresh (`docs/regions.md:9-13`; `CONTRIBUTING.md:30-32`).

## R4. First unit and rollout order

1. **First unit: Big Sur outer coast pilot, 75–105 minutes of implementation and offline checks (estimate, once the owner confirms the water screen).** Reserve `regions/big-sur-coast/region.json`, the two expected changed projections `dist/regions/big-sur-coast/region.json` and `web/trip-calendar-regions.generated.json`, and the existing focused test `tests/test_swell_layer.mjs`. Reserve the R3 static rebuild outputs for diff inspection; stop for separate scope if an unexpected output changes. Keep the current three point IDs and their order; append the six R2 points. In the existing test, feed the committed Big Sur point list to `parseForecast`; assert six lattice nodes, two drawable cells, exactly the R2 envelope, and no inshore points in the grid. Repeat with the one shared interior corner removed and require no field; this catches a broken row or accidental land-bridging fill. Run `node --test tests/test_swell_layer.mjs tests/test_trip_ics.mjs` and `python -m pytest -q tests/contract/test_forecast_lattice_water.py` in that follow-up. The current tests cover the geometry and the regional-only cap, not a new Big Sur positive control (`tests/test_swell_layer.mjs:100-125,155-168`; `tests/contract/test_forecast_lattice_water.py:113-117`). Add an 11-position assertion including stations in the follow-up's focused fixture; it guards against counting only the browser's nine positions. A real wet-hour readback and rollout are separate owner steps, not part of the estimate.
2. **Then the other Central Coast previews** (South Big Sur, Monterey–Point Sur, Santa Cruz–Monterey Bay, Point Arguello–Conception): reuse the pilot evidence and check each rectangle against its native shoreline. Next take the northern previews in small geographic batches, including an island check for Point Reyes–Pigeon. Then do the wide Southern California preview on its own: its **48/50** request leaves the least room for verification stations and needs a size/freshness comparison. This order follows the R2 planning-evidence strengths and request totals, not a readiness promotion.
3. **Last: draft-only geography and any Morro Bay redesign.** Keep draft calendars and feeds unchanged; decide whether the narrow Channel Islands strips add enough value after wet-cell validation. Leave Morro Bay as in R2 unless the owner separately requests a new design. No config, data or test change is part of this report.
