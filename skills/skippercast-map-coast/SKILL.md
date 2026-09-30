---
name: skippercast-map-coast
description: Advance SkipperCast's 0–300 ft seafloor habitat map using the repeatable source-review, physical-mapping, final-screen and publication pipeline. Use for coastal coverage, new survey batches, stalled mapping jobs or regional expansion.
---

# Execute the coastal habitat rollout

The product is a map of measured bottom features suitable for lingcod, rockfish
and other configured species. Start with Monterey Bay–Point Conception and use
the same process for later regions. The user wants habitat suitability; fish
presence and catch confirmation are not prerequisites. Do not spend a session
trying to prove fish are present. Do retain the distinction in map labels.

This file is the canonical execution plan in the repository. Paths below are
relative to its checkout, not to an installed skill directory. Read `AGENTS.md`
for current collaboration, branch and release rules. Use the existing package;
no new one-off survey scripts, parallel catalogs or alternative grading scales.

## What changed in this plan

Physical mapping and legal publication are separate stages. An unavailable MPA
feed, unreviewed security zone or changing legal snapshot must not prevent
survey ingestion, measured coverage, terrain extraction or candidate ranking.
Compute and cache those first. Apply the current spatial screen at the release
stage; only passing candidate polygons enter the public fishing layer or GPX.
A legal hold does not erase a successful physical stage or send it back through
expensive terrain computation. This preserves the owner's request to exclude
MPA fishing points while moving the mapping work forward.

The runner is deterministic Python, not an autonomous research model. Routine
execution uses no LLM or token budget. A modest coding/research model can qualify
metadata and investigate a failed adapter; use more reasoning only for a new
format, contradictory metadata, scientific rule changes or spatial legal review.

## Read the actual state first (minutes, not another broad research project)

1. Fetch main and make a task branch. Review open mapping PRs before qualifying
   another copy of the same survey. Never count a PR's proposed area as merged.
2. Use the repository's pinned runtime (`requirements-seafloor.txt`). Check the
   manifest and restore the reference only if missing or its hash changed.
3. Run the planner and ledger. Select a source batch or the highest-impact
   executable failure. Keep successful neighboring reaches moving.

```bash
python -m pip install -r requirements-seafloor.txt
export PYTHONPATH=src:.
python -m skippercast.seafloor restore-reference --fetch
python -m skippercast.seafloor plan --max-new 3
python -m skippercast.seafloor plan --region monterey-point-sur --json
python -m skippercast.seafloor ledger --region central-coast
```

`plan` uses the verified 250 m reference cells and *reviewed native windows* to
find unprocessed reaches. Overlap is explicitly an estimate for scheduling,
never surveyed area. Only `run`'s valid depth pixels create coverage. It also
lists the source-review backlog; those records have no implied regional
footprint until their native files have been inspected. Three new reaches is a
bounded default, not a scientific limit. Use `--max-new 0` for maintenance.

## Evidence and audit baseline: September 29, 2026

Recompute this baseline; do not preserve these numbers as current truth. At
main `026ab3d77`, the catalog had 385 records (3 usable, 381 candidate, 1 hold),
46 Central Coast reaches and a provisional 3,307.514375 km² reference band.
Mapped cell area was 100.713125 km²; selected valid native footprint was
98.151960 km²; screened habitat was 16.611763 km² / 1,006 polygons. These measures
are distinct: Tier 1 classifies planning cells at the 25% support threshold;
selected valid footprint measures surveyed intersections; Tier 2 is habitat,
not all surveyed bottom. Three Morro Bay reaches were on main, 43 unassessed.

The source catalog preserves the earlier surveys and metadata receipts. Earlier
research also produced hundreds of scripts and a stricter datum qualification
workflow. Its research outputs are leads, not additional published coverage.
Do not redo that corpus or impose navigation-grade datum conversion on Tier 2.

Observed causes and the concrete response:

