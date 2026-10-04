# 01. Architecture

The Text Advisor is a new product area inside the existing Cloudflare Worker
(Hono, TypeScript, D1, R2, Queues, Analytics Engine). It adds no new runtime,
no new hosting account and no new language. The one new machine is the Mac
mini that relays iMessage; it runs nothing of ours except the BlueBubbles
server and a Cloudflare Tunnel.

## System context

```
                 ┌──────────────┐    iMessage/SMS    ┌──────────────────────────┐
  Skippers,      │  Phones      │◄──────────────────►│ Mac mini + spare iPhone  │
  crew, anglers  │ (iMessage,   │                    │ BlueBubbles server :1234 │
                 │  SMS, web)   │                    │ Cloudflare Tunnel        │
                 └──────┬───────┘                    └─────────┬──────▲─────────┘
                        │ web chat                 webhook POST│      │ REST (send)
                        ▼                                      ▼      │
┌─────────────────────────────────────────────────────────────────────┴─────────────┐
│ SkipperCast Worker (server/)                                                      │
│                                                                                   │
│  routes/advisor.ts   inbound webhooks (bluebubbles, twilio, meta), web chat,     │
│                      public port/species/boat pages, media serving               │
│  routes/admin.ts     passkey + admin role: review queue, skippers, rules, funnel │
│  advisor/            engine, channels, vision, intake, answers, social, pages    │
│                                                                                   │
│  D1 `DB`  (advisor_* tables)      R2 `ADVISOR_MEDIA` (private)                    │
│  Queue `ADVISOR_QUEUE` (+DLQ)     Analytics `ANALYTICS` (existing)                │
│  Cron (existing */15, advisor hooks)                                              │
└────────┬───────────────────────┬──────────────────────────┬───────────────────────┘
         │ Messages API          │ vision                   │ Graph API
         ▼                       ▼                          ▼
  Anthropic (Claude)     Hermes classifier (Tailscale    Meta: Instagram, Facebook Page
  text + vision fallback  + Cloudflare Tunnel, local)   (publish, Stories, DMs, insights)
```

## Request flow: an inbound text

1. **Webhook** `POST /api/advisor/inbound/bluebubbles` (or `/twilio`). It is
   mounted *before* the private gate in `server/app.ts`, like `/api/jobs/check`.
   The advisor router's first middleware (`server/advisor/gate.ts`) reads
   `advisorSettings(c.env).enabled` per request and answers
   `json({error: 'Not found'}, 404)` when `TEXT_ADVISOR_ENABLED` is not
   `true`; `app` is a module-level singleton and `env` exists only per
   request, so the mount itself is unconditional.
   Authentication: BlueBubbles sends no signature, so the webhook URL carries a
   secret path segment (`/api/advisor/inbound/bluebubbles/<ADVISOR_WEBHOOK_TOKEN>`)
   and the Mac is also the only origin the Tunnel allows; Twilio is verified by
   `X-Twilio-Signature` (HMAC-SHA1 over the public URL and sorted form params).
   A failed check answers 401 and logs a count, never the body.
2. **Normalize** the provider payload into `InboundMessage` (see `03-channels.md`).
   Drop `isFromMe` messages, reactions, typing events and anything with no
   text and no media. Drop duplicates: `advisor_messages.provider_id` is
   unique per channel; a second delivery answers 200 and does nothing.
3. **Persist** one `advisor_messages` row (direction `in`, status `queued`)
   and the media references (`advisor_media`, status `pending` until the
   consumer downloads them). Resolve or create the `advisor_contacts` row by
   phone hash.
4. **Enqueue** `{message_id}` on `ADVISOR_QUEUE` and answer `200 {}` within
   the provider's timeout. Without the queue binding (local dev, a deployment
   with `ENABLE_ADVISOR` off), the route runs the consumer inline under
   `waitUntil` so behaviour is identical, just not retried.
5. **Consumer** (`server/advisor/consumer.ts`, dispatched from the existing
   `queue()` export in `server/index.ts`): downloads media into
   `ADVISOR_MEDIA`, strips EXIF, runs the **engine** (`04-advisor-engine.md`),
   which returns a list of **actions**: send texts, send media, create or
   update a report draft, queue a social draft, open an admin review, set
   contact fields. Actions are applied in order inside one function so a crash
   mid-way leaves a consistent record (every action is idempotent by stable id,
   same discipline as `server/trips.ts`).
