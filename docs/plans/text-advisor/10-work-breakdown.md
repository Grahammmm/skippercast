# 10. Work breakdown

One task = one branch = one PR, named `claude/ta-<id-lowercase>` (for example
`claude/ta-f1`). Sizes: **S** under a day, **M** one to two days, **L** three
to five days of agent work including tests. **Owner** tasks are the owner's
to do; the engineering side ships the scripts and runbooks they need and
then waits. Every code task ends with the checks in `AGENTS.md` § "Before
opening a PR" (the `node --test tests/test_*.mjs` glob already covers
`tests/test_advisor_*.mjs`).

`.github/CODEOWNERS` gives the owner every file under `server/`,
`.github/workflows/`, `wrangler.jsonc`, `deployments/` and `docs/legal/`, so
**nearly every task below needs the owner's approval on GitHub** in addition
to the independent review `AGENTS.md` requires. The "owner approval" marker
is kept only on tasks that touch workflows, `deployments/`, `docs/legal/` or
secrets, where the owner must also *do* something.

Catalog data and code: `AGENTS.md` says to split source data from app code.
The `catalog/advisor/*.json` files are the advisor's own seed data with no
other consumer, so the tasks that introduce them ship them with the code
that reads them (one PR), stated here as the deliberate exception; later
edits to those files are their own S PRs.

Dependencies are strict: do not start a task before its dependencies are
merged to `main`. Tasks in the same phase with no dependency between them can
run in parallel on separate branches.

The deploy stays dark throughout: `ENABLE_ADVISOR` is set to `true` only at
TA-P1, and `TEXT_ADVISOR_ENABLED` in production only then.

## Phase 0: foundations (nothing user-visible)

### TA-F1 · Settings, flags, bindings and mount points · S · needs owner approval (CODEOWNERS)
- Stories: none directly; enables everything.
- Depends: —
- Files: `server/advisor/settings.ts`, `server/advisor/types.ts`, `server/advisor/gate.ts`, `server/env.ts`, `server/app.ts`, `scripts/wrangler_config.mjs`, `scripts/cloudflare_deploy.sh`, `.github/workflows/deploy-cloudflare.yml` (advisor vars through `env`; bucket and queue creation under `ENABLE_ADVISOR`), `server/routes/advisor.ts` (router with the gate middleware and `/api/advisor/health` only), `tests/test_advisor_settings.mjs`, `tests/test_wrangler_config.mjs`, `tests/test_worker_routes.mjs`, `docs/engineering/api-reference.md`.
- Build: `advisorSettings(env)` parses every var in 01 with the same validation style as `lookupSettings`; `features()` gains `advisor`; `deployConfig` adds the R2 bucket and the queue pair and copies `TEXT_ADVISOR_ENABLED`/`ADVISOR_*` from the environment into `vars`; `app.ts` mounts `advisorPublic` after `jobs` unconditionally and `gate.ts` answers 404 per request when the flag is off; `GET /api/advisor/health` answers `{enabled, channel, providers}` with no secrets.
- Tests: settings defaults and overrides; deploy config with and without `ENABLE_ADVISOR` (bindings, vars); the route is 404 with the flag off and 200 on, using two `env` objects against the same `app`; the `Env` type matches `wrangler.jsonc` and every `env.X` read.
- Done when: `main` deploys unchanged behaviour; the health route exists behind the flag.

### TA-F2 · Core schema, contacts and privacy primitives · M
- Stories: FC-4 (data model side), privacy invariants.
- Depends: TA-F1
- Files: `db/schema.ts`, `drizzle/0006_advisor_core.sql` (+ journal, snapshot, via `pnpm db:generate -- --name advisor_core`), `server/advisor/contacts.ts`, `server/advisor/log.ts` (`advisorLog`), `scripts/advisor/grant-admin.mjs`, `tests/test_advisor_contacts.mjs`, `tests/test_advisor_privacy.mjs`, `tests/test_migrations.mjs` (passes unchanged).
- Build: tables in 02 for migration 0006 (`advisor_contacts`, `advisor_boats` with `status`, `advisor_crew`, `advisor_messages`, `advisor_media`, `advisor_reports`, `advisor_report_edits`, `advisor_reviews`, `users.role`); `phoneHash`, `encryptPhone`, `decryptPhone` (AES-GCM via WebCrypto, key from `ADVISOR_PHONE_KEY`), `e164(input)` normalizer (US default, rejects short codes), `findOrCreateContact`, `applyStop`, `forgetContact` (the D1 batch in 02), `exportContact`.
- Tests: hash is deterministic and keyed; encrypt/decrypt round-trip; e164 cases; forget-me deletes every row and nulls `advisor_reports.contact_id`; `advisorLog` redacts numbers; the fixture directory contains no E.164.
- Done when: migrations apply on a fresh D1 in `wrangler dev`; `grant-admin.mjs` sets `role` for a given user id.

