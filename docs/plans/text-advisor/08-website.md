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

Text-based admin fallback: when the owner replies to an admin notification
text (the engine sends the owner's contact, `role='admin-test'`, a text for
each new `review.skipper` and `review.media` item with a short code), `ok
<code>` / `no <code>` applies the decision. This covers the pilot before the
admin app is polished and is the only engine path that performs an admin
action; it checks `contact.role='admin-test'` and the contact id against
`ADVISOR_ADMIN_CONTACT_ID` (a var) and nothing else can reach it.

## Telemetry

Page views on `/ports`, `/species`, `/boats` go through the existing
`client_event` telemetry with the `s` source (`txt`, `ig`, `fb`, `qr`), and
the CTA click (`sms:` link) is a `client_event` `advisor_cta`. Nothing
identifying.
