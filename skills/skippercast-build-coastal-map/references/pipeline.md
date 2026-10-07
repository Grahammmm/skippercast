# Data → shared map → live product

## Locate the current contracts

These paths are navigation hints, not immutable deployment facts. Inspect only
relevant entries in the selected checkout:

| Need | Existing owner / contract |
| --- | --- |
| Regional scope and primary sources | `regions/<id>/region.json`, `catalog/data-needs.json`, `docs/data-contracts.md`, `docs/region-pipeline.md` |
| Measured terrain and species fit | `src/skippercast/seafloor`, `docs/seabed-views.md`, mapping skill and its publication contract |
| Native rendered coastal map | `packages/coast/src/coast3d/`, `packages/coast/src/coast3d.ts`, `packages/coast/coast.css` |
| Common selection and links | `packages/coast/src/state/experience.ts`, `packages/coast/src/links.ts`, current shared web state |
| Report and history | `packages/coast/src/coast3d/report.ts`, `daily.ts`, `ui/history.ts`, `ui/catches.ts` |
| Conditions, forecast models and alerts | `docs/regional-intelligence.md`, existing adapters and publication jobs |
| Fish transitional data delivery | `docs/coastal-service.md`, `server/coast-data.ts`; inspect live dependency before retiring it |
| Integration parity | `docs/FISH-MERGE-STATUS.md`, `docs/FISH-MERGE-REVIEW.md` or successors |
| Release | `AGENTS.md`, `.github/workflows/deploy-cloudflare.yml`, `docs/operations/release-process.md`, rollback runbook |

Fish previously owns some coastal compilers and collectors. Locate the actual
source repository if needed; do not assume all were migrated because the renderer
is native. Reuse its existing compiler, cache and immutable receipts until an
explicit migration verifies persisted refreshes. Do not edit another owner's
active mapping checkout or duplicate source catalogs/schedulers.

## Choose a deliverable

Name a geographic footprint, fishing methods, target species and depth band;
identify which layer/interaction changes and how a user will verify the change.
For an integration, inventory every unique working capability before retiring a
route: terrain, chart layers, forecasts/horizons, tides, catches, history, home
settings, regulations, exports, accounts/trips, offline and gated fleet/advisor.
A link to legacy tools preserves access but does not prove a unified workspace.

For a source gap, create a row in the established data-needs ledger with need,
bounds/depth, accuracy/resolution needed, candidate primary source, rights,
access/cost, update method, evidence, owner and next check. A proposed source is
not an admitted product. Paid access still needs appropriate authorization.

## Acquire and normalize

Prefer reviewed source bindings and cached physical outputs before discovery.
A bounded source receipt records producer, original URL, source/version/hash,
acquisition dates, datum/CRS, native support/resolution, precision if known,
coverage/mask, license/commercial eligibility, update/failure behavior and size.
Public accessibility is not commercial reuse permission. Mirrors retain producer
restrictions. Mixed-rights archives stay withheld unless a separately eligible
release passes the established gates. Do not repeatedly fetch a rejected identity.
Retaining an old approved file is recovery, not permission to display it after the
live binding changes. An older immutable release can serve only when its own
current eligibility and complete publication binding are independently verified.

Use native valid pixels/soundings for measured depth and habitat analysis.
Chart soundings can support a labeled estimated surface; regional bathymetry
can supply deep-ocean context. Neither creates fine reef evidence. Retain gap
masks and method lineage. Vertical datum conversion requires a documented
transform and uncertainty; never blend unlike datums into one apparent measured
surface. Source disagreement is a review task, not an averaging instruction.

For weather/ocean feeds preserve observation time, forecast issue/cycle, valid
hour and retrieval time independently. Expired currents remain withheld at the
existing thresholds. Missing wet cells do not become measured currents through
interpolation. Tide height is not offshore current velocity. Satellite surface
temperature/clouds need coverage, acquisition time and quality masks. Label
blended/model/interpolated display and retain source sampling scale.

Catch reports keep their original trip date and admitted factual scope. Selected
species counts are not complete totals; absent categories are not zero. AIS stop
classification needs a reviewed pipeline, coverage/rights and evidence of behavior;
a slow/stopped vessel does not prove fishing, catch success or species presence.

## Publish and serve

Compile numeric assets and hashed manifests using existing tools. Retain source
receipts, complete release identities, byte counts and masks. Publish immutable
artifacts then an atomic manifest; preserve the previous valid release and failed
attempt record. Check whole-release readiness and per-archive identity before
rendering. Withdraw stale/replaced/unreviewed habitat immediately; bounded recovery
can admit a new fully verified release. No empty success or foreign-region fallback.

Transport remains bounded: approved origins/path list, GET/HEAD, exact byte ranges,
no identity/private header forwarding, no arbitrary URL or redirect following.
Use existing source clocks and rate limits. A transport adapter never grants
rights. Verify on the actual edge runtime: local Node success does not establish
Cloudflare API compatibility.

## Assemble the fisherman's view

One place, fishing profile, target and selected time drives map and conditions.
Explicit shared links win over preferences; canonical keys win over aliases;
explicit empty/unknown geography cannot silently default to Morro. Support denied
storage and browser history. 2D/3D changes camera perspective over the same data.

Use a compact daily overview with expandable source detail and nearest reliable
outlook. Boat: wind/gust, waves/period/direction, access/harbor notices, tide,
current/depth/target habitat. Shore: local swell/exposure, tide/access, wind and
water conditions, suitable coast context. Spear: swell/surge, entry/exit, tide,
temperature/current, depth and visibility evidence. A visibility proxy is not a
visibility measurement. Label missing values and forecast uncertainty.

Bite windows must retain the existing reviewed methodology and explain drivers
and confidence; do not invent a calibrated catch prediction from tide/weather.
Regional forecasts stay region-bound; SLO conditions cannot serve Monterey as local.

## Release only the scoped change

Keep required gates even for a small release. Rebase to current main, review the
final diff independently, wait for exact-head required checks, use the normal
protected merge and verify merged-main CI/deployment. Do not bypass policy or
change credentials to resolve a blocker. Use existing rollback and release tags.
No new recurring automation is implied by this skill.

Live acceptance checks the actual build, public manifests/data/source clocks,
rights/readiness, representative assets and exact byte range, relevant interaction
and private/regional exclusions. Reuse unchanged verified evidence; rerun what
changed or what a required gate demands. Before a homepage cutover, verify the
capability matrix in the unified experience, not just that old routes return 200.
