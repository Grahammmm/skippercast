# Worker rate limits and D1 budgets

| Coverage | What the code does | Evidence |
| --- | --- | --- |
| Anonymous IP limits | `PUBLIC_LIMITER` allows 60 per 60 seconds per key; `FEED_LIMITER` allows 300. Routes choose their own keys. OM and daily count only cache misses; feeds and coast use middleware before the handler. | `wrangler.jsonc:43–49`; `server/routes/om.ts:24–35`; `server/routes/public.ts:84–96`; `server/routes/feeds.ts:11–13`; `server/routes/coast.ts:8–9` |
| Private API | IP check before session storage; then an account limit for GET or a D1 owner budget for non-GET. Passkey routes instead have their own D1 IP budget; the session probe has neither. | `server/app.ts:60–74`; `server/middleware/auth.ts:15–22`; `server/routes/auth.ts:12–21`; `server/routes/account.ts:13–19` |
| Anonymous work without a caller limit | Advisor media reads a separate R2 bucket; regional forecast, intelligence and habitat read the metered feed bucket on a miss. Advisor sitemap and health also do D1 reads. | `server/routes/advisor.ts:79–83,351–400,681–687`; `server/routes/public.ts:26–34,100–114`; `server/cost-ceiling.ts:234–240` |
| Global feed cost ceiling | Counts `FEEDS` reads, not calls. Default/configured 300,000 operations per UTC day across callers, checked against the isolate's current count and reconciled in D1 batches. Degradation can serve a saved response before any route-local limit. This is not an IP or owner quota and does not meter `ADVISOR_MEDIA`. | `wrangler.jsonc:34–41`; `server/cost-ceiling.ts:34–48,59–107,234–255`; `server/routes/advisor.ts:362–378,397` |

Source: staged `origin/main` at `9e078e2bd4c2db659e0f6e175c33cd6b0fd18553`, equal to the requested baseline. Offline source and test reading only; no deployment state, live endpoint behavior or external platform controls were verified.

## R1. Registered routes

`server/index.ts:67` dispatches HTTP to `app.fetch`; scheduled and queue work are not HTTP routes. The table has 140 method/pattern rows from the registration scan below. It expands literal registration loops but lists wildcard dispatchers once; passkey actions inside the auth wildcard are enumerated below. `ALL` means `.all`; implicit HEAD uses GET dispatch (`tests/test_worker_routes.mjs:246–251`). The first answering handler wins (`server/app.ts:1–7,44–76`). `none` means no caller request limiter or D1 request budget, not that no feature, access, cache or storage guard applies. Application-level keys are shared only when binding and key match (`server/middleware/rate-limit.ts:8–10`; `server/edge-cache.ts:82–90`). IP is `cf-connecting-ip` or the shared `unknown` value when absent.

| Shared limit in the route table | Binding / budget and location | Limit / window; key |
| --- | --- | --- |
| Private GET | `FEED_LIMITER` before identification; then `PUBLIC_LIMITER` after a session is found (`server/app.ts:64`; `server/middleware/auth.ts:15–22`). | 300 / 60 s by IP `private-ip:<ip>`; 60 / 60 s by account `account:<owner>` |
| Private non-GET | Same `FEED_LIMITER` before identification; after session and allowed Origin, D1 `budget()` (`server/middleware/auth.ts:15–22`; `server/http.ts:29–34`). | 300 / 60 s by IP `private-ip:<ip>`; 30 / fixed 60 s by owner ID |

D1 `budget()` hashes its supplied key plus the fixed window number into `request_limits.id`, increments first and then refuses counts above the limit (`server/http.ts:29–34`). Job keys are the verified token's `jti`, not the caller's IP or a site account. The table shows admission quotas; downstream work can have its own spend guards (for example, Advisor model caps in `server/advisor/engine.ts:135–151` and `server/advisor/vision/claude.ts:140–147`).

