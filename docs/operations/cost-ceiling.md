# Cost ceiling and per-caller limits

SkipperCast runs on the owner's own Cloudflare account. Workers and D1 on the
Free plan stop when their allowance runs out; R2 has a payment method on file,
so R2 reads past the free allowance would be billed. The Worker therefore keeps
a hard daily ceiling on R2 reads. Past it, the site serves saved copies and
free fallbacks instead of reading R2, and says so. This page is the reference
that `server/cost-ceiling.ts`, `server/middleware/auth.ts`, `wrangler.jsonc`
and `research/scripts/measure_session_cost.mjs` point to. Every value below
is copied from the file and line named next to it; change the code, not this
page, and then update the page to match.

## What is counted

- **R2 Class B reads on the `FEEDS` bucket: `get` and `head`.** Every
  request's bucket is wrapped by `meter()`, which counts one read per `get` or
  `head` call; every other method passes through uncounted
  (`server/cost-ceiling.ts:4-8`, `server/cost-ceiling.ts:99-106`). No route
  gets the bucket any other way, so no route can read R2 without being counted.
- **Per UTC day.** The count resets when the UTC date changes
  (`server/cost-ceiling.ts:49`, `server/cost-ceiling.ts:60-63`), which is
  4 p.m. Pacific Standard Time, 5 p.m. during daylight saving time.
- **Global, written in batches.** Each Worker isolate keeps its own pending
  reads and adds them to one D1 row per day in `request_limits`, with id
  `cost-ceiling:r2-reads:<YYYY-MM-DD>` (`server/cost-ceiling.ts:76`). It writes
  once it has `FLUSH_READS` = `50` pending reads, or `FLUSH_MS` = `30_000` ms
  after its last write (`server/cost-ceiling.ts:35-36`,
  `server/cost-ceiling.ts:96`). The same statement returns the day's total
  from all isolates (`server/cost-ceiling.ts:88-90`). The row expires 3 days
  after the start of its day (`server/cost-ceiling.ts:86`) and the existing
  cron prunes it (`server/cost-ceiling.ts:10-11`).
- **An isolate sees other isolates' reads only when it writes.** Its view is
  the last total D1 returned plus its own reads not yet written, including a
  batch whose write is still unanswered (`server/cost-ceiling.ts:51-58`,
  `server/cost-ceiling.ts:69`). The ceiling can therefore be passed by up to
  one unwritten batch per running isolate before every isolate notices.
- **A failed D1 write blocks nothing.** The batch goes back to pending and is
  written later (`server/cost-ceiling.ts:91`). Without D1 (tests, a bare dev
  runtime) the count stays in the isolate (`server/cost-ceiling.ts:84`).

Not counted: Worker requests, D1 reads and writes, Cache API reads, R2 reads
and writes made by the publishing jobs outside the Worker (their read-back
checks included; [cloudflare.md](../cloudflare.md)), and requests answered by
static-asset routing (which does not run the Worker).

## Limits

