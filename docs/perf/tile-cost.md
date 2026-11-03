# Per-view request and byte audit (BF-tile-cost)

Opt-in Playwright audit: loads every app view (phone and laptop, Chart presentation) against the
built site and reports requests and bytes by kind and origin. No budget gate: the numbers are the audit; a budget is a later unit.

## Run

```
pnpm build && pnpm exec playwright test e2e/tile-cost.spec.ts   # skipped without TILE_COST
TILE_COST=1 pnpm exec playwright test e2e/tile-cost.spec.ts     # the audit
```

Output: `test-results/tile-cost.json` (schema `tile-cost-v1`) and a Markdown table (printed, and
appended to `GITHUB_STEP_SUMMARY` in CI). Each view runs a cold pass (fresh context, empty HTTP
cache) and a warm pass (same context, same cache); each is a full `page.goto`.

## Isolation keeps the HTTP cache on

Playwright turns the browser's HTTP cache off whenever page or context routing is enabled, so the
audit does not use `e2e/fixtures.ts` (which routes). Instead:

- every host except `localhost` fails to resolve (`--host-resolver-rules`), so no remote origin loads;
- the same-origin paths the local Worker would answer by fetching upstream (`/feeds/*`,
  `/api/forecast*`, `/api/om/*`) are blocked over CDP (`Network.setBlockedURLs`).

Neither turns the cache off. Both kinds of request appear as `requestfailed`: counted, never sized.
Because nothing is stubbed, these views run without forecast, feed or boundary data.

A warm row is only published if the warm pass reused, from the HTTP cache, at least one same-origin
resource the cold pass fetched over the network (`reused_from_cold > 0`; otherwise the test fails).
With a no-op `page.route` added, this check fails (`reused_from_cold` 0), which is the cache-off case.

## Publishing one complete report

The phone and laptop workers run in parallel. Each saves its own rows to
`test-results/tile-cost.run.<runner pid>/<project>.json`; `tile-cost.json` is written only when
every configured project's file is present with a full set of rows (`e2e/tile-cost-publish.ts`). Every
write uses a writer-private temp file and an atomic rename, so a partial run never replaces a
complete report. A run limited to one project (`--project`) saves its rows but publishes no `tile-cost.json`.

## What is and is not measured

- Measured: same-origin requests from the Performance API — scripts, styles, fonts, images,
  tiles (`/tiles/`, `/feeds/tiles/`, `.pbf`/`.mvt`, raster under map sources, WMS `GetMap`),
  `/feeds/`, `/api/` — plus `requestfailed` events. Transfer size 0 (cache, failed requests)
  counts as `null`: counted, never sized.
- `cache_reused`: same-origin entries whose body came from a cache (HTTP cache hit, 304, or a
  module the page reused within one load). Cold rows have some too, so cold transfer bytes are a
  lower bound on what a first visit downloads; `body_bytes` in the JSON sums the bodies.
- Remote origins never load, so they are counted by host but their bytes are not measured here
  (ENC WMS at `gis.charttools.noaa.gov` only loads with a chart layer).
- Not measured: 3D terrain rendering cost, forecast model and feed bytes (blocked),
  service-worker cache hits (service workers are blocked in these tests).

## Local run (2026-11-02, AgentOrange, branch merged with main at 62a92deb plus this change)

| View | Project | Pass | Requests | Transfer B | Cache reused | Reused from cold | Tiles | Feeds | API | Settled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| coast | laptop | cold | 50 | 468939 | 25 | — | 2 | 6 | 5 | yes |
| coast | laptop | warm | 50 | 136861 | 36 | 11 | 2 | 6 | 5 | yes |
| conditions | laptop | cold | 49 | 506171 | 23 | — | 2 | 6 | 5 | yes |
| conditions | laptop | warm | 50 | 136861 | 36 | 12 | 2 | 6 | 5 | yes |
| history | laptop | cold | 50 | 468939 | 25 | — | 2 | 6 | 5 | yes |
| history | laptop | warm | 50 | 136861 | 36 | 11 | 2 | 6 | 5 | yes |
| fleet | laptop | cold | 50 | 468939 | 25 | — | 2 | 6 | 5 | yes |
| fleet | laptop | warm | 50 | 136861 | 36 | 11 | 2 | 6 | 5 | yes |
| reports | laptop | cold | 50 | 468939 | 25 | — | 2 | 6 | 5 | yes |
| reports | laptop | warm | 50 | 136861 | 36 | 11 | 2 | 6 | 5 | yes |
| plan | laptop | cold | 50 | 468939 | 25 | — | 2 | 6 | 5 | yes |
| plan | laptop | warm | 50 | 136861 | 36 | 11 | 2 | 6 | 5 | yes |

Phone rows match within a request or one module (the cold total varies between 468939 and 506171 B
from run to run, depending on which modules the page reuses within the load). A cold view spends
311 KB on its 23 scripts and 133 KB on `/api/coast/report`. Warm, every script and style comes from
the cache; what remains is `/api/coast/report` (133 KB, sent again each visit) and about 4 KB of
304 revalidations. Remote: `api.tidesandcurrents.noaa.gov: 2` per view.

The earlier table (880339 B per cold view) was measured through the routed fixtures: the cache was
off and feeds, forecast and boundaries were stubbed, so it is not comparable and is replaced by this one.
