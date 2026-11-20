# Fish bridge retirement: remaining dependencies

Report-only plan (SCBB-06, checked at main `223ebd8a`). It changes no code, workflow, catalog or
`COAST_FEEDS` value. Retiring the Fish Worker (`fish-report.g4651.workers.dev`) is FE-62 part b; this lists
what that still touches, so it is a plan and not a surprise. Re-run each grep from the repository root.

## How the bridge falls back today

`COAST_FEEDS` (`server/env.ts:64`) names SkipperCast feeds. A named feed is used only while it is present,
valid, fresh and rights-cleared (`FEED_SOURCES`, `server/coast-data.ts:185`); otherwise that source comes
from the Fish Worker. Unset, every source stays on Fish. Terrain and data files have no `COAST_FEEDS` name.

## A. Calls and fallbacks in the Worker (`server/coast-data.ts`)

| path:line | What it does | `COAST_FEEDS` name that replaces it | SkipperCast feed exists? | Still to build (FE-62 b) |
| --- | --- | --- | --- | --- |
| `server/coast-data.ts:12` | `ORIGIN`, the Fish Worker URL | none (constant goes) | n/a | delete the constant |
| `server/coast-data.ts:47` | `coastTarget` builds every upstream URL on `ORIGIN` | none | n/a | return the own-feed key, not a Fish URL |
| `server/coast-data.ts:346` | generic bridge fetch for a snapshot or asset not served locally | per row below | per row below | answer 503/404 instead of forwarding |
| `server/coast-data.ts:151` | comment: Fish fallback is dated, goes with FE-62 | all five names | see below | update comment |
| `server/coast-data.ts:183` | `SNAPSHOT_FEEDS`: report = report + nearshore + water-quality; ocean; history | `report`, `nearshore`, `water-quality`, `ocean`, `history` | yes, all five (`FEEDS`, line 163) | none for the mapping |
| `server/coast-data.ts:229` | `fishEnrichment`: copies Fish's nearshore, water quality and enrichment-processing into the own report | `nearshore` and `water-quality` | yes (`conditions/regions/morro-bay/nearshore.json`, `.../beach-health.json`) | drop the function once both are required |
| `server/coast-data.ts:236` | `fishReport`: the one Fish call made while a report enrichment feed is not switched | `nearshore`, `water-quality` | yes | delete |
| `server/coast-data.ts:335` | call site of `fishReport`; line 336 adds `fish=unavailable` to `X-Coast-Upstream` | `nearshore`, `water-quality` | yes | delete both, so `X-Coast-Upstream` can only read `skippercast` |

Per source fallback after the report moves (`report` switched):

| Source group | Falls back to Fish when | Replacing name | Feed exists |
| --- | --- | --- | --- |
| report base (`nws-weather`, `ndbc-buoys`, `noaa-tides`, `landing-reports`, `noaa-blended-sst`, `cdfw-mpas`) | `report` not named, stale, invalid or rights-refused | `report` | yes, `FEEDS.report` |
| nearshore (`cdip-mop`) | `nearshore` not named or stale; then `fishReport` fills it | `nearshore` | yes |
| water quality (`slo-beach-water-quality`) | `water-quality` not named or stale; then `fishReport` fills it | `water-quality` | yes |
| ocean (`noaa-wcofs`, `noaa-hfr-thredds`, `noaa-goes-nowcoast`) | `/api/coast/ocean` when `ocean` not named or stale | `ocean` | yes, `conditions/regions/morro-bay/coast-ocean.json` |
| history (`ndbc-history`) | `/api/coast/history` when `history` not named or stale | `history` | yes, `data/regions/morro-bay/history.json` |
| terrain and chart files (`/coast-data/data/...`) | R2 group not published (`assetGroup`, line 66) | none | no feed: R2 copy only, made from Fish by section B |

Grep per row (script-free):

- `grep -n "fish-report.g4651" server/coast-data.ts` (line 12)
- `grep -n "new URL(upstream, ORIGIN)" server/coast-data.ts` (line 47)
- `grep -n "fetcher(new Request(target.url" server/coast-data.ts` (line 346)
- `grep -n "dated:" server/coast-data.ts` (line 151)
- `grep -n "^const SNAPSHOT_FEEDS" server/coast-data.ts` (line 183)
- `grep -n "^function fishEnrichment" server/coast-data.ts` (line 229)
- `grep -n "^async function fishReport" server/coast-data.ts` (line 236)
- `grep -n "fishReport(fetcher" server/coast-data.ts` (line 335)
- `grep -n "^export const assetGroup" server/coast-data.ts` (line 66)