6. **Send** through the channel adapter the contact is on. Every outbound
   message is an `advisor_messages` row (direction `out`) written *before* the
   send with status `sending`, then `sent` or `failed` with the provider id.
   A retry never resends a message already `sent`.
7. **Record** one `llm` analytics point per model call (feature
   `advisor:<intent>`), one `advisor_turn` point per processed message (counts
   and timings only), and nothing identifying.

Budget: the consumer has the Worker's wall-clock allowance, not a 10 ms CPU
limit, so a two-turn Claude call with a vision step fits. Hard stops: 45 s
total per message, after which the person gets "Still working on that, one
moment" and the message is retried once with `retry({delaySeconds: 20})`.
The handler receives an `AbortSignal` that fires at the hard stop (pass it to
every `fetch`). If the retry also runs past 45 s the message is marked
`failed` and the contact gets the hourly-throttled apology, as on the
dead-letter path. Without a queue (`runInline`) nothing retries, so a failed
or timed-out turn goes straight to that dead-letter handling.

## Request flow: web chat

`POST /api/advisor/web/message` with a `sc_adv` cookie (random id, 90 days)
runs the same engine inline and returns the reply JSON; media uploads go to
`POST /api/advisor/web/upload` (multipart, 8 MB cap) and come back as a media
id the next message references. A web visitor who gives a phone number is
linked to that contact (`03-channels.md` § web). No queue is needed; the
engine function is the same one the consumer calls.

## Module layout

Everything new, with its job. File names are the contract: tasks in the
breakdown refer to them.

```
server/advisor/
  settings.ts        advisorSettings(env): flags, caps, model ids, channel choice (pure)
  types.ts           InboundMessage, OutboundMessage, Action, EngineResult, Contact, ...
  contacts.ts        phone hashing/encryption, contact lookup/create, STOP/forget-me
  consumer.ts        queue consumer + inline runner; media download; action applier
  engine.ts          one message in -> actions out: context build, Claude loop, tool dispatch
  intents.ts         cheap pre-router (keywords, language detect, commands) before any model call
  prompts/           system prompts and few-shots as .ts string exports, one file per role
  tools/             one file per Claude tool (schema + executor), see 04 § tools
  channels/
    index.ts         channelFor(env, contact): ChannelAdapter
    bluebubbles.ts   REST client + webhook normalizer
    twilio.ts        Messages API client + webhook normalizer + signature check
    web.ts           in-memory "send" that returns the reply to the HTTP caller
  vision/
    index.ts         VisionProvider interface, provider chain, result schema, caching
    hermes.ts        Hermes classifier client (contract in 07)
    claude.ts        Claude vision provider (count board, fish ID, person detect)
  intake/
    skippers.ts      registration, consent, crew, verification state
    reports.ts       count-board/plain-text parsing -> draft -> confirm -> publish, corrections
  answers/
    reports.ts       "what's biting" per port (daily cached answer)
    planning.ts      "is Saturday worth it" (reports + forecast feed + rules + advisories)
    rules.ts         rules table lookup and staleness
    advice.ts        rigging and area advice (catalog strategies + reports, never spots)
    fishid.ts        fish ID flow (vision + rules + look-alikes)
  social/
    meta.ts          Graph API client (IG + Page), token refresh, quota read
    drafts.ts        photo/video -> post draft (caption, tags, hashtags, CTA)
    publish.ts       one-approval publish to IG + FB, Stories, Reels, collab
    daily-post.ts    "what's biting" graphic + caption builder
    calendar.ts      cadence, slot filling, scheduler run from cron
    inbox.ts         IG DM + comment webhooks -> engine; keyword private replies
    insights.ts      per-post and account insights pull -> advisor_post_stats
  pages/
    render.ts        tiny HTML templating with escaping (no new dependency)
    port.ts, species.ts, boat.ts   public pages
    contact-card.ts  vCard generation
  admin/
    queue.ts         review items, approve/edit/reject
    skippers.ts      verify, edit, remove crew
    rules.ts         rules table CRUD + import from dist/data/regulations*.json
    funnel.ts        dashboard queries over Analytics Engine + D1
  cron.ts            advisorCron(env, now): daily answers, calendar, insights, token refresh, prune
  analytics.ts       recordAdvisorTurn, recordPublish (thin wrappers over server/analytics.ts)
server/routes/advisor.ts   public + webhook routes
server/routes/admin.ts     admin API (requireUser + requireAdmin)
web/admin/                 Preact admin app (islands pattern like web/islands.tsx)
web/advisor/               web chat island used by the site pages
dist/admin.html, dist/chat.html    page shells (Vite picks up every dist/*.html)
dist/advisor/              static assets for pages (css), graphics templates for daily posts
catalog/advisor/           seed data: rules import map, hashtags, caption styles, species look-alikes, ports → IG handles
scripts/advisor/           one-off owner scripts: grant-admin.mjs, import-rules.mjs, meta-token.mjs, relay-check.mjs
tests/test_advisor_*.mjs   node:test files; they must sit directly in tests/ to match the
                           `tests/test_*.mjs` glob CI runs (tests/contract/test_test_layout.py enforces it)
tests/fixtures/advisor/    recorded provider and model payloads: bluebubbles/, twilio/, meta/, engine/, vision/
docs/plans/text-advisor/   this plan
docs/operations/runbooks/advisor-*.md   relay-down, port-to-twilio, meta-token-expired, queue-stuck
```