### TA-F3 · Queue consumer skeleton and cron hook · M · needs owner approval (`server/index.ts`, `wrangler.jsonc` touched)
- Depends: TA-F2
- Files: `server/advisor/consumer.ts`, `server/advisor/cron.ts`, `server/advisor/analytics.ts`, `server/index.ts`, `tests/test_advisor_consumer.mjs`, `tests/test_advisor_cron.mjs`.
- Build: `AdvisorMessage = {message_id}`; `consumeAdvisor(batch, env, deps)` loads the row, marks `processing`, runs a pluggable `handler` (the engine lands in TA-E1; here a stub that replies "SkipperCast is warming up"), applies actions, acks or retries with backoff, DLQ consumer acks and writes the apology at most hourly; `runInline(env, message_id, ctx)` for no-queue deployments; `advisorCron(env, now)` with `runSlot` exactly as defined in 01 § cron slots (local-time slots claimed in `job_state`) and the relay watchdog stub; `recordAdvisorTurn`, `recordPublish`, and the `advisor` field (blob6) on `recordCron` with the `server/analytics.ts` header updated for the three new/changed kinds.
- Tests: ack/retry/DLQ paths with a fake batch; idempotent outbound ids; a slot runs once per local day and not before its time, across a DST change; analytics points carry no ids.

### TA-O1 · Owner: number, Apple Account, iPhone, Mac mini, BlueBubbles, tunnel · Owner
- Depends: — (parallel with phase 0)
- Deliverable from engineering first: `docs/operations/runbooks/advisor-relay-setup.md` (the checklist in 03 expanded step by step with screenshots-free precise menu paths), `scripts/advisor/relay-check.mjs` (TA-C1 ships it; the owner runs it after).
- Done when: `relay-check.mjs` reports ping ok, one iMessage and one SMS delivered to the owner's phone, and the secrets `BLUEBUBBLES_URL`, `BLUEBUBBLES_PASSWORD`, `CF_ACCESS_CLIENT_ID/SECRET`, `ADVISOR_WEBHOOK_TOKEN`, `ADVISOR_PHONE_KEY`, `ADVISOR_NUMBER` are in GitHub secrets.

## Phase 1: channels and media

### TA-C1 · BlueBubbles adapter and webhook · L · owner approval (deploy secret lines)
- Stories: FC-1 (transport), OP-7 (health).
- Depends: TA-F3
- Files: `server/advisor/channels/index.ts`, `channels/bluebubbles.ts`, `server/routes/advisor.ts` (`POST /api/advisor/inbound/bluebubbles/:token`), `scripts/advisor/relay-check.mjs`, `scripts/cloudflare_deploy.sh`, `.github/workflows/deploy-cloudflare.yml`, `tests/fixtures/advisor/bluebubbles/*.json`, `tests/test_advisor_bluebubbles.mjs`, `docs/operations/runbooks/advisor-relay-setup.md`, `docs/operations/runbooks/advisor-relay-down.md`.
- Build: 03 § BlueBubbles in full; the inbound route (token check, 64 KB cap, normalize, dedupe, persist, enqueue or inline, 200 fast); `splitForChannel`; relay watchdog in `cron.ts` (`advisor.relay` state, hold logic).
- Tests: every fixture normalizes as specified (text, photo, video, SMS-forwarded MMS, reaction ignored, group ignored, echo ignored, send error marks row); token mismatch 401; duplicate provider id is a no-op; send builds the right chat GUID and multipart; health parses `server/info`.
- Done when: with the owner's relay, texting the number gets the stub reply within 5 s (manual check recorded in the PR).

### TA-C2 · Twilio adapter (dark) · M
- Stories: OP-7.
- Depends: TA-C1
- Files: `channels/twilio.ts`, `server/routes/advisor.ts` (`/inbound/twilio/:token`, `/inbound/twilio-status/:token`), fixtures, `tests/test_advisor_twilio.mjs`, deploy secret lines (`TWILIO_*`).
- Build: 03 § Twilio: signature validation with the public URL, form parsing, media fetch with Basic auth, send with `MediaUrl`, status callback, 21610 → stopped; confirm against Twilio's current docs which of STOP/HELP are forwarded to the webhook and record it in 03.
- Tests: signature vectors computed in the test from a known token; STOP forwarded path; media parameters; send body shape.

