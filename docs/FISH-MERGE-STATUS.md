# Fish → SkipperCast integration

## Objective

One live SkipperCast product. Preserve every working capability from Fish and
SkipperCast, combine overlapping controls, and preserve the refined Fish coast
map. The owner's October 6 request is the product acceptance standard.

## Active increment — shared coastal overview (October 7)

- Objective: connect the continuous Central Coast discovery map to native terrain,
  one target/profile/view/UTC clock, independent model forecasts and managed local
  Conditions. Preserve chart, survey, MPA, federal-area and package planning paths.
- Base: deployed v0.4.0, main `5c622934dca58088d5c66aa2c8adeb7445e76db7`,
  build `f651dcbb81`; release/live receipts remain in the continuation outputs.
- Owner: parent integrates shared state and release; bounded worker owns native
  selection lifecycle and model adapter; independent reviewer checks source scope.
- Overview PR 399 merged at `2bb1c514a678e37753dc661677d58874ad06cd61` after exact-head core/science/e2e/DCO success. Release branch: `codex/release-v0.5.0`; final main deployment and live acceptance are pending.
- Decision: panning keeps the overview; detailed packages require explicit action.
  Only exact currently admitted source identity + reviewed original region bounds
  can bind local SLO readings. No nearest-package or Morro default is admitted.
- Completed: source-bound readable links; UTC/Unix independent models; strict unit
  and horizon gaps; preserved unsupported target/time choices; original publication
  expiry withdrawal across hidden views; immediate stale-response suspension.
- Checks: renderer 66/66, forecast adapter 11/11, exact source resolver 5/5 and final Node 1,413/1,413 passed; focused clock/context,
  Conditions, handoff and readable-page regressions passed. Initial full Node run
  found two maintenance failures (removed copy baseline entries and placeholder
  domain); both corrected. Final scientific suite: 1,896 passed, 32 skipped and five known macOS fleet runner failures. Required Linux CI remains the merge gate.
- Browser finding resolved: selection must move the chart before publishing host
  metadata, so the prior map center cannot withdraw a newly selected habitat.
- Browser: shared original selection, fresh chart Conditions metadata restoration, Map/Conditions round trip, Day 7 gaps, current package hrefs and unsupported coast handoff passed at desktop/390px. Native phone controls clear the clock by 25 px. Receipt: continuation `outputs/coastal-overview-browser-check.json`.
- Independent review accepted the final source; 95 focused checks and actual-source geographic/expiry regressions passed.
- Acceptance remaining:
  release exact-head gates, main CI/deploy/live readback and annotated release tag.
- Full product remains incomplete: shared layer/offline/route integration, full
  readable daily brief, default homepage cutover and capability matrix remain.
- Next action: publish v0.5.0 through the normal protected PR and deployment workflows, verify live, then unify the surface-current source choice.

## Previously completed integration

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

The shared map increment (PR 392, main `39ea66b4c`) and local report/history
increment (PR 393, main `539a3c66c`) are merged through protected flow after
independent review and every exact-head required check. Both merged main CI and
existing Cloudflare deploys passed. Live builds `55dbed0ed0` and `27bf9c676b` match
their workflow smoke receipts. Actual phone map/Conditions/history interactions
passed. Each release's 12 public-data, native range/hash, region and private-route
checks passed; receipts are in the continuation workspace outputs.

The readable routes (PR 395, main `a36d091fb`) are merged after independent
review and exact-head core/science/browser/DCO checks. CI found a genuine
seafloor display race during chart invalidation; the corrected draw waits for
archive/header and mounted legend while retaining publication-expiry gates.
Merged-main CI and Cloudflare deploy `37590022909` passed; live build
`20e554ec41` matches the deployment receipt. Seventeen public route/data/hash/range
and private-boundary readbacks passed. Live source report, selection-preserving
methods link and full privacy notice rendered without horizontal overflow.

Current batch: `codex/coastal-entry-home`, based on main `a36d091fb`.
Actual v1 startup translates legacy Fish place/species/profile/hour choices before
locking shared state. Empty and unsupported targets remain explicit. Canonical
choices win; shared links do not change the saved home location. Home save/forget and
native legacy preferences agree; port changes clear stale place/area selections.

Evidence: independent scoped acceptance; strict typechecks, source-first build,
client/web/repository/copy/token checks; 1,372 local Node tests pass including the
seafloor race and unsupported-rule UI regressions. Actual desktop/phone legacy startup, empty target, home removal,
Avila-to-Morro handoff, profile-only mounted report updates and Back navigation
passed. Browser review also found inherited regulation-target lookup; exact-own complete
record guards and actual header/spot regressions passed independent review.
A second browser finding traced early confidence imports capturing Morro forecast
points before Monterey loaded. Pure unit imports now prevent that capture; a
subprocess startup regression verifies actual selected-region coordinates, and
missing current samples remain unavailable. Independent final scoped review passed
(54 focused cases plus 26 amendment/regulations cases); actual phone Monterey
shows only its three named regional forecast points and the SLO exclusion. Monterey native entry correctly excludes
local SLO readings and labels measured SLO history as a reference.

Start: October 6, 2026 10:31 p.m. Pacific; checkpoint: October 7, 1:31 a.m. Pacific.
Parent owns integration/browser/release. Bounded worker owns source adapters;
independent reviewer owns source review. Existing Fish public Worker remains the
bounded read-only data dependency. No collectors, private stores or schedulers move.

Next: release/read back the readable routes; normalize actual v1 Fish entry links,
Back/Forward target state and home preferences; finish the complete capability and
geography audit. Continuous-coast overview parity, visible imagery transitions,
all profile/target interactions and regional Fish cutover still need explicit
acceptance. Homepage defaults and Fish retirement remain unchanged until that
matrix passes. Reachable legacy links are not parity.

## Remaining cutover gaps (source audit, October 7)

- Continuous overview now shares terrain, source Conditions and UTC/profile/target state (PR 399). Planning/private tools still use explicit detailed-package handoffs; reachability alone is not full workspace parity.
- Native surface-current visibility and chart ocean/current selectors are
  independent (`dist/coast.html`, `dist/coast-workspace.js`).
- Fish snapshots bypass public API caching and native terrain has no explicit
  trip-pack/precache policy (`dist/sw.js`, `dist/offline-core.js`,
  `scripts/precache.mjs`). Existing chart offline remains available.
- Standalone `/coast` retains separate controller/settings. Original Fish route
  aliases and readiness meanings need explicit compatibility acceptance.
- Readable `/report` retains source readings/clocks; full original no-JavaScript
  daily windows, history and catch brief are not yet unified there.
- Imagery transitions and the complete desktop/mobile feature matrix remain
  unaccepted. Upstream collectors/private stores remain upstream; no migration
  or retirement is authorized by these scoped acceptances.

These are remaining implementation/acceptance tasks. They do not prevent the
reviewed regional increments, but they prevent declaring full integration or
changing homepage defaults and retiring Fish.
