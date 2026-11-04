# Front-end backlog: decision dossier (2026-11-03)

This is a recommendation, not the owner's decision and not authorization to run, publish, delete, or change the plan. Source snapshot: `cd2188e267d8f5a49a6183398bf360ada4bca551`; the plan and bridge were unchanged in the fetched main at `4db7e10c`. The plan's dated summary says its per-task Status lines are authoritative. **DONE here means the plan says built, not that owner approvals, live runs, rights or publication have been independently confirmed.** Original S/M/L sizes are relative scope, not cost estimates; remaining cost is unknown unless described.

Coverage: 51 required rows (13 + 38); duplicates: 0; gaps: 0. Not in plan: 13 (listed as individual rows in Needs G). Group counts: already done 36; drop 0; finish 2; needs G 13. No drop is proposed, so no open dependent is orphaned by a proposed drop. The 13 unknown numbers have no known plan-defined dependencies; do not treat absence as evidence of an obsolete feature.

Evidence checks: opened and confirmed [the plan status and graph](../docs/plans/front-end/dev-plan.md#L51), [the plan's two token-bridge subparts](../docs/plans/front-end/dev-plan.md#L313), [README's default-map status](../README.md#L54), [the historical Fish archive](../docs/archive/fish/README.md#L1), and [the contrast check's retirement note](../scripts/check_contrast.mjs#L4); also opened [the bridge](../server/coast-data.ts#L1). These are repository facts, not live-state checks. Plan references below cite the per-task status; the dependency graph below is reproduced verbatim. A missing ID cites the whole plan as evidence of the search, not evidence of its purpose.

## Already done

| ID | Purpose | Plan status / later history | Dependencies (direct) | Recommendation | Evidence |
| --- | --- | --- | --- | --- | --- |
| FE-33 | Tide sparkline and tide tile (S in plan) | DONE (#531). | In: FE-32; out: FE-60 | already done | [Plan status line 353](../docs/plans/front-end/dev-plan.md#L353) |
| FE-34 | "Where to look" ranking (M in plan) | DONE (#527). | In: FE-18, FE-37; out: FE-60 | already done | [Plan status line 361](../docs/plans/front-end/dev-plan.md#L361) |
| FE-35 | History view (S in plan) | DONE (#530). | In: FE-32, FE-74; out: FE-60 | already done | [Plan status line 369](../docs/plans/front-end/dev-plan.md#L369) |
| FE-36 | Shore runs, access points and guidance (M in plan) | DONE (#525 (#529)). | In: FE-30, FE-74; out: FE-60 | already done | [Plan status line 377](../docs/plans/front-end/dev-plan.md#L377) |
| FE-37 | Brief column and mobile sheet (M in plan) | DONE (#524). | In: FE-31, FE-75; out: FE-32, FE-34, FE-52, FE-60 | already done | [Plan status line 337](../docs/plans/front-end/dev-plan.md#L337) |
| FE-40 | CDIP nearshore model collector (M in plan) | DONE (#466) (output = `packages/coast` `NearshoreSite`). | In: none recorded; out: FE-62, FE-84 | already done; plan also names owner steps (completion not verified) | [Plan status line 391](../docs/plans/front-end/dev-plan.md#L391) |
| FE-41 | Beach health collector (S in plan) | DONE (#460) (output = `BeachWaterQuality`). | In: none recorded; out: FE-62, FE-84 | already done; plan also names owner steps (completion not verified) | [Plan status line 399](../docs/plans/front-end/dev-plan.md#L399) |
| FE-42 | NDBC history backfill and seasonal bands (L in plan) | DONE (#423) (output = `HistoryBundle`). | In: none recorded; out: FE-62, FE-84 | already done; plan also names owner steps (completion not verified) | [Plan status line 407](../docs/plans/front-end/dev-plan.md#L407) |
| FE-43 | ESI shore runs and access points import (M in plan) | DONE (#463) (schema = the shore-habitat GeoJSON the renderer reads). | In: none recorded; out: FE-62 | already done; plan also names owner steps (completion not verified) | [Plan status line 415](../docs/plans/front-end/dev-plan.md#L415) |
| FE-44 | GOES frame times index (S in plan) | DONE (#471) (output = `CloudImage`). | In: none recorded; out: FE-62, FE-84 | already done | [Plan status line 423](../docs/plans/front-end/dev-plan.md#L423) |
| FE-45 | NAIP source config and rights (S in plan) | DONE (#465) (host list shared with `map-sources.ts`). | In: none recorded; out: FE-23, FE-62 | already done; plan also names owner steps (completion not verified) | [Plan status line 430](../docs/plans/front-end/dev-plan.md#L430) |
| FE-50 | Account, boat profile and alerts in the masthead (M in plan) | DONE (#420). | In: none recorded; out: FE-51, FE-60 | already done | [Plan status line 464](../docs/plans/front-end/dev-plan.md#L464) |
| FE-51 | Trip planner, GPX export and offline pack (L in plan) | DONE (#498). | In: FE-18, FE-50; out: FE-60 | already done | [Plan status line 471](../docs/plans/front-end/dev-plan.md#L471) |
| FE-52 | Reports view (M in plan) | DONE (this PR: the v2 view; `ui/catches.ts` `catchSheet` and `fleetBrief`, the readable `/report` and `/feed.xml` came with #385, #395). | In: FE-37, FE-75; out: FE-60 | already done | [Plan status line 479](../docs/plans/front-end/dev-plan.md#L479) |
| FE-53 | Fleet view (M in plan) | DONE (#532). | In: FE-21, FE-24; out: FE-60 | already done | [Plan status line 487](../docs/plans/front-end/dev-plan.md#L487) |
| FE-54 | Species plans, regulations and the sources page (M in plan) | DONE (#534). | In: FE-18, FE-30; out: FE-60 | already done | [Plan status line 495](../docs/plans/front-end/dev-plan.md#L495) |
| FE-55 | Advisor entry and pages in the visual system (S in plan) | DONE (#417). | In: none recorded; out: FE-60 | already done; plan also names owner steps (completion not verified) | [Plan status line 503](../docs/plans/front-end/dev-plan.md#L503) |
| FE-60 | Flip `UI_V2` on by default (S in plan) | DONE (#540, fixes #556/#557, v0.8.0); plan records basemap first publish pending at its 2026-10-11 live check | In: FE-07, FE-11, FE-12, FE-14, FE-15, FE-16, FE-17, FE-18, FE-19, FE-20, FE-21, FE-22, FE-23, FE-24, FE-25, FE-27, FE-30, FE-31, FE-32, FE-33, FE-34, FE-35, FE-36, FE-37, FE-50, FE-51, FE-52, FE-53, FE-54, FE-55, FE-71, FE-72, FE-73, FE-74, FE-75, FE-76, FE-77, FE-78, FE-79, FE-80, FE-81, FE-82, FE-83, FE-86; out: FE-61, FE-62 | already done; plan also names owner steps (completion not verified) | [Plan status line 535](../docs/plans/front-end/dev-plan.md#L535) |
| FE-70 | Coast embed API shared by v1 and v2 (M in plan) | DONE (#427). | In: none recorded; out: FE-71, FE-79, FE-81 | already done | [Plan status line 98](../docs/plans/front-end/dev-plan.md#L98) |
| FE-71 | MapStage hosts the coast renderer (L in plan) | DONE (#472). | In: FE-70, FE-73; out: FE-11, FE-12, FE-18, FE-20, FE-60 | already done | [Plan status line 112](../docs/plans/front-end/dev-plan.md#L112) |
| FE-72 | Chart basemap style from tokens (M in plan) | DONE (#416) (the style half of the old FE-10). | In: none recorded; out: FE-11, FE-60 | already done | [Plan status line 119](../docs/plans/front-end/dev-plan.md#L119) |
| FE-73 | One state controller: coast keys and profile parity (M in plan) | DONE (#415). | In: none recorded; out: FE-30, FE-60, FE-71, FE-74, FE-78 | already done | [Plan status line 105](../docs/plans/front-end/dev-plan.md#L105) |
| FE-74 | Coast data client for v2 (M in plan) | DONE (#425). | In: FE-73; out: FE-15, FE-22, FE-27, FE-31, FE-35, FE-36, FE-60 | already done | [Plan status line 293](../docs/plans/front-end/dev-plan.md#L293) |
| FE-75 | CoastMarkup host (S in plan) | DONE (#426). | In: FE-76; out: FE-32, FE-37, FE-52, FE-60 | already done | [Plan status line 300](../docs/plans/front-end/dev-plan.md#L300) |
| FE-76 | Token bridge for `packages/coast`: chrome and renderer (M in plan) | DONE (#419). | In: none recorded; out: FE-60, FE-75, FE-77, FE-86 | already done | [Plan status line 307](../docs/plans/front-end/dev-plan.md#L307) |
| FE-77 | `panel.css` onto the token bridge (L in plan) | DONE: both FE-77a and FE-77b (#467/#477) | In: FE-76; out: FE-32, FE-60 | already done | [Plan status line 314](../docs/plans/front-end/dev-plan.md#L314) |
| FE-78 | Coast and Fish links open the v2 app (S in plan) | DONE (#424). | In: FE-73; out: FE-60 | already done; plan also names owner steps (completion not verified) | [Plan status line 511](../docs/plans/front-end/dev-plan.md#L511) |
| FE-79 | Host-chrome mode for the coast embed (L in plan) | DONE (#470). | In: FE-70; out: FE-60, FE-80 | already done | [Plan status line 261](../docs/plans/front-end/dev-plan.md#L261) |
| FE-80 | Terrain options in the rail and mark card (M in plan) | DONE (#518). | In: FE-20, FE-79; out: FE-60 | already done | [Plan status line 269](../docs/plans/front-end/dev-plan.md#L269) |
| FE-81 | Overlay API on the terrain (L in plan) | DONE (#464). | In: FE-70; out: FE-60, FE-82 | already done | [Plan status line 277](../docs/plans/front-end/dev-plan.md#L277) |
| FE-82 | Registry layers on the terrain (S in plan) | DONE (#510). | In: FE-20, FE-81; out: FE-60 | already done | [Plan status line 284](../docs/plans/front-end/dev-plan.md#L284) |
| FE-83 | Home memory parity with the coast preferences (S in plan) | DONE (#418). | In: none recorded; out: FE-60 | already done | [Plan status line 519](../docs/plans/front-end/dev-plan.md#L519) |
| FE-84 | Snapshots from SkipperCast feeds; bridge upstream switch (L in plan) | DONE (#478), narrowed: only the four sources published by its dependencies; report base moved to FE-87 | In: FE-40, FE-41, FE-42, FE-44; out: FE-62, FE-87 | already done; plan also names owner steps (completion not verified) | [Plan status line 438](../docs/plans/front-end/dev-plan.md#L438) |
| FE-85 | Terrain, imagery and habitat assets in SkipperCast storage (L in plan) | DONE (#462); plan says first publish waits on rights rows (current live state unverified) | In: none recorded; out: FE-62 | already done; plan also names owner steps (completion not verified) | [Plan status line 454](../docs/plans/front-end/dev-plan.md#L454) |
| FE-86 | Readable and information pages in the visual system (S in plan) | DONE (#461). | In: FE-76; out: FE-60 | already done | [Plan status line 526](../docs/plans/front-end/dev-plan.md#L526) |
| FE-87 | Coast report base from SkipperCast feeds (L in plan) | DONE (#481) (split from FE-84), built 2026-10-08. | In: FE-84; out: FE-62 | already done; plan also names owner steps (completion not verified) | [Plan status line 446](../docs/plans/front-end/dev-plan.md#L446) |

## Drop

None proposed; absence from the plan is not enough evidence to drop.

## Finish

| ID | Purpose | Plan status / later history | Dependencies (direct) | Recommendation | Evidence |
| --- | --- | --- | --- | --- | --- |
| FE-61 | Delete the v1 shell and the v1 coastal modules (L in plan) | Plan: part 1 of 3 DONE; parts 2 and 3 described as pending. Later merged history: #703–705, #708–709 and #721. | In: FE-60; out: none recorded | finish: retain G’s BUILD; verify remaining acceptance and close-out, not repeat merged deletions (L originally; remaining effort unknown) | [Plan status line 545](../docs/plans/front-end/dev-plan.md#L545) |
| FE-62 | Archive `fish` receipts and retire the repository (M in plan) | CHANGED: archive built; bridge retirement pending per plan; live owner steps unverified | In: FE-40, FE-41, FE-42, FE-43, FE-44, FE-45, FE-60, FE-84, FE-85, FE-87; out: none recorded | finish: bridge/receipt parity remains; M originally; owner archive/delete and other live steps require separate authorization | [Plan status line 553](../docs/plans/front-end/dev-plan.md#L553) |

## Needs G

| ID | Purpose | Plan status / later history | Dependencies (direct) | Recommendation | Evidence |
| --- | --- | --- | --- | --- | --- |
| FE-38 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-39 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-56 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-57 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-58 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-59 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-63 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-64 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-65 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-66 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-67 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-68 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |
| FE-69 | Unknown; not in the plan | Not in the plan | Unknown: not defined in plan | needs G: what did this number mean, and is there work to retain? | [Plan numbering and index](../docs/plans/front-end/dev-plan.md) (no task or mention for this ID) |

## Reconciliation notes

The status of the v1 cleanup is stale in the plan: part 1 merged as #561, then parts 2a–2c as #703–705, parts 3 groups as #708–709 and the contrast acceptance as #721. Those later commits are present in the source history. The sheet's BUILD remains in force: finish means check whether any acceptance remains and close out only through the proper process, not assume more implementation is necessary or override G's decision. For the bridge retirement, an origin still exists in the checked source; that alone does not establish live traffic, operational receipts or permission to retire it. Original owner steps are explicitly not verified by this dossier.

## Dependency graph as recorded in the plan

Direct in/out values in the rows expand the final graph's ranges using the plan's explicit flip prerequisites. No inference that a DONE prerequisite has live operational receipts is implied.

```
Done: FE-01 … FE-06, FE-08, FE-09.  Dropped: FE-13, FE-26.
No open dependencies: FE-07, FE-10, FE-50, FE-55, FE-70, FE-72, FE-73, FE-76, FE-83, FE-85, FE-40 … FE-45
FE-70 + FE-73 ─► FE-71;  FE-70 ─► FE-79, FE-81
FE-73 ─► FE-74, FE-78;  FE-76 ─► FE-75, FE-77, FE-86
FE-10 + FE-71 + FE-72 ─► FE-11 ─► FE-14, FE-18 (also FE-71), FE-19;  FE-11 + FE-45 ─► FE-23
FE-71 ─► FE-12;  FE-12 + FE-74 ─► FE-15, FE-22;  FE-15 ─► FE-16 ─► FE-17;  FE-17 + FE-74 ─► FE-27
FE-07 + FE-11 + FE-15 ─► FE-25
FE-14 + FE-15 + FE-16 + FE-17 + FE-18 + FE-71 ─► FE-20 ─► FE-21, FE-24
FE-20 + FE-79 ─► FE-80;  FE-20 + FE-81 ─► FE-82;  FE-20 + FE-73 ─► FE-30
FE-30 + FE-74 + FE-12 ─► FE-31;  FE-31 + FE-75 ─► FE-37;  FE-37 + FE-75 + FE-77 ─► FE-32 ─► FE-33
FE-32 + FE-74 ─► FE-35;  FE-37 + FE-18 ─► FE-34;  FE-30 + FE-74 ─► FE-36
FE-18 + FE-50 ─► FE-51;  FE-37 + FE-75 ─► FE-52;  FE-24 + FE-21 ─► FE-53;  FE-30 + FE-18 ─► FE-54
FE-40 + FE-41 + FE-42 + FE-44 ─► FE-84
Phases 0–4 and FE-71 … FE-83, FE-86 ─► FE-60 ─► FE-61;  FE-84 ─► FE-87;  FE-60 + FE-84 + FE-85 + FE-87 + FE-40 … FE-45 ─► FE-62
```