| Method | Pattern | Registration | Limit applied | Limit / window | Key |
| --- | --- | --- | --- | --- | --- |
| ALL | `/feeds` | `server/app.ts:48` | none | — | — |
| ALL | `/api` | `server/app.ts:49` | none | — | — |
| GET | `/feeds/*` | `server/routes/feeds.ts:11` | `FEED_LIMITER` (`server/routes/feeds.ts:11`) | 300 / 60 s | IP `feeds:<ip>` |
| GET | `/api/om/v1/forecast` | `server/routes/om.ts:34` | `PUBLIC_LIMITER` (`server/routes/om.ts:30`) on cache miss | 60 / 60 s | IP `om:<ip>` |
| GET | `/api/om/v1/marine` | `server/routes/om.ts:34` | `PUBLIC_LIMITER` (`server/routes/om.ts:30`) on cache miss | 60 / 60 s | IP `om:<ip>` |
| GET | `/api/om/data/:model{[a-z0-9_]+}/static/meta.json` | `server/routes/om.ts:35` | `PUBLIC_LIMITER` (`server/routes/om.ts:30`) on cache miss | 60 / 60 s | IP `om:<ip>` |
| ALL | `/api/health` | `server/routes/public.ts:21` | none | — | — |
| GET | `/api/habitat` | `server/routes/public.ts:26` | none | — | — |
| GET | `/api/fleet/public/heat` | `server/routes/public.ts:38` | `PUBLIC_LIMITER` (`server/routes/public.ts:38`) after feature flags | 60 / 60 s | IP `fleet-heat:<ip>` |
| ALL | `/api/fleet/public/*` | `server/routes/public.ts:39` | none | — | — |
| GET | `/api/intelligence` | `server/routes/public.ts:41` | none | — | — |
| GET | `/api/daily` | `server/routes/public.ts:46` | `PUBLIC_LIMITER` (`server/routes/public.ts:96`) on cache miss | 60 / 60 s | IP `daily:<ip>` |
| GET | `/api/forecast` | `server/routes/public.ts:98` | none | — | — |
| ALL | `/api/coast/*` | `server/routes/coast.ts:8` | `FEED_LIMITER` (`server/routes/coast.ts:8`) | 300 / 60 s | IP `coast:<ip>` |
| ALL | `/coast-data/*` | `server/routes/coast.ts:9` | `FEED_LIMITER` (`server/routes/coast.ts:9`) | 300 / 60 s | IP `coast:<ip>` |
| ALL | `/report` | `server/routes/coast-pages.ts:12` | `FEED_LIMITER` (`server/routes/coast-pages.ts:12`) | 300 / 60 s | IP `coast-page:<ip>` |
| ALL | `/feed.xml` | `server/routes/coast-pages.ts:12` | `FEED_LIMITER` (`server/routes/coast-pages.ts:12`) | 300 / 60 s | IP `coast-page:<ip>` |
| ALL | `/methodology` | `server/routes/coast-pages.ts:12` | `FEED_LIMITER` (`server/routes/coast-pages.ts:12`) | 300 / 60 s | IP `coast-page:<ip>` |
| ALL | `/about` | `server/routes/coast-pages.ts:12` | `FEED_LIMITER` (`server/routes/coast-pages.ts:12`) | 300 / 60 s | IP `coast-page:<ip>` |
| POST | `/api/telemetry` | `server/routes/telemetry.ts:13` | `PUBLIC_LIMITER` (`server/routes/telemetry.ts:13`) | 60 / 60 s | IP `telemetry:<ip>` |
| POST | `/api/jobs/check` | `server/routes/jobs.ts:12` | D1 `budget()` (`server/routes/jobs.ts:16`) | 30 / fixed 60 s | Verified job `job:<jti>` |
| GET | `/api/advisor/health` | `server/routes/advisor.ts:79` | none | — | — |
| POST | `/api/advisor/inbound/bluebubbles/:token` | `server/routes/advisor.ts:136` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:108`) | 60 / 60 s | IP `advisor-inbound:<ip>` |
| POST | `/api/advisor/inbound/twilio/:token` | `server/routes/advisor.ts:142` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:108`) | 60 / 60 s | IP `advisor-inbound:<ip>` |
| POST | `/api/advisor/inbound/twilio-status/:token` | `server/routes/advisor.ts:145` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:147`) | 60 / 60 s | IP `advisor-inbound:<ip>` |
| GET | `/api/advisor/inbound/meta` | `server/routes/advisor.ts:176` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:177`) | 60 / 60 s | IP `advisor-inbound:<ip>` |
| POST | `/api/advisor/inbound/meta` | `server/routes/advisor.ts:182` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:184`) | 60 / 60 s | IP `advisor-inbound:<ip>` |
| GET | `/u` | `server/routes/advisor.ts:253` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:239`) | 60 / 60 s | IP `advisor-upload:<ip>` |
| GET | `/u/:token` | `server/routes/advisor.ts:283` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:269`) | 60 / 60 s | IP `advisor-upload:<ip>` |
| POST | `/api/advisor/upload/:token` | `server/routes/advisor.ts:284` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:269`) | 60 / 60 s | IP `advisor-upload:<ip>` |
| POST | `/api/advisor/upload` | `server/routes/advisor.ts:287` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:289`) | 60 / 60 s | IP `advisor-upload:<ip>` |
| GET | `/media/:file` | `server/routes/advisor.ts:351` | none | — | — |
| GET | `/media/post/:post/:name` | `server/routes/advisor.ts:391` | none | — | — |
| GET | `/contact.vcf` | `server/routes/advisor.ts:411` | none | — | — |
| GET | `/text` | `server/routes/advisor.ts:435` | none | — | — |
| GET | `/qr/text.svg` | `server/routes/advisor.ts:443` | none | — | — |
| POST | `/api/advisor/web/message` | `server/routes/advisor.ts:472` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:475`) | 60 / 60 s | IP `advisor-web:<ip>` |
| POST | `/api/advisor/web/upload` | `server/routes/advisor.ts:528` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:531`) | 60 / 60 s | IP `advisor-web:<ip>` |
| GET | `/my-data` | `server/routes/advisor.ts:560`; `server/advisor/exports.ts:25` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:239`) | 60 / 60 s | IP `advisor-upload:<ip>` |
| GET | `/api/advisor/export/:token` | `server/routes/advisor.ts:561` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:269`) | 60 / 60 s | IP `advisor-export:<ip>` |
| POST | `/api/advisor/export` | `server/routes/advisor.ts:562` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:564`) | 60 / 60 s | IP `advisor-export:<ip>` |
| GET | `/api/advisor/jobs/media` | `server/routes/advisor.ts:605` | D1 `budget()` (`server/routes/advisor.ts:595–602`) | 240 / fixed 60 s | Verified job `advisor-job:<jti>` |
| POST | `/api/advisor/jobs/media-done` | `server/routes/advisor.ts:611` | D1 `budget()` (`server/routes/advisor.ts:595–602`) | 240 / fixed 60 s | Verified job `advisor-job:<jti>` |
| GET | `/ports/:id` | `server/routes/advisor.ts:670` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:653`) on render miss | 60 / 60 s | IP `advisor-page:<ip>` |
| GET | `/ports/:id/` | `server/routes/advisor.ts:670` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:653`) on render miss | 60 / 60 s | IP `advisor-page:<ip>` |
| GET | `/ports/` | `server/routes/advisor.ts:670` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:653`) on render miss | 60 / 60 s | IP `advisor-page:<ip>` |
| GET | `/species/:key` | `server/routes/advisor.ts:672` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:653`) on render miss | 60 / 60 s | IP `advisor-page:<ip>` |
| GET | `/boats/:slug` | `server/routes/advisor.ts:679` | `PUBLIC_LIMITER` (`server/routes/advisor.ts:653`) on render miss | 60 / 60 s | IP `advisor-page:<ip>` |
| GET | `/sitemap-advisor.xml` | `server/routes/advisor.ts:681`; `server/advisor/pages/sitemap.ts:12` | none | — | — |
| GET | `/robots.txt` | `server/routes/advisor.ts:691` | none | — | — |
| GET | `/api/fleet/jobs/ping` | `server/routes/fleet.ts:111` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| GET | `/go/:slug` | `server/routes/fleet.ts:117` | `PUBLIC_LIMITER` (`server/routes/fleet.ts:117`) after feature flag | 60 / 60 s | IP `fleet-go:<ip>` |
| GET | `/api/fleet/jobs/snapshot` | `server/routes/fleet.ts:119` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| POST | `/api/fleet/jobs/registry` | `server/routes/fleet.ts:124` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| POST | `/api/fleet/jobs/activity` | `server/routes/fleet.ts:129` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| POST | `/api/fleet/jobs/heartbeat` | `server/routes/fleet.ts:134` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| GET | `/api/fleet/jobs/health` | `server/routes/fleet.ts:139` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| GET | `/api/fleet/jobs/watch` | `server/routes/fleet.ts:144` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| POST | `/api/fleet/jobs/watch` | `server/routes/fleet.ts:149` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| GET | `/api/fleet/jobs/labels` | `server/routes/fleet.ts:154` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| POST | `/api/fleet/jobs/labels` | `server/routes/fleet.ts:160` | D1 `budget()` (`server/routes/fleet.ts:67,91–109`) | 240 / fixed 60 s | Verified job `fleet-job:<jti>` |
| ALL | `/api/auth/*` | `server/routes/auth.ts:12` | D1 `budget()` (`server/routes/auth.ts:12–17`) | 20 / fixed 60 s | IP `auth:<ip>` |
| GET | `/api/session` | `server/routes/account.ts:13` | none | — | — |
| GET | `/api/privacy` | `server/routes/account.ts:30` | Private GET | See shared limits | See shared keys |
| DELETE | `/api/privacy` | `server/routes/account.ts:39` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/boat/lookup` | `server/routes/boat.ts:20` | Private non-GET + D1 lookup counters on cache miss (`server/routes/boat.ts:28–35`) | Plus 20 per owner and 500 global by default / UTC day (`wrangler.jsonc:40`; `server/boat-lookup.ts:20–27`) | Plus owner `hash(owner + ":boat:" + day)` and global `global:boat:<day>` |
| GET | `/api/trips` | `server/routes/trips.ts:17` | Private GET | See shared limits | See shared keys |
| POST | `/api/trips` | `server/routes/trips.ts:21` | Private non-GET | See shared limits | See shared keys |
| PATCH | `/api/trips` | `server/routes/trips.ts:32` | Private non-GET | See shared limits | See shared keys |
| DELETE | `/api/trips` | `server/routes/trips.ts:55` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/events/ack` | `server/routes/trips.ts:60` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/catch-log` | `server/routes/catch-log.ts:84` | Private GET | See shared limits | See shared keys |
| GET | `/api/catch-log/:id` | `server/routes/catch-log.ts:98` | Private GET | See shared limits | See shared keys |
| POST | `/api/catch-log` | `server/routes/catch-log.ts:102` | Private non-GET | See shared limits | See shared keys |
| PATCH | `/api/catch-log/:id` | `server/routes/catch-log.ts:114` | Private non-GET | See shared limits | See shared keys |
| DELETE | `/api/catch-log/:id` | `server/routes/catch-log.ts:131` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/spots` | `server/routes/spots.ts:27` | Private GET | See shared limits | See shared keys |
| GET | `/api/spots/:id` | `server/routes/spots.ts:29` | Private GET | See shared limits | See shared keys |
| POST | `/api/spots` | `server/routes/spots.ts:33` | Private non-GET | See shared limits | See shared keys |
| PATCH | `/api/spots/:id` | `server/routes/spots.ts:44` | Private non-GET | See shared limits | See shared keys |
| DELETE | `/api/spots/:id` | `server/routes/spots.ts:60` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/subscription` | `server/routes/subscriptions.ts:12` | Private non-GET | See shared limits | See shared keys |
| DELETE | `/api/subscription` | `server/routes/subscriptions.ts:26` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/subscription/status` | `server/routes/subscriptions.ts:45` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/subscription/test` | `server/routes/subscriptions.ts:55` | Private non-GET + D1 `budget()` (`server/routes/subscriptions.ts:60`) | Plus 3 / fixed 86,400 s | Plus owner `push-test:<owner>` |
| POST | `/api/comfort` | `server/routes/feedback.ts:9` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/comfort` | `server/routes/feedback.ts:16` | Private GET | See shared limits | See shared keys |
| DELETE | `/api/comfort/:id` | `server/routes/feedback.ts:17` | Private non-GET | See shared limits | See shared keys |
| GET | `/admin` | `server/routes/admin.ts:141` | none | — | — |
| GET | `/admin.html` | `server/routes/admin.ts:142` | none | — | — |
| GET | `/api/admin/reviews` | `server/routes/admin.ts:158` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/reviews/:id` | `server/routes/admin.ts:165` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/reviews/:id` | `server/routes/admin.ts:171` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/admin/media/:id` | `server/routes/admin.ts:190` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/health` | `server/routes/admin.ts:208` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/meta/subscribe` | `server/routes/admin.ts:210` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/fleet/map/:layer` | `server/routes/admin.ts:218` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/boats` | `server/routes/admin.ts:222` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/boats/:id` | `server/routes/admin.ts:223` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/boats/invite` | `server/routes/admin.ts:228` | Private non-GET + D1 invite counter (`server/advisor/admin/skippers.ts:43–44,297`) | Plus 20 / UTC day | Plus global `admin:skipper-invite:<day>` |
| POST | `/api/admin/boats/:id` | `server/routes/admin.ts:233` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/boats/:id/crew/:contactId/remove` | `server/routes/admin.ts:238` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/admin/contacts/:id` | `server/routes/admin.ts:239` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/contacts/:id/export` | `server/routes/admin.ts:243` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/funnel` | `server/routes/admin.ts:251` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/rules` | `server/routes/admin.ts:258` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/rules` | `server/routes/admin.ts:262` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/rules/:id/retire` | `server/routes/admin.ts:263` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/rules/:id` | `server/routes/admin.ts:264` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/admin/posts` | `server/routes/admin.ts:267` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/posts/calendar` | `server/routes/admin.ts:272` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/posts/:id/graphics/:name` | `server/routes/admin.ts:276` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/posts/:id` | `server/routes/admin.ts:285` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/posts/:id/publish` | `server/routes/admin.ts:293` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/posts/:id/schedule` | `server/routes/admin.ts:294` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/posts/:id/retry` | `server/routes/admin.ts:295` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/capability` | `server/routes/admin.ts:298` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/clicks` | `server/routes/admin.ts:301` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/reviews` | `server/routes/admin.ts:310` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/fleet/reviews/:id` | `server/routes/admin.ts:312` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/vessels` | `server/routes/admin.ts:313` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/vessels/:id` | `server/routes/admin.ts:316` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/fleet/vessels/:id/link-advisor` | `server/routes/admin.ts:320` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/fleet/vessels/:id` | `server/routes/admin.ts:321` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/operators` | `server/routes/admin.ts:325` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/operators/:id` | `server/routes/admin.ts:327` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/fleet/operators/:id` | `server/routes/admin.ts:328` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/operators/:id/outreach` | `server/routes/admin.ts:329` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/fleet/operators/:id/outreach` | `server/routes/admin.ts:330` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/fleet/outreach/:id` | `server/routes/admin.ts:331` | Private non-GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/coverage` | `server/routes/admin.ts:334` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/ais/health` | `server/routes/admin.ts:338` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/trips` | `server/routes/admin.ts:344` | Private GET | See shared limits | See shared keys |
| GET | `/api/admin/fleet/trips/:id` | `server/routes/admin.ts:346` | Private GET | See shared limits | See shared keys |
| POST | `/api/admin/fleet/trips/:id/labels` | `server/routes/admin.ts:347` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/fleet/labels/:id/delete` | `server/routes/admin.ts:348` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/fleet/trips/:id/approve` | `server/routes/admin.ts:349` | Private non-GET | See shared limits | See shared keys |
| POST | `/api/admin/contacts/:id/block` | `server/routes/admin.ts:354` | Private non-GET | See shared limits | See shared keys |
| ALL | `/api/*` | `server/app.ts:74` | Private GET or non-GET before the 404 | See shared limits | See shared keys |
| ALL | `*` | `server/routes/assets.ts:150` | none | — | — |

`/api/auth/*` is the one Hono registration. Its internal actions all use the same 20 / fixed 60 s D1 budget keyed by IP `auth:<ip>` (`server/routes/auth.ts:12–21`). It applies before Origin and session checks (but after the identity-provider gate); unknown subpaths also spend it. Bare `/api/auth` falls through to the private gate (`server/routes/auth.ts:13–16`; `server/app.ts:64,74`).

| Method | Auth action | Dispatch and access |
| --- | --- | --- |
| POST | `/api/auth/register/options` | `server/auth.ts:144`, no session required |
| POST | `/api/auth/register/verify` | `server/auth.ts:151`, no session required |
| POST | `/api/auth/login/options` | `server/auth.ts:159`, no session required |
| POST | `/api/auth/login/verify` | `server/auth.ts:164`, no session required |
| POST | `/api/auth/logout` | `server/auth.ts:183`, no session required |
| GET | `/api/auth/sessions` | `server/auth.ts:189–190`, session required |
| POST | `/api/auth/sessions/end-others` | `server/auth.ts:189–190`, session required |
| GET | `/api/auth/passkeys` | `server/auth.ts:200–205`, session required |
| POST | `/api/auth/passkeys/options` | `server/auth.ts:200–210`, session required |
| POST | `/api/auth/passkeys` | `server/auth.ts:200–218`, session required |
| DELETE | `/api/auth/passkeys` | `server/auth.ts:200–202,220–227`, session required |

**Ordering details.** Hono matches HEAD as GET but gives the handler the original request (pinned `package.json:22`; inspect installed `node_modules/hono/dist/hono-base.js:262–272`). Thus a HEAD matched to a private GET reaches the non-GET Origin/budget branch, not the account-read check (`server/middleware/auth.ts:19–20`). HEAD on `/go/:slug` still reaches the IP limit but does not write the click (`server/fleet/go.ts:76–84`). The Advisor page limit is *after* the D1 version read and edge-cache lookup; canonical port/species redirects may return earlier (`server/routes/advisor.ts:645–679`; `server/advisor/pages/data.ts:18–23`). `/admin` and `/admin.html` have a role check, not a rate limit, and never serve the admin shell anonymously (`server/routes/admin.ts:141–150`; `server/middleware/admin.ts:23–33`). Advisor and fleet gates may return 404 without reaching a named handler (`server/routes/advisor.ts:74–76,629`; `server/advisor/gate.ts:13–16,33–42`; `server/routes/fleet.ts:47–53,107–109`; `server/fleet/public-heat.ts:102–114`); `/chat.html` is a gated asset, not a separate response registration. The bare `/feeds` and `/api` mounts and the final `*` mount serve bundled assets, not R2 directly (`server/app.ts:47–50,74–75`; `server/routes/assets.ts:92–114,150`; `wrangler.jsonc:12–15`).

**Reproduce from the source checkout:** `git rev-parse origin/main`; `git grep -nE '\.(route|use|all|get|post|put|patch|delete|head|options|on)\(' -- server/app.ts server/routes`; `git grep -nE 'rateLimit\(|overLimit\(|budget\(|request_limits' -- server wrangler.jsonc`; `git grep -n '/api/auth/' -- server/auth.ts`. Separate router registrations from data lookups in the first grep; follow `.use` and the mount order, not just handler names.

## R2. Anonymous work without a caller limit, ranked by estimated cost per call

Rank is an **estimate**, not pricing or a live measurement. It compares work done by the Worker on a successful call with no usable cache entry; object size, range requests, storage state and cache hits can change the order. Equal ranks indicate similar source paths.

| Estimated rank | Anonymous `none` route | Work and constraints |
| --- | --- | --- |
| 1 | `GET /media/:file` | A D1 eligibility read, followed by up to two R2 reads (video HEAD + GET or image fallback); a video can stream a full object or a range. Advisor feature and media state checks still apply. `server/routes/advisor.ts:74–75,351–381`. |
| 2 | `GET /media/post/:post/:name` | D1 post-state and graphic checks, then one R2 graphic GET. Advisor feature and publication-state checks still apply. `server/routes/advisor.ts:74–75,391–400`; `server/advisor/social/graphics.ts:58–66`. Neither media row uses the `FEEDS` meter (`server/cost-ceiling.ts:234–240`). |
| 3 (tie) | `GET /api/intelligence`, `GET /api/forecast` | On a miss, both load and parse the same regional intelligence feed and prepare both responses, priming the other route's cache. The published URL is an R2 logical name, not a GitHub request (`server/routes/public.ts:100–114`; `regions/morro-bay/region.json:564`; `server/feeds.ts:11–25,111–126,134–147`). The metered read can also contribute to a batched D1 counter update (`server/cost-ceiling.ts:77–104,249–255`). |
| 4 | `GET /api/habitat` | On a miss, read and parse the regional habitat feed from the same metered R2 storage; no sibling response. `server/routes/public.ts:26–34`; `regions/morro-bay/region.json:565`; `server/feeds.ts:134–147`; `server/cost-ceiling.ts:234–240`. |
| 5 (conditional) | `GET /api/session` | No session storage work without a cookie; a supplied session cookie can trigger a D1 lookup. A recognized expired session can be deleted (the request still returns signed out); a recognized aging session can be renewed (signed in). `server/routes/account.ts:13–19`; `server/middleware/context.ts:29–33`; `server/auth.ts:64–76`. |

Other `none` work worth separating: `/sitemap-advisor.xml` does a D1 version lookup even on an edge hit; on a miss it can do bounded boat/vessel queries and render XML (`server/routes/advisor.ts:681–687`; `server/advisor/pages/sitemap.ts:25–46`). `/api/advisor/health` reads stored relay status from D1, not the relay itself (`server/routes/advisor.ts:79–83`; `server/advisor/relay.ts:12–21`). These are D1 reads, not writes. `/text` sends a redirect, not an SMS or third-party request (`server/routes/advisor.ts:435–440`). The other `none` rows return static assets, in-process metadata/rendering/redirects, or refusals, not a third-party service or an AI call (R1 registrations). Fleet click writes, telemetry ingestion, and AI boat lookup are excluded because they have request limits (`server/routes/fleet.ts:117`; `server/fleet/go.ts:72–84`; `server/routes/telemetry.ts:13–26`; `server/routes/boat.ts:20–39`).

## R3. Missing bindings and existing tests

`wrangler.jsonc:43–49` describes the no-op but names only OM and feeds. `overLimit` returns false if the binding lacks a callable `limit`, if the call throws/rejects, or if the result does not explicitly say `success: false` (`server/edge-cache.ts:79–94`). An explicit rejection returns JSON 429, `Retry-After: 60` and `Cache-Control: no-store`. Missing bindings do not turn off flags, authentication, Origin checks, D1 budgets, daily lookup counters or the global `FEEDS` ceiling (`server/middleware/auth.ts:15–22`; `server/http.ts:24–34`; `server/routes/boat.ts:28–35`; `server/cost-ceiling.ts:234–255`). In contrast, `budget()` needs D1 and does not fail open if storage is missing or fails (`server/http.ts:9,30–34`; `server/middleware/error.ts:15–32`).

| Existing test source (read only) | Limited path it covers |
| --- | --- |
| `tests/test_cache.mjs:198–271` | OM and feeds thresholds and retry header; OM cache-hit bypass, missing/throwing limiter, shared OM key; daily cache-hit bypass and separate bucket; binding config. |
| `tests/test_worker_routes.mjs:270–278`; `tests/test_telemetry.mjs:96–106` | Built Worker feed refusal; telemetry refusal and IP key. |
| `tests/test_cost_ceiling.mjs:259–286`; `tests/test_accounts.mjs:109–123,422–428,630–639`; `tests/test_worker_http.mjs:118–128` | Private account and pre-session IP refusal; D1 auth IP budget and private 30-write owner budget. `tests/test_cost_ceiling.mjs:133–193` separately covers global degradation and batched counting. |
| `tests/test_subscription_test_push.mjs:97–116`; `tests/test_private_api.mjs:196–231`; `tests/test_advisor_admin_skippers.mjs:264–277` | Daily push test, boat global cap before model spend, and admin invite daily counter. The boat test is not proof of the per-owner 20-call threshold. |
| `tests/test_advisor_bluebubbles.mjs:306–312`; `tests/test_advisor_twilio.mjs:185–191`; `tests/test_advisor_web_chat.mjs:220–232`; `tests/test_public_pages.mjs:149–162` | Advisor inbound and web 429s, page-render refusal. These do not show a direct refusal test for each other Advisor route that shares a key. |
| `tests/test_fleet_go.mjs:168–182`; `tests/test_fleet_public_heat.mjs:84–117` | `/go/:slug` tests flag-first order and 429. Public heat tests flags and anonymous success but not limiter denial. |
| `tests/test_job_cursor.mjs:49–115`; `tests/test_fleet_jobs.mjs:61–111`; `tests/test_advisor_media_jobs.mjs:56–78` | Job auth, order or budget path, not exhaustion of the 30/240-call job quotas. |

Coverage discovery: `git grep -nE 'PUBLIC_LIMITER|FEED_LIMITER|Retry-After|request_limits|429' -- 'tests/*.mjs'`; actual request/refusal assertions above are distinct from tests that only mock an upstream 429 or inspect UI copy. No direct refusal assertion was found for coast or public heat in that search.

## R4. One proposed follow-up (estimate: under two hours)

Test only, if separately admitted: extend `tests/test_fleet_public_heat.mjs` at the existing flag test (`:84–102`). Use in-memory fixtures and the real Worker router. With both flags on, have a synthetic limiter deny the call; assert 429, `Retry-After: 60`, the heat route's IP key, and zero D1 prepares. With a flag off, assert 404 and no limiter call. This catches accidental deletion or reordering of the middleware relative to the D1 read (`server/routes/public.ts:38`; `server/fleet/public-heat.ts:102–114`), which the current anonymous-200 case cannot detect. Offline acceptance: `node --test tests/test_fleet_public_heat.mjs` with the fixture cases executed, not skipped. No cap, flag, policy or code change is proposed here.
