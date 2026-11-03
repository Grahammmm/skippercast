# Per-view request and byte audit (BF-tile-cost)

Opt-in Playwright audit: loads every app view (phone and laptop, Chart presentation) against the
built site and reports requests and bytes by kind and origin. No budget gate: the numbers are the audit; a budget is a later unit.

## Run

```
pnpm build && pnpm exec playwright test e2e/tile-cost.spec.ts   # skipped without TILE_COST
TILE_COST=1 pnpm exec playwright test e2e/tile-cost.spec.ts     # the audit
```

Output: `test-results/tile-cost.json` (schema `tile-cost-v1`) and a Markdown table (printed, and
appended to `GITHUB_STEP_SUMMARY` in CI). Each view runs a cold pass (fresh context) and a warm pass
(same context); each is a full `page.goto`, so both measure what the server sends.

## What is and is not measured

- Measured: same-origin requests from the Performance API — scripts, styles, fonts, images,
  tiles (`/tiles/`, `/feeds/tiles/`, `.pbf`/`.mvt`, raster under map sources, WMS `GetMap`),
  `/feeds/`, `/api/` — plus `requestfailed` events. Transfer size 0 (disk cache, aborted
  remotes) counts as `null`: counted, never sized.
- Remote origins are aborted by `e2e/fixtures.ts` (`blockedbyclient`), so they are counted by
  host but their bytes are not measured here (ENC WMS at `gis.charttools.noaa.gov` only loads with a chart layer; tides stubs through `api.tidesandcurrents.noaa.gov`).
- Not measured: 3D terrain rendering cost, live forecast model bytes beyond the stubs,
  service-worker cache hits (service workers are blocked in these tests).

## First local run (commit 5722771b, 2026-11-02, AgentOrange; re-verified identical at cfd50d73)

| View | Project | Pass | Requests | Transfer B | Tiles | Feeds | API | Settled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| coast | laptop | cold | 44 | 880339 | 1 | 3 | 4 | yes |
| conditions | laptop | cold | 44 | 880339 | 1 | 3 | 4 | yes |
| history | laptop | cold | 44 | 880339 | 1 | 3 | 4 | yes |
| fleet | laptop | cold | 44 | 880339 | 1 | 3 | 4 | yes |
| reports | laptop | cold | 44 | 880339 | 1 | 3 | 4 | yes |
| plan | laptop | cold | 44 | 880339 | 1 | 3 | 4 | yes |

Phone rows are identical (same shell, same stubs). Every view is dominated by the 23 scripts
(662 KB) and 4 API calls (133 KB); remote: `api.tidesandcurrents.noaa.gov: 2` per view.
