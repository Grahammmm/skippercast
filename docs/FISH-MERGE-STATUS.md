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

The shared map increment (PR 392, main `39ea66b4c`) and local report/history
increment (PR 393, main `539a3c66c`) are merged through protected flow after
independent review and every exact-head required check. Both merged main CI and
existing Cloudflare deploys passed. Live builds `55dbed0ed0` and `27bf9c676b` match
their workflow smoke receipts. Actual phone map/Conditions/history interactions
passed. Each release's 12 public-data, native range/hash, region and private-route
checks passed; receipts are in the continuation workspace outputs.

Current batch: `codex/readable-coastal-report`, based on main `3cecd5530`.
Readable `/report`, original-clock `/feed.xml`, methods/about pages and `/privacy`
alias use the existing generated shell and complete privacy notice. Shared public
selection survives links; client identity is never sent to source snapshots. Exact
UTC/profile/area checks retain gaps. Static checks exempt only registered
navigation and the exact RSS tag; scripts/styles/unknown paths still fail. A real
signals regression test now covers profile-only updates after lazy report mount.

Evidence: independent scoped source acceptance; strict typechecks; 19 route/host
and six checker cases passed. Earlier report batch had 1,335 Node passes and live
build `27bf9c676b`. Required full Linux gates, protected merge and readable-route
live acceptance remain pending for this batch.

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