## B. Scripts and workflows

| path:line | What it does | Replacing name | Feed exists? | Still to build (FE-62 b) |
| --- | --- | --- | --- | --- |
| `scripts/coast/publish_assets.py:33` | `ORIGIN` Fish Worker; line 8 says assets are read from it | none (assets are not a feed) | no | a SkipperCast-side source for terrain/chart files, or a final copy and then delete the script |
| `.github/workflows/coast-assets.yml:3` | FE-85 job: copy terrain, imagery, habitat assets from the Fish Worker (calls the script at lines 48, 51, 58) | none | no | run once more on the final Fish release, then remove the workflow |
| `.github/workflows/deploy-cloudflare.yml:390` | comment: unset `COAST_FEEDS` keeps all sources on the Fish bridge; line 391 passes `vars.COAST_FEEDS` | all five | yes | reword; keep the variable |
| `server/env.ts:62` | comment on `COAST_FEEDS` (line 64) naming the Fish Worker | all five | yes | reword |
| `scripts/wrangler_config.mjs:122` | comment: sources served from feeds instead of the Fish Worker (`COAST_VARS`, line 124) | all five | yes | reword |

Greps:

- `grep -n "fish-report.g4651" scripts/coast/publish_assets.py` (line 33)
- `grep -n "Fish Worker" .github/workflows/coast-assets.yml` (line 3)
- `grep -n "Fish Worker bridge" .github/workflows/deploy-cloudflare.yml` (line 390)
- `grep -n "Fish Worker" server/env.ts` (line 62)
- `grep -n "Fish Worker" scripts/wrangler_config.mjs` (line 122)

## C. Docs that name the Worker

| path:line | Note |
| --- | --- |
| `docs/coastal-service.md:39`, `:68`, `:139`, `:154`, `:241` | bridge contract, asset copy, fallback rule, and "deleting the Fish Worker" precondition (moving collectors and witnessing refreshes); rewrite to past tense |
| `docs/FISH-MERGE-STATUS.md:62` | records the bridge (PR 381); FE-62 b must complete this file |
| `docs/plans/front-end/dev-plan.md:553` | FE-62 status line, quoted below |
| `docs/engineering/adr/0009-front-end-rebuild-and-fish-merge.md:83` | decision text naming the bridge (history; leave, add a dated note) |

Greps: `grep -n "Fish Worker" docs/coastal-service.md`, `grep -n "bridge has merged" docs/FISH-MERGE-STATUS.md`,
`grep -n "FE-62 · " docs/plans/front-end/dev-plan.md`, `grep -n "bridge to the Fish Worker" docs/engineering/adr/0009-front-end-rebuild-and-fish-merge.md`.

## D. FE-62 part b still has to build

`docs/plans/front-end/dev-plan.md:553` says: "Part b, retiring the bridge's Fish Worker fallback in
`server/coast-data.ts` and completing `docs/FISH-MERGE-STATUS.md`: pending (`claude/fe-62-bridge`)". Its
accept test 3 is "`server/coast-data.ts` has no Fish Worker origin". Left to do:

1. Name all five feeds in `COAST_FEEDS` (report, nearshore, water-quality, ocean, history) and confirm
   `X-Coast-Upstream` has no `fish=` entry for a full cycle.
2. Remove `ORIGIN`, the `fishReport` call, `fishEnrichment` and the generic Fish fetch (section A).
3. Decide terrain and chart files: they have no SkipperCast feed. Publish the last Fish release to R2 first.
4. Remove `scripts/coast/publish_assets.py` and `.github/workflows/coast-assets.yml` after that copy (section B).
5. Update the docs in section C and complete `docs/FISH-MERGE-STATUS.md`.
6. Owner only: archive then delete the Fish repository and Cloudflare resources (dev-plan line 558).

## E. Not Fish: leave alone

- `scripts/rules_status_probe.mjs:20` and `scripts/check_feed_freshness.py:45` use `skippercast.g4651.workers.dev`,
  SkipperCast's own Worker. Grep: `grep -rn "skippercast.g4651" scripts`.
- `web/fish-links.ts` and `server/coast-pages.ts:3` (`FISH_REGIONS`) map old Fish links to regions and never
  call the Worker. Grep: `grep -n "fish-links" server/coast-pages.ts`.
- `docs/archive/fish/**` is the historical archive (FE-62 part a).

Whole-repo check: `grep -rnIi "fish-report.g4651" server scripts .github` lists only section A line 12 and
section B (`publish_assets.py:33`) after this plan.
