# Fish → SkipperCast integration

## Objective

One live SkipperCast product. Preserve every working capability from Fish and
SkipperCast, combine overlapping controls, and preserve the refined Fish coast
map. The owner's October 6 request is the product acceptance standard.

## Current result

The source comparison, independent capability inventory and first shared-link
adapter are complete. Map/data integration and the live cutover have **not**
happened.

- SkipperCast inspected base: `04dfc9057662553dd6ca3a71c485b7845be46744`.
- Fish inspected base: `68d7b444683ffb853327bb9cb3c72e9366620081`.
- Work branch: `codex/fish-product-merge`, in an isolated SkipperCast checkout.
- Both existing live applications remain available.
- First bounded foundation: shared v2 state understands Fish links and full ISO
  whole-hour timestamps. Explicit canonical values and geographic removals win;
  unknown and inherited-property values cannot select a data package.
- Independent foundation review accepted after all findings were resolved.
  All 1,235 Node tests, type checks, build, generated-region comparison,
  repository/web/copy/token/contrast checks passed locally. Full Python runs on
  macOS completed with five unrelated platform failures (the listener installer
  needs Bash `mapfile`, and macOS injects an extra process environment key).
  Exact-head Linux CI is still required before merge.
- The existing v2 shell has placeholder map and brief components. Enabling its
  default now would fail the owner's feature-preservation requirement.

See [the independently prepared inventory](FISH-MERGE-REVIEW.md) for feature
ownership, code locations and integration constraints. Its final implementation
review is pending; source inspection is not a browser or deployment check.

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

Publish the independently reviewed shared-link foundation through protected
PR/CI flow, then implement the source adapters. Keep the current live homepage until the real map
and information views meet the capability matrix. No feature-removing switch
or data-source activation is included in this assessment.
