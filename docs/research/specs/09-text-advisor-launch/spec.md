# 09 · Launch the built Text Advisor (plain-English briefings by text and on the site)

Status: proposed, 2026-11-19 · Priority 9 · Effort estimate: S engineering. The owner steps dominate the timeline · Depends on: owner decisions B1–B7 and accounts C–E in `docs/plans/text-advisor/11-testing-rollout.md`.
Source: SkipperCast competitor analysis, recommendation 9 (SeaLegs AI DeepCast reports, SkeeterCast voice/AI chat, Cobia AI chat).

## Intended goal

Anglers can text SkipperCast, or use the web chat, and get a plain-English answer about conditions, rules, reports and trip timing for their port. Skippers can text in fish reports. This runs on the advisor that is already built, with its caps and kill switches.

## Purpose

The repository holds a complete Text Advisor build. `docs/plans/text-advisor/README.md` says its status is "Built; pending owner launch steps". Everything is behind `TEXT_ADVISOR_ENABLED` (production off) and `ENABLE_ADVISOR` (`server/advisor/gate.ts` answers 404 when off). Competitors now market AI briefings. SkipperCast's version exists but is invisible. The remaining work is launch execution, not new features. This spec makes that execution explicit for an agent, and draws a hard line at the steps only the owner can take.

## User journey (after launch)

1. An angler texts the SkipperCast number: "Morro tomorrow morning, 23 ft boat, rockfish?"
2. The advisor replies within its caps. It covers the comfort word from the one conditions model (`web/score.ts` via `server/advisor/answers/comfort.ts`), the bar-crossing note, the rockfish season state from the rules table, and recent dated skipper reports with sources. It includes the standard not-a-safety-clearance wording.
3. A skipper texts "Patriot 22 limits ling 6", and the report enters the review queue.
4. The owner approves posts by hand (decision B6), and a daily "what's biting" post publishes when the social flag is on.

## Use cases

- **Phone-first anglers who won't open a map** get the same disclosed model by text.
- **Skippers file reports** without logging in.
- **Port pages and the web chat** answer the same questions on the site.

## Requirements

1. **R1** The agent verifies the engineering is complete. All TA tasks in `docs/plans/text-advisor/10-work-breakdown.md` are marked as built, and `node --test tests/test_advisor_*.mjs` plus the golden conversations pass on current `main`.
2. **R2** The agent prepares, but does not execute, the flip sequence (`11-testing-rollout.md` § Flip order). It produces a checklist PR or issue comment listing each owner item A–E with its current state, derived from repo variables or secrets presence where readable (`gh variable list`, `gh secret list`, names only).
3. **R3** For each step the owner authorises, the agent runs the exact commands from § Flip order, waits for the deploy run to finish green, and runs `node scripts/advisor/preflight.mjs` for that stage. It records the dated results in the plan's status log.
4. **R4** The agent never sets secrets, buys numbers, signs into Apple, Meta or Twilio accounts, or changes caps. Those are owner steps (README "How to use this plan" item 5; AGENTS.md "does not authorize … new paid services, changes to credentials").
5. **R5** After replies go on, the agent monitors the admin Funnel and the kill-switch runbooks (`docs/operations/runbooks/advisor-*.md`) for 72 hours, and reports any trip of a cap.
6. **R6** The site surfaces the advisor only after replies are on: the contact card or deep link per `08-website.md`, and the landing link behind the same flag.

## Acceptance

- A status table of owner items A–E with evidence links exists in the PR or issue before any flip.
- Each authorised flip has a green deploy and a passing preflight recorded with date and time (PT).
- The rollback is documented and tested on the dark stage (`ADVISOR_REPLIES_ENABLED=false`).

## Non-goals

- No new advisor features. No changes to prompts, caps or channels in this spec.
- No in-app AI "brief me" button. The Conditions view already states model disagreement in words. A later spec can add one.

## Open questions for the owner

- Decisions B1–B7 in `11-testing-rollout.md` (vision provider, which mentions an optional **Hermes** local classifier via `HERMES_VISION_URL`; auto-publish; BlueBubbles Private API; booking links; Twilio readiness; log settings).
- Accounts and hardware C (number, Apple Account, spare iPhone, Mac mini relay, Cloudflare Tunnel, Meta app) and secrets D (`ADVISOR_PHONE_KEY`, `ADVISOR_WEBHOOK_TOKEN`, `BLUEBUBBLES_*`, `ANTHROPIC_API_KEY`, `WATCHDOG_GITHUB_TOKEN`, `CF_ANALYTICS_TOKEN`, `META_*`).
