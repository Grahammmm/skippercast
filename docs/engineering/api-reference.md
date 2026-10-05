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

Signed in, it also carries `user` (`{id, display_name}`). `is_admin` (always present, `false` when signed out) is `true` when the account has the Text Advisor admin role (`users.role='admin'`, set only by `scripts/advisor/grant-admin.mjs`); the role itself is never exposed.

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

**Pending changes:** PR #28 ([P0-07]) also prunes from the Worker's cron (`scheduled`), so retention no longer depends on this call.

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

Identity check for the charter fleet's Hermes workflows ([charter fleet design § 12](../plans/charter-fleet/design.md)); later tasks add the other `/api/fleet/jobs/*` routes under the same rules. Every `/api/fleet/*` and `/api/admin/fleet/*` path answers `404` `{"error": "Not found"}` unless the Worker var `FLEET_ENABLED` is `true` (`server/routes/fleet.ts` `fleetGate`); `/api/fleet/map/*` also needs `FLEET_MAP_ENABLED=true`.

- **Auth:** as `POST /api/jobs/check`, but the token's audience must be `<public_origin>/api/fleet/jobs` and its workflow one of `fleet-registry.yml`, `fleet-osint.yml`, `fleet-ais.yml`, `fleet-health.yml`, which `deployments/production.json` `scheduler.workflows` lists (`FLEET_JOB_SCOPE`, `requireFleetJob`). Trip-check and advisor-media tokens are refused here, and fleet tokens there. Anything else → `401`.
- **Query:** `region` (optional): a region id, letters, digits and `-`, at most 64; anything else → `400` `{"error": "invalid region"}`.
- **Limit:** 240 calls per token (`jti`) per minute, shared by every fleet job route.
- **Response:** `200`, `no-store`: `{"ok": true, "region": "<id>"|null}`.

### Cron (`scheduled`)

Not an HTTP route. Every 15 minutes on Cloudflare (`wrangler.jsonc` `triggers`), `server/watchdog.ts` reads `conditions/latest.json` (R2, then GitHub) and, if it is more than 45 minutes old and no `live-conditions.yml` run is queued or in progress, dispatches one with the `GITHUB_TOKEN` Worker secret (`dispatchWorkflow`, which TA-M1 exported; the advisor's cron uses it to dispatch `advisor-media.yml` while media or graphics are pending, at most once per 15 minutes). ChatGPT Sites has no cron.

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

## Where the code is tested

`tests/test_private_api.mjs` (private routes, identity gate, owner isolation, limits), `tests/test_feeds.mjs` (feed keys, Range, R2/GitHub order, watchdog), `tests/test_model_api.mjs` (forecast service), `tests/test_job_auth.mjs` (scheduler token claims, the advisor job scope), `tests/test_boat.mjs` (boat lookup parsing), `tests/test_telemetry.mjs` (client telemetry), `tests/test_advisor_routes.mjs` (Text Advisor gate and health), `tests/test_advisor_bluebubbles.mjs` (BlueBubbles webhook and adapter), `tests/test_advisor_twilio.mjs` (Twilio webhooks and adapter), `tests/test_advisor_media.mjs` (media intake, upload link, media serving), `tests/test_advisor_contact_card.mjs` (contact card, deep link, QR, source marker), `tests/test_advisor_web_chat.mjs` (web chat routes and adapter), `tests/test_advisor_media_jobs.mjs` (media job endpoints, pending list, dispatch, the consumer's wait), `tests/test_advisor_admin.mjs` (admin gate, queue, decisions, media bytes, health), `tests/test_advisor_admin_skippers.mjs` (boats, edits, verification, crew, invites, contacts, block), `tests/test_advisor_admin_funnel.mjs` (funnel counts, the Analytics Engine reader, deploy wiring), `tests/test_advisor_admin_rules.mjs` (rules editor, review stamp, change-watch slot, rule-change card), `tests/test_advisor_meta.mjs` (Meta Graph client, quota in health, token script, deploy secrets), `tests/test_advisor_instagram.mjs` (Meta webhook handshake and signature, DMs, the 24-hour window, comment keywords and replies, subscribe), `tests/test_advisor_insights.mjs` (post insights, Stories, chats started, the Funnel's social rows), `tests/test_advisor_social_drafts.mjs` (post drafts, captions, holds, post decisions, propose_post, Posts list, backfill), `e2e/admin.spec.ts` (an admin approves a review in the browser), `tests/test_advisor_pages.mjs` (public pages, sitemap, robots.txt). See [testing](testing.md).
