# SkipperCast Text Advisor: build plan

Status: **Plan accepted by the owner, 2026-10-03. Being built behind `TEXT_ADVISOR_ENABLED` (off in production); the log below lists each task as it lands.**
Source of the requirements: the owner's "SkipperCast Text Advisor: User Stories"
doc (60 stories in 11 groups, decisions dated 3 Oct 2026). This folder is the
engineering spec for building every MVP story from that doc inside this
repository, as one new product area, without disturbing the trip planner,
the data pipelines or the Codex seafloor work.

The plan is written for an implementing agent (Claude Opus 5.5 or later) that
has not seen the conversation that produced it. Each document says what to
build, where in the repo it goes, how it is tested, and what must never happen.
Read the documents in order the first time; afterwards, the work breakdown
(`10-work-breakdown.md`) is the checklist and the others are the reference.

| Document | What it specifies |
| --- | --- |
| [00-decisions.md](00-decisions.md) | Decisions already made by the owner, the principles, the non-interference rules and what is out of scope |
| [01-architecture.md](01-architecture.md) | Components, request and data flow, the channel adapter, queue, feature flags and bindings |
| [02-data-model.md](02-data-model.md) | Every new D1 table and migration, the private R2 bucket layout, retention and privacy rules |
| [03-channels.md](03-channels.md) | The owned phone number, the Mac relay (BlueBubbles), the Twilio adapter, the web-chat adapter, inbound and outbound contracts, and the port-to-Twilio runbook |
| [04-advisor-engine.md](04-advisor-engine.md) | The conversation engine: identity, intent routing, the Claude tool set, prompts, language, spend caps, abuse and refusals |
| [05-skipper-intake.md](05-skipper-intake.md) | Skipper onboarding, consent, crew, count-board and plain-text reports, corrections, auto-publish, weekly performance text |
| [06-angler-answers.md](06-angler-answers.md) | Reports, trip-planning, fish ID, the rules table, rigging and area advice, safety warnings, angler photo submissions |
| [07-vision.md](07-vision.md) | The vision provider interface, the Hermes local classifier contract, the Claude-vision fallback, and the count-board schema |
| [08-website.md](08-website.md) | Port, species and boat pages, the web chat, contact card and deep links, and the passkey-gated admin pages |
| [09-social.md](09-social.md) | Meta setup, publishing to Instagram and the Facebook Page, Stories, Reels, collab posts, DMs and comment keywords, calendar and insights |
| [10-work-breakdown.md](10-work-breakdown.md) | Phases, PR-sized tasks with ids, dependencies, files touched, acceptance tests, and the story-to-task map |
| [11-testing-rollout.md](11-testing-rollout.md) | Test layers, fixtures, the pilot runbook, launch checklist, metrics and kill switches |

The ADR for the decisions that are hard to reverse is
[ADR 0007](../../engineering/adr/0007-text-advisor-channels-and-vision.md).

## How to use this plan

1. Work through `10-work-breakdown.md` in phase order. Each task names its
   branch (`claude/ta-<task-id>`), the files it touches, and the tests that
   prove it. One task is one PR, as [AGENTS.md](../../../AGENTS.md) requires.
2. Before each task, re-read the referenced section of the specific document;
   the breakdown is deliberately terse and the documents hold the detail.
3. Everything ships behind `TEXT_ADVISOR_ENABLED` (default off) and the
   `ENABLE_ADVISOR` deploy variable, both repository variables applied by a
   deploy (there is no dashboard editing; `wrangler deploy` rewrites vars on
   every `main` commit). Merging to `main` never changes the live site until
   the owner flips those. This is what lets the work land in small PRs over
   weeks while other work continues.
4. When a document and the code disagree, the code was wrong or the document
   is stale: fix the document in the same PR, so the plan stays true.
5. Anything marked **Owner** in the breakdown needs the owner (accounts,
   secrets, paid services, number porting, Meta review). Do the engineering
   around it, stop at the owner step, and say what is needed.

## Status log

Append a dated line when a phase starts or finishes; keep the older lines.

