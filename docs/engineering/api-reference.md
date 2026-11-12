# HTTP API reference

Every route the SkipperCast Worker answers, derived by reading `server/app.ts` and `server/routes/`, `server/feeds.ts`, `server/model-api.js` and `server/boat-lookup.ts` as they stand on current `main`. It describes what the repository's code does, not an audit of any live deployment: which bindings and secrets a deployment has is set outside the code. The Worker runs on SkipperCast's own Cloudflare account ([Cloudflare](../cloudflare.md)), with accounts built on passkeys ([ADR 0006](adr/0006-passkey-accounts-stripe-later.md)); the former ChatGPT Sites runtime and its identity headers are gone. This page is maintained by hand. Generating it from typed route definitions (OpenAPI) is a future goal and is not implemented: nothing in `server/` produces an OpenAPI document. When you change a route, update this page in the same PR.

Examples below were produced by running the Worker in Node with an in-memory D1, a fake R2 bucket and synthetic forecast tiles, the same way `tests/test_private_api.mjs` does.

## Conventions

- **Order of matching** (`server/app.ts`, a Hono app; each route module is under `server/routes/`): `GET /feeds/*` → public `/api/` routes → `/api/auth/*` (see [Accounts / passkeys](#accounts--passkeys)) → `/api/session` → the private gate (`server/middleware/auth.ts`) → private `/api/` routes → `/api/*` `404` → any other path (static site). Routing uses the raw, still percent-encoded path. `HEAD` is answered as `GET` without a body. Unknown `/api/` paths answer `401` to anonymous callers and `404` to signed-in ones, because the identity check comes before the final `404`.
- **JSON responses** from `/api/*` carry `Content-Type: application/json`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`, unless a route below sets a public `Cache-Control`.
- **Identity** (`server/middleware/context.ts`). The Worker variable `IDENTITY_PROVIDER` decides how a request is tied to an account. `wrangler.jsonc` in the repository sets it to `skippercast`; this page does not infer anything about a deployment's secrets or bindings beyond that. No request header ever names a user, so forged `oai-*` headers or an arbitrary cookie never authenticate.

  | `IDENTITY_PROVIDER` | How the request is identified | Owner id | `signIn` link |
  | --- | --- | --- | --- |
  | `skippercast` | The `__Host-sc_session` cookie is looked up (see [Session cookie](#session-cookie)); a missing, malformed, unknown or expired cookie is anonymous | `users.id` of the session's account | `/#account` |
  | `none`, absent (the default), empty, `chatgpt-sites` or any other string | No identity, whatever the request carries | none | `null` |

  The value is compared as written: it is not trimmed or case-normalised, so `SkipperCast` or ` skippercast` is an unrecognised string. Where the provider is `none` or unrecognised, `/api/auth/*` answers `404` and every private route answers `401` (fail closed). With `skippercast`, an anonymous caller can still register, sign in and sign out; only passkey management and session management answer `401` without a session.
- **Mutations** (any non-GET private route) require an `Origin` header in `deployments/production.json` `allowed_origins` or the `EXTRA_ORIGINS` Worker secret, and a budget of 30 requests per owner per minute (`request_limits` table). Other limits in front of the private routes (`server/middleware/auth.ts`): before the session lookup, 300 requests a minute per IP (`FEED_LIMITER`); on an authenticated `GET`, 60 a minute per account (`PUBLIC_LIMITER`); both answer `429` with `Retry-After: 60` and are skipped where the binding is absent. `/api/auth/*` has its own separate budget of 20 a minute per IP (D1, `request_limits`), not the 30-a-minute private one.
- **Bodies** are JSON objects of at most 8,192 bytes, read as a stream; anything else is `400`.
- **Request ids.** Every response carries `X-Request-Id` (a UUID, or a well-formed incoming `X-Request-Id` of 8–64 letters, digits, `-` or `_`), and every JSON error body repeats it as `request_id`, e.g. `{"error": "origin rejected", "request_id": "…"}`. Failures are logged with the same id (`server/middleware/request-id.ts`).
- **Errors** (`server/middleware/error.ts`, for paths under `/api/`; the bodies below also carry `request_id`):

  | Status | Body | When |
  | --- | --- | --- |
  | `400` | `{"error": "<message>"}` | A validation error (message kept, e.g. `"date must be within the next seven days"`, `"push endpoint rejected"`, `"origin rejected"`, `"body too large"`) |
  | `429` | `{"error": "Please try again shortly"}` | The 30-per-minute mutation budget, or the 20-per-minute `/api/auth/*` budget |
  | `503` | `{"error": "This service is temporarily unavailable. Your existing records are preserved."}` | Anything else: storage missing, a feed unreadable, a region mismatch |

  A thrown `ClientError` (or `AuthError`) is a validation error, `RateLimited` is `429`, and anything else is `503` (`server/errors.ts`).

## Public feeds

### `GET /feeds/<branch>/<path>`

Published feeds and tiles. `server/feeds.ts` `serveFeed`.

- **Path:** `<branch>` is `conditions`, `data`, `forecasts` or `tiles`; the whole key must match `^(conditions|data|forecasts|tiles)/(?!.*\.\.)[A-Za-z0-9._/-]{1,300}$`. Anything else answers `404` `Not found` (text). Only `GET` reaches this route; `HEAD` falls through to the static site.
- **Source order:** R2 bucket `FEEDS` if bound and the object exists → for `tiles/*`, the static assets → otherwise `https://raw.githubusercontent.com/Grahammmm/skippercast/<branch>/<path>` (18 s timeout, no redirects). The response header `X-Feed-Source` says which: `r2`, `assets` or `github`. An R2 *error* (as opposed to a missing object) is not caught and fails the request.
- **Headers:** `Content-Type` from the extension (`.json`/`.geojson` → `application/json`, `.md` → `text/markdown; charset=utf-8`, otherwise `application/octet-stream`); `Cache-Control: public, max-age=60` for names starting `latest`, `index`, `manifest`, `status`, `health`, `intelligence`, `habitat-dynamics` and ending `.json`, else `max-age=300`; `Access-Control-Allow-Origin: *`; `Access-Control-Expose-Headers: ETag, Content-Range, Content-Length, Accept-Ranges`; `X-Content-Type-Options: nosniff`. From R2 also `ETag`, `Accept-Ranges: bytes`, `Content-Length`.
- **Range and conditional requests:** R2 honours `Range` (`206` + `Content-Range`) and `If-None-Match`/`If-Modified-Since` (`304`). Tiles from static assets support single ranges (`206`; unsatisfiable → `416` with `Content-Range: bytes */<size>`). The GitHub fallback ignores `Range` and returns the whole body.
- **Seafloor archives** (`tiles/seafloor/seafloor-<region>.pmtiles`) are served only from R2, only while `tiles/seafloor/manifest-<region>.json` has `status: "ready"`, the same `region`, a future `expires_at` and a 64-hex `archive_sha256` that equals the object's `sha256` custom metadata. Otherwise `503` (`Seafloor screening unavailable or expired` / `Seafloor archive revision unavailable`). All `tiles/seafloor/*` responses are `Cache-Control: no-store` and never fall back.
- **Errors:** GitHub `404` → `404`; other upstream failures → `502` with `{"error": "Feed unavailable"}`.

Example (`GET /feeds/forecasts/gfs_global/manifest.json` from R2): `200`, `Cache-Control: public, max-age=60`, `X-Feed-Source: r2`

```json
{"model":"gfs_global","tiles":["35_-121"],"meta":{"last_run_initialisation_time":0,"data_end_time":18000},"provider":"NOAA GFS","documentation":"https://example","cycle_iso":"2026-09-28T12:00:00Z"}
```

Feed contents are described in [data contracts](../data-contracts.md), [live conditions](../live-conditions.md), [the data feed README](../data-feed-readme.md) and [forecast data](../forecast-data.md).

- **Edge cache and limit** (`server/feeds.ts`, `server/routes/feeds.ts`, `server/edge-cache.ts`): an R2 object of up to 32 MiB (`EDGE_CACHE_MAX_BYTES`) is cached whole in the Workers Cache API and `Range` and conditional requests are answered from the cached copy; `X-SC-Cache: hit|miss` says which. Seafloor archives are never cached. `/feeds/` is limited to 300 requests per minute per IP (`FEED_LIMITER`): over the limit `429` with `Retry-After: 60` and `{"error": "Too many requests; try again in a minute."}`. Cache and limiter apply only where the Cache API and the binding exist (not in a bare Node test run).

Security headers (HSTS, CSP with `frame-ancestors 'none'`, `Permissions-Policy` and related) are added to every Worker response (`server/middleware/security-headers.ts`); see the static site below.

## Static site

### `GET /`, `GET /<page>.html`, other assets

Any path not under `/api/` or `/feeds/`. Stable page paths (`/`, `/index.html`, `/sources.html`, …; the `SHELLS` map built by `scripts/client-build.mjs`) are served from their build-id copy with `Cache-Control: no-store`. Every other path goes to the static assets binding unchanged (hashed scripts and styles, `vendor/`, `data/`, `regions/`). No authentication.

**Pages** (`server/routes/assets.ts` `shellFor`). `GET /` serves `dist/landing.html`, or `dist/app.html` when the query names an area (`region`, `coast`, `view`, `spot`, `target`, `focus` and the other keys in `AREA_PARAMS`); `GET /index.html` answers the same way, and `GET /map` serves `dist/app.html`. `/landing.html` and `/app.html` serve their own pages. `/coast` and `/coast.html` redirect to `/map` with `presentation=3d` unless the link names one. FE-61 removed the v1 shell and the front-end switch, so no Worker variable or `?ui=` query changes which page is served.

`GET /sw.js` keeps its unhashed path (`scripts/client-build.mjs` preserves it) and is served with `Cache-Control: no-cache` (`server/routes/assets.ts`). The legal pages `/terms.html`, `/privacy.html` and `/licenses.html` are built into `dist/`. Security headers (HSTS, CSP, `frame-ancestors 'none'`, `Permissions-Policy` and related) go on every Worker response, pages included, and `client-build.mjs` writes a generated `_headers` file for static assets (`server/security-headers.ts`).

## Public API

### `GET /api/health`

Liveness. Any method answers. No authentication.

```json
{"service":"SkipperCast","version":"0.3.0","build":"0c321d2522","revision":"52411925dd9c2c3aa241c2741bd745b024c4c8eb","revision_dirty":false}
```

`build` is the client content hash and is unchanged. `revision` is the full 40-hex commit of the checkout that ran `pnpm build`, read once by `scripts/build-revision.mjs` at build time (the Worker and requests never run Git); `revision_dirty` is `true` when tracked files had staged or unstaged edits (untracked files do not count). When Git was unavailable, the checkout was unborn or the output was malformed, both are `null`; that is not an outage. A revision is not deploy attestation or proof the sources were byte-identical to the commit. Only these five fields are returned, so the public endpoint does not reveal which bindings and secrets exist; feed storage is visible per response in `X-Feed-Source`. `scripts/smoke_test.sh` reads `service` and `build` only.

### `GET /api/om/v1/forecast` and `GET /api/om/v1/marine`

SkipperCast's own NOAA/ECMWF forecast service with an Open-Meteo-compatible query and response (`server/model-api.js`), sampled from the tiles on the `forecasts` feed. No authentication.

| Parameter | Values | Default |
| --- | --- | --- |
| `latitude`, `longitude` | comma-separated lists of equal length, 1–50 numbers | required |
| `models` | forecast: `gfs_global`, `ecmwf_ifs025`; marine: `ncep_gfswave016`, `ecmwf_wam` | `gfs_global` / `ncep_gfswave016` |
| `hourly` | forecast: `wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m`, `visibility`, `precipitation`, `temperature_2m`, `cloud_cover`, `weather_code`; marine: `{wave,wind_wave,swell_wave,secondary_swell_wave}_{height,period,direction}`, `wave_peak_period` | none |
| `forecast_days` | integer 1–8 | 7 |
| `timezone` | IANA zone; `auto` means `GMT` | `GMT` |
| `wind_speed_unit` | `kmh`, `ms`, `mph`, `kn` | `kmh` |
| `cell_selection` | `sea` or `land` | `sea` for marine, `land` for forecast |
| `length_unit=imperial`, `temperature_unit=fahrenheit`, `precipitation_unit=inch`, `timeformat=unixtime` | switches | metric, °C, mm, ISO 8601 |

With more than one model, variables are suffixed `_<model>`. With more than one point, the response is an array. Cells outside the published tiles return `null` values.

Example (`?latitude=35.2&longitude=-120.8&hourly=wind_speed_10m,wind_gusts_10m&forecast_days=1&wind_speed_unit=kn&timezone=UTC`, truncated): `200`, `Cache-Control: public,max-age=300`

```json
{"latitude":35.25,"longitude":-120.75,"generationtime_ms":28,"utc_offset_seconds":0,"timezone":"UTC","timezone_abbreviation":"UTC","elevation":0,
 "hourly_units":{"time":"iso8601","wind_speed_10m":"kn","wind_gusts_10m":"kn"},
 "hourly":{"time":["2026-09-29T00:00","2026-09-29T01:00","…"],"wind_speed_10m":[…],"wind_gusts_10m":[…]}}
```

Errors: `400` `{"error": true, "reason": "latitude and longitude must be matching lists of up to 50 numbers"}` (also `Model … is not available for …`, `Variable … is not available`, `forecast_days must be 1 to 8`, `Invalid timezone`, `Invalid wind_speed_unit`). A tile or manifest that cannot be read is `503`.

### `GET /api/om/data/<model>/static/meta.json`

Open-Meteo-style model metadata from the model's manifest (`server/routes/om.ts`, `meta` in `server/model-api.js`). No authentication, feature gate or required query or body. `<model>` is matched as `[a-z0-9_]+` and is one of the four above (`gfs_global`, `ecmwf_ifs025`, `ncep_gfswave016`, `ecmwf_wam`); any other name of that shape → `400` `{"error": true, "reason": "Unknown model", "request_id": "…"}`, and a model with no published manifest metadata → `400` `{"error": true, "reason": "Model not yet published", …}`. A feed that cannot be read → `503`. The answer is the manifest's `meta` object plus `provider`, `source` (the manifest's `documentation`) and `cycle_iso`; the example below is a contract shape, not a captured response. Query parameters are not used to compute the answer, but they still split the cache key. Success carries `Cache-Control: public, max-age=300, s-maxage=300`.

```json
{"last_run_initialisation_time":0,"data_end_time":18000,"provider":"NOAA GFS","source":"https://example","cycle_iso":"2026-09-28T12:00:00Z"}
```

Both `/api/om` routes cache answers in the Workers Cache API keyed on the path, the sorted query and the build id (`X-SC-Cache: hit|miss`, `Cache-Control: public, max-age=300, s-maxage=300`). Only a cache **miss** counts against the limit of 60 requests per minute per IP (`PUBLIC_LIMITER`; `429` + `Retry-After: 60`); a cache hit is never refused. The limiter applies only where the binding exists.

### `GET /api/forecast?region=<id>`

The `forecast` object of the region's intelligence feed (`region.intelligence_feed`, read R2-first): `{region_id, requested_points, models, retrieved, coverage}`. `Cache-Control: public,max-age=300`. Unknown region → `404` `{"error": "Unknown region"}`; a feed whose `region_id` differs → `503`.

### `GET /api/intelligence?region=<id>`

The intelligence feed without `forecast`: `{schema_version, region_id, generated_at, completed_at, ocean_collected_at, sources, verification, health}`. Sources whose id starts `model-` or `verify-` are reduced to `{name, status, issue, url, checked_at}`. `Cache-Control: public, max-age=60, s-maxage=60`. Errors as `/api/forecast`.

### `GET /api/habitat?region=<id>`

The region's dynamic-habitat feed (`region.habitat_feed`): `{schema_version, method, region_id, bounds, generated_at, completed_at, layers, sources, species_methods, interpretation, health}`. Requires `schema_version: 1` and a matching `region_id` (else `503`). `Cache-Control: public,max-age=300`. A region without a habitat feed → `404`.

### `GET /api/daily?region=<id>&part=<part>`

One part of the region's daily feed (`region.daily_feed`, read R2-first), for the map's startup (P4-05): the whole feed is ~1.4 MB. The feed must pass the checks the app applies to it (matching `region_id`, `schema_version: 1`, a valid `generated_at`, `sources` object, `reports` array, `health`, `catch_probability` and `bite_score` null), else `503`. Every part carries `{schema_version, region_id, generated_at, catch_probability: null, bite_score: null, part}` plus:

- `part=regulations` → `regulations` (the rule checks the regulations badge reads);
- `part=mpa-boundaries` or `part=additional-closures` → `sources: {<part>: record}` (`{}` when the feed has no such record).

Edge-cached per region and part (`X-SC-Cache`); one feed read fills all three parts. `Cache-Control: public, max-age=300, s-maxage=300`. Limited to 60 requests per minute per IP (`PUBLIC_LIMITER`, key prefix `daily`; `429` + `Retry-After: 60`). Unknown part → `400`; unknown region → `404`. The service worker saves it like the other public data APIs, and offline packs include all three parts. The client (`dist/daily-feed.js`) falls back to the full feed when this fails.

**Region endpoints (`/api/forecast`, `/api/intelligence`, `/api/habitat`):** all three are edge-cached keyed on `region` only (other parameters are ignored). The intelligence feed is decoded once for both `/api/forecast` and `/api/intelligence` and the sibling answer is cached too. Regions are looked up with `Object.hasOwn`, so `?region=__proto__` and similar are a plain `404`.

### Coast data: `/api/coast/*` (and what is not a route)

The coastal read-only bridge (`server/routes/coast.ts`, `server/coast-data.ts`). Anonymous `GET` and `HEAD` only: no request body is read and no cookie, `Origin`, `Referer`, `Authorization` or other client header is forwarded. Data comes from the owner's reviewed Fish public service, or from SkipperCast's own published feeds and R2 asset groups where they are present (below); it is not an arbitrary proxy and it approves no new source or rights. Other methods → `405` (plain body `Method not allowed`, `Allow: GET, HEAD`). Each request has a 20-second overall deadline; past it, and on any read, size or digest failure not listed below, the answer is `503` `{"error": "Coast source unavailable"}`.

Only these paths are answered, all under `/api/coast/`: `report`, `ocean`, `history`, `habitat/release` and `habitat/tiles`. Everything else (an unknown name, a percent escape, a trailing or doubled slash, `.`/`..`, a query the path does not take, a query key given twice) → `404` `{"error": "Unknown coast dataset"}`.

**Limit, cache and headers.** `/api/coast/*` is limited per IP by `FEED_LIMITER` (key prefix `coast`; 300 requests per minute where the binding exists, as for `/feeds/`): over the limit `429` with `Retry-After: 60` and `{"error": "Too many requests; try again in a minute."}`. No Worker variable or flag turns the router on or off. Every success carries `Cache-Control: no-store`: these answers are not edge-cached and not given a public TTL. From the bridge, only `Content-Type`, `ETag`, `Last-Modified`, `Content-Range`, `Accept-Ranges`, `X-Fish-Habitat-Release`, `X-Fish-Habitat-Source` and `X-Fish-Bathymetry-Source` are passed on, when the upstream sent them, plus `Content-Length`; error answers are JSON with the `json` helper's headers, not these. Further headers appear only in the cases named below.

**`Range`.** Only `Range: bytes=<start>-<end>` with both ends given, `end` not before `start`, safe integers, and a length within the path's byte limit is accepted; anything else (suffix, open-ended, reversed, oversized) → `416` `{"error": "Invalid coast range"}`. The three snapshots (`report`, `ocean`, `history`) take no `Range` at all and answer the same `416`. A valid range is `206`. A range past the end of a locally served object → `416` with `Content-Range: bytes */<size>` and no body. If the upstream does not answer a valid range with a matching `206` and `Content-Range`, the answer is `503` `{"error": "Coast range unavailable"}`.

#### `GET /api/coast`

Not a dataset: it answers `404` `{"error": "Unknown coast dataset"}` (`no-store`). The readable page is `/report` and the feed is `/feed.xml` (`server/coast-pages.ts`, which read `/api/coast/report`); they are not a JSON `/api/coast`. The descendants are [`/api/coast/report`](#get-apicoastreport), `/api/coast/ocean`, `/api/coast/history`, [`/api/coast/habitat/release`](#get-apicoasthabitatrelease) and [`/api/coast/habitat/tiles`](#get-apicoasthabitattiles). See [the coastal service](../coastal-service.md) for what the data is.

#### `GET /api/coast/report`

The San Luis Obispo County coast report packet (`schemaVersion: 1`, `countyId: "slo"`, `generatedAt`, the `forecasts`, `observations`, `tides`, `tideEvents`, `alerts` and `catches` arrays, `sources`, and the enrichments the source packet carries). It is the source's packet with its own assembly, issue and retrieval clocks kept, not a forecast generated here and not a safety rating for an exact place.

- **Query:** optional `county=slo` and optional `region=morro-bay` or `region=cambria-san-simeon`, each at most once. They validate that the request is for the SLO snapshot; they do not select other geography. Any other query key, other value or repeated key → `404 Unknown coast dataset`.
- **Answer:** `200`, JSON, at most 8 MiB. `HEAD` answers the headers without a body. A bridge answer must be `application/json` with `schemaVersion: 1`, `countyId: "slo"` and a valid `generatedAt`, else `503 Coast source unavailable`.
- **Sources (`COAST_FEEDS`):** the Worker variable `COAST_FEEDS` is a comma-separated list of `nearshore`, `water-quality`, `ocean`, `history` and `report`. A name is honoured only while none of the catalog sources behind it (`FEED_SOURCES`) is restricted, unavailable or refused for commercial use in `catalog/sources.json`; unset, unknown or refused names change nothing. A listed feed is used only while its published object is bound, present, valid and inside its age limit (`report` 2 hours; the others from `catalog/feed-health.json`); otherwise that source comes from the bridge as before, and `X-Coast-Upstream` names the outcome (for example `nearshore=fish (stale)`). A fresh owned `report` is served even when the bridge's enrichment (nearshore rows, beach water quality) is unavailable, with `fish=unavailable` noted and no value invented.
- **Headers:** `Cache-Control: no-store`. `X-Coast-Upstream` appears only when `COAST_FEEDS` was consulted for the request; it is not on every answer.
- **Errors:** as the family above (`404`, `405`, `416`, `429`, `503`).

`/api/coast/ocean` (currents and cloud) and `/api/coast/history` (station series against baseline) are the same kind of SLO snapshot with the same query rules; `ocean` is limited to 8 MiB and `history` to 16 MiB. Neither takes `Range`.

#### `GET /api/coast/habitat/release`

The current habitat release record, as the owner's service published it (not the dynamic-habitat feed at `/api/habitat?region=`). **No query string** is accepted (any query → `404 Unknown coast dataset`). At most 512 KiB.

`/api/habitat/release` and `/api/habitat/tiles` are the upstream service's names for this record and the tiles below. They are **not** public aliases on this Worker: the Worker answers only the `/api/coast/habitat/…` paths, and an anonymous request to the upstream names reaches the private gate instead (not a `404` from this router).

#### `GET /api/coast/habitat/tiles`

The habitat tile archive bytes for one region, as published (the content type is the upstream's or the published object's, not assumed to be GeoJSON). At most 2 MiB for a whole body or a single range.

- **Query:** `region` is required: `morro-bay`, `cambria-san-simeon`, `monterey-point-sur` or `point-arguello-conception`. `release` is optional: exactly 64 lowercase hexadecimal characters, the release the caller expects. No other query key, none twice. Otherwise `404 Unknown coast dataset`.
- **Published copy:** when the R2 binding holds a ready current release (`coast/current.json`) that includes the `habitat` group, the object is served from R2 only after its whole bytes match the SHA-256 in that release's manifest, and the manifest itself matches its release id. The answer carries `ETag: "sha256-<digest>"`, `Accept-Ranges: bytes`, `Content-Length`, the entry's `Content-Type` and, when the manifest names one, `X-Fish-Habitat-Release`; ranges are `206` with `Content-Range`. A `release` that differs from the manifest entry's → `404` `{"error": "Unknown coast release"}` (the release is never silently swapped); an entry past its `expiresAt` → `503` `{"error": "Coast release expired"}`; a path with no valid manifest entry → `404 Unknown coast dataset`; a whole-body `GET` of an object over the 2 MiB limit, or a manifest, identity or digest failure → `503 Coast source unavailable`. `HEAD` has no body, and its declared size need not fit a `GET`'s limit. With no ready release, or without the group, the bridge answers instead.
- **Errors:** as the family above. An upstream `404` stays `404`, any other upstream failure is `503 Coast source unavailable`.

The same published-copy rules apply to `/api/coast/habitat/release`.

### `GET /api/fleet/public` and `GET /api/fleet/public/heat`

`GET /api/fleet/public` is **not** a listing: nothing is served at that path, and every `/api/fleet/public/*` path other than `heat` answers `404` `{"error": "Not found"}` (`no-store`), whatever the flags. There is no public events, tracks, boats or ports route.

`GET /api/fleet/public/heat` (`server/routes/public.ts`, `server/fleet/public-heat.ts`; [the public heat runbook](../operations/runbooks/fleet-public-heat.md), [charter fleet design § 14–15](../plans/charter-fleet/design.md#14-map-layers-and-filters)) is the charter fleet's public heat map: grid cells only. Anonymous, ahead of the private gate.

- **Gate:** `404` `{"error": "Not found"}` unless both `FLEET_ENABLED` and `FLEET_PUBLIC_HEAT_ENABLED` are `true` (trimmed, any case; anything else keeps the default, off). This is checked before the limiter and before any query. `FLEET_MAP_ENABLED` is independent and opens only the admin map. Documenting the route does not enable it; going live is the owner's step in the runbook.
- **Limit:** `PUBLIC_LIMITER`, key prefix `fleet-heat` (60 a minute per IP where the binding exists): `429` with `Retry-After: 60`.
- **Query:** `region` (required; 1–64 letters, digits or hyphens, starting and ending with a letter or digit), `kind` (optional, one of `drift-anchor`, `troll-slow`, `troll-pelagic`), `season` (optional, a four-digit year), `limit` (optional integer 1–5000, default 5000) and `cursor` (optional, the opaque `meta.next` of the previous page). An empty `kind`, `season` or `limit` counts as absent. Only these names are read; other keys are not examined.
- **Whole seasons only:** a `season_part` parameter, even an empty one, is a `400`. Publishing part cells beside a whole-season cell would let a reader subtract them and recover the dwell of a part withheld under the floors.
- **Answer:** `200`, a GeoJSON `FeatureCollection` of `Polygon` cells, most `dwell_min` first, ties by cell id; the cells are of the grid module only. Each feature's properties are exactly `kind`, `season`, `dwell_min`, `vessels_n`, `basis` (always `inferred-from-movement`) and `computed_at`. `meta` is `{region, cell_m, min_vessels, delay_hours, count, capped, next}`: `cell_m` lists the cell sizes in metres present on the page, `min_vessels` is 3, `delay_hours` is 72, `capped` is true when more cells matched than the page holds, and `next` is the cursor for the following page, or `null`. A client pages with `meta.next` until it is `null`, not by counting features. No vessel, boat, pin, track, event, port, class, cell id, season part, source or rights value is in the answer. `Cache-Control: no-store`; it is not shared-edge-cached.
- **What a cell must clear** (`PUBLIC_HEAT`, applied in SQL and checked again on the rows):
  - at least **3 distinct vessels** (`vessels_n`);
  - a **72-hour delay**: the cell's last local calendar date must be wholly at least 72 hours old in every time zone. The code takes the UTC date of now minus 72 + 36 hours as the latest date allowed; a cell with no date, or a date that is not a real `YYYY-MM-DD`, is withheld, not corrected;
  - **rights** exactly `public-domain`, `public-record`, `facts-only` or `api-terms`. `internal-only` and `noaa-planning-only` (MarineCadastre) cells, and any other or unknown value, never appear. While the AIS stream source (aisstream) stays `internal-only`, its cells are not served; the route returns an empty collection until that changes (runbook, Q1).
- **Errors:** `400` `{"error": …}` with `region is required`, `invalid kind`, `season must be a year`, `limit must be 1-5000`, `invalid cursor` or `season_part is not offered: whole-season cells only`; `503` `{"error": "This service is temporarily unavailable."}` without storage; `404` and `429` as above.

### `POST /api/telemetry`

Cookie-less funnel events and client error reports from `web/telemetry.ts` (`navigator.sendBeacon`). Anonymous, but needs an allowed `Origin` (`400 origin rejected`), is limited by `PUBLIC_LIMITER` to 60 a minute per IP (`429` + `Retry-After: 60`) and takes at most 4,096 bytes (`400 body too large`). The body is exactly `{build, events}`: `build` is 10 hex characters or `dev`; `events` holds 1–10 of `{"type": "funnel", "name": "port_selected"|"map_viewed"|"forecast_viewed"|"spot_saved"|"offline_saved"|"install", "region"?}` or `{"type": "error", "kind": "error"|"rejection", "message"?, "source"?, "line"?, "column"?, "request_id"?}`. Any other field or value answers `400 {"error": "invalid telemetry"}`. A funnel event repeated within a batch is written once. Valid batches answer `204` with no body, written to Analytics Engine when `ANALYTICS` is bound and discarded otherwise. `GET` is not a route (it reaches the private gate). See [client telemetry](telemetry.md).

```json
{"build":"0123456789","events":[{"type":"funnel","name":"map_viewed","region":"morro-bay"},{"type":"error","kind":"error","message":"x is undefined","source":"index.0123456789.js","line":12,"column":7,"request_id":"3f0c…"}]}
```

### `GET /api/session`

Whether the caller is signed in, the push public key and the sign-in link. Public (it runs before the private gate); it answers for every `IDENTITY_PROVIDER` value and, with the `skippercast` provider, touches storage only when the request carries a session cookie.

| Field | Meaning |
| --- | --- |
| `signedIn` | `true` when a request is identified |
| `publicKey` | `VAPID_PUBLIC_KEY` for Web Push, or `null` when the Worker has none |
| `signIn` | The sign-in link from the provider rule, even when signed out: `/#account` for `skippercast`, `null` for every other provider |
| `user` | `{id, display_name}` when identified (`display_name` may be `null`), else `null` |
| `is_admin` | Always present; `true` only when the account has the Text Advisor admin role (`users.role='admin'`, set only by `scripts/advisor/grant-admin.mjs`), `false` when signed out. The role itself is never exposed |
| `advisor` | Boolean from the Text Advisor enabled gate (the same decision that answers `/chat.html`); a visibility hint for the page, not an authorization |

The probe exposes no role, credential, public key or session hash. A session that is close to expiry is renewed here like anywhere else identity is resolved (see [Session cookie](#session-cookie)).

Illustrative signed-out answer with the `skippercast` provider (the `publicKey` and `advisor` values depend on the deployment's configuration):

```json
{"signedIn":false,"publicKey":null,"signIn":"/#account","user":null,"is_admin":false,"advisor":false}
```

With any other provider the same answer has `"signIn":null`. Illustrative signed-in answer (placeholders, not real values; `display_name` is `null` when the person never chose one):

```json
{"signedIn":true,"publicKey":"<VAPID public key>","signIn":"/#account","user":{"id":"<user id>","display_name":null},"is_admin":false,"advisor":false}
```

### `GET /api/advisor/health`

Text Advisor liveness (docs/plans/text-advisor/). No authentication. Answers `404` `{"error": "Not found"}` unless the Worker var `TEXT_ADVISOR_ENABLED` is `true`, like every advisor path (`/api/advisor/*`, `/ports/*`, `/species/*`, `/boats/*`, `/media/*`, `/u/*`, `/contact.vcf`, `/text`, `/qr/*`, and the web chat page `/chat.html`), which are reserved and gated by `server/advisor/gate.ts` before their routes exist. When on, `Cache-Control: no-store`:

```json
{"enabled":true,"channel":"bluebubbles","providers":["hermes","claude"],"relay":{"state":"up","checked_at":"2026-10-03T15:00:00.000Z"}}
```

`channel` is `ADVISOR_CHANNEL` (`bluebubbles` or `twilio`); `providers` is the vision provider chain from `ADVISOR_VISION_PROVIDERS`; `relay` is the Mac relay watchdog's last result from `job_state` `advisor.relay` (`up` or `down`, and when it was checked), or `null` before the first check. Never a secret, the relay URL or the advisor's phone number.

### `POST /api/advisor/inbound/bluebubbles/<token>`

The Mac relay's webhook (BlueBubbles server → Worker; [relay setup](../operations/runbooks/advisor-relay-setup.md), [03 · Channels](../plans/text-advisor/03-channels.md)). Gated like every advisor path (`404` unless `TEXT_ADVISOR_ENABLED=true`).

- **Auth:** BlueBubbles signs nothing, so `<token>` (redacted here) is the secret `ADVISOR_WEBHOOK_TOKEN`, compared in constant time. A wrong or missing token → `401` `{"error": "Unauthorized"}` and a counted log line (`advisor_webhook_unauthorized`), never the body.
- **Limits:** per-IP `PUBLIC_LIMITER` when bound (`429`); body at most 64 KB (`400`).
- **Body:** BlueBubbles' JSON `{type, data}`. `new-message` from a one-to-one chat with text or attachments is stored (contact found or created by phone hash, an `advisor_messages` row `queued`, one placeholder `advisor_media` row per attachment) and queued on `ADVISOR_QUEUE`, or processed inline when the queue is not bound. Messages from us, reactions, group chats, non-text items and senders outside the North American numbering plan are ignored. `updated-message` confirms or fails one of our outbound rows; `message-send-error` marks it `failed`; `new-server` is logged; every other type is ignored. A second delivery of the same message (same channel and provider id) does nothing.
- **Response:** `200` `{}` in every accepted case, fast, so the relay never retries a stored message.

<!-- TA-C2: Twilio webhooks -->
### `POST /api/advisor/inbound/twilio/<token>`

Twilio's incoming-message webhook for the advisor number after a port to Twilio ([03 · Twilio adapter](../plans/text-advisor/03-channels.md)). Mounted always, so a port in progress loses nothing; gated like every advisor path (`404` unless `TEXT_ADVISOR_ENABLED=true`).

- **Auth:** `<token>` (redacted here) is `ADVISOR_WEBHOOK_TOKEN`, compared in constant time, exactly as for BlueBubbles; then `X-Twilio-Signature` must equal base64(HMAC-SHA1(`TWILIO_AUTH_TOKEN`, URL + every POST parameter as name+value, sorted by name)), where the URL is `ADVISOR_PUBLIC_BASE` + the request path + query, never the `Host` header, and `AccountSid` (when present) must be `TWILIO_ACCOUNT_SID`. Either failure → `401` `{"error": "Unauthorized"}` and a counted log line (`advisor_webhook_unauthorized`), never the body. Without `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` every request is `401`.
- **Limits:** per-IP `PUBLIC_LIMITER` when bound (`429`); body at most 64 KB (`400`).
- **Body:** `application/x-www-form-urlencoded`: `MessageSid`, `AccountSid`, `From`, `To`, `Body`, `NumMedia`, `MediaUrl0..N`, `MediaContentType0..N`, `SmsStatus`, optionally `OptOutType`. A received message from a North American number with text or media is stored like a BlueBubbles one (channel `sms`, `provider_id` the `MessageSid`, one placeholder `advisor_media` row per `MediaUrlN` on `https://api.twilio.com/`, which the consumer downloads with Basic auth) and queued. STOP, HELP and every other keyword are stored as ordinary text, so the engine's STOP/START/HELP handling runs on whatever Twilio forwards. Status callbacks, other senders and empty messages are ignored. A second delivery of the same `MessageSid` does nothing.
- **Response:** `200` `<?xml version="1.0" encoding="UTF-8"?><Response/>` (`text/xml`) in every accepted case: Twilio sends nothing itself; replies go out through the Messages API.

### `POST /api/advisor/inbound/twilio-status/<token>`

The `StatusCallback` set on every message the advisor sends through Twilio. Same token check, signature check, limits and gate as the inbound webhook.

- **Body:** form-encoded `MessageSid`, `MessageStatus` (`queued`, `sent`, `delivered`, `undelivered`, `failed`, ...), `ErrorCode` when it failed.
- **Effect:** the outbound `advisor_messages` row with that `provider_id`: `sent` or `delivered` → `sent` (and `sent_at` if unset); `undelivered` or `failed` → `failed` with error `twilio-<ErrorCode>` (`opted-out` for 21610, which also stops the contact). Other statuses and unknown sids change nothing.
- **Response:** `204`, or `401` / `429` / `400` / `503` as above.

<!-- TA-S6: Meta's webhook -->
### `GET /api/advisor/inbound/meta`

The webhook subscription handshake for the Meta app's Instagram product ([09 · Inbox](../plans/text-advisor/09-social.md), [App Review runbook](../operations/runbooks/advisor-meta-app-review.md)). Gated like every advisor path.

- **Query:** `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`.
- **Response:** `200` `text/plain` with the challenge when `hub.verify_token` equals `META_VERIFY_TOKEN` (constant-time compare); otherwise `403` `Forbidden` and a counted log line. A challenge that is not 1-200 word characters, dots or dashes is refused rather than echoed. Per-IP `PUBLIC_LIMITER` (`429`).

### `POST /api/advisor/inbound/meta`

Instagram DMs and comments from Meta (TA-S6, `server/advisor/social/inbox.ts`). Dark until the owner sets `ADVISOR_INBOX_ENABLED=true` after App Review.

- **Auth:** `X-Hub-Signature-256: sha256=<hex>` must be the HMAC-SHA256 of the raw body keyed with `META_APP_SECRET`, checked in constant time before anything is parsed. Missing or wrong → `401` `{"error": "Unauthorized"}` and a counted log line.
- **Limits:** per-IP `PUBLIC_LIMITER` (`429`); body at most 256 KB (`400`); a body that is not JSON → `400`.
- **Switch:** with `ADVISOR_INBOX_ENABLED` off (or `META_PAGE_TOKEN`/`META_IG_USER_ID` missing) a signed delivery answers `200` `{}` and nothing is written.
- **Body:** `{"object": "instagram", "entry": [...]}` for `META_IG_USER_ID` (other accounts' entries are skipped). `messaging[]` with a `message` that has text or image attachments on Meta's CDN is a DM: stored on channel `instagram_dm` (`provider_id` the `mid`, the contact found or created by the sender's IGSID in `advisor_contacts.ig_sid`, source `igdm`; one placeholder `advisor_media` row per image, downloaded by the consumer from `lookaside.fbsbx.com`, `*.fbcdn.net` or `*.cdninstagram.com` only) and queued. Echoes of our own messages, reads, reactions, deletions, unsupported items and shares without text are skipped. `changes[]` with `field: "comments"`: a comment whose first word is a keyword of `catalog/advisor/keywords.json`, or (only with `ADVISOR_INBOX_PUBLIC_REPLIES=true`) a question, is stored on channel `instagram_comment` (`provider_id` the comment id, source `igcomment`) and queued; any other comment and our own comments are not stored. A second delivery of the same message or comment id does nothing.
- **Response:** `200` `{}` in every accepted case; `503` when storage fails, so Meta retries.

<!-- TA-C4: upload link and media serving -->
### `GET /u`

The upload page a skipper gets by text when a photo or video is too big for the channel ([03 · Uploads for compressed channels](../plans/text-advisor/03-channels.md)). Gated like every advisor path. The link is `/u#<token>`: the token is the URL fragment, which the browser never sends, so this route serves `dist/upload.html` to anyone (`200`, `Cache-Control: no-store`, `X-Robots-Tag: noindex`) and checks nothing; the page sends the token with the file. `<token>` is `base64url(contact_id|expiry|HMAC-SHA256(upload key, contact_id|expiry))`, valid 24 hours, verified statelessly (`server/advisor/media.ts` `verifyUploadToken`; the key is the `upload` HKDF subkey of `ADVISOR_PHONE_KEY`). Per-IP `PUBLIC_LIMITER` when bound (`429`).

### `GET /u/<token>` and `POST /api/advisor/upload/<token>` (retired)

Links sent before the token moved to the fragment ([threat model § 9.3](../legal/threat-model.md#93-web-chat-upload-links-and-data-exports)). A genuine token (expired or not) less than 7 days past its expiry → `410` ("This upload link has been replaced. Text LINK to SkipperCast for a new one.", plain text for the page, `{"error": ...}` for the POST); anything else → `404`. Neither serves the page nor takes a file.

### `POST /api/advisor/upload`

The upload page's request (JavaScript, not a form: the CSP has `form-action 'none'`). The token comes in the `X-Upload-Token` header, never in the URL. A missing, bad, tampered or expired token, an unknown or blocked contact → `404` `{"error": "Not found"}`, the gate's body.

- **Body:** `multipart/form-data`; the first part with a filename is read as a stream, at most 300 MB (`413` `{"error": "That file is too large."}`).
- **Processing:** the file is sniffed by its magic bytes (JPEG, PNG, GIF, WebP, HEIC/HEIF, MP4/MOV, M4A/AAC/AMR/CAF; anything else → `415` `{"error": "That file type is not supported."}`, the media row kept as `rejected`), JPEG/PNG metadata is stripped, and the file is stored privately in `ADVISOR_MEDIA` (an identical file from the same contact is linked, not stored twice). Then a synthetic inbound message (`body` empty, `media_json` the new media id, the contact's channel, `provider_id` `upload:<media id>`) is queued exactly like a webhook message, so the reply comes by text.
- **Response:** `200` `{"ok": true}`; `400` for a body with no file part; `503` when storage is unavailable.

### `GET /media/<id>.jpg` and `GET /media/<id>.png`

Public images for the site pages and for Meta to fetch ([09 · Media that Meta fetches](../plans/text-advisor/09-social.md)). Gated like every advisor path. Served only when the media's `publish_state` is `approved` or `posted`: `advisor/derived/<id>/public.jpg` when the media job has written it (`.jpg` only), otherwise the metadata-stripped original when its stored type matches the extension and its EXIF orientation was upright (a JPEG stored sideways, `orientation` 2-8, is served only as `public.jpg`). HEIC, video and audio originals are never served. `Content-Type` from the stored row (`image/jpeg` for the derived file), `Cache-Control: public, max-age=3600`, `X-Robots-Tag: noindex`. Anything else (unknown id, private, queued or rejected media, another extension) → `404` with the same body as a missing id.

### `GET /media/<id>.story.jpg` and `GET /media/<id>.mp4`

For Meta's fetch when a post is published (TA-S2, [09 · Publishing](../plans/text-advisor/09-social.md)). Same gate and `publish_state` rule as above. `<id>.story.jpg` is the media job's `advisor/derived/<id>/story.jpg` (1080 x 1920 with the footer), with no fallback to the original. `<id>.mp4` is only ever the media job's metadata-stripped copy of a video, `advisor/derived/<id>/video.mp4` (no container metadata, no location atoms; 00 principle 7), served as `video/mp4` once the row has `derived_at` and no `derived_error`; the original is never served (`404` until the copy exists, and when stripping failed). It answers with `Accept-Ranges: bytes`: a single `Range: bytes=a-b`, `a-` or `-n` answers `206` with `Content-Range: bytes a-b/size`, a range past the end `416` with `Content-Range: bytes */size`, anything else the whole file. Same `Cache-Control: public, max-age=3600` and `X-Robots-Tag: noindex`. Anything else → `404`.

### `GET /media/post/<post_id>/<name>`

A post's generated graphic for Meta's fetch (TA-S4, [09 · Media that Meta fetches](../plans/text-advisor/09-social.md)): the daily card (`daily.jpg`), the roundup's cover and slides (`roundup.jpg`, `roundup-<n>.jpg`) or a Story card (`story.jpg`) that the media job wrote to `advisor/posts/<post_id>/<name>`. Gated like every advisor path. Served (`image/jpeg`, `Cache-Control: public, max-age=3600`, `X-Robots-Tag: noindex`) only while the post is `approved`, `publishing`, `posted` or `partial` and only for a name its graphic's done state lists; a draft, rejected or failed post, an unknown post or name → `404` with the same body as a missing id.

<!-- TA-C3: web chat -->
### `POST /api/advisor/web/message`

The web chat ([08 · Web chat](../plans/text-advisor/08-website.md), [03 · Web adapter](../plans/text-advisor/03-channels.md)). Gated like every advisor path. First-party only: the `Origin` must be an allowed origin (`deployments/production.json` or `EXTRA_ORIGINS`), as for private mutations (`400` `{"error": "origin rejected"}`). Per-IP `PUBLIC_LIMITER` with key `advisor-web:<ip>` (`429`).

- **Identity:** the `sc_adv` cookie. The first call without one (or with a malformed one) gets a new value, 32 random bytes base64url, in `Set-Cookie: sc_adv=<value>; Max-Age=7776000; Path=/; Secure; HttpOnly; SameSite=Lax`; later calls send it back. `advisor_contacts.web_session` stores its SHA-256. A new web contact's `source` is `web`, or the `[via <s>]` marker of its first message.
- **Body:** JSON, at most 8 KB: `{"text": "...", "media_ids": ["<media id>", ...]}`. `text` at most 2,000 characters; `media_ids` at most 4, each an image this visitor uploaded through `/api/advisor/web/upload`, stored and not yet used by a message. Empty text with no media, another visitor's id, a used or rejected one → `400`.
- **Processing:** stored through the shared inbound path, then the advisor turn runs inline (no queue) with a per-request outbound channel, so its replies come back in this response.
- **Response:** `200` `{"replies": [{"id": "<outbound message id>", "text": "...", "links": [], "media": ["/media/<id>.jpg"]}], "contact": {"language": "en", "linked": false}}`. If the turn has not finished after 40 s: `200` `{"replies": [], "pending": true}`; the turn completes in the background and its late replies are recorded as `failed` (`web-closed`), not delivered. The replies are the engine's (TA-E1; without `ANTHROPIC_API_KEY`, the warm-up text). `contact.linked` is `true` once this session belongs to a phone contact (the web phone link, [03 · Web adapter](../plans/text-advisor/03-channels.md)). `503` without storage.

<!-- TA-E1: send me my data -->
### `GET /my-data` and `POST /api/advisor/export`

The download a contact gets by text after "send me my data" ([02 · Retention and deletion](../plans/text-advisor/02-data-model.md)). Gated like every advisor path. The link is `/my-data#<token>`: `GET /my-data` serves `dist/my-data.html` to anyone (`no-store`, `noindex`), and its button sends `POST /api/advisor/export` with the token in the `X-Export-Token` header, so the token is in no request URL. `<token>` (redacted here) is `base64url(contact_id|key|expiry|HMAC-SHA256(upload key, contact_id|key|expiry))`, where `key` is the export object `advisor/exports/<contact_id>/<YYYY-MM-DD>.json` in `ADVISOR_MEDIA` and `expiry` is 24 hours after the export (`server/advisor/exports.ts`; the `upload` HKDF subkey of `ADVISOR_PHONE_KEY`, as for upload links). Per-IP `PUBLIC_LIMITER` (`advisor-export:<ip>`, `429`).

- **Response:** `200` with the JSON export (`exportContact`: the contact without its number or session, its messages, media rows, reports, report edits, crew rows, a pending crew invitation and boats), `Content-Type: application/json; charset=utf-8`, `Content-Disposition: attachment; filename="skippercast-data.json"`, `Cache-Control: no-store`, `X-Robots-Tag: noindex`.
- **Errors:** a missing, bad, tampered or expired token, a key that is not the contact's, a contact that has since been forgotten, or a missing object → `404` `{"error": "Not found"}` (the gate's body). `503` on a storage failure.
- **Retired:** `GET /api/advisor/export/<token>` (links sent before the change) answers `410` `{"error": "This data link has been replaced. Text SEND ME MY DATA to SkipperCast for a new one."}` for a genuine token less than 7 days past its expiry, `404` otherwise; it never serves the data.

### `POST /api/advisor/web/upload`

A photo for the web chat. Same gate, Origin check, limiter key and cookie handling as the message route.

- **Body:** `multipart/form-data`, the first file part, at most 8 MB (`413` `{"error": "That photo is too large."}`, by `Content-Length` or while streaming). Images only, by magic bytes (JPEG, PNG, GIF, WebP, HEIC/HEIF); anything else → `415` `{"error": "Send a photo: JPEG, PNG, HEIC, GIF or WebP."}`. Refused files are kept as `rejected` media rows with nothing stored.
- **Processing:** the same intake as uploads and provider media (`ingestMedia`: JPEG/PNG metadata stripped, stored privately in `ADVISOR_MEDIA`, linked when identical to this visitor's earlier upload). No message is created; the next message references it.
- **Response:** `200` `{"media_id": "<id>"}`; `404` for a blocked visitor; `400` without a file part; `503` without storage or the media bucket.

<!-- TA-C6: contact card, deep link and QR -->
### `GET /contact.vcf`

The advisor's contact card ([03 · Contact card and deep links](../plans/text-advisor/03-channels.md)). Gated like every advisor path. A vCard 3.0 (`server/advisor/pages/contact-card.ts`): `FN:SkipperCast`, `N:SkipperCast;;;;`, `ORG:SkipperCast`, `TEL;TYPE=CELL,VOICE:<ADVISOR_NUMBER>`, `URL:<ADVISOR_PUBLIC_BASE>`, `PHOTO;ENCODING=b;TYPE=PNG:` (the app icon, `dist/app-icon-192.png`), CRLF line endings, lines folded at 75 octets. `Content-Type: text/vcard; charset=utf-8`, `Content-Disposition: attachment; filename="SkipperCast.vcf"`, `Cache-Control: public, max-age=86400`. Without `ADVISOR_NUMBER` → `503` with a plain-text message (`no-store`).

### `GET /text?s=<source>&m=<message>`

TA-S7: `p=<post id>` (`^[\w-]{1,64}$`) with `s=ig` makes the marker `[via ig:<post id>]`, which records the contact's first-touch post (`advisor_contacts.source_post_id`) for the post's "chats started"; a bad `p`, or `p` with another source, is dropped.

The "text us" deep link for the site, Instagram and print. Gated like every advisor path. `302` to `sms:<ADVISOR_NUMBER>?&body=<body>` (`Cache-Control: no-store`), where `<body>` is `m` (control characters replaced by spaces, trimmed, at most 140 characters; default `Hi SkipperCast`) followed by ` [via <s>]` when `s` matches `^[a-z0-9:_-]{1,32}$` (any other `s` is dropped), percent-encoded. The engine strips that marker from the first message and records the source on the contact (`server/advisor/intents.ts` `parseSourceMarker`; `[via ig:<post id>]` records `ig`). Without `ADVISOR_NUMBER` → `503`.

### `GET /qr/text.svg`

A QR code of `<ADVISOR_PUBLIC_BASE>/text?s=qr` for print and the site, as SVG (byte mode, error correction M, a four-module quiet zone; `server/advisor/pages/qr.ts`, no dependency). Gated like every advisor path; needs no number. `Content-Type: image/svg+xml; charset=utf-8`, `Cache-Control: public, max-age=86400`.

### `GET /ports/<port-id>`, `GET /species/<key>`, `GET /boats/<slug>`

The advisor's public pages ([08 · Public pages](../plans/text-advisor/08-website.md), `server/advisor/pages/`). Gated like every advisor path. Server-rendered HTML (`Content-Type: text/html; charset=utf-8`, `Content-Language`, `Vary: Accept-Language`) in English, or in Spanish with `?lang=es` or a first `Accept-Language` range of `es`; `?lang=en` forces English.

- **Port** (`<port-id>` from `catalog/home-ports.json` whose region is built): today's daily answer (stored when current, else composed from the same facts; never a model call), published skipper reports of the last 14 days (verified boats linked, others "Another boat"), today's fishing-window conditions and advisories, the port's verified boats, and the coastal-directory species with today's state from `advisor_rules` (open, closed, under review, check the rules). `Cache-Control: public, max-age=300`.
- **Species** (a `catalog/advisor/species-pages.json` key; a synonym such as `california-halibut` → `301` to the key): names, description, field marks and look-alikes, the rules card at `#rules` (every jurisdiction's active and review rows with source and reviewed date; stale rows "Under review"; a species without rows shows its group's), recent catches from verified boats (14 days, by date and port), method notes. `Cache-Control: public, max-age=900`.
- **Boat** (`slug` of a `verified` or `pending` boat): verified badge or "Not verified yet" (pending pages carry `noindex`), the last 30 days of published reports ("edited" when `version > 1`), up to 12 approved or posted photos through `/media/<id>.jpg`, booking link, phone and Instagram. `Cache-Control: public, max-age=300`.

Edge-cached (`server/edge-cache.ts`) under the path, the resolved language and `build:<job_state advisor.pages.version>`, which publishing, editing, verifying a boat and deciding a photo bump; other query parameters (`s`) are not part of the key. Per-IP `PUBLIC_LIMITER` (`advisor-page:<ip>`, `429`) only for renders the cache could not answer. Unknown ids, rejected boats → `404` HTML page (`noindex`, `no-store`). `503` without storage.

### `GET /go/<slug>?t=booking|website&p=profile|directory|map`

The charter fleet's outbound link ([design § 12](../plans/charter-fleet/design.md#12-worker-api), `server/fleet/go.ts`, CF-34). `404` unless `FLEET_ENABLED=true`, then limited per IP by `PUBLIC_LIMITER` (`fleet-go:<ip>`, `429`). `302` (`Cache-Control: no-store`, `X-Robots-Tag: noindex`) to the vessel's stored `booking_url` (`t=booking`) or `website` (`t=website`), never to a URL from the request: other parameters are ignored. Appends `utm_source=skippercast&utm_medium=referral&utm_campaign=fleet-<region>&utm_content=<p>`, keeping the stored URL's parameters and any `utm_*` it already has; an unknown or missing `p` is `other`. Unknown slug, a vessel not `status=active` and `profile_status=listed`, a missing `t` or URL, or a stored URL that is not plain `https` (credentials included) → `404 {"error": "Not found"}`; `503` without storage. A `GET` adds one to the day's `fleet_link_clicks` row (vessel, target, placement, UTC day) and writes an Analytics Engine `fleet_click` point (slug, target, placement) when `ANALYTICS` is bound; `HEAD` is answered but not counted. Nothing about the visitor (IP, user agent, referrer, cookie, user id) is stored. Admins read the counts at `GET /api/admin/fleet/clicks?days=7|30|90&region=` (raw redirects, not visitors).

### `GET /sitemap-advisor.xml`

Gated. The port pages of active regions, every species page and verified boats' pages, each with its `?lang=es` alternate (`xhtml:link`) and, for boats, the latest report date as `lastmod`. `Content-Type: application/xml; charset=utf-8`, `Cache-Control: public, max-age=3600`, edge-cached under the pages version.

### `GET /robots.txt`

While `TEXT_ADVISOR_ENABLED=true`: `User-agent: *`, `Allow: /` and `Sitemap: <ADVISOR_PUBLIC_BASE>/sitemap-advisor.xml` (`Cache-Control: public, max-age=3600`). Otherwise the request falls through to the static site, which publishes no `robots.txt`.

## Scheduler

### `POST /api/jobs/check`

Runs saved-trip checks for one page of 25 trips, delivers push alerts and prunes expired rows. Called by `scripts/check_saved_trips.py` from `live-conditions.yml`.

- **Auth:** `Authorization: Bearer <GitHub Actions OIDC token>` with audience `<public_origin>/api/jobs/check`, verified by `server/job-auth.ts` against GitHub's fixed JWKS: RS256; issuer, subject, repository, repository id, owner id, ref, workflow and event (`schedule`, `workflow_dispatch`, `push`) must match `deployments/production.json` `scheduler` (the workflow is `scheduler.workflow`, `live-conditions.yml`, only); lifetime at most 600 s. Anything else → `401` `{"error": "Unauthorized"}`.
- **Body:** `{"cursor": "<last trip id>"}` or `{}`; cursor at most 50 characters.
- **Limit:** 30 calls per token (`jti`) per minute.
- **Response:** `{"checked": 25, "changes": 1, "delivered": 1, "held": 0, "in_app": 0, "next_cursor": "<id>|null"}`. The script pages until `next_cursor` is `null` (at most 100 pages).

Retention does not depend on this call: the Worker's cron (`scheduled`, `server/index.ts` calling `scheduledPrune` in `server/trips.ts`) prunes expired rows too.

<!-- TA-M1: the advisor-media runner job -->
### `GET /api/advisor/jobs/media`

The Text Advisor's media job asks for its work ([09 · Derived images and graphics](../plans/text-advisor/09-social.md)). Called by `scripts/advisor/media_job.py` from `advisor-media.yml`. Gated like every advisor path (`404` unless `TEXT_ADVISOR_ENABLED=true`).

- **Auth:** as `POST /api/jobs/check`, but the token's audience must be `<public_origin>/api/advisor/jobs` and its workflow `advisor-media.yml`, which `deployments/production.json` `scheduler.workflows` must list (`verifyJobToken(token, policy, {audiencePath, workflows})`). A trip-check token is refused here and this token there. Anything else → `401`.
- **Limit:** 240 calls per token (`jti`) per minute, shared with `media-done`.
- **Response:** `200`, `no-store`: `{"media": [{"id", "r2_key", "mime", "sha256", "bytes", "orientation", "keys": {"public": "advisor/derived/<id>/public.jpg", "thumb": ".../thumb.jpg", "story": ".../story.jpg"}}], "graphics": [{"id", "kind": "daily|story|roundup", "out_key": "advisor/posts/<post>/<name>.jpg", "data": {}, "media": [{"id", "r2_key", "mime", "orientation", "public_key"}]}]}`, oldest first, at most 25 media and 10 graphics, plus `"videos": [{"id", "r2_key", "mime", "sha256", "bytes", "keys": {"video": "advisor/derived/<id>/video.mp4"}}]` (at most 5): every stored video, private ones included, not rejected and without `derived_at`, for the job to strip its container metadata. `orientation` is the JPEG's EXIF Orientation read at intake (1-8; null for other formats), which the job applies because the stored original has no EXIF. Media listed: stored images, not rejected, without `derived_at`, that are over 4.5 MB, HEIC/HEIF, stored sideways (`orientation` 2-8), or `queued`/`approved`/`posted`. Graphics: `job_state` `advisor.graphic.<id>` with `status` `pending`.

### `POST /api/advisor/jobs/media-done`

The job reports one item. Same auth and limit.

- **Body:** JSON, at most 8 KB. Media: `{"media_id", "keys": {"public", "thumb", "story"?}, "width", "height", "source_width"?, "source_height"?}` where the keys are exactly that item's `advisor/derived/<id>/` files and the sizes are `public.jpg`'s (positive integers); video: `{"media_id", "keys": {"video": "advisor/derived/<id>/video.mp4"}, "width"?, "height"?}` (the stripped copy; `"error": "no-ffmpeg"` when the runner has no ffmpeg); graphic: `{"graphic_id", "keys": {"public": <its out_key>, "slides"?: ["<out_key stem>-<n>.jpg", ...]}, "width", "height"}`. Either may instead carry `"error": "<short reason>"` (letters, digits, spaces and `.:,;()/'-`, at most 200), which gives the item up.
- **Effect:** media and video: `derived_at` set (and `derived_error` with an error; a video given up stays held, never approved or served); `width`/`height` filled from `source_width`/`source_height` only when the row had none (HEIC). Graphic: its `job_state` value becomes `status` `done` with `keys`, `width`, `height`, `done_at`, or `failed` with `error`.
- **Response:** `200` `{"ok": true, "kind": "media|graphic", "status": "done|failed"}`; `400` `{"error": "invalid media-done report"}` for anything malformed (other keys, a missing size, both ids); `404` for an unknown id.

<!-- CF-01: the charter fleet jobs -->
### `GET /api/fleet/jobs/ping`

Identity check for the charter fleet's Hermes workflows ([charter fleet design § 12](../plans/charter-fleet/design.md)). The other `/api/fleet/jobs/*` routes below (`snapshot`, `registry`, `activity`, `heartbeat`, `health`, `watch` and `labels`) follow the same rules; the admin-only map is a separate family, [`GET /api/fleet/map/<layer>`](#get-apifleetmaplayer-admin-only), under account auth, not job auth. Every `/api/fleet/*` and `/api/admin/fleet/*` path answers `404` `{"error": "Not found"}` unless the Worker var `FLEET_ENABLED` is `true` (`server/routes/fleet.ts` `fleetGate`); `/api/fleet/map/*` also needs `FLEET_MAP_ENABLED=true`.

- **Auth:** as `POST /api/jobs/check`, but the token's audience must be `<public_origin>/api/fleet/jobs` and its workflow one of `fleet-registry.yml`, `fleet-osint.yml`, `fleet-ais.yml`, `fleet-health.yml`, which `deployments/production.json` `scheduler.workflows` lists (`FLEET_JOB_SCOPE`, `requireFleetJob`). Trip-check and advisor-media tokens are refused here, and fleet tokens there. Anything else → `401`.
- **Query:** `region` (optional): a region id, letters, digits and `-`, at most 64; anything else → `400` `{"error": "invalid region"}`.
- **Limit:** 240 calls per token (`jti`) per minute, shared by every fleet job route.
- **Response:** `200`, `no-store`: `{"ok": true, "region": "<id>"|null}`.

<!-- CF-11: registry snapshot and operations -->
### `GET /api/fleet/jobs/snapshot`

What the Python resolver reads before a run ([design § 7, § 12](../plans/charter-fleet/design.md)). Same gate, auth and limit as `ping` (`server/fleet/jobs.ts` `snapshot`).

- **Query:** `region` (required, as `ping`); `cursor` (optional, `<section>:<last id>`, from the previous page's `next`). Anything else → `400`.
- **Response:** `200`, `no-store`: `{"region", "cursor", "advisor_slugs"?, "operators": [...], "vessels": [...], "reviews": [...], "next": "<cursor>"|null}`. Each page holds one section, in order: operators (500 a page: id, slug, name and business contacts), vessels (100 a page: the resolved columns and stable keys, `waters`, `pinned` (the pinned column names, `["*"]` when unreadable), and their `aliases` and `offerings`), then decided and dismissed reviews (500 a page, with `candidate`, `proposal`, `decision`, but not who decided). The first page also carries `advisor_slugs` (every `advisor_boats.slug`, which a new vessel slug must not take), and each vessel its `sources`: the winning-source record, `{id, field, source_id, confidence, retrieved_at}` of every current scalar fact without its value (CF-17), and `removal_requested` (a boolean, so `plan-agent` and `ingest` skip a boat whose operator asked for removal; #346). Consent, outreach, removal request times, map consent and fact values are never in the snapshot. `next` is `null` after the last page.

### `POST /api/fleet/jobs/registry`

Registry operations from the ingest step ([design § 9](../plans/charter-fleet/design.md#9-ingest-and-refresh); contract in `server/fleet/registry.ts`). Same gate, auth and limit as `ping`.

- **Body:** JSON, at most 1 MB (`413` beyond): `{"region", "run_id", "batch"?: <int>, "ops": [...]}`, at most 500 operations (`413` beyond). Each op is `{"op": "<kind>", ...columns}` with kind `operator.upsert`, `vessel.upsert`, `fact.upsert`, `alias.upsert`, `offering.upsert`, `departure.upsert`, `review.open`, `change.record` or `run.record`; keys are column names, `*_json` keys take a JSON value. Fact, departure, review and change ids are derived when omitted and must match when given (`server/fleet/ids.ts`). `operator.upsert` and `offering.upsert` need `seen_at`. The full contract is in [design § 9](../plans/charter-fleet/design.md#9-ingest-and-refresh) (Operation contract).
- **Validation:** every op before any write: unknown keys, enums, formats, timestamps (ISO-8601 UTC), confidence 0–1, a fact's `source_url` https (`admin:` provenance is written only by the admin API), references (a fact's vessel must be in this region or upserted in the same request; operator, offering and slug checks). One bad op → `400` `{"error": "invalid operations", "errors": [{"index", "op", "error"}]}` (at most 50) and nothing is written.
- **Effect:** upserts keyed on deterministic ids; an update runs only when a stored value changes, so the same batch twice changes no row. Omitted fields keep their value; an older replay never overwrites newer values (each row's recency column). Pinned vessel columns (`pinned_json`) are never overwritten; a vessel with a removal request is never re-listed; `review.open` never reopens or edits a decided or dismissed review, or one of another region; `fact.upsert` may name up to 20 facts it `supersedes` (same vessel and field, not newer). Statements bind at most 100 parameters and run in one D1 batch. Each call writes `fleet_runs` `<run_id>:registry.<batch>` (`ok` or `failed`; the first `ok` is kept).
- **Response:** `200` `{"ok": true, "run_id", "batch", "ops", "changed", "counts": {"<kind>": {"ops", "changed"}}}`.

### `POST /api/fleet/jobs/activity`

What the AIS processor (`fleet-ais.yml`, `src/skippercast/fleet/ais/process.py`) derives ([design § 11](../plans/charter-fleet/design.md#11-ais-processor); contract in `server/fleet/activity.ts`). Same gate, auth and limit as `ping`.

- **Body:** JSON, at most 1 MB (`413` beyond): `{"region", "source"?, "replace"?: [{"mmsi", "from", "to"}], "trips"?, "segments"?, "events"?, "aggregates"?: {"module", "season", "cells", "delete"?, "prune"?}, "processed"?: {"run_id", "counts"}}`; at most 50 windows, 200 trips, 4,000 segments, 2,000 events and 1,000 cells. Rows carry exactly the `fleet_trips`, `fleet_segments`, `fleet_events` and `fleet_aggregates` columns, times as `YYYY-MM-DDTHH:MM:SS.mmmZ`.
- **Validation:** every row before any write: fields, enums, ids derived as design § 5 says, each trip inside a window of its MMSI with the request's source, segments and events of the request's trips, events `basis` `inferred-from-movement`, trip vessels in this region. Anything wrong → `400` `{"error"}` and nothing is written.
- **Effect:** one D1 batch: for each window, this region's and source's trips of that MMSI departing in `[from, to)` are deleted with their segments and events, then the new rows are inserted, so the same request twice leaves the same rows; labels are never touched. `aggregates` upserts cells by id, deletes the listed ids of that season and, with `prune` (a `computed_at`), that module's cells of the season computed at any other time. `processed` sets `job_state` `fleet.ais.<region>.processed` to `{"at", "run_id", "counts"}`.
- **Response:** `200` `{"ok": true, "windows", "changes": {"deleted_trips", "trips", ...}}` (rows changed per statement kind).

### `POST /api/fleet/jobs/heartbeat`

The listener's heartbeat and hourly counters, pushed by the processor. Same gate, auth and limit as `ping`.

- **Body:** `{"region", "heartbeat": {...} | null, "hours": [...], "messages_24h"?}`. `heartbeat` takes only the listener's `source`, `written_at`, `started_at`, `last_message_at`, `connected`, `messages_per_min`, `watched_messages_per_min`, `vessels`, `reconnects`, `dropped`, `queue_depth`, `watch_size` and `git_sha`; at most 72 `hours` rows (`hour` an ISO UTC hour start, `messages`, `watched_messages`, `vessels`, `reconnects`, `max_gap_s`, `dropped`).
- **Effect:** upserts `fleet_ais_hours` by (region, hour); a non-null heartbeat replaces `job_state` `fleet.ais.<region>.heartbeat` (with `received_at` and `messages_24h`); writes an Analytics Engine `fleet_ais` point (heartbeat age, last-message age, 24-hour rows) that `scripts/ops_report.py` reads.
- **Response:** `200` `{"ok": true, "hours", "heartbeat": true|false}`; `400` on any invalid field.

### `GET /api/fleet/jobs/health`

What `fleet-health.yml` (hosted, hourly) reads to open or close the `fleet-ais-stale` issue. Same gate, auth and limit as `ping`.

- **Query:** `region` (required).
- **Response:** `200` `{"region", "checked_at", "stale_after_s": 10800, "stale", "checks": {"heartbeat", "last_message", "processed": {"age_s": <int>|null, "stale"}}}`: ages and booleans only, no counters or listener state. A check is stale when its time is unknown or more than 3 hours old.

<!-- CF-46: the AIS watch list -->
### `GET /api/fleet/jobs/watch`

The region's AIS watch list, which the processor's matcher reads each run ([design § 11, § 12](../plans/charter-fleet/design.md); `server/fleet/watch.ts` `watchList`, CF-46). Same gate, auth and limit as `ping`.

- **Query:** `region` (required, as `ping`; a missing or malformed one → `400` `{"error": "invalid region"}`); `cursor` (optional, the previous page's `next`: an MMSI of 1–9 digits, the first not `0`; an empty value starts at the first page, anything else → `400` `{"error": "invalid cursor"}`); `status` (optional, `candidate`, `watched` or `rejected`; any other value, including an empty one, → `400` `{"error": "invalid status"}`). Without `status` every row of the region is listed.
- **Response:** `200`, `no-store`: `{"region", "rows": [...], "next": "<mmsi>"|null}`. At most 1,000 rows a page, ordered by `mmsi` as a string (so lexical, not numeric) ascending, those after the cursor; `next` is the last returned MMSI when more rows follow, `null` after the last page. Each row is the stored `fleet_ais_watch` row without `region`: `mmsi`, `vessel_id`, `match_method`, `confidence`, `status`, `ais_name`, `ais_call_sign`, `ais_class`, `first_seen_at`, `last_seen_at`, `last_seen_source`, `positions_30d`, `updated_at`. There is no total count, and pages are read one after another, not from a fixed snapshot.
- **Errors:** `400` as above; `503` `{"error": "This service is temporarily unavailable."}` when the database binding is missing; `429` when the shared job budget is spent.

### `POST /api/fleet/jobs/watch`

What the matcher pushes after a run: watch rows and, optionally, the registry operations matching may write (`watchUpdate`). Same gate, auth and limit as `ping`.

- **Body:** JSON, at most 1 MB (`413` `{"error": "body too large"}` beyond): `{"region", "run_id", "rows"?: [...], "ops"?: [...]}`, with no other key. `region` and `run_id` are checked as for [`registry`](#post-apifleetjobsregistry); at most 500 rows and at most 500 operations (`413` `{"error": "at most 500 rows per request"}` or `… operations per request`); at least one of the two must be non-empty (`400` `nothing to do`).
- **Rows** carry exactly `mmsi` (required), `vessel_id` (optional, a 32-character lower-case hex id of a vessel in this region), `match_method` (`fcc-uls`, `call-sign`, `ais-static-name`, `geofence-presence`, `admin` or `schedule-correlation`), `confidence` (a number from 0 to 1), `status` (`candidate`, `watched` or `rejected`), `first_seen_at` and `last_seen_at` (required, `YYYY-MM-DDTHH:MM:SS.mmmZ`, the first not after the last), and optionally `ais_name`, `ais_call_sign`, `ais_class` (`A` or `B`), `last_seen_source` (`aisstream`, `marinecadastre`, `datalastic` or `local-nmea`) and `positions_30d` (an integer, default 0). `region` is taken from the request and `updated_at` is set by the Worker, so a row naming either is refused, as is any unknown field. The full per-field rules are in `checkRow`; they are not copied here.
- **Validation:** every row, and every operation, before any write. An MMSI that appears twice in `rows` is refused. A `watched` row needs a `vessel_id`, a method of `fcc-uls`, `geofence-presence`, `admin` or `schedule-correlation` (`call-sign` and `ais-static-name` stay candidates) and a confidence of at least 0.85, and it is refused when its MMSI is another vessel's registry MMSI or the vessel holds a different one: AIS never overrides the registry. An `admin` row needs its vessel to hold that MMSI with `mmsi` pinned. A named `vessel_id` must exist in the region. Any failure → `400` `{"error": "<message naming rows[i]>"}` and nothing is written.
- **Operations** are limited to `fact.upsert` with method `ais`, source `ais-static` and a field under `ais.` (no `supersedes`), and `review.open` of kind `mmsi`; they are then validated by the same code as `registry`. Anything else, or any invalid operation → `400` `{"error": "invalid operations", "errors": [{"index", "op", "error"}]}` (at most 50).
- **Effect:** rows are upserted on (`region`, `mmsi`) in D1 batches: `first_seen_at` keeps the earliest and `last_seen_at` the latest, and a row is written (and `updated_at` moved) only when a stored value changes, so the same request twice changes nothing. A stored `rejected` row is not moved to `candidate` or `watched` by a non-`admin` row (only an `admin` row whose vessel pins that MMSI can do that); a row whose `status` is still `rejected` does update its other fields. The operations are applied **after** the rows: the two are not one transaction, so a request can have written its rows when the operations then fail with the common `503`.
- **Response:** `200` `{"ok": true, "rows", "changed", "ops"?: {"count", "changed", "counts": {"<kind>": {"ops", "changed"}}}}`; `ops` is present only when operations were sent. Other failures: `400` for a body that is not a JSON object, `503` for an unavailable database or an unexpected storage failure.

<!-- CF-48 and N7: trip labels -->
### `GET /api/fleet/jobs/labels`

The region's labelled trips with their labels, which `python -m skippercast.fleet.ais validate` reads (`server/fleet/admin/labels.ts` `labelledTrips`, CF-48). Same gate, auth and limit as `ping`. This is not the admin trip view: it returns no progress counts and no segments.

- **Query:** `region` (required, as `ping`; → `400` `{"error": "invalid region"}`); `cursor` (optional, the previous page's `next`: 32 lower-case hex characters; empty starts at the first page, anything else → `400` `{"error": "invalid cursor"}`).
- **Response:** `200`, `no-store`: `{"region", "trips": [...], "next": "<trip id>"|null}`. Up to 90 distinct labelled trip ids a page, ascending by id; `next` is the last id when more follow, `null` after the last page. Each trip is `{id, mmsi, vessel_id, source, departed_at, returned_at, status, depart_port_id, orphan, labels}` and each label `{id, started_at, ended_at, label, labeller, basis, created_at}`, by start time. Labels whose trip row is gone (a re-run replaced the trip under another id, so its region is unknown) come as **orphans**: `orphan: true`, the other trip fields `null`, and they appear on every region's pages. No raw positions or tracks are returned.
- **Errors:** `400` as above; `503` when the database binding is missing; `429` when the shared job budget is spent.

### `POST /api/fleet/jobs/labels`

An agent's proposed labels for one trip (N7; `python -m skippercast.fleet.ais label import`; `importAgentLabels`). Same gate, auth and limit as `ping`.

- **Body:** JSON, at most 256 KiB (`413` `{"error": "body too large"}` beyond): `{"trip_id", "labeller": "agent:<name>", "labels": [{"started_at", "ended_at", "label", "basis"}]}`, with no other key at either level (`400` `unknown field …`). `<name>` is 1–64 letters, digits, `.`, `_` or `-`, starting with a letter or digit. At most 200 labels. Each label is an ISO UTC range of at least one minute lying inside the trip's window (departure to return; an open trip ends at its last segment, else at its computation time), a `label` of `in-port`, `transit`, `drift-anchor`, `troll-slow` or `troll-pelagic`, and a `basis` of 2–500 characters after trimming (what the labeller went on).
- **Effect:** in one D1 batch, every label of that `labeller` on the trip is deleted and the new ones inserted, so an empty `labels` list withdraws the agent's labels. Labels of other labellers, including the owner's, stay: once the owner approves an agent's labels they carry the owner's id and a later import never replaces them. The new labels may not overlap each other or any kept label, and the trip may not hold more than 200 labels in all. A label is a proposal, never a confirmed fishing claim.
- **Response:** `200` `{"ok": true, "trip_id", "labeller", "replaced": <labels deleted>, "labels": <labels inserted>}`. Errors: `400` `{"error"}` for a malformed body, `labeller must be agent:<name>`, `labels must be an array`, more than 200 labels or any invalid label (`labels[i]: …`); `404` `trip not found`; `409` an overlap (`labels[i]: overlaps the … label …`) or more than 200 labels with the others kept; `503` when the database binding is missing.

### Cron (`scheduled`)

Not an HTTP route. Every 15 minutes on Cloudflare (`wrangler.jsonc` `triggers`), `server/watchdog.ts` reads `conditions/latest.json` (R2, then GitHub) and, if it is more than 45 minutes old and no `live-conditions.yml` run is queued or in progress, dispatches one with the `GITHUB_TOKEN` Worker secret (`dispatchWorkflow`, which TA-M1 exported; the advisor's cron uses it to dispatch `advisor-media.yml` while media or graphics are pending, at most once per 15 minutes).

## Accounts / passkeys

SkipperCast accounts are passkeys (WebAuthn) and a first-party session cookie: no passwords, email, OAuth or recovery flow (`server/auth.ts`, `server/routes/auth.ts`, [ADR 0006](adr/0006-passkey-accounts-stripe-later.md)). Billing is not part of this API. The `/api/auth/*` routes run before the private gate and answer even to anonymous callers. Examples below use typed placeholders only; a real registration or assertion is browser authenticator output and is not shown.

**Gate for every `/api/auth/*` call**, in this order:

1. The path must start with `/api/auth/`. `/api/auth` without a trailing slash is not this handler: it is an ordinary private path and gets the private gate's answer.
2. Accounts must be enabled (`IDENTITY_PROVIDER` is `skippercast`, see Conventions); otherwise `404` `{"error": "Accounts are not available on this site", "signIn": null}`, before anything is counted.
3. Every call, `GET` included, counts against **20 requests per minute per IP** (a D1 budget separate from the private 30-a-minute budget); over it `429` `{"error": "Please try again shortly"}`.
4. Every non-`GET` needs an allowed `Origin` (`deployments/production.json` `allowed_origins` plus `EXTRA_ORIGINS`), else `400` `origin rejected`.
5. The relying party is the request's own host: its RP ID is the request hostname and the expected origin the request origin, and that origin must be an allowed one, else `400` `this address cannot use accounts` (also for `GET`, and for logout).
6. Then the route below. A path or method that matches no entry answers `404` `{"error": "Not found"}`.

An exception caught inside registration or login verification (a verifier error, or a failed challenge-store read in the `expectedChallenge` callback) becomes a fixed `400` auth error with its fixed text, never a `401`. The generic `503` is only for a dependency failure that escapes those catches, such as a missing database binding or an auth-budget failure. Bodies, where a route reads one, are JSON objects of at most 8,192 bytes (`400` `body too large` or `invalid JSON body`); `login/options`, `logout` and `passkeys/options` read no body, so a client may send `{}` or nothing. Responses carry the usual `no-store` and security headers and, on errors, `request_id`.

| Method and path | Body | Success | Specific errors and limits |
| --- | --- | --- | --- |
| `POST /api/auth/register/options` | JSON object `{display_name?}` (an empty `{}` is fine; no body at all is `400` `invalid empty body`) | `200` WebAuthn registration options (`PublicKeyCredentialCreationOptionsJSON`): resident key and user verification required, attestation `none`, a random provisional user handle, a 5-minute timeout and a fresh challenge | `400` `invalid name` when `display_name` is not a string, `null` or empty. The name has control characters removed, is trimmed and cut to 60 UTF-16 code units; an empty result means no name. This creates no account and no session: it only stores a `register` challenge bound to the provisional user handle. The name is not kept from this call; `register/verify` reads its own |
| `POST /api/auth/register/verify` | JSON `{response: <RegistrationResponseJSON>, display_name?}` — the browser's credential, wrapped under `response` | `201` `{"signedIn": true, "user": {"id": "<user id>", "display_name": <string or null>}}` plus the session cookie. Only this success creates the user and passkey (one batch), ends the session this browser already had and starts a new one | `400` `invalid passkey response` (malformed or missing `response`), `invalid name`, `this sign-in request expired; try again` (no live `register` challenge), `passkey could not be verified` (anything else the verifier refuses, including user verification missing or the wrong origin or RP ID), `this passkey is already registered; sign in instead` |
| `POST /api/auth/login/options` | none read (the client may send `{}`) | `200` WebAuthn authentication options: discoverable credential, user verification required, 5-minute timeout, fresh challenge | Stores a `login` challenge bound to no user. Not signed in yet |
| `POST /api/auth/login/verify` | JSON `{response: <AuthenticationResponseJSON>}` | `200` `{"signedIn": true, "user": {"id": "<user id>", "display_name": <string or null>}}` plus the session cookie. Updates the passkey's counter and `last_used_at`, ends this browser's previous session and starts a new one | `400` `invalid passkey response` (malformed `response`); `this sign-in request expired; try again` (a known passkey but no live `login` challenge); `that passkey is not recognised here` for an unknown credential, a wrong origin or RP ID, missing user verification, a signature or counter failure. These are fixed messages, but they do distinguish a known credential from an unknown one: with a spent or missing `login` challenge, a known credential gets `this sign-in request expired; try again` while an unknown credential gets `that passkey is not recognised here`, so a caller who replays a spent challenge can tell whether a credential ID is registered |
| `POST /api/auth/logout` | none read | `200` `{"signedIn": false}` plus a cookie that clears `__Host-sc_session` | Works signed out too. Ends only the current session, not the account's other sessions. Still passes the gate above (Origin, 20-a-minute budget, allowed relying party) |
| `GET /api/auth/passkeys` | none | `200` `{"passkeys": [{"id", "transports", "created_at", "last_used_at"}]}` — oldest first; `transports` is a decoded array; no public key or counter | `401` as below when signed out |
| `POST /api/auth/passkeys/options` | none read | `200` WebAuthn registration options for the signed-in user, excluding the credentials they already have; stores an `add` challenge bound to them | `409` `{"error": "Limit of 10 passkeys"}` when they already have 10; `401` as below |
| `POST /api/auth/passkeys` | JSON `{response: <RegistrationResponseJSON>}` | `201` `{"added": true, "id": "<passkey id>"}` | `400` as `register/verify` for a bad or expired response, `passkey could not be verified` when the `add` challenge belongs to another user, `this passkey is already registered` for a duplicate; `409` `Limit of 10 passkeys`, checked again at this step (the cap is not atomic across concurrent additions); `401` as below |
| `DELETE /api/auth/passkeys` | JSON `{id: "<passkey id>"}` | `200` `{"removed": true}` | `400` `passkey id required` unless `id` is a non-empty string of at most 1,400 characters; `404` `{"error": "Not found"}` for a missing id and for another account's id alike; `409` `This is your only passkey. Add another before removing it, or delete the account.` for the last one. The count is re-checked inside the delete statement, so two parallel removals cannot delete the last passkey; `401` as below |
| `GET /api/auth/sessions` | none | `200` `{"sessions": [{"current", "created_at", "expires_at", "device"}]}` — this account's unexpired sessions only (expired rows are not listed or pruned here), oldest first. `current` is `true` for the session making the request; `created_at` is the stored ISO string, `expires_at` integer epoch seconds; `device` is a label from the stored user agent through a fixed table: `Edge on Windows`; `Firefox on Windows`/`Mac`/`Linux`; `Chrome on Windows`/`Mac`/`Android` (`Chrome/` or `CriOS/`, not Edge); `Safari on iPhone`/`iPad`/`Mac`; anything else, including an empty or truncated agent (stored agents are cut to 80 characters), is `Unknown browser`. No raw user agent, owner id, session id or hash is returned. Example: `{"sessions": [{"current": true, "created_at": "2026-11-01T08:00:00.000Z", "expires_at": 1796112000, "device": "Safari on iPhone"}]}` | `401` as below when signed out |
| `POST /api/auth/sessions/end-others` | none read | `200` `{"ended": <n>}` — one `DELETE` of every session row of this account except the current one, so the current session and its cookie are unchanged and other accounts are never touched. `ended` counts session rows (expired rows awaiting pruning included), not physical devices; `0` when only the current session exists. Passkeys and saved data are untouched. The ordinary sliding renewal of the current session still applies | `401` as below when signed out |

**Session management needs a session.** `GET /api/auth/sessions` and `POST /api/auth/sessions/end-others` answer `401` `{"error": "Sign in to manage sessions", "signIn": "/#account"}` without one, after the gate above; other methods and paths under `/api/auth/sessions` answer the generic `404`. Removing a passkey does not end existing sessions: a lost phone stays signed in until you end it here, sign out on it, or it idles for 30 days. `GET /api/privacy` is unchanged.

**Passkey management needs a session.** Any path starting `/api/auth/passkeys` (including unknown ones) answers `401` `{"error": "Sign in to manage passkeys", "signIn": "/#account"}` when there is no session, after the gate above. This is neither the private data gate's `401` nor the accounts-off `404`.

**Challenges.** A challenge is created by an options call with one of three kinds (`register`, `login`, `add`) and lives **300 seconds**. It is single-use: verification deletes it (`DELETE … RETURNING`) whether or not it then matches, so a wrong-kind or expired challenge is spent and cannot be tried again; start over with a new options call. A malformed `response` is refused before any challenge is read and so does not spend one. Login with an unknown credential still tries to spend its challenge. Verification requires user verification, the expected RP ID and the expected origin. Only the 400 messages named above are returned, never verifier internals.

### Session cookie

A successful `register/verify` or `login/verify` sets one cookie:

```
Set-Cookie: __Host-sc_session=<opaque token>; Max-Age=2592000; Path=/; Secure; HttpOnly; SameSite=Lax
```

- No `Domain` attribute (the `__Host-` prefix requires `Secure`, `Path=/` and no `Domain`). The token is 32 random bytes in base64url (43 characters); the server stores only its SHA-256 and a user-agent label of at most 80 printable characters, never the token. Any cookie value that is not 43 base64url characters is ignored as anonymous.
- The session lasts **30 days**. Whenever identity is resolved for a request with a live session that has **strictly fewer than 15 days** left, the expiry is moved to 30 days from now and the response carries the cookie again (a response that already sets its own cookie, such as logout, keeps that one). An expired session is deleted when it is next presented and resolves to anonymous. A request that does not need identity, or carries no session cookie, does no lookup and no renewal.
- `logout` and `DELETE /api/privacy` send the same cookie with an empty value and `Max-Age=0`.
- This is unrelated to the Text Advisor's `sc_adv` web-chat cookie.

## Private API (signed in)

All routes below answer `401` when the caller has no identity. The text depends on the provider rule (`server/middleware/auth.ts`: `signInPath` of `IDENTITY_PROVIDER`), not on where the Worker is hosted. With `skippercast`:

```json
{"error":"Sign in to save private trips or feedback","signIn":"/#account"}
```

With any other value (`none`, absent, empty, `chatgpt-sites`, unrecognised): `{"error":"Accounts are not available on this site yet","signIn":null}`. These two differ from the `/api/auth/*` answers: `404` `Accounts are not available on this site` (no "yet") when accounts are off, and `401` `Sign in to manage passkeys` for passkey management (see [Accounts / passkeys](#accounts--passkeys)). Every query is scoped to the caller's owner id. Non-GET routes need an allowed `Origin` and the 30-per-minute budget (see Conventions).

| Method and path | Body | Success | Specific errors and limits |
| --- | --- | --- | --- |
| `GET /api/trips` | — | `200` `{"trips": [...], "events": [...]}` — up to 50 trips (newest date first) and 30 alert events `{id, trip_id, kind, message, status, created_at}` | — |
| `POST /api/trips` | `{region, point, species, date, start_hour, end_hour, wind_limit, gust_limit, sea_limit}` plus the optional planner fields `launch_point` (slug), `targets` (1–3 region species; `species` is always first), `plan` (`{spots[≤12]: {id, name, lat, lon, order, notes, depth_ft}, legs[≤13]: {from, to, nm, minutes}, window: {depart, return_by, hours[]}, exports[≤20]: {format, sha256, exported_at}}`, 16 KB cap; the request body for these two routes may be 24 KB) and `status` (`draft`, `planned` (default), `done`, `cancelled`) | `201` `{"id": "<uuid>"}` | `400` `unknown area or species`, `date must be within the next seven days` (date in the region's time zone, today to +7 days), `invalid <field>` (hours 0–22 / 1–23, wind 1–30 kn, gust 1–40 kn, seas 0.5–10 ft), `invalid window or thresholds` (end after start, integer hours, gust ≥ wind); `409` `Limit of 20 active trips` |
| `PATCH /api/trips` | `{"id", launch_point?, targets?, plan?, status?}` — only the given planner fields change; the alert fields are fixed at save time | `200` the trip's planner fields `{id, launch_point, targets, plan, status}` | `400` as for `POST` plus `invalid launch point`, `targets must be one to 3 species of the region`, `targets repeat a species`, `invalid status`, `too many spots (limit 12)`, `plan too large`; `404` `Not found` (another owner's trip too) |
| `DELETE /api/trips` | `{"id": "<trip id>"}` | `200` `{"deleted": true}` (also when nothing matched) | `400` `trip id required` |
| `POST /api/events/ack` | `{"id": "<event id>"}` | `200` `{"read": true}`; a `final`/`missed-final` event also closes its trip | `400` `event id required` unless the id is 64 lowercase hex characters; `404` `Not found` |
| `POST /api/subscription` | Web Push subscription `{endpoint, keys: {p256dh, auth}}` | `200` `{"enabled": true}` | `400` `subscription missing`, `push endpoint rejected` (HTTPS only, no port or credentials, ≤ 2,000 chars, host `fcm.googleapis.com`, `updates.push.services.mozilla.com`, `web.push.apple.com` or `*.notify.windows.com`), `push keys invalid`; `409` `Subscription belongs to another signed-in user`, `Limit of five notification devices. Stop notifications on another device to free a slot, or use Stop on all devices here.` |
| `DELETE /api/subscription` | exactly one of `{"endpoint": "<this device's endpoint>"}` (1–2,000 characters, not trimmed) or `{"all": true}` | `200` `{"enabled": false}` — `endpoint` removes only that device; `all` removes all the caller's devices (also when there are none) | `400` for no body, `{}`, an endpoint-less body or any other missing scope (`Send this device's endpoint or all: true. Update this page before stopping notifications.`; nothing is deleted, so an older cached page asks for a refresh instead of stopping every device), both keys, `all` other than `true`, unknown keys, an invalid endpoint; `404` `Not found` when no device of the caller has that endpoint (another owner's endpoint answers the same) |
| `POST /api/subscription/status` | `{"endpoint": "<this device's endpoint>"}` only (1–2,000 characters; in the body so the endpoint stays out of URLs and request logs) | `200` `{"registered": true}` only when the caller holds that endpoint's row (the id POST and DELETE use); `{"registered": false}` alike for an absent endpoint and another owner's, so it tells nothing about other accounts. Reads only; writes nothing | `400` `invalid endpoint`, `Only endpoint can be sent.`; signed out is refused by the private gate |
| `POST /api/comfort` | `{region, rating (1–10 integer), phase ("outbound"\|"fishing"\|"return"), wind?, sea?, period?, heading?, point?}` | `201` `{"saved": true}` | `400` `invalid feedback`, `invalid feedback context` (wind ≤ 200, sea ≤ 100, period ≤ 60, heading ≤ 360, all ≥ 0), `invalid feedback point` |
| `GET /api/comfort` | — | `200` `{"feedback": [...]}` — up to 100, newest first; `context` is a JSON string | — |
| `GET /api/catch-log` | — ; optional single `cursor` query value | `200` `{"entries": [...]}` — at most 200 rows (`LIST_LIMIT`), newest `started_at` first, then ascending `id`. Header `X-SC-Catch-Log-Has-More` is `true` or `false`; `X-SC-Catch-Log-Next-Cursor` is present only when more rows remain. Pass the cursor back unchanged | `400` `invalid catch-log cursor` for an empty, repeated, malformed or over-512-character `cursor`. The cursor is an opaque position, not a capability: the query is always bound to the caller. No total count and no snapshot guarantee between pages |
| `POST /api/catch-log` | `{started_at, outcome, ended_at?, trip_id?, method?, species?, count?, lat?, lon?, note?}` (see [catch-log and saved-spot notes](#catch-log-and-saved-spot-notes)); body at most 8,096 bytes | `201` `{id, owner, trip_id, started_at, ended_at, method, species, outcome, count, lat, lon, note, created_at}` | `400` with the field message (`started_at is required`, `started_at must be an ISO date and time with a zone`, `ended_at is before started_at`, `outcome must be fish, blank or unknown`, `count must be a whole number from 0 to 9999`, `a fish entry needs a count of at least 1`, `a blank entry has a count of 0`, text-limit and coordinate errors); `404` `Not found` when `trip_id` is not the caller's trip. Unknown keys are ignored, not rejected |
| `GET /api/catch-log/:id` | — | `200` the stored row itself (no `entry` wrapper) | `404` `Not found` for a missing id and for another account's id alike |
| `PATCH /api/catch-log/:id` | any of `trip_id, started_at, ended_at, method, species, outcome, count, lat, lon, note` (see [catch-log and saved-spot notes](#catch-log-and-saved-spot-notes)); body at most 8,096 bytes | `200` the updated row. Omitted fields keep their stored value; the merged result is validated as a whole. `{}` re-validates and returns the stored row. A text field set to `null` or blank text is cleared; `ended_at` clears only with `null`; `lat` and `lon` must both be present (both `null` clears them); changing `fish` to `blank` or `unknown` needs `count: 0`, changing to `fish` needs a count of at least 1 | `404` `Not found` for a missing or another account's id, answered before the body is read, and for a `trip_id` that is not the caller's; `400` for any other key (`only trip_id, started_at, ended_at, method, species, outcome, count, lat, lon, note can be changed`), `coordinates_incomplete` and the same validation messages as `POST`; `409` `This entry changed while you were editing it. Reload it and try again.` when the row was saved by someone else between the read and the write (the write is compare-and-swap; no row data is returned) |
| `DELETE /api/catch-log/:id` | — | `200` `{"deleted": true}` | `404` `Not found` for a missing or another account's id |
| `GET /api/spots` | — | `200` `{"spots": [...]}` — at most 100 (`MAX_SPOTS`), newest `created_at` first then `id`; no cursor | — |
| `POST /api/spots` | `{lat, lon, name?, note?}`; body at most 8,096 bytes (see [catch-log and saved-spot notes](#catch-log-and-saved-spot-notes)) | `201` `{id, owner, name, lat, lon, note, created_at}`; a missing or `null` name is stored as `""`, a missing, `null` or blank note as `null` | `400` `coordinates_required: send latitude and longitude`, `coordinates_incomplete`, `coordinates_not_finite`, `coordinates_out_of_range`, `name must be text of at most 80 characters`, `note must be text of at most 1000 characters`; `400` `you can keep at most 100 saved spots; remove one first` when the caller already has 100 (a 400, not 409; nothing is truncated; the count check and insert are one statement) |
| `GET /api/spots/:id` | — | `200` the stored row `{id, owner, name, lat, lon, note, created_at}` | `404` `Not found` for a missing or another account's id |
| `PATCH /api/spots/:id` | `{name?, note?}`; body at most 8,096 bytes | `200` the full updated row. Only the keys sent are written; `name: null` clears to `""`, `note: null` or blank clears to `null` | `404` `Not found` for a missing or another account's id, answered before the body is read; `400` `send name and/or note` for `{}`, `lat cannot be changed; save a new spot for a different position` (or `lon`) for any `lat` or `lon` key even if unchanged or `null`, `only name and note can be changed` for other keys, and the `POST` text-limit messages |
| `DELETE /api/spots/:id` | — | `200` `{"deleted": true}` | `404` `Not found` for a missing or another account's id |
| `GET /api/privacy` | — | `200` `{account, trips, feedback, events, devices, catch_log, saved_spots}` — everything stored for the caller, unpaginated (the catch-log 200-row limit does not apply). `account` is `{user, passkeys, sessions}`: `user` is `{id, created_at, display_name}` or `null`; passkeys `{id, transports, created_at, last_used_at}` (`transports` as stored); sessions `{created_at, expires_at, user_agent}` — no public keys, signature counters or session tokens. `events` are `{message, created_at, status}`. `devices` are `{push_service, created_at}` — the push host (`unknown` when the stored endpoint cannot be parsed) and creation date (`null` when absent), never the endpoint path or keys. `catch_log` (ordered `started_at, id`) and `saved_spots` (ordered `created_at, id`) are the full private rows with coordinates and notes | — |
| `DELETE /api/privacy` | — (no body needed) | `200` `{"deleted": true, "signedIn": false}` with a `Set-Cookie` that clears `__Host-sc_session` (`Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax`). Deletes the caller's trips, subscriptions, alert events, their delivery receipts, comfort feedback, catch log, saved spots, passkeys, sessions, sign-in challenges bound to the caller, and the user record itself, so the caller is signed out. Other identity domains' records (advisor, fleet) are not part of this route | — |
| `POST /api/boat/lookup` | `{"query": "<make model year>"}` (3–120 characters after whitespace folding) | `200` `{query, boat, confidence, estimated, notes, sources, looked_up_at}`; `cached: true` when served from the 30-day lookup cache | `400` `invalid boat name`; `429` after 20 lookups per owner per UTC day, or when the global daily cap is reached (default 500); `502` when the lookup fails; `503` when the kill switch `BOAT_LOOKUP_ENABLED=false` is set or `ANTHROPIC_API_KEY` is not set |

### Catch-log and saved-spot notes

Shared by the `/api/catch-log` and `/api/spots` rows above; everything here is private to the signed-in owner and feeds no public route, feed, score or aggregate.

- **Gates.** These routes sit behind the sign-in gate. `POST`, `PATCH` and `DELETE` need an allowed `Origin` and the 30-per-minute budget; the usual `400` (invalid JSON object), `429` and generic `503` responses apply as under Conventions.
- **Catch-log fields.** `started_at` (required) and `ended_at` are ISO date-times with a zone, stored as UTC; the written day must exist and the hour be 00–23, and `ended_at` may not precede `started_at`. `outcome` is `fish`, `blank` or `unknown`. `count` is an integer 0–9999, default 0; `fish` needs at least 1 and the other outcomes need 0. `trip_id` is at most 64 characters and must be one of the caller's trips. `method` is at most 40 characters, `species` 60, `note` 1,000 (Unicode code points); blank text is stored as `null`. `lat` and `lon` go together or not at all.
- **Coordinates** (both routes): finite numbers, latitude strictly between -90 and 90, longitude strictly between -180 and 180.
- **Spot fields.** `name` is at most 80 UTF-16 code units (an astral character counts as two), `note` at most 1,000 Unicode code points. A spot's position never changes; save a new spot instead.
- **Body size.** The `POST` and `PATCH` bodies for both routes are capped at 8,096 bytes, slightly below the default 8,192.
- **Another account's id** answers exactly what an id that never existed answers: `404` `Not found`.

Example `GET /api/trips`:

```json
{"trips":[{"id":"e3a9a976-d65f-4ab4-af0e-d7fe7f205b1b","owner":"alice","region":"morro-bay","point":"north","species":"reef","date":"2026-09-29","start_hour":7,"end_hour":13,"wind_limit":8,"gust_limit":12,"sea_limit":3,"enabled":1,"created_at":"2026-09-29T04:44:01.204Z","last_assessment":null,"final_delivered_at":null}],"events":[]}
```

The boat lookup sends the query to Anthropic's Messages API with web search (`server/boat-lookup.ts`); `boat` holds the fields of the manual boat form (`loa_ft`, `beam_ft`, `hull`, `layout`, …) validated by `normalizeBoat` in `dist/boat-handling.js`, and `sources` up to six cited URLs.

The global daily cap (`BOAT_LOOKUP_GLOBAL_DAILY_LIMIT`, default 500; over it `429` `AI boat lookup is busy today; try again tomorrow or enter details by hand.`), the kill switch (`BOAT_LOOKUP_ENABLED=false` → `503` `AI boat lookup is switched off for now; enter your boat details by hand.`), the model id from `BOAT_AI_MODEL` (`server/boat-lookup.ts` `lookupSettings`) and a usage log line per lookup (counts only, never the query or owner) are all implemented. `POST /api/events/ack` validates its id as 64 lowercase hex characters (`400` `event id required`) and trip ids in `PATCH`/`DELETE /api/trips` are at most 64 characters (`400` `trip id required`).

## Text Advisor admin (signed in, admin role)

The admin app and its API ([08 · Admin](../plans/text-advisor/08-website.md), `server/routes/admin.ts`, mounted after the private routes). Every route needs a passkey session **and** `users.role='admin'` (`server/middleware/admin.ts` `requireAdmin`), and its feature switched on. The page paths (`/admin`, `/admin.html`) open when either the Text Advisor or the charter fleet (`FLEET_ENABLED=true`) is on; the advisor's `/api/admin/*` routes below still need `TEXT_ADVISOR_ENABLED`, and `/api/admin/fleet/*` needs `FLEET_ENABLED`. A signed-in caller without the role, or anyone while the feature is off, gets the same `404` as a path that does not exist (`{"error": "Not found"}` under `/api/`, a plain-text `Not found` for the page paths), so the admin's existence is not confirmed. Under `/api/` a signed-out caller gets the private gate's `401` like any unknown `/api/` path. `POST`s need an allowed `Origin` and count against the 30-a-minute budget (requireUser).

| Method and path | Body / query | Success | Errors |
| --- | --- | --- | --- |
| `GET /admin` | — | `302` to `/admin.html` | `404` |
| `GET /admin.html` | — | `200` the admin shell (`dist/admin.html`, `Cache-Control: no-store`). The built file also exists at its hashed name like every page; it holds no data. | `404` |
| `GET /api/admin/reviews` | `status` (`open` default, `approved`, `edited`, `rejected`, `all`), `kind` (`media`, `report`, `post`, `skipper`, `conversation`, `rule`), `cursor` (the previous page's `next`) | `200` `{"items": [...], "next": "<cursor>"\|null}`: at most 50 review items, newest `opened_at` first, each `{id, kind, ref_id, reason, status, note, opened_at, decided_at, detail}` | `400` `unknown status` / `unknown kind` |
| `POST /api/admin/reviews/<id>` | `{"decision": "approve"\|"edit"\|"reject", "patch"?, "note"?, "reply"?}` (16 KB; `reply` alone means approve) | `200` `{"review": {...}, "sends": n}` (`"held": "replies-off"` when `ADVISOR_REPLIES_ENABLED` is off and a text was owed); a review already decided: `200` `{"review": {...}, "repeated": true}` and nothing changes | `400` a decision the kind does not take, an edit without fields; `404` unknown review; `409` the contact stopped or blocked, replies off for a reply, a report date the boat already has |
| `GET /api/admin/media/<id>` | `v=original` (optional) | `200` the bytes from `ADVISOR_MEDIA`: `advisor/derived/<id>/thumb.jpg`, else `public.jpg`, else the stored original when it is JPEG, PNG, GIF or WebP and was not stored sideways (`orientation` 2-8, TA-M1's orientation fix); with `v=original`, the stored original whatever its type. `Cache-Control: private, no-store`, `Content-Disposition: inline`. | `404` |
| `GET /api/admin/health` | — | `200` (below) | — |
| `POST /api/admin/meta/subscribe` | — | `200` `{"subscribed": true\|false, "fields": "messages,comments"}`: `POST /<ig-user-id>/subscribed_apps` with `subscribed_fields=messages,comments`, one try (TA-S6, the Health view's "Subscribe webhooks") | `409` Meta secrets missing; `502` `{"error": "meta subscribed_apps failed: HTTP <status> code <code>"}` |
| `GET /api/admin/boats` | — | `200` `{"boats": [...]}`: up to 500, pending first, then verified, then rejected, newest first; each `{id, slug, name, landing, port, region, instagram, booking_url, phone_public, status, verified_at, created_at, owner, last_report_date, reports_30d, posts, consent, consent_photos_at, consent_revoked_at, consent_note, crew, review_open}` (TA-W3) | — |
| `POST /api/admin/boats/<id>` | `{"fields"?: {name, port, landing, instagram, booking_url, phone_public}, "status"?: "verified"\|"rejected", "consent_note"?: text\|null}` (8 KB) | `200` `{"boat": {...}, "sends": n}` (`"held": "replies-off"` when a text was owed with replies off) | `400` a field the registration's parsers refuse, an unknown field or status; `404` unknown boat; `409` from the review decision |
| `POST /api/admin/boats/<id>/crew/<contact id>/remove` | — | `200` `{"boat": {...}}` | `404` no such crew link |
| `POST /api/admin/boats/invite` | `{"phone": "...", "boat_name"?: "...", "language"?: "en"\|"es"}` (4 KB) | `200` `{"contact_id": "...", "sends": n, "created": bool}`; the number is never returned or logged | `400` not a US number, a bad boat name; `409` a stopped or blocked contact, an existing boat owner, replies off, more than 20 invites today; `503` no `ADVISOR_PHONE_KEY` |
| `GET /api/admin/contacts/<id>` | — | `200` `{"contact": {...}, "boats": [...], "messages": [...], "export": "/api/admin/contacts/<id>/export"}` | `404` |
| `GET /api/admin/contacts/<id>/export` | — | `200` the contact's data (`contacts.ts` `exportContact`) as `application/json` with `Content-Disposition: attachment`, `Cache-Control: private, no-store` | `404` |
| `GET /api/admin/funnel` | `days` (`7` default, or `30`) | `200` (below) | `400` any other `days` |
| `GET /api/admin/rules` | `jurisdiction` (a `jurisdictions/*.json` id), `status` (`active`, `review`, `retired`, or `due`: in review or past `review_due`) | `200` `{"rules": [...], "today": "YYYY-MM-DD", "jurisdictions": [...], "regions": [{id, jurisdiction}], "species": [{key, name}]}`; each rule is the `advisor_rules` row plus `due` (TA-A4) | `400` unknown jurisdiction or status |
| `POST /api/admin/rules` | `{"jurisdiction", "region"?: "*"\|<region of it>, "species_key", "species_label", "source_name", "source_url", ...content}` (16 KB) | `200` `{"rule": {...}}`, `status` `active` (the admin reviewed it) | `400` a field below refuses it; `409` that row exists (same id as the importer's) |
| `POST /api/admin/rules/<id>` | content fields only (`{}` confirms the row unchanged) | `200` `{"rule": {...}}` with `reviewed_at` now, `review_due` the sooner of 90 days and the season's end, `status` `active`, `updated_by` the admin | `400` an identity or status field, a bad value; `404` |
| `POST /api/admin/rules/<id>/retire` | — | `200` `{"rule": {...}}`, `status` `retired` (never quoted again) | `404` |
| `GET /api/admin/posts` | `status` (`all` default, or `draft`, `approved`, `scheduled`, `publishing`, `posted`, `partial`, `failed`, `rejected`), `kind` (`photo`, `carousel`, `reel`, `story`, `daily`, `roundup`), `cursor` | `200` `{"posts": [...], "next": "<cursor>"\|null}`: at most 50, newest change first, each the `post` card below (TA-S1). A draft is decided through its `review_id` with `POST /api/admin/reviews/<id>`. | `400` `unknown status` / `unknown kind` |
| `POST /api/admin/posts/<id>/publish` | — | `200` `{"post": {...}, "outcome": "posted"\|"partial"\|"failed"\|"pending"\|"deferred"\|"quota"\|"held", "error"?}`: an `approved` post published now, its `scheduled_for` cleared (TA-S2, `social/publish.ts`); `pending` while Instagram processes a video (the cron finishes it) | `404`; `409` not `approved`, `ADVISOR_SOCIAL_ENABLED` off, Meta secrets missing, or being published right now |
| `POST /api/admin/posts/<id>/schedule` | `{"scheduled_for": "<ISO>"\|null}` (1 KB) | `200` `{"post": {...}}`; null clears the time: the calendar gives it the next free slot of its kind (TA-S4), or, for a kind with no calendar slot, it is posted on the next tick | `400` missing, unreadable, past or more than 60 days ahead; `404`; `409` not `approved` |
| `GET /api/admin/posts/calendar` | `start` (`YYYY-MM-DD`, optional: any day of the week; default this week) | `200` `{"tz", "start", "end", "days": [{"date", "weekday", "slots": [{"slot", "kind", "region", "time", "at", "capacity", "posts": [...], "empty", "past"}], "others": [...]}]}`: the 7 days from that Monday in the calendar's zone, every `catalog/advisor/calendar.json` slot instance with the posts holding its time (`empty` while fewer than its capacity) and the other scheduled or posted posts of each day; a post is `{id, kind, region, status, at, scheduled_for, posted_at, boat, summary}` (TA-S4, `social/calendar.ts calendarWeek`) | `400` `start must be YYYY-MM-DD` |
| `GET /api/admin/posts/<id>/graphics/<name>` | — | `200` `image/jpeg`: one of the post's generated graphics in any status, for the admin's preview (`Cache-Control: private, no-store`) | `404` |
| `POST /api/admin/posts/<id>/retry` | — | `200` `{"post": {...}, "outcome", "error"?}`: a `partial` or `failed` post again, only the surfaces without a stored id | `404`; `409` not `partial`/`failed`, publishing off or not configured |
| `POST /api/admin/contacts/<id>/block` | `{"blocked": true\|false}` | `200` `{"status": "blocked"\|"active"\|"stopped"}`; unblocking restores the status before the block | `400` not a boolean; `404` |

`detail` by kind (`server/advisor/admin/queue.ts`; `null` when the referenced row is gone). Contacts appear as `{id, channel, language, display_name, role, status}` only; no number or hash leaves the server.

- `media`: `{media: {id, kind, mime, bytes, width, height, has_person, publish_state, credit, created_at, stored, thumb, original, labels, boat, hold}}`; `hold` is why a video cannot be approved yet (its location metadata not removed: waiting for the media job, or the job gave up, for example without ffmpeg), null otherwise, and approving or editing it answers `409` with that text; `thumb`/`original` are the media route above; `labels` are the classify result's `kind`, `kind_confidence`, `has_person`, `person_confidence`, `has_fish`, `text_present`, `nsfw`, `provider` (and the top three fish-ID candidates when present).
- `report`: `{report: {id, port, region, report_date, trip_type, anglers, counts, notes, source, status, verified, version, edits, published_at, media, boat: {id, name, slug, status}}}`.
- `skipper`: `{boat: {id, slug, name, landing, port, region, instagram, booking_url, phone_public, status, verified_at, consent_photos_at, consent_revoked_at, created_at}, contact, messages}`; `messages` are the bodies of the owner's first three inbound texts.
- `conversation`: `{contact, flagged_message, messages}`; `messages` are the contact's last six, oldest first, `{direction, body, created_at, team}` (`team`: sent from the queue).
- `post` (TA-S1, `server/advisor/admin/posts.ts`): `{post: {id, kind, region, status, caption, caption_stats: {length, hashtags, mentions}, targets, allowed_targets, collaborators, user_tags, scheduled_for, error, created_by, approved_by, approved_at, posted_at, created_at, updated_at, boat: {id, name, slug, status, instagram}|null, media: [{id, kind, has_person, publish_state, credit, review_open, thumb, original}], review_id, hold}}`; `review_id` is the open `post` review (null once decided) and `hold` why approval is refused now (null when it is not). TA-S4 adds `graphics`: the admin preview URLs of a daily card, roundup cover and slides or Story card (`[]` for other posts and before the job renders them); `hold` also names a graphic still being rendered or that failed, and a roundup photo's boat that is not verified or has no photo consent. TA-S2 adds `ig_media_id`, `fb_post_id`, `fb_story_id` and `collab_status` (TA-S3: null, `invited`, `accepted` or `declined`, from Meta's collaborator invite status). TA-S7 adds `stats`: `null` unless the post is `posted` or `partial`, else `{instagram, facebook, chats}` where each surface is `null` or its latest insights row `{views, reach, likes, comments, saved, shares, follows, profile_visits, link_taps, day, fetched_at, notes}` and `chats` counts contacts whose first message came from the post's link.
- `rule`: `{rule: {...the advisor_rules row}, summary: null}` when `ref_id` is a rule id; for a change-watch review (reason `rule_source_changed`, `ref_id` `<jurisdiction>:<16 hex>`, TA-A4) `{rule: null, summary: {jurisdiction, regions, checked_at, sources: [{id, name, url, content_sha256, approved_sha256}], marked_at, rows_marked, rules: {review, active}}}`: the changed pages (links only on the jurisdiction's authority hosts), their new and reviewed fingerprints, and the jurisdiction's rows by status now.

Rules (TA-A4, `server/advisor/admin/rules.ts`): content fields are `species_label` (1–80), `size_min_in`, `size_max_in` (0–120), `bag_limit` (whole, 0–100), `depth_limit_ft` (whole, 0–2,000), `season_open` and `season_close` (`MM-DD` or `YYYY-MM-DD`, both or neither: neither is year-round), `bag_notes`, `area_notes`, `gear_notes` (≤ 500), `source_name` (≤ 120) and `source_url` (https on one of the jurisdiction's `authority_hosts`); `null` or empty clears an optional one. `jurisdiction`, `region` (`*` or a region whose `jurisdiction_id` it is) and `species_key` (a catalog or species-extra key, or `other` with the label naming it) fix the row's id and cannot be edited. Every create, edit and retire bumps the pages version. The daily `rules-watch` slot (06:15 America/Los_Angeles) reads each active region's daily feed `regulations.checks`; a check whose `status` is `changed` puts that jurisdiction's active rows into `review` (`updated_by` `rule-watch`) and opens one `rule` review per jurisdiction and set of changed pages, once.

Skippers and contacts (TA-W3, `server/advisor/admin/skippers.ts`): `owner` and each contact are the same contact view as above (no number or hash); `consent` is `given`, `revoked` or `not given`; `posts` counts the boat's social posts that were not rejected (TA-S1); `consent_note` (`{note, at}` or `null`) is the team's record only and never changes photo consent. Verifying or rejecting decides the boat's open `new_skipper` review when there is one (the queue's decision and text), else applies the same status, pages version and text once per status. The invite hashes and encrypts the number on receipt, finds or creates the contact (`source='skipper-invite'`), starts the registration flow and texts `skipper_invite` plus its first question; the outbound id is per contact and day. A contact's `messages` are its last 50, oldest first, `{direction, body, intent, status, created_at, team, media}`; there is no route that lists or searches contacts.

Decisions (`server/advisor/admin/decisions.ts`, shared with the text admin fallback; the review's `status` becomes `approved`, `edited` or `rejected`, `decided_by` the admin's `users.id`):

| Kind | approve | edit (`patch`) | reject |
| --- | --- | --- | --- |
| `media` | `publish_state` `private`/`queued` → `approved`, the advisor-media job requested for `public.jpg` (TA-M1) and the pages version bumped | `{credit}`: the credit set, then approved (the job requested and the pages version bumped too) | → `rejected` (also from `approved`, which bumps the pages version) |
| `report` | a `draft`/`pending_confirm` report published (`verified` frozen; not a skipper confirmation: no `confirmed_at`, no clean count) | report fields (`report_date`, `trip_type`, `anglers`, `counts`, `notes`): an `advisor_report_edits` row with no contact or message, `version + 1` | `status='rejected'`; a published one also bumps the pages version and drops the port's daily answer |
| `skipper` | `new_skipper`: the boat `verified`, `verified_at`, `verified_by`, the pages version bumped, and 05's verification text to the owner through their channel; other reasons only close the review | `400` (boat fields are edited with `POST /api/admin/boats/<id>`) | `new_skipper`: the boat `rejected` and 05's reject text |
| `conversation` | closes; with `reply` (1–1,000 characters), the text goes to the contact through its channel as an outbound row with `created_by` = the admin and `in_reply_to` the flagged message | `400` | closes |
| `rule` | closes (rules are edited with `/api/admin/rules`; the card links the Rules view on the jurisdiction) | `400` | closes |
| `post` (TA-S1) | a `draft` → `approved`, `approved_by`, `approved_at`; `patch` may hold only `scheduled_for` (an ISO time within 60 days); the post's `queued` photos become `approved` (public; the media job asked for `public.jpg`, the pages version bumped). `409` with the reason while a photo is held (a media review open, a `has_person` photo not approved, a rejected photo), the boat is not verified or its photo consent is not active | `{caption?, targets?, collaborators?, user_tags?, scheduled_for?}`: caption ≤ 2,200 characters, ≤ 30 hashtags, ≤ 20 mentions; targets a subset of the kind's surfaces; ≤ 3 collaborators and no collaborators on a story; ≤ 20 tags `{username, x, y}` (0-1) on photos only; then approved as above. `400` for anything else | `rejected` |

Texts a decision sends have deterministic ids (the review id and the decision), so a repeated request never texts twice; they are held while the relay is down like every outbound text.

`GET /api/admin/health`:

```json
{"checked_at":"…","enabled":true,"replies_enabled":true,"channel":"bluebubbles",
 "relay":{"state":"up","failures":0,"checked_at":"…","last_ok_at":"…"},
 "queue":{"stale_queued":0,"oldest_queued_at":null,"held_outbound":0,"failed_today":0},
 "vision":[{"name":"hermes","configured":false,"down_until":null,"last_ok_at":null},{"name":"claude","configured":true,"down_until":null,"last_ok_at":"2026-10-04T15:58:12.000Z"}],
 "caps":{"day":"2026-10-04","llm":{"used":12,"limit":2000},"vision":{"used":3,"limit":400}},
 "media_jobs":{"pending":0},"reviews":{"open":4},
 "meta":{"configured":true,"quota_usage":3,"quota_total":50,"checked_at":"…","error":null},
 "inbox":{"enabled":false,"public_replies":false,"webhook_ready":true}}
```

`GET /api/admin/funnel` (TA-W4, `server/advisor/admin/funnel.ts`): numbers and the bounded labels they are grouped by, never an id.

```json
{"days":7,"since":"…","generated_at":"…",
 "contacts":{"new":4,"sources":["instagram","skipper-invite"],"by_day":[{"day":"2026-10-03","total":2,"by_source":{"instagram":2}}]},
 "messages":{"inbound":4,"by_intent":[{"intent":"report.daily","count":2}]},
 "replies":{"outbound":4,"contacts":2,"per_contact":2},
 "return_rate":{"active":3,"returning":1,"rate":0.333},
 "boats":{"verified":1,"verified_total":2,"pending":1,"reports_published":3,"boats_reporting":2,"reports_per_boat":1.5},
 "photos":{"submitted":2,"approved":1},"consent":{"boats":3,"given":2,"rate":0.667},
 "social":{"posts":2,"instagram":{"views":7050,"reach":5191,"likes":336,"comments":25,"saved":56,"shares":36,"follows":14,"profile_visits":84},
   "facebook":{"views":0,"reach":812,"likes":57,"comments":6,"saved":0,"shares":4,"follows":0,"profile_visits":0},
   "by_kind":[{"kind":"photo","posts":1,"chats":1,"views":1840,"reach":1203,"likes":96,"comments":7,"saved":12,"shares":5,"follows":3,"profile_visits":21}],
   "chats_from_posts":2,"chats_from_instagram":3,"site_visits_per_post":null},
 "analytics":{"available":true,"reason":null,
   "llm":[{"feature":"advisor:report.daily","calls":12,"input_tokens":3400,"output_tokens":900}],
   "turns":{"count":40,"p50_ms":2310,"p95_ms":9020},
   "pages":[{"event":"advisor_port_view","source":"txt","count":30}]}}
```

`social` (TA-S7): posts published in the window with the latest `advisor_post_stats` row of each summed per surface and per kind (Page `views`, `saved`, `follows` and `profile_visits` are always 0; `reach` is unique impressions and `likes` reactions), `chats_from_posts` (contacts whose first message's link named one of those posts), `chats_from_instagram` (contacts created in the window with source `ig`, `igdm` or `igcomment`); `site_visits_per_post` is `null` (page telemetry has no post id). Days are UTC. `contacts.by_day` has every day of the window (first-touch `source`, `unknown` when none); `messages.by_intent` is the top 20 inbound intents (`none` for unclassified, the rest summed as `other`); replies exclude failed sends; the return rate is contacts with inbound messages on two or more days over contacts with any; reports are those published in the window; consent counts boats that are not rejected. `analytics` comes from Analytics Engine through the SQL API with the Worker secrets `CF_ANALYTICS_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`: `llm` by feature, `advisor_turn` latency, and advisor page views and CTA clicks by visit source. Without the secrets `available` is `false` with `reason` `not-configured`; `no-data` when the dataset has never been written, `error` for any other failure (the D1 part still answers).

`relay` is `job_state` `advisor.relay` (`null` before the first check); `stale_queued` counts inbound messages still `queued` after 2 minutes; `vision[]` (TA-V2) is each provider in `ADVISOR_VISION_PROVIDERS` order: `configured` (Hermes: `HERMES_VISION_URL` is an https URL and `HERMES_VISION_TOKEN` is set; Claude: `ANTHROPIC_API_KEY` is set), `down_until` its 10-minute skip after a failure, and `last_ok_at` when it last answered (`job_state` `advisor.vision.<name>.last_ok`; the view never pings a provider); `caps` are today's UTC-day counters of the global model and vision caps; `media_jobs.pending` is `media.ts` `mediaJobPending` (TA-M1), the count the cron dispatches the advisor-media job on: images without `derived_at` that are over 4.5 MB, HEIC, stored sideways or queued, approved or posted, plus pending graphics; `meta` (TA-S0) is `{configured: false, …null}` without the `META_*` secrets, else the Instagram publishing quota from `content_publishing_limit` (posts used in the last 24 hours of `quota_total`), read at most every 10 minutes and cached (`checked_at`); `error: "unavailable"` when Meta did not answer. `inbox` (TA-S6) is `ADVISOR_INBOX_ENABLED`, `ADVISOR_INBOX_PUBLIC_REPLIES`, and whether `META_VERIFY_TOKEN` and `META_APP_SECRET` are both set (the webhook can be verified).

## Fleet map (signed in, admin role)

### `GET /api/fleet/map/<layer>` (admin only)

The charter fleet's map data ([design § 14](../plans/charter-fleet/design.md); `server/routes/admin.ts`, `server/fleet/map.ts` `fleetMap`, CF-50). It is kept admin-only while the public layer is undecided, and it is **not** a public or job route: the public heat map is [`GET /api/fleet/public/heat`](#get-apifleetpublic-and-get-apifleetpublicheat), with its own gate and privacy floors.

- **Gate and auth:** the flag gate comes first and looks at no layer: `404` `{"error": "Not found"}` unless both `FLEET_ENABLED` and `FLEET_MAP_ENABLED` are `true` (`fleetGate`, checked again in the handler). With both on, the private gate and the admin check run before the layer is validated: a signed-out caller gets `401` and a signed-in caller without the admin role gets `404`, whatever `<layer>` names. Only an admin reaches the handler, where any `<layer>` other than `filters`, `events`, `tracks` or `heat` answers `404` `{"error": "Not found"}`. GETs use the private read limits (300 a minute per IP, 60 a minute per account; `429` `Retry-After: 60`). No job token is accepted. Responses are `no-store`.
- **Query, every layer:** `region` (required; as `ping`; anything else → `400` `{"error": "region is required"}`). For `filters` nothing else is read.
- **Query, `events`, `tracks` and `heat`:** `bbox=minLon,minLat,maxLon,maxLat` (four numbers inside ±180 and ±90, west < east, south < north); `from` and `to` (`YYYY-MM-DD`, real Gregorian dates, inclusive, matched against the trip's local departure date; `from` not after `to`); `vessel`, `port`, `class`, `trip_type`, `kind` (`drift-anchor`, `troll-slow` or `troll-pelagic`) and `source` (`aisstream`, `marinecadastre`, `datalastic` or `local-nmea`), each a comma-separated list of at most 10 tokens; `season` (four digits); `season_part` (a token, or `all`); `module` (a token, default `grid`, read by `heat` only); `limit` (an integer from 1 to the layer's cap, which is also the default); `cursor` (opaque: the previous page's `meta.next`). Unknown query keys are ignored, not refused. Anything malformed → `400` `{"error": "<message>"}` (`bbox must be …`, `bbox out of range`, `from and to must be YYYY-MM-DD`, `from is after to`, `season must be a year`, `invalid <name>`, `<name>: at most 10 values`, `limit must be 1-<cap>`, `invalid cursor`).
- **`filters`:** `200` `{"region", "vessels": [{id, name, slug, vessel_class, port_id}], "truncated", "ports", "classes", "trip_types", "kinds", "seasons", "season_parts", "sources", "modules", "dates": {"min", "max"}, "rights", "planning_only_rights", "basis", "caps"}`: the values the region's data holds; at most 500 vessels, `truncated: true` past that.
- **`events`, `tracks` and `heat`:** `200` a GeoJSON `FeatureCollection` with `meta` `{layer, region, count, cap, next, planning_only, ignored}`. `events` are `Point` features, newest first, at most 2,000 a page. `tracks` are `LineString` features, one per **fishing** segment (drift-anchor, troll-slow, troll-pelagic; in-port, transit, uncertain and gap segments never appear), for trips newest first; `limit` and the cap of 300 count trips, `meta.trips` is the page's trip count and `meta.count` its segment features. `heat` are `Polygon` cells of the `module` aggregates, most dwell first, at most 5,000 a page. The full property lists are in `server/fleet/map.ts` and the design, not repeated here.
- **Paging:** `meta.next` is `null` after the last page. A `bbox` drops tracks after the page is cut, so a page can be empty while `next` is still set: clients page until `next` is `null`, never on counts.
- **Honesty tags:** every feature carries `basis` `inferred-from-movement` (never a confirmed stop or catch), its `rights` (and, on `events` and `tracks` features, its `source`; heat cells carry no `source`), and `planning_only: true` for `noaa-planning-only` rows (counted in `meta.planning_only`) so a client can exclude them.
- **Heat specifics:** `vessel`, `port`, `class`, `trip_type` and `source` cannot be applied to aggregates; any that were sent are listed in `meta.ignored`, not silently widened. An omitted `season_part` selects the whole-season cells, `all` also the per-part ones. Cells with no dates are kept under `from`/`to` and the bound they escaped (`from` or `to`) is added to `meta.ignored`.
- **Errors:** `400` as above; `503` `{"error": "This service is temporarily unavailable."}` when the database binding is missing; a failing query is the common `503`.

## Where the code is tested

`tests/test_private_api.mjs` (private routes, identity gate, owner isolation, limits), `tests/test_feeds.mjs` (feed keys, Range, R2/GitHub order, watchdog), `tests/test_model_api.mjs` (forecast service), `tests/test_job_auth.mjs` (scheduler token claims, the advisor job scope), `tests/test_boat.mjs` (boat lookup parsing), `tests/test_telemetry.mjs` (client telemetry), `tests/test_advisor_routes.mjs` (Text Advisor gate and health), `tests/test_advisor_bluebubbles.mjs` (BlueBubbles webhook and adapter), `tests/test_advisor_twilio.mjs` (Twilio webhooks and adapter), `tests/test_advisor_media.mjs` (media intake, upload link, media serving), `tests/test_advisor_contact_card.mjs` (contact card, deep link, QR, source marker), `tests/test_advisor_web_chat.mjs` (web chat routes and adapter), `tests/test_advisor_media_jobs.mjs` (media job endpoints, pending list, dispatch, the consumer's wait), `tests/test_advisor_admin.mjs` (admin gate, queue, decisions, media bytes, health), `tests/test_advisor_admin_skippers.mjs` (boats, edits, verification, crew, invites, contacts, block), `tests/test_advisor_admin_funnel.mjs` (funnel counts, the Analytics Engine reader, deploy wiring), `tests/test_advisor_admin_rules.mjs` (rules editor, review stamp, change-watch slot, rule-change card), `tests/test_advisor_meta.mjs` (Meta Graph client, quota in health, token script, deploy secrets), `tests/test_advisor_instagram.mjs` (Meta webhook handshake and signature, DMs, the 24-hour window, comment keywords and replies, subscribe), `tests/test_advisor_insights.mjs` (post insights, Stories, chats started, the Funnel's social rows), `tests/test_advisor_social_drafts.mjs` (post drafts, captions, holds, post decisions, propose_post, Posts list, backfill), `e2e/admin.spec.ts` (an admin approves a review in the browser), `tests/test_advisor_pages.mjs` (public pages, sitemap, robots.txt). See [testing](testing.md).