## Feature flags, bindings, variables and secrets

Deploy-time (repository variables, read by `scripts/wrangler_config.mjs` and
`scripts/cloudflare_deploy.sh` from the deploy workflow's `env`). There is no
dashboard editing: `wrangler deploy` runs on every `main` commit and rewrites
the Worker's `vars` from the config, so every advisor setting is a repository
variable and changing one means a deploy (the workflow has
`workflow_dispatch`).

| Variable | Effect |
| --- | --- |
| `ENABLE_ADVISOR=true` | Bindings only. `cloudflare_deploy.sh` creates (idempotently, like the trip queues) the private R2 bucket `skippercast-advisor-media` and the queues `skippercast-advisor` and `skippercast-advisor-dlq`; `deployConfig` adds the bucket as `ADVISOR_MEDIA`, the queue producer `ADVISOR_QUEUE` and both consumer entries. The advisor queue is its own consumer entry, not shared with the trip queue. |
| `TEXT_ADVISOR_ENABLED`, `BLUEBUBBLES_PRIVATE_API`, `ADVISOR_*` (every var below) | `deployConfig` copies each of these that is present in `process.env` into `config.vars`, so the table below is also the list of repository variables. It refuses (throws) any name in the secrets table, so a secret can never land in plain vars. Because `ADVISOR_WEBHOOK_TOKEN` and `ADVISOR_PHONE_KEY` share the prefix, the deploy job passes those two to `cloudflare_deploy.sh` as `SECRET_ADVISOR_WEBHOOK_TOKEN` and `SECRET_ADVISOR_PHONE_KEY`, and the script's secrets list maps them back (the `WATCHDOG_GITHUB_TOKEN` → `GITHUB_TOKEN` pattern). The GitHub secret names stay `ADVISOR_WEBHOOK_TOKEN` and `ADVISOR_PHONE_KEY`. |

Runtime vars (all optional, read only through `advisorSettings()`):

| Var | Default | Meaning |
| --- | --- | --- |
| `TEXT_ADVISOR_ENABLED` | `false` | Hard switch. Off: every advisor route (webhooks included) answers 404, cron hooks no-op, the consumer acks and drops. |
| `ADVISOR_REPLIES_ENABLED` | `true` | Soft switch for bad-reply incidents: `false` keeps webhooks and the consumer running (inbound is stored, acked, marked `held`) but nothing is sent and no model is called. |
| `ADVISOR_NUMBER` | — | The owned number, E.164; used in the contact card, links and prompts. |
| `ADVISOR_CHANNEL` | `bluebubbles` | Which adapter sends outbound texts: `bluebubbles` or `twilio`. Inbound webhooks for both are always mounted so a port-in-progress loses nothing. |
| `BLUEBUBBLES_PRIVATE_API` | `false` | `true` enables typing-indicator and read-receipt calls (needs the Private API on the Mac). |
| `ADVISOR_ADMIN_CONTACT_ID` | — | The owner's contact id for the text-based admin fallback (08). |
| `ADVISOR_INBOX_PUBLIC_REPLIES` | `false` | Public replies to non-keyword Instagram comments (09). |
| `ADVISOR_MODEL` | `claude-sonnet-5` | Text model. Same validation as `BOAT_AI_MODEL`. |
| `ADVISOR_VISION_MODEL` | `claude-sonnet-5` | Claude vision fallback model. |
| `ADVISOR_VISION_PROVIDERS` | `hermes,claude` | Ordered provider chain. `claude` alone is valid. |
| `ADVISOR_DAILY_MESSAGES_PER_CONTACT` | `40` | OP-3 cap on inbound messages processed per contact per day. |
| `ADVISOR_DAILY_LLM_PER_CONTACT` | `30` | OP-3 cap on model calls per contact per day. |
| `ADVISOR_GLOBAL_DAILY_LLM` | `2000` | Global model-call ceiling per day. |
| `ADVISOR_GLOBAL_DAILY_VISION` | `400` | Global vision-call ceiling per day (Claude provider only; Hermes is local). |
| `ADVISOR_PUBLIC_BASE` | `https://skippercast.com` | Base for links in replies and for Meta-fetchable media URLs. |
| `ADVISOR_REGION_DEFAULT` | `morro-bay` | Region assumed when a contact has no home port yet. |
| `ADVISOR_AUTO_PUBLISH_AFTER` | `5` | SC-5: clean reports before auto-publish is offered. |
| `ADVISOR_SOCIAL_ENABLED` | `false` | Publishing to Meta; off means drafts queue but nothing posts. |
| `ADVISOR_INBOX_ENABLED` | `false` | IG DM and comment handling (needs Meta review). |

Secrets (uploaded by `scripts/cloudflare_deploy.sh`, each optional; a missing
secret disables the feature that needs it with a logged warning):

| Secret | Used by |
| --- | --- |
| `ANTHROPIC_API_KEY` | existing; engine and Claude vision |
| `ADVISOR_WEBHOOK_TOKEN` | BlueBubbles webhook path secret (32+ random bytes, base64url) |
| `BLUEBUBBLES_URL` | e.g. `https://relay.skippercast.com` (Cloudflare Tunnel to the Mac) |
| `BLUEBUBBLES_PASSWORD` | BlueBubbles server password |
| `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` | Cloudflare Access service token the Worker presents to the Tunnel |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | Twilio adapter and signature check |
| `HERMES_VISION_URL`, `HERMES_VISION_TOKEN` | Hermes provider (`07-vision.md`) |
| `META_APP_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN` | Graph API app, webhook verification |
| `META_IG_USER_ID`, `META_IG_TOKEN` | Instagram professional account id and long-lived token |
| `META_PAGE_ID`, `META_PAGE_TOKEN` | Facebook Page id and non-expiring Page token |
| `ADVISOR_PHONE_KEY` | 32-byte master key (base64); HKDF derives the phone-hash and phone-encryption subkeys (02) |
| `CF_ANALYTICS_TOKEN` | already a GitHub secret for `ops-report.yml`; also passed to the Worker for the admin funnel's Analytics Engine SQL reads (08) |
| `R2_ADVISOR_TOKEN` | GitHub secret only (never the Worker): an R2 token scoped to `skippercast-advisor-media` for the media runner job; `R2_PUBLISH_TOKEN` is scoped to the feeds bucket and is not reused |

Each secret is added to `scripts/cloudflare_deploy.sh` and
`.github/workflows/deploy-cloudflare.yml` in the task that first needs it
(both files are CODEOWNERS-protected, so those PRs need the owner's approval:
the breakdown marks them).

## Touch points in existing files

Every change outside the new directories, so reviewers can hold the author to
it. Each is a few lines.

| File | Change |
| --- | --- |
| `server/app.ts` | After `app.route('/', jobs);` add `app.route('/', advisorPublic);` (webhooks, pages, web chat; the router gates itself per request, see § request flow). After `app.route('/', privacy);` add `app.route('/', admin);` (guarded inside by `requireAdmin`). |
| `server/env.ts` | Add the bindings, vars and secrets listed above, each commented like the existing ones. `tests/test_worker_routes.mjs` checks the typed `Env` against `wrangler.jsonc` and against every `env.X` read under `server/`, so the optional bindings follow the `ANALYTICS?`/`TRIP_QUEUE?` pattern and every new var is declared before it is read. (The file's own header comment names a `tests/test_worker_types.mjs` that does not exist; fix the comment when next touching the file.) `R2_ADVISOR_TOKEN` is a GitHub secret only and is not in `Env`. |
| `server/index.ts` | In `scheduled()`: add `advisorCron(env, started)` to the `Promise.all`; its one-word outcome goes into `recordCron` as a new `advisor` field (blob6; documented in the `server/analytics.ts` header with the new `advisor_turn` and `publish` kinds). In `queue()`: branch on `batch.queue` for `ADVISOR_QUEUE_NAME` and `ADVISOR_DLQ_NAME` before the trip-check path. The generic type of the default export becomes a union of message types. |
| `scripts/wrangler_config.mjs` | `features()` gains `advisor`; `deployConfig` appends the advisor queue consumers/producer and the R2 bucket, and copies `TEXT_ADVISOR_ENABLED` and every `ADVISOR_*` present in the environment into `vars`. `tests/test_wrangler_config.mjs` gets the matching cases. |
| `db/schema.ts` | New tables appended (02). Existing tables untouched except `users`: one nullable column `role` (02). |
| `drizzle/0006_advisor_core.sql` … | Generated with `pnpm db:generate --name advisor_core` (drizzle-kit's `--name` gives the file its name), never hand-written; journal and snapshot committed. |
| `scripts/cloudflare_deploy.sh`, `.github/workflows/deploy-cloudflare.yml` | Under `ENABLE_ADVISOR=true`: create the bucket and the two queues before the deploy (same idempotent `queues info`/`create` and `r2 bucket create` pattern as the trip queues); pass the advisor vars through `env`; secret pass-through lines, with the two `ADVISOR_`-prefixed secrets renamed `SECRET_ADVISOR_*` in the workflow env (see the flags table). Done in TA-F1 except the secret lines, which each later task adds as it needs them. |
| `server/job-auth.ts`, `deployments/production.json` | `validJobClaims` pins `aud` to `/api/jobs/check` and `workflow_ref` to `scheduler.workflow` (`live-conditions.yml`). TA-M1 parameterises both: `verifyJobToken(token, policy, {audiencePath, workflows})`, and `deployments/production.json` gains `scheduler.workflows: ["live-conditions.yml", "advisor-media.yml"]` (the existing `workflow` key stays for the trip job). The media job requests its token with `audience: <public_origin>/api/advisor/jobs`. |
| `server/watchdog.ts` | Export `dispatchWorkflow(env, file, ref = 'main')` built from the private `github()` helper, so the advisor can trigger `advisor-media.yml` without a second GitHub client. |
| `scripts/build-worker.mjs`, `server/globals.d.ts` | A new build-time define `ADVISOR_ASSETS` (the Vite manifest entries for `advisor/pages.css`, `advisor/admin.css`, `advisor/chat.css` → hashed paths) so server-rendered pages can link hashed stylesheets; `SHELLS` maps only HTML. |
| `scripts/check_copy.mjs` | `copyFiles()` also lints `web/advisor/copy.ts`, where every user-facing string of the server-rendered pages lives (the templates import from it), so page copy stays under the copy lint. |
| `vite.config.mjs` | Nothing: `pages()` already picks up `dist/admin.html`, `dist/chat.html` and `dist/upload.html`. |
| `package.json` | No new runtime dependency (`twilio`, `@anthropic-ai/sdk` and `preact-render-to-string` were considered and rejected: the raw-fetch pattern in `server/boat-lookup.ts` is the house style, and server HTML is small). No change to the `test` script: advisor tests are `tests/test_advisor_*.mjs` and the existing glob runs them. |
| `pyproject.toml`, `scripts/pytest_report.py` | TA-M1: the `advisor` extra with exact pins (`tests/contract/test_packaging.py` requires `name==x.y.z`) and the allow-listed skip reason for a runner without `ffprobe`. |
| `docs/README.md`, `docs/engineering/api-reference.md`, `CHANGELOG.md`, `docs/engineering/adr/README.md` | Index lines. |
| `docs/legal/threat-model.md` | A new section for the webhook surface, the relay and the media bucket (task TA-C5). |
| `docs/legal/data-rights-register.md` | Row for skipper-submitted content (consent recorded per SK-2) and for Meta content terms. |

Nothing under `src/`, `regions/`, `research/`, `atlas/`, `catalog/*.json`
(other than new files in `catalog/advisor/`), or any existing workflow.

## Idempotency and failure rules

- Every row the consumer writes has a deterministic id derived from
  `(message_id, action_index)` so a retried message cannot double-send,
  double-post or double-draft.
- A send that fails after the provider accepted it (timeout) is marked
  `unknown`; the next cron run reconciles by querying the provider
  (BlueBubbles `GET /api/v1/message/:guid`, Twilio message status) before any retry.
- The DLQ consumer logs counts and acks; the contact gets one apology text
  ("Sorry, something went wrong on my end. Please send that again.") at most
  once per hour, recorded in `advisor_contacts.last_error_notice_at`.
- The relay watchdog (`cron.ts`): every 15 minutes `GET {BLUEBUBBLES_URL}/api/v1/ping`;
  three consecutive failures write `job_state` key `advisor.relay` = `down`, log an error
  line (Cloudflare alerting picks it up like the trip watchdog), and the
  admin dashboard shows the banner. Outbound sends while `down` are held
  (status `held`) for up to 6 hours, then the Twilio adapter is tried only if
  `ADVISOR_CHANNEL=twilio` has been set (the runbook step), never automatically,
  because a Twilio send from a number still registered to iMessage would fail.

## Security notes (summary; threat-model task has the full list)

- Webhooks: path secret + Tunnel origin allowlist (BlueBubbles), HMAC
  (Twilio, Meta). Bodies capped at 64 KB; media fetched by the consumer, never
  trusted from the webhook URL alone (Twilio media URLs are fetched with Basic
  auth; BlueBubbles attachments with the server password).
- Media: `ADVISOR_MEDIA` is private. Public pages serve a derived JPEG through
  `GET /media/:id.jpg` only for media with `publish_state in ('approved','posted')`;
  Meta fetches those same URLs. EXIF is stripped at download.
- Prompt injection: everything a contact sends is data. Tools that write
  (publish, verify, change rules) are admin-only and never callable from the
  engine; the engine can only *propose* (draft, review item). Content from
  Instagram comments and DMs is treated the same way.
- Admin role: `users.role='admin'` set by `scripts/advisor/grant-admin.mjs`
  (runs `wrangler d1 execute` with the owner's user id). Admin routes require
  a passkey session *and* the role; the Origin check applies as today.
- `securityHeaders` runs on every response (`app.use('*')`), including
  `/media/*` and the upload page; nothing opts out. CSP on an image response
  does not stop Meta fetching it. The upload page therefore submits with a
  JavaScript `fetch` (`connect-src 'self'` allows it), not a `<form>`
  (`form-action 'none'`).

## Cron slots

The only trigger is the existing `*/15 * * * *` (UTC). `cron.ts` defines
`runSlot(env, name, {local: 'HH:MM', tz: 'America/Los_Angeles'}, fn)`: on each
tick it computes the local date and time; if the local time is at or past
`local` and `job_state` key `advisor.slot.<name>` is not today's local date,
it claims the key with the same UPSERT-with-WHERE idiom as
`scheduleTripChecks` and runs `fn`. A slot therefore runs once per local day,
within 15 minutes of its time, and never twice. Weekly slots carry a
`weekday`. Every local time quoted in 05–09 is a slot name defined in one
table in `cron.ts`.
