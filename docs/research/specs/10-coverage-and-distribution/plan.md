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