### TA-C3 · Web chat adapter, API and island · M
- Stories: WH-2 (transport), FC-1 on web.
- Depends: TA-C1
- Files: `channels/web.ts`, routes `/api/advisor/web/message`, `/api/advisor/web/upload`, `web/advisor/chat.tsx`, `dist/chat.html`, `dist/advisor/chat.css`, `tests/test_advisor_web_chat.mjs`, `e2e/advisor-chat.spec.ts`.
- Build: 08 § web chat; the `sc_adv` cookie; inline engine run; rate limits.
- Tests: cookie issued once; message round trip with the stub handler; upload size cap; Playwright: open panel, send, see reply.

### TA-C4 · Media intake, EXIF strip, R2 storage, upload link, media serving · L
- Stories: SC-1, SC-3, SP-3 (storage side), OP-2 (storage side), privacy principle 7.
- Depends: TA-C1
- Files: `server/advisor/media.ts` (download, sniff incl. HEIC, `stripJpegMetadata` keeping APP0 and the ICC APP2, `stripPngMetadata`, SOF size read, sha256 dedupe, R2 put), routes `GET /u/:token`, `POST /api/advisor/upload/:token`, `GET /media/:id.:ext`, `dist/upload.html` (JavaScript `fetch` upload; `form-action 'none'` blocks a plain form), `tests/test_advisor_media.mjs` with crafted JPEG/PNG fixtures (built in the test from bytes, no binaries committed except two tiny files).
- Tests: APP1 removed, APP0 and ICC APP2 kept, other APPn removed, image still decodes (checked by a marker re-walk); PNG chunks removed with CRCs intact; sniffing rejects a renamed HTML file and accepts HEIC; dedupe links the second upload; token expiry; media route 404 when `publish_state='private'`.

### TA-C5 · Threat model, privacy scan, data-rights rows · S · owner approval (`docs/legal/`)
- Depends: TA-C4
- Files: `docs/legal/threat-model.md` (new section), `scripts/check_repository.py` (the 02 § privacy regex over `tests/fixtures/advisor/` and `docs/plans/text-advisor/`; handles against `catalog/advisor/fixture-handles.json`), `docs/legal/data-rights-register.md` (skipper content with consent; Meta platform terms), `CONTRIBUTING.md` (one line: advisor transcripts and media are private records).

### TA-C6 · Contact card, deep links, source attribution · S
- Stories: FC-3, FC-5.
- Depends: TA-C1
- Files: `pages/contact-card.ts`, routes `/contact.vcf`, `/text`, `/qr/text.svg`, `server/advisor/intents.ts` (source marker parsing `[via <source>]`), tests.
- Tests: vCard fields; `/text?s=ig&m=hi` redirects to `sms:<number>?&body=` with the marker appended; first message strips the marker and stores `source`. Manual check on one iPhone and one Android recorded in the PR.

### TA-C7 · Runbooks: relay down, port to Twilio, 10DLC package · S
- Stories: OP-7.
- Depends: TA-C2
- Files: `docs/operations/runbooks/advisor-port-to-twilio.md` (03 § runbook, full text, with the 10DLC campaign description, sample messages, HELP/STOP wording), `docs/operations/runbooks/advisor-relay-down.md` (diagnosis tree), `docs/README.md` index lines.

### TA-O3 · Owner: Twilio account, number-port readiness, 10DLC registration · Owner
- Depends: TA-C7 for the paste-ready text; not blocking any engineering.
- Done when: a Twilio account exists with the brand and campaign approved and `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` in secrets (`TWILIO_FROM` stays unset until a port).

## Phase 2: engine, vision, skipper intake

### TA-E1 · Engine core: guards, commands, language, model loop, rules guard, links · L
- Stories: FC-1, FC-2, FC-4, FC-6, OP-3, OP-4, WH-1 (links).
- Depends: TA-C1, TA-C4
- Files: `server/advisor/engine.ts`, `intents.ts`, `links.ts`, `prompts/system.ts`, `prompts/examples.ts`, `tools/index.ts` (registry, role filtering), `tools/update_profile.ts`, `tools/escalate.ts`, `tools/send_upload_link.ts`, `tools/send_contact_card.ts`, fixtures `tests/fixtures/advisor/engine/`, `tests/test_advisor_engine.mjs`, `test_advisor_prompts.mjs`, `scripts/advisor/eval.mjs`, `consumer.ts` (wire the engine as the handler).
- Build: 04 in full except the data tools; the system prompt is written here and the PR asks the owner to read it.
- Tests: as listed in 04 § tests. The rules guard test feeds a reply containing "14 inch minimum" with no `get_rules` call and asserts the replacement and the review item.