| Limit | Value | Where it is set |
| --- | --- | --- |
| R2 reads a UTC day before the Worker degrades (deployed) | `"300000"` | `wrangler.jsonc:41` (`COST_CEILING_R2_READS_PER_DAY`) |
| Default ceiling when the variable is missing or not a positive integer | `300_000` (below R2's free Class B allowance of 10 million a month: 300,000 × 31 days is 9,300,000) | `server/cost-ceiling.ts:33-34` (`DEFAULT_R2_READS_PER_DAY`) |
| How the variable is read: a positive integer of at most 12 digits is used; `"off"` disables the ceiling; anything else gives the default | `/^[1-9]\d{0,11}$/`, `"off"` | `server/cost-ceiling.ts:42-47` (`ceilingOf`) |
| Reads per batch written to D1 | `50` | `server/cost-ceiling.ts:35` (`FLUSH_READS`) |
| Longest wait before pending reads are written | `30_000` ms | `server/cost-ceiling.ts:36` (`FLUSH_MS`) |
| How long a last-known copy is kept | `7 * 24 * 3600` seconds (7 days) | `server/cost-ceiling.ts:37` (`LAST_KNOWN_SECONDS`) |
| Largest last-known copy | `32 * 1024 * 1024` bytes (32 MiB) | `server/cost-ceiling.ts:38` (`LAST_KNOWN_MAX_BYTES`) |
| `Retry-After` on the degraded 503 | `600` seconds | `server/cost-ceiling.ts:39` (`DEGRADED_RETRY_SECONDS`) |
| Private routes, per IP, before the session lookup | `300` a `60`-second period (`FEED_LIMITER`, key `private-ip:<ip>`) | `wrangler.jsonc:48`; applied at `server/middleware/auth.ts:16` |
| Private reads (GET), per account | `60` a `60`-second period (`PUBLIC_LIMITER`, key `account:<user id>`) | `wrangler.jsonc:47`; applied at `server/middleware/auth.ts:20` |
| Private mutations, per account | `30` a minute (D1 counter in `request_limits`) | `server/http.ts:30` (`budget`, `limit = 30`); applied at `server/middleware/auth.ts:19` |
| `Retry-After` on every 429 | `60` seconds | `server/edge-cache.ts:72` (`RETRY_AFTER_SECONDS`), response at `server/edge-cache.ts:85-87` |

The per-caller limits on private routes (`server/middleware/auth.ts:1-8`)
exist so that a flood of requests, with or without a session cookie, cannot
become D1 reads: the per-IP check runs before the session is looked up. Over
a limit the answer is `429` with `{"error": "Too many requests; try again in a
minute."}`, `Cache-Control: no-store` and `Retry-After: 60`
(`server/edge-cache.ts:85-87`). The two Rate Limiting checks do nothing where
the bindings are absent (tests, a bare dev runtime), and a limiter failure lets
the request through (`server/edge-cache.ts:75-79`).

The same two bindings also limit the anonymous read endpoints per IP, each
under its own key prefix: `/feeds/*` on `FEED_LIMITER`
(`server/routes/feeds.ts:11`), `/api/om` on `PUBLIC_LIMITER`
(`server/routes/om.ts:30`) and `/api/daily` on `PUBLIC_LIMITER`
(`server/routes/public.ts:84`). The full list of public limits is in
[cloudflare.md](../cloudflare.md) and the
[API reference](../engineering/api-reference.md).

## What a session costs

`research/scripts/measure_session_cost.mjs` records the requests three visitor
sessions make on the real site, each in a fresh browser profile with a phone
viewport (`research/scripts/measure_session_cost.mjs:8-12`):

- **first-run**: the landing page, then a port chosen;
- **brief**: a returning visitor opening the Boat brief for Morro Bay;
- **map**: the map, panned and zoomed, with three layers switched on.

It sorts each response into `worker` (the Worker ran), `asset` (static-asset
routing answered it for free) and `third-party`
(`research/scripts/measure_session_cost.mjs:13-18`). It does not replay R2 or
D1 operations: those are read from the Worker's code path per request
(`research/scripts/measure_session_cost.mjs:20-22`).

**No capture output is recorded in this repository**, so nothing on this page
was measured here. The only recorded run is the pre-merge capture described in
pull request #1267 (live site, build `beeeea5e43`, two captures that agreed):

| Session | Worker requests | Static (free) | Bytes through the Worker | R2 Class B (code path) | D1 |
| --- | --- | --- | --- | --- | --- |
| first-run | 11 | 35 | 0.50 MB | ~11 warm / ~15 cold | 0 |
| brief | 26 | 30 | 2.0 MB | ~39 | 0 |
| map | 118 | 134 | 102–108 MB | ~163 | 0 |

The projection is arithmetic on those per-session figures, not a measurement:

- Worker requests a day = sessions a day × Worker requests per session;
- R2 reads a day = sessions a day × R2 Class B reads per session.

Compare the first with the Workers Free plan's 100,000 requests a day
(`docs/cloudflare.md:76`) and the second with the ceiling, 300,000 R2 reads
a UTC day (`wrangler.jsonc:41`).

| Sessions a day | first-run: Worker / R2 | brief: Worker / R2 | map: Worker / R2 | one visitor doing all three: Worker / R2 |
| --- | --- | --- | --- | --- |
| 100 | 1,100 / 1,100–1,500 | 2,600 / 3,900 | 11,800 / 16,300 | 15,500 / 21,300–21,700 |
| 1,000 | 11,000 / 11,000–15,000 | 26,000 / 39,000 | 118,000 / 163,000 | 155,000 / 213,000–217,000 |
| 10,000 | 110,000 / 110,000–150,000 | 260,000 / 390,000 | 1,180,000 / 1,630,000 | 1,550,000 / 2,130,000–2,170,000 |

Read this way, the Workers Free limit binds before the R2 ceiling: a visitor
doing all three sessions makes 155 Worker requests, so 100,000 requests a day
covers about 645 such visitors, while the R2 ceiling would cover about 1,380
(300,000 ÷ 217). Workers Free stops serving past its limit rather than
billing (`server/cost-ceiling.ts:6-7`). Re-run the capture after any change to how pages read feeds, and
replace the table with the new figures and their build.

## Owner checks

These are Cloudflare dashboard pages the owner opens; none is automated
(checks 1, 3 and 4 are the follow-up list of pull request #1267). Use
the dashboard menus by name; do not copy account ids or URLs that contain them
into this repository.

1. **Workers & Pages → the `skippercast` Worker → Metrics.** Confirm the plan
   is still Workers Free, and compare requests a day with 100,000
   (`docs/cloudflare.md:76`). A day near that line means the Free limit, not
   the R2 ceiling, is the first thing visitors will hit.
2. **R2 → usage for the account.** Compare Class B operations this month with
   the free 10 million (`server/cost-ceiling.ts:33`). At 300,000 a day for a
   31-day month the ceiling keeps the Worker's share near 9,300,000.
3. **R2 → Billing usage notification.** Set a notification so any R2 usage
   that would be billed sends the owner an email.
4. **Notifications → "Usage Based Billing" alert.** Add it, delivered by email,
   so any usage-based charge on the account is reported.
5. **The Worker's own count (optional).** In the D1 console for the
   `skippercast` database, the row with id `cost-ceiling:r2-reads:<today's UTC
   date>` in `request_limits` holds the count the Worker has written for today.
   Compare it with the ceiling, 300,000 (`wrangler.jsonc:41`). The
   dashboard's Class B figure also includes reads made outside the Worker,
   such as the publishing jobs' read-back checks, so it is usually higher.

Changing the ceiling means editing `COST_CEILING_R2_READS_PER_DAY` in
`wrangler.jsonc` (`wrangler.jsonc:37-42`) in a reviewed pull request: the
config has no `keep_vars`, so the deploy writes the committed vars and a value
set only in the dashboard is lost at the next deploy.

## When it trips

Once today's count reaches the ceiling (`server/cost-ceiling.ts:71`), the
Worker is degraded until the UTC day ends (`server/cost-ceiling.ts:17-27`,
`server/cost-ceiling.ts:229-251`). No request reads R2: the bucket is
withheld, so feeds come from their GitHub branch, tiles from the shipped
assets and coast data from the Fish bridge. Public reads (`GET` on `/feeds/*`
except seafloor archives, `/api/daily`, `/api/forecast`, `/api/intelligence`,
`/api/habitat` and `/api/om/*`; `server/cost-ceiling.ts:110-117`) are answered
first from their last-known copy, the response saved the last time they were
served normally. Every degraded response carries `X-SC-Degraded:
cost-ceiling`, and a saved copy also carries `X-SC-Last-Known-At`. A public
read with neither a copy nor a free fallback answers `503` with
`Cache-Control: no-store`, `Retry-After: 600` and this JSON body
(`server/cost-ceiling.ts:211-215`):

```json
{"error":"Live data is paused for today to stay inside SkipperCast's free running budget, and no saved copy of this is held yet.","degraded":true}
```

The app sees the header and shows "Live
data is paused for today to keep SkipperCast free; some readings are saved
copies.", with the saved copy's time when it has one (`web/degraded.ts:55-58`),
on the desktop masthead and the mobile sheet (`web/app/Masthead.tsx:98`).

## Readers under a 429 or the cost-ceiling 503

Every client file that names `/feeds/`, `/api/daily`, `/api/om` or
`/api/coast` (`grep -rlE "/feeds/|/api/daily|/api/om|/api/coast" web dist`,
tests and the two data files under `dist/data/` left out) is below, as a
reader or under "Not a reader". Each answer was read from the code at the line
named. Meanings:

- **keeps last good**: the reader holds an earlier copy and goes on showing it.
- **shows the notice**: the page's cost-ceiling notice appears. The 503 carries
  `X-SC-Degraded` (`server/cost-ceiling.ts:211-215`), so the notice appears on
  the two pages that call `installDegradedWatch` (the app, `web/app/main.tsx:23`;
  the landing page, `web/landing/main.tsx:68`) and on no other page. A 429
  carries no such mark, so a 429 never shows the notice.
- **says unavailable**: the reader tells the user the data is not available.
- **throws to caller (X)**: the reader rethrows; X handles it.
- **not checked: reason**: the code cannot be read from here.

Two facts apply to every row. A degraded answer from a saved copy is a `200`
with the mark (`server/cost-ceiling.ts:195-208`), so a reader sees normal data;
only the `503` (no saved copy) is an error. And the `503` is sent only for
`/feeds/*` (seafloor archives excepted), `/api/daily` and `/api/om/*`
(`server/cost-ceiling.ts:113-117`, `:243`). `/api/coast/*` is not on that list:
past the ceiling it is answered, marked and without a saved-copy time
(`server/cost-ceiling.ts:217-222`, `:243`), and its own failures reach the reader as
non-OK answers like a 429.

| Reader (file:function) | Path(s) read | On 429 | On 503 degraded | Evidence |
| --- | --- | --- | --- | --- |
| `web/coast-data.ts:request` | `/api/coast/{report,ocean,history}` | keeps last good (an unexpired snapshot: report 3 h, ocean 6 h, history 36 h); with none it is `error`, and the views say unavailable. No retry until `refresh()` or a new place | not sent for this path; any non-OK answer is handled as the 429 is | `web/coast-data.ts:35-41`, `:198-199`, `:209-214` |
| `web/app/views/History.tsx:historyState` | `/api/coast/history` (through `coast-data.ts`) | keeps last good while the snapshot lives; else says unavailable ("Recorded history is unavailable right now…") | as 429; not sent for this path | `web/app/views/History.tsx:49-52`, `:60` |
| `web/app/Trip.tsx:save` | `/api/coast/{report,ocean,history}` (saved by `saveCoastal`) | keeps last good (the earlier saved readings stay) and says "Save failed. Previous saved readings are unchanged…" | as 429; not sent for this path | `web/app/Trip.tsx:128-130` |
| `dist/coastal-offline-core.js:saveCoastalSnapshot` | `/api/coast/{report,ocean,history}` | throws to caller (`web/trip.ts` `saveCoastal`, then `Trip.tsx`): a non-200 is "Complete readable snapshot unavailable", the half-written cache is removed and the committed snapshot is untouched | as 429; not sent for this path. A marked `200` is saved like a live one (only `X-SC-Offline` is refused) | `dist/coastal-offline-core.js:23`, `:28`, `:30` |
| `web/map/clouds.ts:cloudIndex` | `/feeds/conditions/goes-times.json` (and `/api/coast/ocean` through `coast-data.ts`) | keeps last good (the index in memory; its frames leave through the 90-minute gate); a first read that fails gives "no frames for this area" | as 429, plus shows the notice | `web/map/clouds.ts:81-86`, `:155-156` |
| `web/map/habitat-feed.ts:manifestLayer`, `allRows` | `/feeds/conditions/regions/<id>/habitat-dynamics.json` and its tiles | says unavailable (`state: 'error'`; the layers print "…unavailable"); no stored copy, no retry | as 429, plus shows the notice | `web/map/habitat-feed.ts:164`, `:176`, `:251`, `:343`; `web/map/sst.ts:156`, `web/map/currents.ts:117`, `web/map/contrast.ts:138`, `web/map/chlorophyll.ts:20` |
| `web/map/style.ts:basemapArchive` | `/feeds/tiles/basemap/manifest.json` | says unavailable on the Chart (`basemap` marked unavailable). On the landing page's night map: nothing shown, no notice (the static shoreline stays) | as 429; on the landing page the notice shows | `web/map/style.ts:25`; `web/map/chart.ts:194`; `web/landing/NightMap.tsx:134` |
| `web/reports.ts:loadReports` | `/feeds/data/recent-intel.json`, `/feeds/data/regions/<id>/latest.json`, the region's charter grounds | says unavailable, section by section (the other sections still show); no stored copy | as 429, plus shows the notice | `web/reports.ts:106-109`, `:115-117`; `web/app/views/Reports.tsx:62`, `:82` |
| `web/brief/Brief.tsx:readDaily`, `readFeed` | `/api/daily?part=brief`, `/feeds/data/regions/<id>/latest.json`, the conditions feed | the brief part falls back once to the whole daily feed (a different URL; no retry of the same one). A refresh that reads neither keeps last good. A first load that reads neither says unavailable ("Daily feed could not be read") | as 429, plus shows the notice | `web/brief/Brief.tsx:70-75`, `:82-85`, `:127-129`; `:64-68` |
| `web/landing/readings.ts:loadReadout` | `/feeds/conditions/regions/<id>/latest.json` | says unavailable (tiles read "No reading"); one read per page, no retry, no stored copy | as 429, plus shows the notice | `web/landing/readings.ts:173-181`, `:129` |
| `dist/daily-feed.js:loadDailyPart` | `/api/daily?part=…` | throws to caller (`dist/protected-areas.js`, which then reads the full daily feed) | as 429 | `dist/daily-feed.js:25`; `dist/protected-areas.js:8` |
| `dist/forecast.js:fetchJSON` | `/api/om/…` (and any URL passed in) | throws to caller (`dist/marine-data.js` `attempt`, `dist/live-conditions.js`, `dist/protected-areas.js`): "HTTP 429"; no retry here | as 429 | `dist/forecast.js:223-228` |
| `dist/marine-data.js:loadMarine` | `/api/om/v1/{forecast,marine}`, `/api/om/data/<model>/static/meta.json` | retries each failed URL once at once, then keeps last good (the same model's earlier result, in this tab, under 3 h, only when a `previous` is passed), else the model carries the error. Nothing in `web/` or `dist/` calls `loadMarine` at this head | as 429 | `dist/marine-data.js:307-313`, `:331-336`; `dist/morning-outlook.js:69` |
| `dist/status-page.js:load` | `/feeds/conditions/latest.json`, `/feeds/data/latest.json`, the coast and region feeds | says unavailable (the row reads "unavailable"); no stored copy | as 429, but no notice: `status.html` does not call `installDegradedWatch`, and a saved copy is shown with the feed's own time | `dist/status-page.js:35`, `:208-210` |
| `dist/recent-discussions.js:initRecentDiscussions` | `/feeds/data/recent-intel.json` | says unavailable ("Recent discussion search is unavailable…"). Nothing calls it at this head; the app uses only `recentDiscussionState` through `web/reports.ts` | as 429 | `dist/recent-discussions.js:42-44` |
| `dist/seafloor-data.js:loadManifest` | `/feeds/tiles/seafloor/manifest-<region>.json` | says unavailable ("Seafloor layer unavailable"); never uses a cached copy | not the ceiling's: this path is outside the saved-copy list (`server/cost-ceiling.ts:115`). A 503 from the route itself is read as its own body says (`updating`, else unavailable) | `dist/seafloor-data.js:38-50` |
| `dist/sw.js:networkFirstData`, `networkFirstCoastal` | `/feeds/*` (except `/feeds/tiles/seafloor/`), `/api/daily`, `/api/om/*`; `/api/coast/{report,ocean,history}` | returns the 429 itself. A saved copy is used only when the network request throws, never for an HTTP status | **saved file**: returns the 503; the saved copy in `sc-data` is not used. **unsaved file**: returns the 503. Both the same. A marked `200` is stored as a new copy (only status and type are checked) | `dist/sw.js:63-68`, `:119-121`, `:175-189`, `:221-226` |
| `web/shared-fetch.ts:shareStatic` | `/regions/…` and `/data/…` JSON only; `/feeds/` and `/api/` pass straight through | passes the answer on unchanged; no retry (a non-OK read is forgotten so the next caller asks again) | as 429 | `web/shared-fetch.ts:9`, `:18`, `:27`, `:76` |

### Not a reader

| File | Why |
| --- | --- |
| `web/map/habitat.ts` | `/api/daily` appears only in a comment on `validDailyPart` (line 132); it fetches nothing. |
| `dist/feeds.js` | Rewrites URLs to `/feeds/` (`feedURL`, `withFeeds`); it fetches nothing. |
| `dist/offline-core.js` | Builds the `/api/daily` URLs (`dailyPartPath`, `packRequests`); the fetching is in `dist/offline-pack.js` (not checked: outside the grep list). |
| `dist/data/daily-evidence.json`, `dist/data/source-catalog.json` | Data files that hold the path text; no code. |

### Readers the grep does not find

These build the paths through `dailyPartPath` or `feedURL` and so do not name them: `web/regs.ts`, `web/map/marks.ts`, `web/trip.ts`, `dist/offline-pack.js`, `dist/protected-areas.js`, `dist/coasts.js`, `dist/live-conditions.js`. Only `dist/protected-areas.js` was read (above). The rest: not checked: outside the 21-file list; each needs its own row.

### Gaps (nothing shown, no notice)

- The landing page's night map on a 429 of the basemap manifest: the map is dropped and the static shoreline stays, with no message (`web/landing/NightMap.tsx:124-129`).
- `status.html` shows a last-known copy on a degraded `200` with no notice, only the feed's own time.
- `dist/sw.js` never serves its saved copy for a 429 or a 503, so a reader behind it gets the error even when a saved copy exists.

This section changes no setting, limit, header or code; each gap becomes its own unit.
