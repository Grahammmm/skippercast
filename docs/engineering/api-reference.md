# HTTP API reference

Every route the SkipperCast Worker answers, derived by reading `server/app.ts` and `server/routes/`, `server/feeds.ts`, `server/model-api.js` and `server/boat-lookup.ts` on `main` (after PR #24, [P0-01]). The same Worker runs on ChatGPT Sites (skippercast.com today) and on SkipperCast's own Cloudflare account ([Cloudflare](../cloudflare.md)). Where an open PR changes a route, the change is listed under **Pending changes** so this page describes the system as it will be once they merge. The guide's target (P5-03, P3-01) is to generate this from typed route definitions (Hono + zod → OpenAPI); until then this page is maintained by hand. When you change a route, update this page in the same PR.

Examples below were produced by running the Worker in Node with an in-memory D1, a fake R2 bucket and synthetic forecast tiles, the same way `tests/test_private_api.mjs` does.

## Conventions

- **Order of matching** (`server/app.ts`, a Hono app; each route module is under `server/routes/`): `GET /feeds/*` → public `/api/` routes → `/api/auth/*` → `/api/session` → the private gate (`server/middleware/auth.ts`) → private `/api/` routes → `/api/*` `404` → any other path (static site). Routing uses the raw, still percent-encoded path. `HEAD` is answered as `GET` without a body. Unknown `/api/` paths answer `401` to anonymous callers and `404` to signed-in ones, because the identity check comes before the final `404`.
- **JSON responses** from `/api/*` carry `Content-Type: application/json`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`, unless a route below sets a public `Cache-Control`.
- **Identity.** A request is signed in only when `IDENTITY_PROVIDER` is `chatgpt-sites` *and* both `oai-authenticated-user-id` and `oai-authenticated-user-email` headers are present; the owner id is the first. ChatGPT Sites injects those headers and strips visitor copies. The Cloudflare deployment sets `IDENTITY_PROVIDER=none` in `wrangler.jsonc`, so no request is ever signed in there and every private route answers `401`. The variable defaults to `chatgpt-sites` when absent (the Sites package has no Wrangler config).
- **Mutations** (any non-GET private route) require an `Origin` header in `deployments/production.json` `allowed_origins` or the `EXTRA_ORIGINS` Worker secret, and a budget of 30 requests per owner per minute (`request_limits` table).
- **Bodies** are JSON objects of at most 8,192 bytes, read as a stream; anything else is `400`.
- **Request ids.** Every response carries `X-Request-Id` (a UUID, or a well-formed incoming `X-Request-Id` of 8–64 letters, digits, `-` or `_`), and every JSON error body repeats it as `request_id`, e.g. `{"error": "origin rejected", "request_id": "…"}`. Failures are logged with the same id (`server/middleware/request-id.ts`).
- **Errors** (`server/middleware/error.ts`, for paths under `/api/`; the bodies below also carry `request_id`):

  | Status | Body | When |
  | --- | --- | --- |
  | `400` | `{"error": "<message>"}` | A validation error (message kept, e.g. `"date must be within the next seven days"`, `"push endpoint rejected"`, `"origin rejected"`, `"body too large"`) |
  | `429` | `{"error": "Please try again shortly"}` | The 30-per-minute mutation budget |
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

**Pending changes:** PR #43 ([P0-05]) caches R2 objects up to 32 MB whole in the Workers Cache API (Range and conditional requests answered from the cached copy; `X-SC-Cache: hit|miss`; seafloor never cached) and limits `/feeds/` to 300 requests per minute per IP (`FEED_LIMITER`; over the limit `429` with `Retry-After: 60` and `{"error": "Too many requests; try again in a minute."}`); the rate limit and shared cache are absent on ChatGPT Sites. PR #38/#43 ([P0-06]) add security headers to every Worker response.

## Static site

### `GET /`, `GET /<page>.html`, other assets

Any path not under `/api/` or `/feeds/`. Stable page paths (`/`, `/index.html`, `/sources.html`, …; the `SHELLS` map built by `scripts/client-build.mjs`) are served from their build-id copy with `Cache-Control: no-store`. Every other path goes to the static assets binding unchanged (hashed scripts and styles, `vendor/`, `data/`, `regions/`). No authentication.

**Pending changes:** PR #25 ([P0-02]) keeps `sw.js` unhashed and serves `GET /sw.js` with `Cache-Control: no-cache`. PR #36 ([P0-09]) adds `/terms.html`, `/privacy.html` and `/licenses.html` pages. PR #38/#43 ([P0-06]) add HSTS, CSP, `frame-ancestors 'none'`, `Permissions-Policy` and related headers to pages and (via a generated `_headers` file) to static assets.

## Public API

### `GET /api/health`

Liveness. Any method answers. No authentication.

```json
{"service":"SkipperCast","version":"0.3.0","build":"0c321d2522","storage":true,"feeds":"r2","notifications":false}
```

`storage`: D1 bound; `feeds`: `r2` when `FEEDS` is bound, else `github`; `notifications`: both VAPID keys set.

**Pending changes:** PR #45 ([P3-06]) reduces this to `{"service","version","build"}` so the public endpoint no longer reveals which bindings and secrets exist; feed storage is then visible per response in `X-Feed-Source`. PR #26's smoke test (`scripts/smoke_test.sh`) reads `service` and `build` only.

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

Open-Meteo-style model metadata from the model's manifest. `<model>` is one of the four above; unknown → `400` `Unknown model`; not yet published → `400` `Model not yet published`. `Cache-Control: public,max-age=300`.

```json
{"last_run_initialisation_time":0,"data_end_time":18000,"provider":"NOAA GFS","source":"https://example","cycle_iso":"2026-09-28T12:00:00Z"}
```

**Pending changes (both `/api/om` routes):** PR #43 caches answers in the Workers Cache API keyed on the path, sorted query and build id (`X-SC-Cache: hit|miss`, `Cache-Control: public, max-age=300, s-maxage=300`) and limits them to 60 requests per minute per IP (`PUBLIC_LIMITER`; `429` + `Retry-After: 60`).

### `GET /api/forecast?region=<id>`

The `forecast` object of the region's intelligence feed (`region.intelligence_feed`, read R2-first): `{region_id, requested_points, models, retrieved, coverage}`. `Cache-Control: public,max-age=300`. Unknown region → `404` `{"error": "Unknown region"}`; a feed whose `region_id` differs → `503`.

### `GET /api/intelligence?region=<id>`

The region's intelligence feed without `forecast`: `{schema_version, region_id, generated_at, completed_at, ocean_collected_at, sources, verification, health}`. Sources whose id starts `model-` or `verify-` are reduced to `{name, status, issue, url, checked_at}`. `Cache-Control: no-store` on `main`. Errors as `/api/forecast`.

### `GET /api/habitat?region=<id>`

The region's dynamic-habitat feed (`region.habitat_feed`): `{schema_version, method, region_id, bounds, generated_at, completed_at, layers, sources, species_methods, interpretation, health}`. Requires `schema_version: 1` and a matching `region_id` (else `503`). `Cache-Control: public,max-age=300`. A region without a habitat feed → `404`.

### `GET /api/daily?region=<id>&part=<part>`

One part of the region's daily feed (`region.daily_feed`, read R2-first), for the map's startup (P4-05): the whole feed is ~1.4 MB. The feed must pass the checks the app applies to it (matching `region_id`, `schema_version: 1`, a valid `generated_at`, `sources` object, `reports` array, `health`, `catch_probability` and `bite_score` null), else `503`. Every part carries `{schema_version, region_id, generated_at, catch_probability: null, bite_score: null, part}` plus:

- `part=regulations` → `regulations` (the rule checks the regulations badge reads);
- `part=mpa-boundaries` or `part=additional-closures` → `sources: {<part>: record}` (`{}` when the feed has no such record).

Edge-cached per region and part (`X-SC-Cache`); one feed read fills all three parts. `Cache-Control: public, max-age=300, s-maxage=300`. Limited to 60 requests per minute per IP (`PUBLIC_LIMITER`, key prefix `daily`; `429` + `Retry-After: 60`). Unknown part → `400`; unknown region → `404`. The service worker saves it like the other public data APIs, and offline packs include all three parts. The client (`dist/daily-feed.js`) falls back to the full feed when this fails.

**Pending changes (region endpoints):** PR #43 caches all three keyed on `region` only (other parameters ignored), decodes the intelligence feed once for both `/api/forecast` and `/api/intelligence`, and sets `/api/intelligence` to `public, max-age=60, s-maxage=60`. PR #45 looks regions up with `Object.hasOwn`, so `?region=__proto__` and similar are a plain `404`.

### `POST /api/telemetry`

Cookie-less funnel events and client error reports from `web/telemetry.ts` (`navigator.sendBeacon`). Anonymous, but needs an allowed `Origin` (`400 origin rejected`), is limited by `PUBLIC_LIMITER` to 60 a minute per IP (`429` + `Retry-After: 60`) and takes at most 4,096 bytes (`400 body too large`). The body is exactly `{build, events}`: `build` is 10 hex characters or `dev`; `events` holds 1–10 of `{"type": "funnel", "name": "port_selected"|"map_viewed"|"forecast_viewed"|"spot_saved"|"offline_saved"|"install", "region"?}` or `{"type": "error", "kind": "error"|"rejection", "message"?, "source"?, "line"?, "column"?, "request_id"?}`. Any other field or value answers `400 {"error": "invalid telemetry"}`. A funnel event repeated within a batch is written once. Valid batches answer `204` with no body, written to Analytics Engine when `ANALYTICS` is bound and discarded otherwise. `GET` is not a route (it reaches the private gate). See [client telemetry](telemetry.md).

```json
{"build":"0123456789","events":[{"type":"funnel","name":"map_viewed","region":"morro-bay"},{"type":"error","kind":"error","message":"x is undefined","source":"index.0123456789.js","line":12,"column":7,"request_id":"3f0c…"}]}
```

### `GET /api/session`

Whether the caller is signed in, the push public key and the sign-in link.

```json
{"signedIn":false,"publicKey":null,"signIn":"/signin-with-chatgpt?return_to=%2F%23forecast"}
```

On Cloudflare (`IDENTITY_PROVIDER=none`) `signedIn` is always `false` and `signIn` is `null`.

### `GET /api/advisor/health`

Text Advisor liveness (docs/plans/text-advisor/). No authentication. Answers `404` `{"error": "Not found"}` unless the Worker var `TEXT_ADVISOR_ENABLED` is `true`, like every advisor path (`/api/advisor/*`, `/ports/*`, `/species/*`, `/boats/*`, `/media/*`, `/u/*`, `/contact.vcf`, `/text`), which are reserved and gated by `server/advisor/gate.ts` before their routes exist. When on, `Cache-Control: no-store`:

```json
{"enabled":true,"channel":"bluebubbles","providers":["hermes","claude"]}
```

`channel` is `ADVISOR_CHANNEL` (`bluebubbles` or `twilio`); `providers` is the vision provider chain from `ADVISOR_VISION_PROVIDERS`. Never a secret or the advisor's phone number.

## Scheduler

### `POST /api/jobs/check`

Runs saved-trip checks for one page of 25 trips, delivers push alerts and prunes expired rows. Called by `scripts/check_saved_trips.py` from `live-conditions.yml`.

- **Auth:** `Authorization: Bearer <GitHub Actions OIDC token>` with audience `<public_origin>/api/jobs/check`, verified by `server/job-auth.ts` against GitHub's fixed JWKS: RS256; issuer, subject, repository, repository id, owner id, ref, workflow and event (`schedule`, `workflow_dispatch`, `push`) must match `deployments/production.json` `scheduler`; lifetime at most 600 s. Anything else → `401` `{"error": "Unauthorized"}`.
- **Body:** `{"cursor": "<last trip id>"}` or `{}`; cursor at most 50 characters.
- **Limit:** 30 calls per token (`jti`) per minute.
- **Response:** `{"checked": 25, "changes": 1, "delivered": 1, "held": 0, "in_app": 0, "next_cursor": "<id>|null"}`. The script pages until `next_cursor` is `null` (at most 100 pages).

**Pending changes:** PR #28 ([P0-07]) also prunes from the Worker's cron (`scheduled`), so retention no longer depends on this call.

### Cron (`scheduled`)

Not an HTTP route. Every 15 minutes on Cloudflare (`wrangler.jsonc` `triggers`), `server/watchdog.ts` reads `conditions/latest.json` (R2, then GitHub) and, if it is more than 45 minutes old and no `live-conditions.yml` run is queued or in progress, dispatches one with the `GITHUB_TOKEN` Worker secret. ChatGPT Sites has no cron.

## Private API (signed in)

All routes below answer `401` when the caller is not signed in:

```json
{"error":"Sign in to save private trips or feedback","signIn":"/signin-with-chatgpt?return_to=%2F%23forecast"}
```

(On Cloudflare: `{"error":"Accounts are not available on this site yet","signIn":null}`.) Every query is scoped to the caller's owner id. Non-GET routes need an allowed `Origin` and the 30-per-minute budget (see Conventions).

| Method and path | Body | Success | Specific errors and limits |
| --- | --- | --- | --- |
| `GET /api/trips` | — | `200` `{"trips": [...], "events": [...]}` — up to 50 trips (newest date first) and 30 alert events `{id, trip_id, kind, message, status, created_at}` | — |
| `POST /api/trips` | `{region, point, species, date, start_hour, end_hour, wind_limit, gust_limit, sea_limit}` plus the optional planner fields `launch_point` (slug), `targets` (1–3 region species; `species` is always first), `plan` (`{spots[≤12]: {id, name, lat, lon, order, notes, depth_ft}, legs[≤13]: {from, to, nm, minutes}, window: {depart, return_by, hours[]}, exports[≤20]: {format, sha256, exported_at}}`, 16 KB cap; the request body for these two routes may be 24 KB) and `status` (`draft`, `planned` (default), `done`, `cancelled`) | `201` `{"id": "<uuid>"}` | `400` `unknown area or species`, `date must be within the next seven days` (date in the region's time zone, today to +7 days), `invalid <field>` (hours 0–22 / 1–23, wind 1–30 kn, gust 1–40 kn, seas 0.5–10 ft), `invalid window or thresholds` (end after start, integer hours, gust ≥ wind); `409` `Limit of 20 active trips` |
| `PATCH /api/trips` | `{"id", launch_point?, targets?, plan?, status?}` — only the given planner fields change; the alert fields are fixed at save time | `200` the trip's planner fields `{id, launch_point, targets, plan, status}` | `400` as for `POST` plus `invalid launch point`, `targets must be one to 3 species of the region`, `targets repeat a species`, `invalid status`, `too many spots (limit 12)`, `plan too large`; `404` `Not found` (another owner's trip too) |
| `DELETE /api/trips` | `{"id": "<trip id>"}` | `200` `{"deleted": true}` (also when nothing matched) | `400` `trip id required` |
| `POST /api/events/ack` | `{"id": "<event id>"}` | `200` `{"read": true}`; a `final`/`missed-final` event also closes its trip | `404` `Not found` |
| `POST /api/subscription` | Web Push subscription `{endpoint, keys: {p256dh, auth}}` | `200` `{"enabled": true}` | `400` `subscription missing`, `push endpoint rejected` (HTTPS only, no port or credentials, ≤ 2,000 chars, host `fcm.googleapis.com`, `updates.push.services.mozilla.com`, `web.push.apple.com` or `*.notify.windows.com`), `push keys invalid`; `409` `Subscription belongs to another signed-in user`, `Limit of five notification devices` |
| `DELETE /api/subscription` | — | `200` `{"enabled": false}` (removes all the caller's devices) | — |
| `POST /api/comfort` | `{region, rating (1–10 integer), phase ("outbound"\|"fishing"\|"return"), wind?, sea?, period?, heading?, point?}` | `201` `{"saved": true}` | `400` `invalid feedback`, `invalid feedback context` (wind ≤ 200, sea ≤ 100, period ≤ 60, heading ≤ 360, all ≥ 0), `invalid feedback point` |
| `GET /api/comfort` | — | `200` `{"feedback": [...]}` — up to 100, newest first; `context` is a JSON string | — |
| `GET /api/privacy` | — | `200` `{"trips": [...], "feedback": [...], "events": [{message, created_at, status}]}` — everything stored for the caller | — |
| `DELETE /api/privacy` | — | `200` `{"deleted": true}` — deletes trips, subscriptions, alert events, their receipts and feedback | — |
| `POST /api/boat/lookup` | `{"query": "<make model year>"}` (3–120 characters after whitespace folding) | `200` `{query, boat, confidence, estimated, notes, sources, looked_up_at}`; `cached: true` when served from the 30-day lookup cache | `400` `invalid boat name`; `429` after 20 lookups per owner per UTC day; `502` when the lookup fails; `503` when `ANTHROPIC_API_KEY` is not set |

Example `GET /api/trips`:

```json
{"trips":[{"id":"e3a9a976-d65f-4ab4-af0e-d7fe7f205b1b","owner":"alice","region":"morro-bay","point":"north","species":"reef","date":"2026-09-29","start_hour":7,"end_hour":13,"wind_limit":8,"gust_limit":12,"sea_limit":3,"enabled":1,"created_at":"2026-09-29T04:44:01.204Z","last_assessment":null,"final_delivered_at":null}],"events":[]}
```

The boat lookup sends the query to Anthropic's Messages API with web search (`server/boat-lookup.ts`); `boat` holds the fields of the manual boat form (`loa_ft`, `beam_ft`, `hull`, `layout`, …) validated by `normalizeBoat` in `dist/boat-handling.js`, and `sources` up to six cited URLs.

**Pending changes:** PR #29 ([P0-08]) adds a global daily cap (`BOAT_LOOKUP_GLOBAL_DAILY_LIMIT`, default 500 → `429` `AI boat lookup is busy today…`), a kill switch (`BOAT_LOOKUP_ENABLED=false` → `503`), the model id from `BOAT_AI_MODEL`, and a usage log line per lookup. PR #45 validates `POST /api/events/ack` ids as 64-hex (`400` `event id required`) and trip ids as at most 64 characters. The guide's P3-02 replaces ChatGPT identity with SkipperCast accounts; this whole section changes then.

## Where the code is tested

`tests/test_private_api.mjs` (private routes, identity gate, owner isolation, limits), `tests/test_feeds.mjs` (feed keys, Range, R2/GitHub order, watchdog), `tests/test_model_api.mjs` (forecast service), `tests/test_job_auth.mjs` (scheduler token claims), `tests/test_boat.mjs` (boat lookup parsing), `tests/test_telemetry.mjs` (client telemetry), `tests/test_advisor_routes.mjs` (Text Advisor gate and health). See [testing](testing.md).