### TA-E2 · Data tools: port report (interim), conditions, rules (interim), species, strategy, trips · M
- Stories: FR-1 (interim), FR-2 (data), AD-1, AD-2, AD-3, ID-2 (data).
- Depends: TA-E1
- Files: `tools/get_port_report.ts`, `get_conditions.ts`, `get_rules.ts`, `get_species.ts`, `get_strategy.ts`, `get_trips.ts`, `answers/advice.ts`, `answers/confidence.ts`, `answers/comfort.ts`, `catalog/advisor/public-grounds.json`, `catalog/advisor/port-aliases.json`, `catalog/advisor/species-synonyms.json`, `catalog/advisor/species-extra.json`, `tests/test_advisor_tools.mjs`.
- Build: until TA-A0 lands, `get_rules` reads `dist/data/regulations*.json` directly and always returns `stale: true` (so every rules answer says "double-check"); `get_port_report` returns skipper reports only (no daily answer yet). `get_conditions` reads the regional feeds with `readFeed` and its own parsers (06 § planning); `answers/confidence.ts` and `answers/comfort.ts` are the server re-implementations pinned by test to the `web/` fixtures.
- Tests: each tool against feed fixtures already in `tests/fixtures`; `get_strategy` never returns a coordinate (regex over the output); public-grounds allowlist filters a non-public spot name.

### TA-V1 · Vision interface, Claude provider, thresholds, synthetic fixtures · M
- Stories: OP-8, ID-1, ID-3, SC-1 (reading), OP-2 (detection).
- Depends: TA-C4
- Files: `vision/index.ts`, `vision/claude.ts`, `prompts/vision.ts`, `catalog/advisor/lookalikes.json`, `catalog/advisor/protected.json`, `tests/fixtures/advisor/vision/`, `tests/test_advisor_vision.mjs`, `scripts/advisor/make-fixture-images.mjs` (SVG → PNG at build time; committed PNGs under 50 KB).
- Tests: schema-forced tool output parses into each result type; thresholds table; cache in `classification_json`; global cap; 10-minute skip after failure; an original over 4.5 MB is routed to the media job and re-queued rather than sent.

### TA-V2 · Hermes provider and conformance script · S
- Stories: OP-8.
- Depends: TA-V1
- Files: `vision/hermes.ts`, `scripts/advisor/vision-conformance.mjs`, `docs/plans/text-advisor/07-vision.md` (status line: contract handed to Hermes on <date>), deploy secret lines (`HERMES_VISION_URL`, `HERMES_VISION_TOKEN`).
- Tests: client maps responses and errors; chain prefers hermes then claude; conformance script passes against a local mock server in the test.
- Owner step inside: hand the contract to the Hermes side; the chain runs Claude-only until Hermes passes conformance.

### TA-I1 · Skipper registration, consent, crew, verification state, boat slug · M
- Stories: SK-1, SK-2, SK-3, SK-4 (state), FC-2 for skippers.
- Depends: TA-E1
- Files: `intake/skippers.ts`, `tools/register_boat.ts`, `tools/add_crew.ts`, `tools/remove_crew.ts`, `engine.ts` (stage 2 registration and consent flows), fixtures, `tests/test_advisor_skippers.mjs`.
- Tests: the state machine over a scripted conversation in English and Spanish; port alias matching; consent recorded with the message id; crew invite text sent through the adapter and credited on reply; only the owner can remove crew.

### TA-I2 · Reports: count board, plain text, confirmation, corrections, auto-publish offer (dark) · L
- Stories: SC-1, SC-2, SC-4, FR-4 (dates), SK-5 (data for the page); SC-5 (Next) is built here behind `ADVISOR_AUTO_PUBLISH_AFTER` because it is the same code path, and stays off.
- Depends: TA-I1, TA-V1
- Files: `intake/reports.ts` (`draftFromBoard`, `parseCountText`, `parseCorrection`, publish, invalidate), `tools/read_count_board.ts`, `propose_report.ts`, `edit_report.ts`, `engine.ts` (pending-confirm flow, pre-router for count text), `tests/test_advisor_reports.mjs` with a table of 40 count-text and 20 correction phrasings (en/es).
- Tests: grammar table; uncertain lines get `?`; unique constraint turns a second board into an edit; `clean_reports` increments and resets; `y`/`n`/correction/other paths; `auto` toggles.