| Cause / evidence | Response and remaining work |
| --- | --- |
| `jobs.select` formerly selected only processed reaches | `plan` schedules intersections of usable native windows with new reference reaches. Catalog promotion now unlocks work without a hand-edited ledger PR per reach. |
| Legal snapshot was included in the terrain cache key | `physical.json` hashes source/rule outputs separately. Snapshot changes rescreen saved candidates. `run --physical-only` deliberately defers the legal step. |
| A worker failure skipped the entire publication job | Per-batch private receipts identify completed, coverage-only and failed work. Aggregation runs after failures; other complete regions can publish. Missing/interrupted receipts never count as current success. |
| A >20-million-pixel habitat window lost already computed coverage ([#95](https://github.com/Grahammmm/skippercast/issues/95)) | A checked coverage checkpoint survives and is reported as `terrain-pending`. Large native windows now use bounded owned tiles, derivative halos, reach-wide thresholds, and joined components. Run the tiled/untiled parity tests and retain processing pixel/read bounds; insufficient scratch space still preserves the coverage checkpoint. |
| [Run 36500826580](https://github.com/Grahammmm/skippercast/actions/runs/36500826580) failed in all three workers | Logs show missing `jsonschema`. Main now installs the combined seafloor requirements and validates before writes. Do not diagnose this old run as an MPA failure. |
| [Run 36617058494](https://github.com/Grahammmm/skippercast/actions/runs/36617058494) failed during normalized-source verification | Logs show a reviewed COG hash mismatch. Preserve byte verification; investigate normalization/runtime differences rather than accepting arbitrary new bytes. Later runs passed. |
| [Run 36629238770](https://github.com/Grahammmm/skippercast/actions/runs/36629238770) published and verified tiles but failed opening the ledger PR | GitHub Actions lacked PR-creation permission. Later runs passed; #107 added explicit CI dispatch for bot-created PRs. Distinguish data publication from bookkeeping failure. |
| #91/#92/#94/#97/#104/#110 edit shared catalog, ledger or screens | Reconcile source/code dependencies once, rerun from current main, and let the scheduled job generate one ledger-refresh PR. Never cherry-pick an older whole ledger over newer reach results. |
| Many catalog products remain candidates | Batch original sources by format and geographic footprint; native inspection plus rights review is still required. Metadata counts are not mapped area. |
| Grades had two inconsistent ledger fields | New summaries populate `habitat_by_grade` and legacy `polygons_by_grade` consistently. |

Five later seafloor runs through [36658855204](https://github.com/Grahammmm/skippercast/actions/runs/36658855204)
succeeded. A green refresh alone is not geographic expansion: inspect the area
and candidate-count delta and the public manifest.

## The repeatable source batch

Qualify a whole producer product/window that intersects several reaches, rather
than treating each reach as an independent research project. Use the original
publisher. Search in this order; these are discovery priorities, not coverage
claims:

| Need | Publisher/product | Qualification check |
| --- | --- | --- |
| Fine coastal depth and substrate | [USGS CSMP / DS 781](https://pubs.usgs.gov/ds/781/) and [CMG releases](https://cmgds.marine.usgs.gov/) | Actual ZIP member, native raster, source dates, interpolation and depth-dependent resolution; many delivered 2 m grids include coarser deep data. |
| Outer shelf / 200–300 ft gaps | [NOAA NCEI hydrographic surveys](https://www.ncei.noaa.gov/products/bathymetry/hydrographic-surveys) | BAG elevation/uncertainty, actual shallow valid pixels, depth-band overlaps and survey lineage. |
| Local missing blocks | CSUMB SFML original files; NCEI multibeam acquisition archive | Rights and format first. Raw sonar may need specialist processing; do not promise it is a finished grid. |
| Locate original contributors / reference denominator | [NOAA BlueTopo](https://nauticalcharts.noaa.gov/data/bluetopo.html) | Compilation is context and discovery only in this pipeline, not Tier-2 depth. |
| Add evidence after terrain | USGS character/backscatter, video and samples | Record positional accuracy and same-survey lineage. Absence of video does not block habitat suitability. |

```bash
python -m skippercast.seafloor add-survey --url ORIGINAL_URL --id SURVEY_ID \
  --format usgs-geotiff --member EXACT_TIFF_MEMBER --bounds W S E N --fetch
# Review/edit the row metadata in var/seafloor/drafts/SURVEY_ID.json.
# Read original rights and acquisition metadata; do not edit its adapter receipt.
python -m skippercast.seafloor promote-survey \
  --draft var/seafloor/drafts/SURVEY_ID.json --rights-url ORIGINAL_RIGHTS_URL
python -m skippercast.seafloor plan --max-new 3
```

Promotion reopens the cached native source, checks normalized bytes, validates
schema/lineage and writes `catalog/surveys.json`. It is an explicit reviewer
operation, never performed by the scheduled job. The current promotion helper
supports the reviewed public-domain government license; a new license needs a
reviewed schema/adapter extension, not a fabricated public-domain label.

Record acquisition date separately from product release date. Mixed dates stay
explicit in notes; unknown stays unknown. The nominal 91.44 m ceiling is measured
in the source datum. Unknown datum prevents stronger depth claims, not basic
physical habitat work. Known filled/interpolated cells do not create habitat.
Same-acquisition bathymetry and backscatter are one evidence line.

Timebox one unresolved source to about 45 minutes. Record `access-failed`,
`format-unsupported`, `license-unclear`, `no-valid-cells`, `coarse-only` or
`duplicate` with the evidence and next action. Source holds do not imply the
reach has no habitat. Retry transport failures when the source is available;
license or unsupported-format holds need review/code, not endless retries.
The scheduler processes usable sources only; it does not automatically resolve
held licenses or discover missing native formats.

## Physical work first, spatial screen last

```bash
python -m skippercast.seafloor run --reach REACH_ID --physical-only --fetch
# After applicable restriction coverage is reviewed:
python -m skippercast.seafloor refresh-screen
python -m skippercast.seafloor run --reach REACH_ID --fetch
python -m skippercast.seafloor publish --region REGION_ID
```

The physical stage selects finer/newer supported depth, calculates slope/VRM/BPI,
joins known substrate, extracts patches, and grades A/B/C plus species fit 1–3.
Use existing `catalog/habitat-rules.json` and `atlas.scoring`; change thresholds
only with a versioned science review and before/after fixtures. Unknown substrate
is not soft sediment. Fine grids support small features; coarser grids support
broad areas. Mixed-resolution pixels must never become invented fine detail.

Each reach's private cache inventory includes only its own source hashes, so
workers do not download unrelated surveys as the coast expands.

Saved work is hash-verified under `var/seafloor/reaches/<reach>/`:

| File | Meaning |
| --- | --- |
| `coverage-checkpoint.json`, `coverage-cells.json` | Recoverable measured coverage if terrain/habitat fails; never implies published spots. |
| `physical.json` | Survey/rule identity and hashes of cells, terrain, candidate and comparison outputs. Legal snapshot is excluded. |
| `candidates.geojson` | Private physical candidates with legal status pending. |
| `habitat.geojson`, `held.geojson` | Current whole-polygon screen outputs. |
| `run.json` | Combined identity, measured timing, counts and ledger summary. |

A valid physical cache avoids repeated terrain work. Changed sources, masks,
rules, dependencies or physical implementation invalidate it. Corrupt output
fails; it is never silently reused. `--force` is for a justified recomputation,
not the normal daily command.

CDFW MPA, NOAA federal-area and local security review are the final spatial
screen. Qualify legal scope as a coherent coastal region, then add its reach IDs
to `catalog/seafloor-screen.json`; do not research the same permanent rule for
every rock pile. Source refresh still checks hashes and freshness. Missing,
stale, changed or out-of-scope evidence holds public candidates. Dynamic launch,
season and gear restrictions remain trip-time checks. All MPA-overlap polygons
remain excluded, consistent with the owner's earlier request.

## Daily execution and publication

`.github/workflows/seafloor.yml` runs daily at 10:23 UTC, on relevant main changes,
and by manual dispatch. Inputs are region (blank = catalog scope), optional
reach and `max_new` (default 3). It uses existing GitHub/R2 credentials; no new
bot, model provider or personal-data service is required. It becomes active only
when merged onto main. Local proof is not a production dispatch.

1. Validate runtime/manifest, restore verified reference, plan the next batch.
2. Attempt the legal refresh without stopping physical workers on failure.
3. Run at most three workers concurrently. Each records a unique run/attempt
   receipt, caches successful physics and saves measured coverage checkpoints.
4. Aggregate only that batch's receipts. A coverage-only reach shows measured
   cells with no old habitat; an interrupted reach blocks its regional bundle,
   while unrelated complete regions continue.
5. Build complete regional PMTiles, screen all public candidates, read bytes back
   from R2 and check the public HTTP Range endpoint for ready bundles.
6. Use lightweight private progress receipts to advance the next batch even
   while the ledger PR is pending; they do not change the reported main totals.
   Propose one small ledger-refresh PR and dispatch its required checks. Keep
   raw surveys, drafts and review receipts private. Surface incomplete stages as
   a failed workflow after retaining progress; never turn a failure into green.

Current publication uses a brief `updating` gate and can temporarily hide a
region while it rebuilds. Replacing this with immutable archive versions plus an
atomic manifest switch is a later availability improvement. Do not remove the
expiry/current-screen checks to hide an operational failure.

## Execute the remaining backlog in this order

1. **Reconcile existing work.** #91 adds southern Morro; #92 fixes deep Point
   Estero effective resolution; #94 adds southern Cambria; #97 and #104 add
   Conception NOAA depth; #110 supplies part of the Vandenberg screen. Check
   current status. This rollout includes the #92 resolution correction; reconcile its
   existing PR instead of applying it twice. Rebuild shared output after merging, never add PR totals.
2. **Use bounded native processing (#95).** `build_candidates` selects the
   disk-backed tile path above 20 million pixels; do not split accepted reach
   ownership or change resolution to avoid the guard. Verify
   `tests/gis/test_seafloor_habitat_tiles.py`, then retain the run receipt and
   `candidates.geojson` processing metadata. Budget scratch space for the native
   window, sample vectors and labels; resource failures retain coverage and
   must be investigated instead of repeated blindly. See the
   [r01 proof and handoff](../../docs/archive/seafloor-tiled-habitat-2026-09-30.md).
3. **Finish the inspected Monterey product.** Reuse the original DS781 2 m ZIP
   and private draft if present; verify bytes and mixed 1998–2012/2009–2010 input
   dates. Qualify the native window, then run all intersecting reaches. It is
   not completed just because the archive was downloaded.
4. **Batch adjacent originals.** Work north through Monterey/Aptos/Santa Cruz and
   south through remaining Morro/Buchon/Conception windows. For Big Sur and
   San Simeon, prioritize NOAA native shelf products and original contributors;
   a USGS program footprint is not proof of local coverage.
5. **Legal release sweep.** Screen completed physical outputs in regional batches.
   Where security evidence needs specialist review, leave that scope held and
   release other reviewed regions. MPA review never restarts acquisition.
6. **Audit the map from the visitor's perspective.** For reef/lingcod, check each
   released region's manifest, archive and map filtering. A public archive alone
   does not prove the UI selected it. Report data-feed and UI failures separately.
7. **Expand the reference scope only after the Central Coast loop is proven.**
   Add regional packages and explicit boundaries to the scope catalog, rebuild
   the reference with a migration of accepted reach IDs/ownership, review new
   sources and legal scope, then use the same planner/runner. Current scope is
   seven regions; this feature does not magically create statewide coverage.

## Completion and honest progress

A reach is not "complete" because it ran once. Report its surveyed fraction,
selected valid footprint, physical candidate count, public habitat area/count,
held count/reasons, and unresolved acquisition gaps. Distinguish a fully surveyed
smooth bottom with no suitable patch from missing or unprocessed surveys.

Every rollout report must state: before/after Tier 1 and Tier 2 km²; new public
candidate count (not catches); failed/held reaches and exact next action; source
batch queued next; public URL verification. A zero delta is a maintenance run.
After a week of zero new physical coverage, work the source/processing queue
instead of repeatedly refreshing only Morro Bay. Do not use a research document
count or a green CI badge as the progress measure.

## Validation before the PR

Run the seafloor GIS/contract tests, platform regeneration, repository/web checks,
and the repository's full CI checks. New behavior must demonstrate: new reaches
selected without accepting candidate envelopes, corrupt cache rejected, screen
changes reuse physics, missing-screen candidates remain private, failed terrain
retains coverage, and a missing current-batch receipt never becomes success.
Keep source qualification PRs separate from app UI changes. The installed skill
is a copy of this file; update it after changing the repo version so two plans
do not drift.

## Original ArcInfo GRID shelf products

Some original USGS shelf grids are `.tgz` archives containing an ArcInfo GRID
**directory**, rather than a GeoTIFF or E00 file. Use the existing `arcgrid`
adapter and specify `--format arcgrid` with the exact reviewed
`--member` directory (for example `sgf5gd/sgf5g`). Never select a rendered
hillshade, infer the folder name, or treat a directory listing as a downloadable
survey. The fetcher accepts this container only on the original USGS host.

Inspect the native AIG grid's CRS, spacing, mask and actual valid shallow pixels;
then normalize through the usual ingestion command. The archive and extracted
members have separate checksums, extraction is bounded, and links/traversal are
rejected. Original TGZ files are private recovery objects; extracted members
are reproducible scratch. The existing bounded processing, source qualification,
lineage, physical ranking and final spatial screen remain required.

1998 Monterey/Carmel/Point Sur EM300 grids have 5 m spacing, but that is not
sounding accuracy. Retain unknown vertical datum and interpolation masks when
not documented. Shared survey lineage cannot become independent evidence.
An adapter receipt proves faithful ingestion, not deduplicated geographic
expansion or published habitat. Adding an adapter changes normalization cache
keys; unchanged scientific raster identities can still verify prior source
reviews across lossless encodings.
