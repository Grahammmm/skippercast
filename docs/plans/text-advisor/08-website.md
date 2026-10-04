# 08. Website: public pages, web chat, admin

Stories: WH-1, WH-2, WH-4, SK-5, FC-3, FC-5, OP-1, OP-5, OP-6, SK-4, SO-1,
SO-2, SO-4, SP-6, SP-10 (admin surfaces). Code: `server/advisor/pages/`,
`server/routes/advisor.ts`, `server/routes/admin.ts`, `web/advisor/`,
`web/admin/`, `dist/chat.html`, `dist/admin.html`, `dist/advisor/`.

## Public pages (server-rendered)

The existing site is a single-page map app. The advisor adds three
server-rendered page families so links in texts land on fast, shareable,
indexable pages that work without JavaScript. They are rendered in the
Worker by `pages/render.ts`, a 40-line template helper (tagged template
`html` with auto-escaping, `raw()` for trusted fragments), styled by
`dist/advisor/pages.css`. Vite hashes that file as part of `dist/chat.html`'s
stylesheet set, and `scripts/build-worker.mjs` exposes the hashed paths to
the Worker as the `ADVISOR_ASSETS` define (01 § touch points) because
`SHELLS` maps HTML pages only. Every user-facing string in the templates is
imported from `web/advisor/copy.ts`, which `scripts/check_copy.mjs` lints
(the templates themselves are not under the lint). No new dependency.

| Route | Content | Cache |
| --- | --- | --- |
| `GET /ports/<port-id>` | Port name and region; today's daily answer; published reports from verified boats, last 14 days, newest first (date, boat → boat page, trip, anglers, counts); unverified boats as "another boat" rows; conditions snapshot (reuses the API the map uses); active advisories; the boats list; species in season for the port (from `coastal-directory` data); "Text SkipperCast" CTA with the `sms:` link and a QR image (`/qr/text.svg`, generated once, static). | edge 5 min, key includes `advisor.pages.version` |
| `GET /species/<key>` | Species name, photo-free ID notes and look-alike cues (`lookalikes.json`), the rules card from `advisor_rules` with source and reviewed date (`#rules` anchor; `stale` rows show "under review"), recent catches of this species across ports (counts by date), the strategy summary (same source as `get_strategy`), CTA. | edge 15 min |
| `GET /boats/<slug>` | 05 § boat page. | edge 5 min |

The species page's names, description and sources come from
`catalog/advisor/species-pages.json` (TA-A3; 06 § As built (TA-A3)); its
season and rules card always comes from the rules table.

Edge caching uses `cached()`/`cacheKey()` with
`build: build() + ':' + pagesVersion` (05 § boat page); the TTLs above are
the `Cache-Control` max-age.
| `GET /contact.vcf`, `GET /text`, `GET /u/<token>`, `GET /media/<id>.jpg` | 03. | varies |