- 2026-10-03: plan written (Claude Fable 5.1); no code yet.
- 2026-10-03: TA-F1 implemented (PR #252, Opus 5.5 under Fable orchestration); plan corrected for the `ADVISOR_`-prefixed secrets and `BLUEBUBBLES_PRIVATE_API`.
- 2026-10-03: TA-F3 implemented (queue consumer, cron slots and relay watchdog, advisor analytics); plan corrected: inbound `held` status in 02, hard-stop details in 01.
- 2026-10-03: TA-C1 implemented (BlueBubbles adapter, inbound webhook, relay-down hold and release, relay runbooks and `relay-check.mjs`); plan corrected: migration `0007_advisor_media_ref` added (`advisor_media.provider_ref`), so the answers and social migrations become 0008 and 0009; `channelHint` on `OutboundMessage`; `splitForChannel` takes the contact's channel; outbound `media_json` holds R2 keys.
- 2026-10-03: TA-C4 implemented (media intake with magic-byte sniffing and JPEG/PNG metadata stripping, R2 storage with per-contact dedupe, download-before-handler with two retries, upload link and page, `/media` serving); plan corrected in 02 (rejected `kind='unknown'`, extensions, derived-file fallback, multipart for large files), 03 (token format, XHR, `fetchMediaByRef`, `inbound.ts`) and 07 (`tIME`, post-EOI data).
- 2026-10-03: TA-C7 written (port-to-Twilio runbook with the 10DLC package and HELP wording; relay-down escalation rule); plan corrected in 03 § runbook (diagnosis lives in the relay-down runbook; the port adds the Messaging Service sender, the HELP auto-reply and the STOP/HELP forwarding check).
- 2026-10-03: TA-V1 implemented (vision provider chain with result cache and 10-minute provider skip, Claude vision provider with forced-tool output, thresholds as `decide*` functions, vision prompts, `catalog/advisor/` species-extra, lookalikes and protected lists, synthetic fixture images); plan corrected in 07 § As built (four fixture images, the over-4.5 MB re-queue moves to TA-M1, the protected-warning threshold question for TA-I3).
- 2026-10-04: TA-C6 implemented (`/contact.vcf`, `/text` deep link, `/qr/text.svg` with a dependency-free QR encoder, `[via <source>]` parsing in `intents.ts` and first-touch `source` in `storeInbound`); plan corrected in 03 § contact card (PNG photo, 503 without a number, the marker is visible, not invisible).
- 2026-10-04: TA-C3 implemented (web chat adapter with a per-request collector, `/api/advisor/web/message` and `/web/upload`, `sc_adv` cookie, the chat island on `dist/chat.html`); plan corrected in 03 § web adapter (collector via `deps.channel`, `mediaIds`) and 08 § web chat (reply `id`, pending shape, Origin check).
- 2026-10-04: TA-E1 implemented (conversation engine: stage 0 guards and caps, en/es commands and language switching, stage 2 extension point with the upload link, text admin fallback and web phone link, the model loop with caching, tool rounds, `pause_turn` and the rules guard; system prompt and few-shots for the owner's review; tool registry with stubs for TA-E2/TA-I*; strings catalog; export link route); plan corrected in 04 § As built (stage order, caps keys, the DELETE window, new actions, the link merge) and 03 § web.
- 2026-10-04: TA-A0 implemented (migration `0008_advisor_answers` with `advisor_rules` and `advisor_daily_answers`, `scripts/advisor/import-rules.mjs` seeding `review` rows from the five published regulations files, `answers/rules.ts` lookup and review hook, the real `get_rules`); plan corrected in 02 § advisor_rules "As built" (rows per jurisdiction, sub-species rows, upsert rules).
- 2026-10-04: TA-E2 implemented (the data tools `get_port_report`, `get_conditions`, `get_species`, `get_strategy`, `get_trips` on the regional feeds and D1; `answers/` confidence ladder and comfort rubric pinned to the app's, conditions parser, advisories, date words, port and species resolution; `catalog/advisor/` public-grounds allowlist, port aliases and species synonyms; prompt lines for AD-2 and few boats); plan corrected in 06 § As built (TA-E2) and 04 § As built (TA-E2).
- 2026-10-04: TA-I1 implemented (skipper registration state machine with port aliases and the nearest-three fallback, unique slugs, consent with the message id, the 7-day re-ask and revoke, crew add/remove by the owner with the invite texted to the crew number, the verification text to the skipper, the boat and consent in the contact brief; golden conversations 2 (en, es, to the consent step) and 3 (to the crew reply)); plan corrected in 05 § As built (TA-I1) (flow state in job_state, the boat created only on completion, the `boat_create` action name, the consent decline wording) and 04 § As built (TA-I1).
- 2026-10-04: TA-I2 implemented (skipper reports: count-board photos read by vision into a draft with `?` on uncertain lines, the deterministic count-text grammar en/es, Y/N confirmation, corrections with `advisor_report_edits`, same-day reports as edits, publish with the frozen `verified`, `clean_reports`, the pages version and the port's daily answers invalidated, catch photos and videos queued with consent and `has_person` reviews, the SC-5 AUTO offer behind `ADVISOR_AUTO_PUBLISH_AFTER`, the `read_count_board`, `propose_report` and `edit_report` tools; golden conversations 2 and 3 extended); plan corrected in 05 § As built (TA-I2) (`cancel` stays STOP, one live report per boat and day across sources, daily answers deleted rather than re-hashed, `edit_report`'s patch list, post drafts left to TA-S1).
- 2026-10-04: TA-I3 implemented (angler fish ID without a model call: classify, `identifyFish`, the three 06 reply shapes with look-alike cues, the rules table quoted with source and checked date or "double-check" when stale, the must-release warning at any candidate ≥ 0.3; the AC-1 share offer at ≥ 0.6 for non-skippers, YES within 24 h, the credit asked once and stored on `advisor_media.credit`, the `angler_photo` review; `identify_fish` and `share_angler_photo`; golden conversation 4); plan corrected in 06 (protected threshold ≥ 0.3, § As built (TA-I3)), 07 § As built and 04 § As built (TA-I3).
- 2026-10-04: TA-A1 implemented (daily port answers: inputs hash over the published reports of three days, the landing reports with their ladder label, today's advisories and conditions and the rules with stale flags; one forced-tool model call for English and Spanish, ≤ 480 characters, no percentage, no follow offer, the two 06 fallbacks, unverified boats as "another boat"; the `daily-answers` slot at 05:30 for every active port; the pre-router for the plain "what's biting" forms; `get_port_report`'s `daily`; golden conversation 1); plan corrected in 06 (slot name, the one-call pick, § As built (TA-A1)), 04 § As built (TA-A1) and 10.
- 2026-10-04: TA-A2 implemented (the planning brief through `get_conditions` with a species: the advisory line first in the reply language, the season from the rules table without numbers, the port's recent reports and one confidence phrase from the ladder for that species, the NWS closer, the 7-day horizon and two-day weekends; the engine's advisory backstop; engine fixtures for both); plan corrected in 06 § As built (TA-A2), 04 § As built (TA-A2) and 10.
- 2026-10-04: TA-A5 checked (`get_trips` already met 06 § Trips for newcomers: verified boats, landing, https booking link, boat page, 60-day trip types, newest report first, never ranked, `few` under two; tests now prove each clause, and that a trips list is not capped); 06 § As built (TA-A5) and 10.
- 2026-10-04: TA-A6 implemented (the Spanish pass: the consumer's texts, the AD-2 line, the few-boats phrase, escalate's line and the remaining words of the daily and fish-ID answers moved into `strings.json`; `cues_es` in `lookalikes.json` for Spanish fish IDs; the Spanish fish-ID few-shot; a static scan for hard-coded sentences at a send; golden conversation 5); 06 § As built (TA-A6), 04 § As built (TA-A6) and 10.
- 2026-10-04: TA-A3 implemented (look-alike cues for every fish key and species-extra key, each citing its CDFW or NOAA Fisheries page and checked against CDFW's identification flyers; quillback added to the protected list from CDFW's groundfish summary, canary still a sub-bag species; `catalog/advisor/species-pages.json` for the species pages; species-data tests with the size guard); 06 § As built (TA-A3), 07 § As built and 10.
- 2026-10-04: TA-M1 implemented (the `advisor-media` runner job: `.github/workflows/advisor-media.yml` dispatched by the Worker, `scripts/advisor/media_job.py` with Pillow and pillow-heif writing `public.jpg`, `thumb.jpg` and `story.jpg` with the footer band, HEIC to JPEG and the daily, story and roundup graphics from `catalog/advisor/graphics.json`; the job endpoints behind a parameterised `verifyJobToken`; `dispatchWorkflow` exported from the watchdog; the consumer's wait for `public.jpg` and the vision chain reading it); plan corrected: migration `0009_advisor_media_derived`, so social becomes 0010; three waits, not four; 09 § Derived images "As built", 07 and 02.
- 2026-10-04: photo orientation kept through EXIF stripping (found in the TA-M1 review: iPhone JPEGs were stored and derived sideways): intake reads the EXIF Orientation before dropping APP1 and stores only that value (`advisor_media.orientation`, migration `0010_advisor_media_orientation`, so social becomes 0011, and R2 custom metadata); the media job turns the pixels upright and lists every sideways image; the Claude vision prompt names the orientation; `/media` never serves a sideways original. 07 and 09 § As built (orientation), 02, 10.
