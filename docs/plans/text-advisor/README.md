# SkipperCast Text Advisor: build plan

Status: **Plan accepted by the owner, 2026-10-03. Nothing built yet.**
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