### TA-I3 · Angler photo sharing and fish-ID flow glue · S
- Stories: AC-1, ID-1, ID-2, ID-3.
- Depends: TA-I2, TA-E2
- Files: `answers/fishid.ts`, `tools/identify_fish.ts`, `tools/share_angler_photo.ts`, `engine.ts` (media-only angler path), tests.
- Tests: the three confidence bands produce the specified reply shapes; protected-species line; the AC-1 offer only when ≥ 0.6 and not a skipper; credit asked once.

## Phase 3: angler answers

### TA-A0 · Migration 0007 and the rules importer · M
- Stories: OP-6 (data).
- Depends: TA-F2
- Files: `db/schema.ts`, `drizzle/0007_advisor_answers.sql` (`pnpm db:generate -- --name advisor_answers`), `scripts/advisor/import-rules.mjs` (reads `dist/data/regulations*.json` and `jurisdictions/*.json`, writes `review` rows via `wrangler d1 execute` SQL it prints or applies with `--apply`), `answers/rules.ts`, `tools/get_rules.ts` (switch to the table), `tests/test_advisor_rules.mjs`.
- Tests: importer maps every species in the regulations files to a row; staleness by `review_due`; the tool never returns `retired`; `review` rows are `stale: true`.

### TA-A1 · Daily answers: generator, cron, pre-router, both languages · M
- Stories: FR-1, FR-4, FC-6 (daily es).
- Depends: TA-A0, TA-I2
- Files: `answers/reports.ts`, `prompts/daily.ts`, `cron.ts` (05:30 slot and the publish-time invalidation), `engine.ts` (pre-router match), fixtures, `tests/test_advisor_daily.mjs`.
- Tests: inputs hash changes when a report publishes; no reports → the "no reports in three days" text; unverified boats anonymized; length ≤ 480; no `%`; Spanish output present.

### TA-A2 · Planning brief with advisories and the confidence ladder · M
- Stories: FR-2, AD-4.
- Depends: TA-E2, TA-A1
- Files: `answers/planning.ts`, `tools/get_conditions.ts` (date parsing, window), `prompts/system.ts` (confidence words section), tests with a feed fixture carrying a Small Craft Advisory.
- Tests: advisory first; horizon message beyond 7 days; weekend → two days; only the three confidence words appear.

### TA-A3 · Species pages data, look-alikes review, protected list · S
- Stories: ID-2, WH-4 (data).
- Depends: TA-A0
- Files: `catalog/advisor/lookalikes.json` (complete for the 20 species in `catalog/species.json`, each cue with a CDFW source URL), `catalog/advisor/protected.json`, `docs/plans/text-advisor/06-angler-answers.md` (source list).
- Owner review: the owner reads the cues in the PR (fishing knowledge check).

