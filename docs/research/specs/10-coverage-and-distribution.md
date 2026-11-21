<!-- Generated from 10-coverage-and-distribution/spec.md, plan.md, tasks.md. Edit those, not this file. -->

# 10 · Coverage and distribution: a second active region, and an installable store-listed app

Status: proposed, 2026-11-19 · Priority 10 · Effort estimate: L · Depends on: owner decisions in `docs/plans/second-active-region.md` §6 and §8. Specs 01–08 should work for any active region (no Morro Bay hard-coding).
Source: SkipperCast competitor analysis, recommendation 10 (Fish or Pass covers the whole SoCal Bight; Salty Offshore covers 34 regions; every rival is in the App Store or Google Play).

## Intended goal

More anglers can use SkipperCast for real. A second region reaches `active` under the bar the owner approves. SkipperCast can be found and installed from the app stores as a thin wrapper around the existing phone-first web app.

## Purpose

SkipperCast has one active region (Morro Bay & Avila), 15 preview and 6 draft packages. The repo already holds a costed second-region plan (`docs/plans/second-active-region.md`, which recommends Southern California) and a technical promotion preflight (`scripts/check_region_promotion.mjs`, runbook `docs/operations/runbooks/region-promotion.md`). The promotion sheet dated 2026-11-16 says all five candidate regions FAIL on stale feeds, tides, rules and brief, and recommends HOLD. Fish or Pass already serves Southern California, the closest direct competitor geographically. Distribution matters too: the app installs as a PWA (`web/install-app.ts`, `web/app/InstallApp.tsx`), but there is no store listing.

## User journey

1. A San Diego angler sees SkipperCast in the App Store (search "fishing forecast California"), installs it, and lands on the region picker.
2. Southern California shows **Active**. The brief, layers, rules cards, alerts and trip tools work as they do in Morro Bay.
3. Preview regions stay labelled preview with their gaps, as today.

## Use cases

- **SoCal anglers get the same tools** as Morro Bay anglers.
- **People who look for apps in stores**, not browsers, can find SkipperCast.

## Requirements

1. **R1** Region: execute `docs/plans/second-active-region.md` §5 "Costed plan" in its dependency order. Phase 0 is the Morro Bay refinement (M1a, M1c, M3, M4; M1b is an owner gate). Phase 1 is the Southern California gaps (S1a–S3; S1c is an owner gate). Phase 2 is B6 (encode the approved `active` bar in `src/skippercast/platform/contracts.py` with a failing-first test) and B7.
2. **R2** Before any status change, `node scripts/check_region_promotion.mjs southern-california` must exit 0 on fresh data. Paste the output into the PR. PASS is not permission; the owner promotes.
3. **R3** Agents never change `regions/*/region.json` status, the roadmap order or data-rights decisions without the owner's recorded decision (`AGENTS.md`; second-active-region §6).
4. **R4** Distribution (separate PR series): a Trusted Web Activity for Google Play (Bubblewrap), and a minimal iOS wrapper (Capacitor or a WKWebView shell) loading `https://skippercast.com/map`. The service worker, offline pack and passkeys must keep working. Passkeys in WKWebView need associated domains (`apple-app-site-association` served from `dist/.well-known/`). Push needs the platform's own path on iOS (web push works in iOS 16.4+ home-screen apps only). The spec's first task is a feasibility receipt.
5. **R5** Store accounts, listings, privacy labels and payments are owner steps. The agent prepares the listing text, screenshots from `scripts/showcase_capture.mjs`, and the privacy-label answers from `docs/legal/`, then stops.
6. **R6** Specs 01–08 must not assume Morro Bay. They read the region from state and feeds.

## Acceptance

- Phase 0–2 cards merged with independent review. The promotion preflight PASS output is recorded. The owner's written decision is linked before `status: active`.
- A feasibility receipt for the TWA and iOS wrapper covers passkey sign-in, offline pack, push and deep links, each with pass, fail or workaround.

## Non-goals

- No paid acquisition, no store payments or subscriptions in this spec.
- No new region data sources beyond those in the costed plan.

## Open questions for the owner

- Accept Southern California as the second active region, reordering the roadmap (second-active-region §6 decision 1)? Or HOLD/CAMBRIA per the 2026-11-16 sheet?
- Dynamic-closures scope for the Navy ranges (§6 decision 2).
- Store distribution: yes or no, and which platforms first. Apple Developer ($99/yr) and Google Play ($25 one-time) accounts are needed. Fees as listed by Apple and Google; verify before purchase.


---

# Implementation plan · 10 coverage and distribution

## Evidence (observed 2026-11-19, commit fa9c358)

- `docs/plans/second-active-region.md`: §1 (no written `active` criteria; the bar is "what Morro Bay has"), §5 costed plan (Phase 0: M1a–M5; Phase 1: S1a–S3; Phase 2: B6–B8; "Agent total" ~35 h plus owner gates), §6 owner decisions, §8 promotion sheet 2026-11-16 (all five candidates FAIL; recommends HOLD).
- `scripts/check_region_promotion.mjs` and `docs/operations/runbooks/region-promotion.md`: checks for package, feeds, tides, rules, habitat and smoke. Exit 0, 1 or 2. "PASS is a technical preflight, not permission to promote".
- `regions/` holds 24 packages (`southern-california`, `san-diego`, `santa-barbara-channel` …). Generated outputs come from `PYTHONPATH=src python -m skippercast.platform.build` (AGENTS.md generated-files table).
- PWA: `web/install-app.ts`, `web/app/InstallApp.tsx`, service worker and offline pack (`web/map/offline.ts`, `web/map/ocean-pack.ts`). Passkeys: `@simplewebauthn/server`, `server/auth.ts`.

## Plan

- Region work follows the costed plan exactly. This spec adds no new requirements to it. It sequences it for the build agent and marks the owner gates.
- Distribution starts with a receipt (`docs/plans/store-distribution.md`, new): a TWA built with Bubblewrap against the production manifest, Digital Asset Links (`/.well-known/assetlinks.json`), and an iOS shell feasibility check (passkeys via associated domains, push options, offline). Only after the owner says go does the wrapper code land, in a new `apps/` folder kept out of the Worker build.

## Files to create or modify

| File | Change |
| --- | --- |
| per costed-plan cards | as listed there |
| `src/skippercast/platform/contracts.py` + test | B6 active bar |
| `docs/plans/store-distribution.md` (new) | feasibility receipt |
| `dist/.well-known/assetlinks.json`, `apple-app-site-association` (later, owner-approved) | |

## Dependencies

Owner decisions. Specs 01–08 should be region-agnostic (R6).


---

# Tasks · 10 coverage and distribution

- [ ] T0 **Owner decision**: SOCAL, CAMBRIA or HOLD (second-active-region §6, §8). Stop until it's recorded.
- [ ] T1 Phase 0 agent cards M1a, M1c (after the owner's M1b), M4. Rerun the promotion preflight for morro-bay (R1).
- [ ] T2 Phase 1 S1a discovery receipt, then S1b if usable, S2 and S3 (R1).
- [ ] T3 Phase 2 B6 failing-first active-bar test, then B7 (R1).
- [ ] T4 Fresh `check_region_promotion.mjs southern-california` PASS, pasted in the PR. The owner promotes (R2, R3).
- [ ] T5 Store-distribution feasibility receipt (R4). Prepare the listing package and stop for the owner (R5).
- [ ] T6 Audit specs 01–08 code for region hard-coding (R6).

## Verification

Dated preflight outputs and owner decision links.
