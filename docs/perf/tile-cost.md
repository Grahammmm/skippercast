# Per-view request and byte audit (BF-tile-cost)

Opt-in Playwright audit: loads every app view (phone and laptop, Chart presentation) against the
built site and reports requests and bytes by kind and origin. No budget gate yet.

```
pnpm build && TILE_COST=1 pnpm exec playwright test e2e/tile-cost.spec.ts   # skipped without TILE_COST
```

Output: `test-results/tile-cost.json` (schema `tile-cost-v1`) and a Markdown table (printed, and
appended to `GITHUB_STEP_SUMMARY` in CI). Each view runs a cold pass (fresh context, empty HTTP
cache) and a warm pass (same context and cache), each a full `page.goto`.

## Isolation keeps the HTTP cache on

Playwright routing turns the HTTP cache off, so the audit does not use `e2e/fixtures.ts`. Instead
every host but `localhost` fails to resolve (`--host-resolver-rules`), and the same-origin paths the
Worker proxies upstream (`/feeds/*`, `/api/forecast*`, `/api/om/*`) are blocked over CDP
(`Network.setBlockedURLs`). Views therefore run without forecast, feed or boundary data. A warm row
must reuse, from the HTTP cache, a resource the cold pass fetched (`reused_from_cold > 0`), or the
test fails; a no-op `page.route` makes it fail.

Each project saves its rows to `test-results/tile-cost.run.<runner pid>/<project>.json`;
`tile-cost.json` is written (temp file + atomic rename) only once every configured project is
complete, so a `--project` run saves rows but publishes nothing.

## What is counted

- Every timed resource and the navigation, by kind: script, style, font, image, tile (`/tiles/`,
  `/feeds/tiles/`, `.pbf`/`.mvt`, raster under map sources, WMS `GetMap`), feed, API, other.
- A `requestfailed` URL is added only when no timed entry covers it, so a blocked or unresolved
  request counts once. Transfer size 0 (cache hit, failure) is `null`: counted, never sized.
- Remote origins never load: counted by host, bytes not measured.
- `cache_reused`: same-origin bodies served from a cache (hit, 304, or reuse within one load).
  Cold rows have some, so cold transfer bytes are a lower bound; `body_bytes` sums the bodies.
- Not measured: 3D terrain rendering, forecast and feed bytes (blocked), service-worker caching.

## Local run (2026-11-02, AgentOrange, branch merged with main at 42cfe12d)

| View | Project | Pass | Requests | Transfer B | Cache reused | Reused from cold | Tiles | Feeds | API | Settled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| coast | laptop | cold | 43 | 468992 | 24 | — | 1 | 3 | 3 | yes |
| coast | laptop | warm | 44 | 136878 | 36 | 11 | 1 | 3 | 3 | yes |
| conditions | laptop | cold | 43 | 468992 | 24 | — | 1 | 3 | 3 | yes |
| conditions | laptop | warm | 43 | 136878 | 35 | 11 | 1 | 3 | 3 | yes |
| history | laptop | cold | 43 | 468992 | 24 | — | 1 | 3 | 3 | yes |
| history | laptop | warm | 44 | 136878 | 36 | 11 | 1 | 3 | 3 | yes |
| fleet | laptop | cold | 44 | 468992 | 25 | — | 1 | 3 | 3 | yes |
| fleet | laptop | warm | 44 | 136878 | 36 | 11 | 1 | 3 | 3 | yes |
| reports | laptop | cold | 43 | 468992 | 24 | — | 1 | 3 | 3 | yes |
| reports | laptop | warm | 43 | 136878 | 35 | 11 | 1 | 3 | 3 | yes |
| plan | laptop | cold | 43 | 506224 | 23 | — | 1 | 3 | 3 | yes |
| plan | laptop | warm | 44 | 136878 | 36 | 12 | 1 | 3 | 3 | yes |

Phone rows match within one request (43–44). Cold transfer varies 468992–506224 B with which
modules the page reuses within the load. Warm, scripts and styles come from the cache; what remains
is `/api/coast/report` (sent again each visit) and small 304 revalidations. Remote:
`api.tidesandcurrents.noaa.gov`, 1 request per view (it fails to resolve here).