### TA-A4 · Rules admin API, change-watch hook · M
- Stories: OP-6.
- Depends: TA-A0, TA-W2
- Files: `admin/rules.ts`, `routes/admin.ts` (rules endpoints), `cron.ts` (read the daily feed's regulation change flags → set jurisdiction rows to `review`), `web/admin/rules.tsx`, tests.

### TA-A5 · Trips tool from verified boats, newcomer answers · S
- Stories: AD-3.
- Depends: TA-I1, TA-E2
- Files: `tools/get_trips.ts` (switch from stub to `advisor_boats`), tests.

### TA-A6 · Spanish pass · S
- Stories: FC-6.
- Depends: TA-A1, TA-I2
- Files: `prompts/examples.ts` (es), `intake/*.ts` (every user-facing string through `t(language, key)` in `server/advisor/strings.ts`), `catalog/advisor/strings.json`, tests asserting every key has both languages.

## Phase 4: media job, public pages, admin

### TA-M1 · `advisor-media` runner job: derived images and graphics · L · owner approval (workflow)
- Stories: SP-4 (story image), SO-2 (graphic), SK-5 (page images), SP-5.
- Depends: TA-C4, TA-F3
- Files: `.github/workflows/advisor-media.yml` (`workflow_dispatch` only, self-hosted runner, job-level `if`), `scripts/advisor/media_job.py`, `catalog/advisor/graphics.json`, `pyproject.toml` (`[project.optional-dependencies] advisor = ["Pillow==<exact>", "pillow-heif==<exact>"]`: `tests/contract/test_packaging.py` requires exact pins), `scripts/pytest_report.py` (allow-list the skip reason `ffprobe is not installed on this runner`), `server/job-auth.ts` (parameterised audience path and workflow list), `deployments/production.json` (`scheduler.workflows`), `server/watchdog.ts` (export `dispatchWorkflow`), routes `GET /api/advisor/jobs/media`, `POST /api/advisor/jobs/media-done`, `server/advisor/media.ts` (pending list, done handler, dispatch on demand and from cron while pending), `tests/unit/test_advisor_media_job.py`, `tests/test_advisor_media_jobs.mjs`, `tests/test_job_auth.mjs` (new cases).
- Owner step: create `R2_ADVISOR_TOKEN` (R2 read/write scoped to `skippercast-advisor-media`) as a GitHub secret.
- Build: 09 § derived images; the job is idempotent (skips keys that exist with the same source sha); Story footer and daily graphic drawn from the JSON layout; HEIC conversion; `ffprobe` validation when available (skips with the exact allow-listed reason when absent).
- Tests: Python: resize bounds, footer text present (pixel check of the band colour), graphic renders from a fixture payload; Node: endpoints auth and payload shapes.

### TA-W1 · Public pages: port, species, boat, sitemap, telemetry source · L
- Stories: WH-4, SK-5, WH-1 (targets), FC-5 (CTA).
- Depends: TA-I2, TA-A1, TA-A3, TA-M1
- Files: `pages/render.ts`, `pages/port.ts`, `pages/species.ts`, `pages/boat.ts`, `pages/sitemap.ts`, `web/advisor/copy.ts` (all page strings; added to `scripts/check_copy.mjs`), `dist/advisor/pages.css`, `scripts/build-worker.mjs` and `server/globals.d.ts` (`ADVISOR_ASSETS` define), `routes/advisor.ts` (routes, edge cache keyed on `advisor.pages.version` as in 05), `web/telemetry.ts` (`s` source if missing), `dist/robots.txt` (if present) or the assets route, `e2e/advisor-pages.spec.ts`, `tests/test_advisor_pages.mjs`.
- Tests: escaping (a boat named `<script>` renders inert); verified/unverified rendering; cache key bump after publish; copy lint passes; axe check in e2e.

### TA-W2 · Admin shell, health, review queue · L
- Stories: OP-1, OP-2, SK-4, OP-7 (banner).
- Depends: TA-I2, TA-F2
- Files: `server/middleware/admin.ts` (`requireAdmin`), `routes/admin.ts` (also `GET /admin` → `/admin.html`), `admin/queue.ts`, `admin/skippers.ts` (verify/reject), `web/admin/app.tsx`, `web/admin/queue.tsx`, `dist/admin.html`, `dist/advisor/admin.css`, `routes/account.ts` (`is_admin` on `/api/session`), tests, `e2e/admin.spec.ts` (signs in with the passkey fixture used by `e2e/app.spec.ts`; grants the role by running, from the spec via `child_process`, `npx wrangler d1 execute skippercast --local --persist-to .wrangler/e2e-state --config <the e2e wrangler config e2e/serve.mjs writes> --command "UPDATE users SET role='admin' WHERE id=…"` after the account exists; approves a seeded review).
- Tests: 404 for non-admins; decisions update the referenced rows (media approve → `approved`, report edit → edit row + version, skipper verify → `verified_at` and the text to the skipper via the fake adapter); keyboard shortcuts.

### TA-W3 · Admin skippers, contacts, invite · M
- Stories: SK-3, SK-4, pilot recruiting.
- Depends: TA-W2
- Files: `admin/skippers.ts` (list, edit, crew removal, invite), `web/admin/skippers.tsx`, `web/admin/contact.tsx`, tests.

### TA-W4 · Funnel dashboard and text-based admin fallback · M · owner approval (secret `CF_ANALYTICS_TOKEN` to the Worker)
- Stories: OP-5, SP-10 (data), OP-1 (fallback).
- Depends: TA-W2
- Files: `admin/funnel.ts` (D1 queries + Analytics Engine SQL via `CF_ANALYTICS_TOKEN`), `web/admin/funnel.tsx`, `engine.ts` (admin-test `ok/no <code>` path), var `ADVISOR_ADMIN_CONTACT_ID`, tests with a fake SQL API.

## Phase 5: social

### TA-O4 · Owner: Instagram Business, Facebook Page, developer app, tokens · Owner
- Depends: TA-S0 for the token script.
- Done when: `META_APP_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_PAGE_ID`, `META_PAGE_TOKEN`, `META_IG_USER_ID` are in secrets and `GET /api/admin/health` shows the publishing quota.

### TA-S0 · Migration 0008, Graph client, token script, health · M
- Stories: SO-4 (client), SP-10 (quota).
- Depends: TA-F2, TA-W2
- Files: `db/schema.ts`, `drizzle/0008_advisor_social.sql` (`pnpm db:generate -- --name advisor_social`: `advisor_posts`, `advisor_post_stats`, `advisor_contacts.ig_sid`), `social/meta.ts`, `scripts/advisor/meta-token.mjs`, `admin/health.ts` (quota), deploy secret lines, fixtures `tests/fixtures/advisor/meta/`, `tests/test_advisor_meta.mjs`.
- Tests: `appsecret_proof` value for a known pair; retry on code 4/17/32; error bodies logged without tokens; quota parse.

### TA-S1 · Drafts and captions, review items, backfill · M
- Stories: SO-1, SC-3, SO-5 (tags in caption), SP-3 (reel drafts), AC-1 (angler posts).
- Depends: TA-S0, TA-I2
- Files: `social/drafts.ts`, `prompts/caption.ts`, `tools/propose_post.ts`, `catalog/advisor/hashtags.json`, `engine.ts` (SC-3 path creates the draft), `scripts/advisor/backfill-drafts.mjs` (media left `queued` by phase 2), `web/admin/posts.tsx` (draft editor), tests.
- Tests: caption limits (2,200 chars, ≤ 30 hashtags, ≤ 20 mentions); credit line; no draft without consent; `has_person` blocks approval.

### TA-S2 · Publishing to Instagram and the Page: photo, carousel, reel, story · L
- Stories: SO-4, SP-4 (publish side), SP-5 (carousel), SP-3 (reel publish).
- Depends: TA-S1, TA-M1
- Files: `social/publish.ts`, `cron.ts` (publish slot every 15 min), `routes/advisor.ts` (`/media/post/:id/:name`), `admin/posts.ts` (post now, schedule, retry), tests with recorded container/publish/status responses including `IN_PROGRESS` polling and a quota error.
- Tests: idempotent on rerun (no second container when `ig_container_id` exists); partial failure state; skipper notification text with the permalink.

### TA-S3 · Collaborators, user tags, collab status · S
- Stories: SP-7, SO-5.
- Depends: TA-S2
- Files: `social/publish.ts` (collaborators, user_tags), `cron.ts` (collab status read), tests. Confirms the current Meta field for invite status in the PR description.

### TA-S4 · Daily post, weekly roundup, calendar · M
- Stories: SO-2, SP-5, SP-6.
- Depends: TA-S2, TA-A1
- Files: `social/daily-post.ts`, `social/calendar.ts`, `catalog/advisor/calendar.json`, `cron.ts` (06:30 daily, Sunday roundup, slot filling), `web/admin/posts.tsx` (week grid), tests (deterministic ids, slot filling picks oldest approved, empty slots shown).

### TA-S5 · Stories cron and Instagram profile content · S
- Stories: SP-4, SP-1 (content).
- Depends: TA-S2, TA-M1
- Files: `cron.ts` (07:00 Stories), `social/publish.ts` (`STORIES` and `/photo_stories` already from TA-S2; this task wires the daily selection), `docs/plans/text-advisor/09-social.md` § profile (bio text, highlight covers list, the three highlight scripts: Reports, Fish ID, Tips), tests.

### TA-S6 · Inbox: Meta webhooks, DM channel, comment keywords (dark), review package · L
- Stories: SP-8, SP-9.
- Depends: TA-S0, TA-E1
- Files: `social/inbox.ts`, `routes/advisor.ts` (`/api/advisor/inbound/meta` GET+POST), `channels/instagram.ts` (send DM, private reply), `catalog/advisor/keywords.json`, fixtures, tests, `docs/operations/runbooks/advisor-meta-app-review.md` (the review submission: permissions, usage text, screencast script, test account steps, privacy-policy additions to `dist/privacy.html` in the same PR).
- Tests: handshake; signature; dedupe; 24-hour window error handled; one private reply per comment; everything no-ops when `ADVISOR_INBOX_ENABLED=false`.

### TA-O5 · Owner: Business Verification, App Review, go Live · Owner
- Depends: TA-S6
- Done when: the app is Live, Advanced Access granted for comments and messages, `ADVISOR_INBOX_ENABLED=true`.

### TA-S7 · Insights cron, post stats, funnel wiring · M
- Stories: SP-10, SC-7 (data), OP-5.
- Depends: TA-S2, TA-W4
- Files: `social/insights.ts`, `cron.ts` (03:00), `admin/funnel.ts` (chats-started and site-visits per post), `web/admin/posts.tsx` (stats columns), tests with recorded insights responses including a Story at expiry.

## Phase 6: pilot

### TA-P1 · Launch checklist and flip · S · owner approval (vars)
- Depends: everything above except TA-O5, TA-S6, TA-S7 (those can follow).
- Files: `docs/plans/text-advisor/11-testing-rollout.md` § launch checklist ticked in the PR; `docs/plans/text-advisor/README.md` status log; `CHANGELOG.md`; release tag.
- Owner steps: rules rows for the pilot species reviewed to `active`; 3–5 skippers invited from the admin page; `ENABLE_ADVISOR=true`; `TEXT_ADVISOR_ENABLED=true`, `ADVISOR_SOCIAL_ENABLED=true`.

### TA-P2 · Two-week pilot review · S
- Depends: TA-P1 + 14 days.
- Deliverable: a dated section in `11-testing-rollout.md` with the metrics in § metrics, the top ten conversation failures from the review queue (anonymized), prompt and parser fixes as separate PRs, and the list of "Next" stories the pilot argues for first.

## Next (not scheduled)

| Story | Prerequisites | Rough size |
| --- | --- | --- |
| SC-6 voice notes | a transcription provider (Hermes Whisper or Anthropic audio when available); `kind='audio'` path in intake | M |
| SC-7 weekly skipper text | TA-S7 | S |
| FR-3 follow a port or boat | a `advisor_follows` table; a publish hook; the frequency cap | M |
| AC-2 where it was caught | a `tips` field on media and a page module that labels it unverified | S |
| WH-3 weekly email roundup | an email sender (Resend was the candidate in the old branch) and `advisor_contacts.email` | M |
| SO-3 tips posts | templates from catalog strategies | S |
| SP-11 TikTok and Shorts | developer apps; two clients | M |
| SP-12 regional accounts | per-region credentials map | S |
| SP-13 contest | monthly cron and a review reason | S |
| WhatsApp channel | Meta WhatsApp product on the same app; `channels/whatsapp.ts`; display name approval | M |

## Story-to-task map

| Story | Tasks |
| --- | --- |
| FC-1 | TA-C1, TA-C3, TA-E1 |
| FC-2 | TA-E1 (tool + prompt), TA-I1 |
| FC-3 | TA-C6 |
| FC-4 | TA-F2, TA-E1 |
| FC-5 | TA-C6, TA-W1 |
| FC-6 | TA-E1, TA-A1, TA-A6 |
| SK-1 | TA-I1 |
| SK-2 | TA-I1 |
| SK-3 | TA-I1, TA-W3 |
| SK-4 | TA-I1, TA-W2, TA-W3 |
| SK-5 | TA-I2, TA-W1 |
| SC-1 | TA-C4, TA-V1, TA-I2 |
| SC-2 | TA-I2 |
| SC-3 | TA-C4, TA-I2 (queued media), TA-S1 |
| SC-4 | TA-I2 |
| SC-5 (Next) | TA-I2 (offer built dark; default off) |
| FR-1 | TA-E2 (interim), TA-A1 |
| FR-2 | TA-A2 |
| FR-4 | TA-A1, TA-I2 |
| ID-1 | TA-V1, TA-I3 |
| ID-2 | TA-A0, TA-I3 |
| ID-3 | TA-V1, TA-I3 |
| AD-1 | TA-E2 |
| AD-2 | TA-E2 |
| AD-3 | TA-A5 |
| AD-4 | TA-A2 |
| AC-1 | TA-I3, TA-S1 |
| WH-1 | TA-E1 (links), TA-W1 |
| WH-2 | TA-C3, TA-E1 (`offer_text_link`) |
| WH-4 | TA-W1, TA-A3 |
| SO-1 | TA-S1 |
| SO-2 | TA-S4 |
| SO-4 | TA-S0, TA-S2 |
| SO-5 | TA-S1, TA-S3 |
| OP-1 | TA-W2, TA-W4 (fallback) |
| OP-2 | TA-V1, TA-C4, TA-W2 |
| OP-3 | TA-E1 |
| OP-4 | TA-E1 |
| OP-5 | TA-W4, TA-S7 |
| OP-6 | TA-A0, TA-A4 |
| OP-7 | TA-C1 (watchdog), TA-C2, TA-C7, TA-O3 |
| OP-8 | TA-V1, TA-V2 |
| SP-1 | TA-O4, TA-S5 |
| SP-3 | TA-C4, TA-M1, TA-S1, TA-S2 |
| SP-4 | TA-M1, TA-S2, TA-S5 |
| SP-5 | TA-S4 |
| SP-6 | TA-S4 |
| SP-7 | TA-S3 |
| SP-8 | TA-S6, TA-O5 |
| SP-9 | TA-S6, TA-O5 |
| SP-10 | TA-S7, TA-W4 |
