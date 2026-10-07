# Fish → SkipperCast integration

## Objective

One live SkipperCast product. Preserve every working capability from Fish and
SkipperCast, combine overlapping controls, and preserve the refined Fish coast
map. The owner's October 6 request is the product acceptance standard.

## Current result

The shared-link foundation is live (PR 379, main `d7cffd49`). The read-only
public coastal bridge has merged (PR 381, main `88d16e9a`). Its production
runtime revealed that Cloudflare rejects `Request.redirect="error"`; the native
renderer release uses `manual` plus the unchanged strict 200/206 response gate.
A synthetic redirect regression verifies no follow-on request. The actual local
Worker now returns 200 for the report and terrain manifest.

The native Fish renderer is live at `/coast` (PR 385, main `8bad7cb1`),
with a launch link in the existing map options. It retains the original 2D/3D
terrain, pins, outlines, rankings, source inspection, streaming seam refinements,
current fields and report/history/catch components. It uses strictly typed
reusable source in `packages/coast`; page entry wrappers are built by Vite into
hashed assets. Panel styles are external to satisfy the existing CSP. No atlas,
source admission, private dataset, migration, cron or security policy is added.

- Source origin: Fish `4ac5e0cabb369c97beba5db639856b855fda347a`.
- Independent source review accepted after geographic conflict, launch-state,
  receipt-path and empty-geography fixes; 52 focused tests pass.
- Final local Node suite: 1,287 passed, no failures or skips. All three strict
  type checks, build, client/web/repository/copy/token checks passed; platform
  rebuild left generated regions unchanged. Exact-head and merged-main Linux
  Python/GIS/e2e CI passed. Cloudflare run `37573305538` published build `127342282d`.
- Local browser: Morro terrain/imagery, shore summary, daily report dialog,
  camera-only 2D toggle and Monterey location binding were exercised. Monterey
  correctly labels the separate SLO forecast instead of treating it as local.
  Root mobile check at 390 × 844 verified no horizontal overflow, selectable
  Cabezon pins and original details, the 60-foot spear filter, the report dialog,
  dated catch facts, historical buoy charts and the mobile chart/tools link.
  Independent desktop review confirmed Morro in 3D/2D, compact reef selection
  and native lidar source/datum inspection; it stopped safely when another
  operator changed its browser. Root also verified Point Conception, source
  receipt navigation and Back navigation. Twelve actual production checks
  passed: exact snapshot/terrain hashes and source clocks, habitat HEAD/ranges,
  source receipts and private/regional exclusions. Live 2D/3D interaction passed.
  A final medium-width check caught zoom controls overlapping the species
  selector; the follow-up places them below the location card.
- Existing SkipperCast chart, seven-day dual-model forecast, planning/export,
  legal, account, alert, offline and fleet/advisor functions remain available.
  Keeping their routes is preservation, **not** proof of a finished unified UI.
- The homepage and v2 feature flag are unchanged. Full shared-workspace cutover
  remains pending against the capability inventory below. Do not claim the
  clean merge is complete merely because `/coast` works.

See [the independently prepared inventory](FISH-MERGE-REVIEW.md) for capability
ownership and final parity requirements.

## Product decisions

1. SkipperCast is the canonical repository, account system, deployment pipeline
   and public product. Keep its private accounts, trips, alerts and fleet data
   behind their existing authorization boundaries.
2. There is one map workspace, one home/profile setting, one target selection,
   one selected time and one selected place. Conditions, history, public reports
   and planning tools use that state.
3. Preserve Fish's actual Three coast renderer, refinements and native terrain
   evidence. Its 2D/3D switch changes perspective over the same information.
   The older front-end plan's MapLibre-only direction needs reconciliation with
   this newer working map; replacing it with less capable relief is not parity.
4. Keep SkipperCast's wider geography and its chart, atlas, legal, export,
   forecast, offline, account, fleet and advisor capabilities. A coast display's
   terrain coverage never defines where forecasts or legal reviews apply.
5. Combine shared readings and layers; preserve source-specific observations,
   forecast horizons and original dates rather than choosing whichever report
   happens to be newer. Fish's SLO forecast cannot fill other regions.
6. SLO Fish Report becomes a regional entry to the same product after equivalent
   routes and links are verified. Do not delete its deployment, database,
   private archives or repository as part of an unverified cutover.

## Implementation order

| Step | Concrete result | Acceptance |
| --- | --- | --- |
| Shared state | Alias existing Fish links to the shared port/profile/target/time model; one settings flow | Explicit links win, Back/Forward works, denied storage is supported, old species and locations remain addressable |
| Data integration | Public report/history/ocean adapters and approved terrain assets in SkipperCast's existing delivery model | Rights, hashes, masks, source clocks, region binding, byte ranges and private-prefix denials remain enforced; private account data stays isolated |
| Shared map | Fish coast rendering in the common workspace with selected marks, reef context, layers and details | 2D/3D preserve state; nautical/statewide functionality stays available; no second map navigation or competing time control |
| Shared information | One Conditions view plus History, public reports and planning actions | Retain dual-model outlook, tides, buoy history, shore/dive fields, GPX, regulations, saved trips, offline and gated account/fleet/advisor actions |
| Live cutover | Reviewed, protected merge; exact-head CI; canonical production deployment and regional entry links | Desktop/mobile feature matrix passes, actual deployed revision is verified, live public/private boundaries and source freshness pass |

## Required verification

- Review every inventory row against the unified experience before switching
  the homepage. Reachable legacy files alone do not establish integration.
- Exercise Boat, Shore and Spear; each coast area; selected species and reefs;
  regional exclusions; 2D/3D; home changes; shared links and browser history.
- Walk the map at harbor, shoreline, reef and regional zooms on desktop and
  mobile. Include Morro Rock, estuary channels, Monterey and Point Conception.
- Check CSP, graphics failure, denied storage, missing or expired sources,
  forecast horizon and offline states using actual supported browser access.
- Run the repository's required checks and obtain independent final review.
  Merge through protected PR flow; preserve existing rollback until parity.
- Verify production independently of build success. A live shell does not
  establish a working data refresh pipeline.

## Next action

The medium-width control fix is complete (PR 387, main `2427b0bda`, v0.3.3).

Current batch: embed the native coast renderer inside the existing working chart,
Conditions and planning workspace. The parent owns `codex/unified-coast-workspace`;
a bounded worker owns the root-scoped renderer adapter. Start: October 6, 2026
10:31 p.m. Pacific; checkpoint: October 7, 1:31 a.m. Pacific. Actual fetched main
is `2fbaf7946`; public `/api/health` reads build `76493feb3f`.

Acceptance: one place/target/profile/hour, native camera-only 2D/3D, current
scientific gates unchanged, preserved chart/planner/account/offline capabilities,
independent review, exact current PR-head CI, main/deploy checks and live desktop/
mobile interactions. Full Fish report/history/shore/dive integration and complete
capability verification remain required before homepage or regional cutover.

Next: finish and test the embedded presentation, then mount the source-specific
report/history views against the shared clock. Do not treat legacy links as parity.