Each page has `<title>`, description, canonical, Open Graph image (the port
or boat's latest approved photo, else the existing preview), and JSON-LD
`Organization` + `BreadcrumbList`; pages are listed in a new
`dist/advisor/sitemap-advisor.xml` the Worker serves at `/sitemap-advisor.xml`
(generated on request from D1, cached 1 h) and referenced from `robots.txt`.
Copy lint (`scripts/check_copy.mjs`) runs over the templates; no "hotspot",
no probabilities, the standard disclaimer line from `docs/legal/disclaimers.md`
in the footer.

## Web chat (WH-2)

`dist/chat.html` is a page shell with a Preact island (`web/advisor/chat.tsx`)
and is also embedded on the three page families as a floating button that
opens a panel. The island:

- `POST /api/advisor/web/message` `{text, media_ids?}` → `{replies: [{text, links, media}], contact: {linked: boolean, language}}`.
  The engine runs inline (04); the request has a 40 s client timeout with a
  "still thinking" state.
- `POST /api/advisor/web/upload` (multipart, 8 MB) → `{media_id}`; images only.
- "Continue by text" button → the engine's `offer_text_link` flow (03).
- Stores nothing in `localStorage` except the collapsed/expanded state; the
  `sc_adv` cookie carries identity.
- Rate limit: `PUBLIC_LIMITER` 60/min per IP plus the per-contact daily cap.

As built (TA-C3): `dist/chat.html` + `web/advisor/chat-page.ts` (page text)
mount `web/advisor/chat.tsx` open; it is not embedded elsewhere yet (TA-W1).
`/chat.html` is gated like the advisor routes (404 while `TEXT_ADVISOR_ENABLED`
is off).
Both routes check `Origin` like private mutations and use the limiter key
`advisor-web:<ip>`; the per-contact daily cap is the engine's (TA-E1). The
server waits 40 s and then answers `{replies: [], pending: true}`; the island
shows "Thinking…", then "Still thinking" after 8 s, and gives up at 45 s.
Replies carry an `id` (the outbound row id) besides `text`, `links` (always
empty until TA-E1) and `media` (`/media/<id>.jpg` for derived images). The
island uploads a photo first and sends its id with the next message. The
footer's "Continue by text" offers `/text?s=web` and `/contact.vcf`; the
engine's `offer_text_link` flow replaces it in TA-E1. Strings are in
`web/advisor/copy.ts` (`CHAT_COPY`); `localStorage` holds only
`skippercast-chat-open`. The Playwright run turns the advisor on through
`e2e/serve.mjs` (`TEXT_ADVISOR_ENABLED=true`, test runs only).

## Admin (OP-1, OP-5, OP-6, SK-4, social approvals)

`dist/admin.html` + `web/admin/app.tsx` (Preact, hash-routed views) talking
to `server/routes/admin.ts`. The URL is `/admin.html` (the shell Vite
emits; views are `#queue`, `#skippers`, `#rules`, `#posts`, `#funnel`,
`#health`); `routes/admin.ts` also answers `GET /admin` with a redirect to
`/admin.html`. Access: passkey session (`requireUser`) and
`requireAdmin` (`users.role='admin'`, else 404 so the page's existence is
not confirmed to non-admins). All admin mutations are `POST` with the
Origin check that `requireUser` already applies.

| View | API | Shows / does |
| --- | --- | --- |
| **Queue** | `GET /api/admin/reviews?status=open`, `POST /api/admin/reviews/<id>` `{decision: 'approve'|'edit'|'reject', patch?, note?}` | One list, newest first, filterable by kind. Each item renders by kind: a media thumb with the vision labels and the `has_person` box; a report with its counts editable inline; a social draft with the image, caption editable, targets checkboxes, collaborator and tag fields, "post now" / "schedule"; a skipper registration with "verify"; a conversation with the last 6 messages and "reply as team" (sends through the channel, recorded as `out` with `created_by=admin`); a rule change with the diff of the CDFW page hash and a link. Keyboard: `a`/`r`/`e`. |
| **Skippers** | `GET /api/admin/boats`, `POST /api/admin/boats/<id>` (edit fields, verify, reject, consent note), `POST /api/admin/boats/<id>/crew` (remove), `POST /api/admin/boats/<id>/invite` (send a registration invite to a number the admin types; the number is hashed on receipt) | The recruiting tool for the pilot: list, status, last report, reports count, posts count, link clicks. |
| **Rules** | `GET /api/admin/rules?region=`, `POST /api/admin/rules` (create), `POST /api/admin/rules/<id>` (edit; sets `reviewed_at=now`, `review_due`, `status='active'`), `POST /api/admin/rules/import` (re-run the importer, new rows arrive as `review`) | Table editor; rows due for review highlighted; the CDFW change-watch (`pipeline/regulations.py` output in the daily feed) sets rows for that jurisdiction to `review` from the cron (OP-6). |
| **Posts** | `GET /api/admin/posts?status=`, `POST /api/admin/posts/<id>` (approve, schedule, reject, retry), `POST /api/admin/posts/daily` (generate today's daily post now) | The content calendar: a week grid of scheduled and posted items (SP-6), the drafts pool, per-post stats (SP-10). |
| **Funnel** | `GET /api/admin/funnel?days=` | OP-5: new contacts per day by `source`; messages by intent; replies per contact; link clicks (telemetry `s=txt`); site visits from social (`s=ig`, `s=fb`); chats started from posts (SP-10: contacts whose first message carried `[via ig:<post>]`); return rate (contacts with ≥ 2 active days / all); LLM and vision spend (tokens, calls) from Analytics Engine via the same SQL API `scripts/ops_report.py` uses, run from the Worker with `CF_ANALYTICS_TOKEN` passed as a secret (the Worker never writes to the API). Numbers only; no contact ids. |
| **Health** | `GET /api/admin/health` | Relay up/down and last ping, queue depth proxy (open `queued` messages older than 2 min), Hermes health, Meta token expiry (if Instagram Login is ever used) and publishing quota (`content_publishing_limit`), today's caps usage. The relay-down banner shows on every admin view. |
| **Contacts** | `GET /api/admin/contacts/<id>` (by id from a review item only; no search by number) | Conversation view for support, export, block. There is deliberately no "search by phone number" (CONTRIBUTING: no chat identifiers in casual reach); the admin finds a contact from a review item or a boat. |

As built (TA-W2): `server/middleware/admin.ts` (`requireAdmin`, `isAdminUser`,
`adminUser`), `server/routes/admin.ts` (mounted after `privacy`; `adminRoutes(deps)`
so tests pass a recording channel), `server/advisor/admin/queue.ts` (list and
per-kind detail), `server/advisor/admin/decisions.ts` (`decideReview`, the one
decision path for the queue and the text admin; the consumer's
`applyAdminReview` now calls it) and `server/advisor/admin/health.ts`. The
admin is also behind `TEXT_ADVISOR_ENABLED`: with the advisor off every admin
route is the 404, like the other advisor paths. `/admin.html` is served (no-store)
only to an admin; everyone else gets the plain 404 a missing page gets. The
built shell also exists at its hashed name (`admin.<build>.html`) like every
page and its bundle is precached like every hashed asset; neither holds data,
so the API's gate is the one that matters. Under `/api/admin/*` a signed-out
caller gets the private gate's 401, as for any `/api/` path.
Decisions (api-reference § Text Advisor admin): the kind's effect runs first,
then the text it owes (deterministic outbound id `sha256(<review id>:admin.skipper)`
for the verification, `sha256(<flagged message id>:team.<sha of the reply>)` for
"reply as team"), then the review closes with `UPDATE … WHERE status='open'`;
a repeat after that answers `repeated: true` and does nothing. An interrupted
decision is finished by repeating it. Report approve publishes like SC-5's
auto-publish (no `confirmed_at`, no clean count: the team publishing is not the
skipper confirming); report edit writes an `advisor_report_edits` row with
`contact_id` and `message_id` null; report reject sets `status='rejected'` and,
for a published report, bumps the pages version and drops the daily answer.
Verifying sets `verified_by` (null from the text admin) and also bumps the
pages version (05: the page re-renders). Media reject also takes an `approved`
photo back; a media approve, an edit, or a reject of an approved photo bumps
the pages version (TA-W1). "Reply as team" is refused (409) for a stopped or blocked contact
and while `ADVISOR_REPLIES_ENABLED` is off; other decisions still apply then and
say `held: 'replies-off'` instead of texting. Post decisions answer 400 until
TA-S1; skipper edits until TA-W3. The media route serves `thumb.jpg`, then
`public.jpg`, then a JPEG/PNG/GIF/WebP original that was not stored sideways
(`orientation` 2-8 waits for the job's upright files; `?v=original` any original).
Health reads the relay state, inbound `queued` older than 2 minutes, held
outbound, failures today, the vision providers' skip marks, today's global LLM
and vision counters, open reviews and the media job's backlog (`media.ts`
`mediaJobPending`: images without `derived_at`, including sideways ones, and
pending graphics); Meta is `null` until TA-S0. A media approve or edit in
`decideReview` calls `requestMediaJob`, so either admin path starts the job
for the photo's `public.jpg`. The app: `dist/admin.html` + `web/admin/app.tsx` (hash views;
`#skippers`, `#rules`, `#posts`, `#funnel` are placeholders), `queue.tsx`
(kind and status filters, 50 a page with "Load more", cards by kind, inline
report and credit editors, the reply box, a note field, `a`/`r`/`e` on a
focused card from `keys.ts`), `health.tsx`, `api.ts`, `dist/advisor/admin.css`;
strings in `web/advisor/copy.ts` `ADMIN_COPY`. The relay-down banner reads
the same health call (on load and every minute). `/api/session` has
`is_admin`. Tests: `tests/test_advisor_admin.mjs`, `e2e/admin.spec.ts` (passkey
sign-in, the role granted with `wrangler d1 execute --local`, a seeded photo
review approved with `a`, axe on the queue and Health).

Text-based admin fallback: when the owner replies to an admin notification
text (the engine sends the owner's contact, `role='admin-test'`, a text for
each new `review.skipper` and `review.media` item with a short code), `ok
<code>` / `no <code>` applies the decision. This covers the pilot before the
admin app is polished and is the only engine path that performs an admin
action; it checks `contact.role='admin-test'` and the contact id against
`ADVISOR_ADMIN_CONTACT_ID` (a var) and nothing else can reach it. As built (TA-E1):
the code is the first 6 hex characters of the review id; it must match
exactly one open `skipper` or `media` review. Verifying a `new_skipper`
review sets the boat `verified` (`verified_at`, no `verified_by`: the decider
is a contact, not a `users` row); rejecting it sets `rejected`. A `media`
decision sets `publish_state`. The review's `note` is `text admin`.

## Telemetry

Page views on `/ports`, `/species`, `/boats` go through the existing
`client_event` telemetry with the `s` source (`txt`, `ig`, `fb`, `qr`), and
the CTA click (`sms:` link) is a `client_event` `advisor_cta`. Nothing
identifying.

## As built (TA-W1)

Public pages in `server/advisor/pages/`, routes in `server/routes/advisor.ts`
(`// TA-W1` block). Where the code differs from the text above:

- **Template and layout.** `render.ts` has `html` (escapes every value; arrays
  join; `raw()` and nested `html` pass through), `jsonLd` (escapes `<`, `>`,
  `&`) and `layout()`: title, description, canonical (`?lang=es` for Spanish)
  with `hreflang` alternates, Open Graph image (the port's or boat's latest
  approved photo, else `/skippercast-parker-preview.jpg`), JSON-LD
  `Organization` and `BreadcrumbList` (only crumbs that have a page; there is
  no index of ports, species or boats), the stylesheet and script from
  `ADVISOR_ASSETS`, the CTA, the footer and the chat island host. It is longer
  than 40 lines because the shell lives there too.
- **Assets.** `dist/chat.html` links `advisor/pages.css`, so Vite builds it
  into the chat page's single stylesheet; `scripts/client-build.mjs`
  `advisorAssetPaths()` reads the chat page's manifest entry and
  `build-worker.mjs` defines `ADVISOR_ASSETS = {'advisor/pages.css': <its css>,
  'advisor/chat.js': <its script>}` (declared in `server/globals.d.ts`). The
  pages' styles are scoped to `body.adv-page`. The chat page's script imports
  `web/advisor/pages.ts` (telemetry), so the island mounts closed on every page.
- **Language.** `?lang=es|en`, else the first `Accept-Language` range that is
  English or Spanish; English by default. The cache key carries the resolved
  language. Strings are `PAGES_COPY` in `web/advisor/copy.ts` (en and es). The
  catalog method notes on the species page are English only and marked
  `lang="en"`, with a note on the Spanish page. The Spanish footer line
  translates caveats C1 and C3 and awaits the owner's review.
- **Port page.** Today's answer is the stored `advisor_daily_answers` row when
  its inputs hash is current (or a feed is down, as `dailyAnswer` does), else
  `composeDaily` of the same inputs; a page view never calls the model, and the
  link back to the page itself is dropped. Conditions and advisories come from
  the same `dailyInputs` (the fishing window at the port's forecast point).
  Reports: published, last 14 days; a report frozen as verified whose boat is
  still verified links the boat, every other one is "Another boat". Species
  and seasons: the `catalog/coasts.json` targets of the port's coast (else the
  region's species), expanded as `targetSpecies` does, each with today's state
  from `lookupRules`: open, closed, under review (stale) or "check the rules"
  (no row).
- **Species page.** Rules: every jurisdiction's active and review rows (the
  species pages are statewide), the default region's jurisdiction first,
  headed by the CDFW region; a species with no rows of its own shows its
  group's ("Group rule: …"). Recent catches count only published reports
  from verified boats (14 days, by date and port); a line counts when its
  `species_key` is the page key or its label names the species (a "vermilion"
  line filed under rockfish counts on the vermilion page). Method notes are
  `strategyFor(key, ADVISOR_REGION_DEFAULT)` with any sentence that mentions a
  hotspot, a percentage or odds dropped (`pageSafe`). A synonym path
  (`/species/california-halibut`) answers `301` to the page key.
- **Boat page.** `pending` boats have a page that says "Not verified yet" and
  carries `noindex` (05: their reports publish at once); `rejected` boats and
  unknown slugs are `404`. Photos: `kind='image'`, `approved`/`posted`, and
  servable by `/media` (a stripped JPEG original, or a derived `public.jpg`
  found with one `head`).
- **Cache.** `pageCacheKey(url, language, version)` =
  `cacheKey(<path>?lang=<language>, {build: build() + ':' + version})`;
  `?s=` and other parameters are not in the key. 404s are not cached. Admin
  decisions bump `advisor.pages.version` in `admin/decisions.ts`
  `decideReview`, so the admin app and the text admin purge alike: a boat
  verified or rejected, a photo approved, re-credited or taken back, a report
  published, edited or rejected.
- **CTA.** `sms:<ADVISOR_NUMBER>?&body=<message> [via web]` (the port page
  pre-fills "What's biting out of <port>?", which the daily pre-router answers
  without a model call), with "Save the number" and the QR image; without a
  number it links `/chat.html`.
- **Sitemap and robots.** `GET /sitemap-advisor.xml` (gated, 1 h) lists the
  ports of active regions, every species page and verified boats, each with
  its `?lang=es` alternate. There is no `dist/robots.txt`; `GET /robots.txt`
  answers from the Worker only while the advisor is on (allow all, plus the
  sitemap line) and otherwise falls through to the static site as before.
- **Telemetry.** New funnel events `advisor_port_view`,
  `advisor_species_view`, `advisor_boat_view` and `advisor_cta`; funnel events
  may carry `source` (`txt`, `ig`, `fb`, `qr` from the page URL's `s`), which
  the server validates and writes as `blob5` (docs/engineering/telemetry.md).
- **Tests.** `tests/test_advisor_pages.mjs` (template escaping, language,
  verified and unverified boats, the `<script>` boat inert in HTML, title and
  JSON-LD, stale rules, 404s, the cache key and a version bump, Spanish, no
  percentage or hotspot on any of the 34 species pages, ports and boats,
  sitemap, robots, telemetry) and `e2e/advisor-pages.spec.ts` (the three pages
  in the real Worker; axe on each). Its D1 rows are `e2e/seed/advisor-pages.sql`,
  which `e2e/serve.mjs` now loads (every `e2e/seed/*.sql`) after the migrations
  and before the Worker starts: seeding from a spec while other workers ran
  tests made page reads fail intermittently.
