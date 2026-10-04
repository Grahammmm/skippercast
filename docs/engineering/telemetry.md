# Client telemetry and error reporting

SkipperCast counts a few steps of a visit and reports uncaught browser errors,
so the owner can see whether people get from a port to a saved spot and which
builds break. It uses the Worker's own Workers Analytics Engine dataset
(`skippercast_events`, see [Cloudflare → Observability](../cloudflare.md#observability)).
There is no third-party analytics service, no cookie, no local storage and no
visitor, session or device id.

| Piece | File |
| --- | --- |
| Browser module: batching, opt-out, error capture | `web/telemetry.ts` |
| Funnel call sites | `dist/home-port.js`, `dist/navigation.js`, `dist/export-ui.js`, `dist/offline-pack.js`, `dist/offline.js`; started in `dist/boot.js` |
| Endpoint `POST /api/telemetry` | `server/routes/telemetry.ts` |
| Validation and Analytics Engine columns | `server/telemetry.ts` |
| Daily report tables | `scripts/ops_report.py` |
| Tests | `tests/test_telemetry.mjs`, `tests/contract/test_ops_report.py`, `e2e/telemetry.spec.ts` |

## When nothing is sent

- The browser sends **Do Not Track** (`navigator.doNotTrack` or `window.doNotTrack` is `"1"` or `"yes"`) or **Global Privacy Control** (`navigator.globalPrivacyControl === true`). The module then installs no listeners, keeps no queue and sends no request.
- The browser has no `navigator.sendBeacon`.
- The Worker has no `ANALYTICS` binding (the default until the owner sets `ENABLE_ANALYTICS=true`). The endpoint still validates and answers `204`, but writes nothing.

## What is collected

**Funnel events.** One of a fixed list, each counted at most once per page load and region:

| Event | Sent when |
| --- | --- |
| `port_selected` | A port is chosen in the home-port picker (sent at once, because the page may reload) |
| `map_viewed` | The Map view is shown |
| `forecast_viewed` | The Forecast view is shown |
| `spot_saved` | A spot is added to the day plan (Export); the plan is kept in this browser |
| `offline_saved` | "Save for offline" finishes a region pack |
| `install` | The browser reports the app was installed (`appinstalled`) |
| `advisor_port_view`, `advisor_species_view`, `advisor_boat_view` | A Text Advisor port, species or boat page is opened (`web/advisor/pages.ts`; [08 · Telemetry](../plans/text-advisor/08-website.md)) |
| `advisor_cta` | The "Text SkipperCast" link on one of those pages is followed (sent at once) |

Each carries the region id when one is shown. The server records a region it does not publish as `other`. An event may also carry `source`, the page URL's `s` parameter when it is one of `txt` (a link in an advisor text), `ig`, `fb` (Instagram and Facebook posts) or `qr` (the printed QR code); any other value is not sent, and the server rejects it. It says where the visit came from, never who made it.

**Client errors.** Uncaught errors (`error` on `window`) and unhandled promise rejections (`unhandledrejection`), each with:

- kind (`error` or `rejection`);
- message: in the browser and again on the server, the query or fragment after any path-like token (a full URL, `/api/om?latitude=…` or `dir/file#x`) is removed and coordinate-shaped numbers (`35.3658`, `-120.8512`) become `[coord]`; the browser cuts it to 200 characters, and the server also replaces emails with `[email]` and runs of six or more digits with `#`, and cuts it to 96 characters;
- the script's file name only (no directory, query or fragment), line and column;
- the last `X-Request-Id` the Worker returned to a `fetch` on that page (the module wraps `window.fetch` and reads the header only when the response URL has the page's origin), stored as the first 16 hex characters of its sha256, the same form as the `request` data points, so an error can be matched to the Worker's request point and logs;
- the page's build id, from `<meta name="skippercast-build">`, which `scripts/client-build.mjs` writes into every page.

Identical errors are sent once per page load, and a page sends at most 5 errors and 30 events in all. Cross-origin "Script error." reports without a file name are dropped.

**Not collected:** user or account ids, cookies, IP addresses (the rate limiter keys on the IP as on every public route, but it is not written), user agent, full URLs or query strings, stack traces, form values, positions, boat details or anything typed.

## Transport and endpoint

The module batches events (at most 10 a beacon) and flushes when 10 are waiting, 10 seconds after the first one, or when the page is hidden or unloaded (`visibilitychange`, `pagehide`). Each batch goes out with `navigator.sendBeacon('/api/telemetry', json)` as `text/plain`, at most 3,500 bytes. A refused beacon is dropped, not retried.

`POST /api/telemetry` (`server/routes/telemetry.ts`):

1. `PUBLIC_LIMITER`, keyed `telemetry:<ip>` (60 a minute), else `429`.
2. An allowed `Origin` (production origins or `EXTRA_ORIGINS`), else `400 origin rejected`. Beacons from the site are same-origin and carry it.
3. A JSON object of at most 4,096 bytes, else `400 body too large`.
4. Strict validation (`parseBatch`): exactly `{build, events}`; `build` is 10 hex characters or `dev`; 1 to 10 events (the client's batch size); each event is `{type: "funnel", name, region?, source?}` or `{type: "error", kind, message?, source?, line?, column?, request_id?}` with the types and bounds in `server/telemetry.ts`. Any other field, name or type is `400 invalid telemetry`; nothing is written from a rejected batch.
5. A funnel event repeated in one batch (same name and region, after unknown regions become `other`) is kept once. One Analytics Engine data point per remaining event, then `204` with `Cache-Control: no-store`.

## Analytics Engine columns

| Kind (`index1`, `blob1`) | Text columns | Number columns |
| --- | --- | --- |
| `client_event` | `blob2` event, `blob3` region id (`''` none, `other` unknown), `blob4` page build, `blob5` visit source (`txt`, `ig`, `fb`, `qr`; absent when none) | `double1` 1 |
| `client_error` | `blob2` kind, `blob3` scrubbed message, `blob4` script file name, `blob5` page build, `blob6` first 16 hex of sha256(request id) | `double1` line, `double2` column |

Every telemetry request also writes the usual `request` point for route `/api/telemetry`.

## Reading it

The daily **Operations report** (`.github/workflows/ops-report.yml`) adds two tables for the last 24 hours:

- **Client funnel:** events per step, in visit order (`port_selected` → `map_viewed` → `forecast_viewed` → `spot_saved`, then `offline_saved` and `install`), with zero for steps not seen. These are page-load counts, not people: there are no visitor ids, and people who opt out are not counted, so ratios between steps are indicative only.
- **Top client errors:** the 10 most reported message, file, line, kind and build combinations. Message and file are printed as code spans with backticks removed, so text from a browser cannot render as a link, image or HTML in the summary.

Ad-hoc queries use the same SQL API, for example:

```sql
SELECT blob4 AS build, blob3 AS message, SUM(_sample_interval) AS reports
FROM skippercast_events WHERE index1 = 'client_error' AND timestamp > NOW() - INTERVAL '7' DAY
GROUP BY build, message ORDER BY reports DESC LIMIT 20
```

## Retention

Analytics Engine's default: Cloudflare stores data points for three months ([limits](https://developers.cloudflare.com/analytics/analytics-engine/limits/), checked 2026-09-29). SkipperCast sets no other retention and keeps no copy; the daily report exists only as a GitHub Actions run summary.

## Adding an event

Add the name to `FUNNEL` in `web/telemetry.ts`, `FUNNEL_EVENTS` in `server/telemetry.ts` and `FUNNEL` in `scripts/ops_report.py`, call `track('<name>')` at the call site, update the tables above and the tests. An event carries no fields beyond its name, region and visit source; anything more needs a review of this page and of the privacy policy. (The advisor page events are not in `scripts/ops_report.py`'s `FUNNEL` while the advisor is dark; the report lists unknown names after the steps.)
