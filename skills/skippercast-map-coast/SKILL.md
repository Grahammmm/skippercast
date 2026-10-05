---
name: skippercast-map-coast
description: Expand measured 0–300 ft coastal habitat coverage using original survey qualification, cached physical mapping, rankings and final-screen publication. Use for new survey batches, stalled mapping or regional rollout; distinguish maintenance from geographic expansion.
---

# Execute measured coastal habitat expansion

Map bottom features suitable for lingcod and rockfish, initially Monterey–Point
Conception at nominal 0–91.44 m. Habitat suitability does not require proof that
fish are present. Preserve the distinction in map labels. Read current
`AGENTS.md` and `CONTRIBUTING.md`; use existing `skippercast.seafloor` commands,
catalogs, grades and progress storage. Paths are relative to the checkout.

## Deliver the appropriate level of detail

Choose one visitor-visible batch with an explicit acceptance test before
research. First reuse rights-qualified measured rough patches whose only
physical hold is insufficient surrounding support for a grade. The separate
search-area screen can release these as unranked, limited-confidence outlines;
it does not change the 80% grading rule, measured geometry or coverage credit.
Search areas remain Tier 1 and are not exported as precise fishing spots.

Use detailed rankings where supported and broader search outlines where only
that claim is supported. Do not make useful habitat information depend on
navigation-grade certainty. Preserve unknown datum/accuracy and limits on
depth interpretation; this is not permission to ignore known terrain artifacts,
private-source qualification, source rights or spatial restrictions. A source
quality hold stays held until evidence resolves the specific issue. Unknown
substrate stays unknown. Retain shallow 4–24ft knowledge separately for future
shore-fishing and spearfishing layers.

Keep the first batch bounded to one reach and its regional publication. Reuse
hash-verified physical outputs when only the display/screen policy changes.
Acceptance is a newly usable map outline with accurate labels, current source
rights and whole-polygon restrictions, verified archive/map readback, and no
unsupported ranks or precise exports. Count search areas separately from ranked
habitat and new measurement area. A green job or diagnostic is not that release.

## Start from the smallest current state

Fetch main, reconcile relevant PRs, latest ledger, saved physical receipts and
active jobs. Do not read the entire research archive or conversation. One
coordinator owns shared catalog/skill/ledger integration and public releases;
source workers own isolated qualification tasks and independent review. Record
ownership and exact source/gap in the established coordination issue/checkpoint.
Do not duplicate another worker's batch or wait repeatedly for an idle chat.

For an authorized parallel or overnight run, use the bounded
[parallel pilot procedure](references/parallel-pilot.md). It assigns isolated
work, limits work waiting for integration, and measures verified map additions
before deciding whether more agents would help. Use the existing coordination
issue and private checkpoint; this is not another source catalog or scheduler.

Use the pinned runtime and existing verified reference/cache:

```bash
PYTHONPATH=src:. python -m skippercast.seafloor plan --max-new 3 --json
PYTHONPATH=src:. python -m skippercast.seafloor plan --physical-only --max-new 3 --json
PYTHONPATH=src:. python -m skippercast.seafloor ledger --region central-coast --json
```

Restore the reference only if missing/changed. `plan.execution` identifies the
selected new-reach batch, existing refreshes and next action. A processed reach
may still gain a new source; scheduling output never proves geographic growth.

## Choose the next executable task

The goal is additional usable habitat, not necessarily additional sonar coverage.
Before another maintenance or infrastructure batch, apply
[habitat expansion preflight](references/habitat-expansion-preflight.md).
A processed reach may contain reviewed classified habitat that the rough-terrain
extractor did not outline. Test a bounded positive delta and preserve the
distinction between an interpreted habitat area and a ranked terrain patch.
Do not assume an exhausted native-survey queue exhausts habitat opportunities.


1. Release already supported, rights-qualified private candidates with current
   spatial screening. Apply the appropriate ranked or unranked contract.
2. Test reviewed classifications for additional habitat within measured coverage.
   A positive private proof needs its own reviewed release contract; never
   fabricate a terrain grade to reuse an incompatible contract.
3. Harvest qualified cached sources not yet processed in useful native windows.
4. Otherwise qualify a dense original producer grid against a retained native
   gap. Include gaps inside partially supported planning cells and inspect a
   bounded window before large acquisition.
5. Use raw sonar only when a small test establishes useful shallow gap support
   and a realistic path to sufficient terrain measurements.

Prioritize additional valid shallow support and supported habitat rankings,
then effective resolution, access/rights readiness and processing resources.
Envelope overlap is only a scheduling estimate. Survey hulls, vessel tracks,
program goals, mirrors and related products do not establish new measurement.
Reconcile acquisition lineage and saved negative findings before downloads.
BlueTopo supplies planning context/original-contributor discovery, not fine
Tier-2 terrain in this pipeline.

Use the existing source-review queue and retained discovery receipts; do not
create a second catalog. Each assigned item needs the target checkpoint/gap,
source lineage/hash, owner, stage, next reproducible command, cache location,
resource bound, uncertainty and exact blocker. Keep at most two qualified
handoffs ahead of processing. A rejected lead is revisited only for new evidence,
changed access or a materially different method. Missing data differ from
measured smooth bottom with no suitable patch.

When resuming source discovery, use `plan --region REGION_ID` and its
`deferred_source_reviews` before reopening a historical lead. After a bounded
completed test, save the evidence-bound discovery decision with `review-source`;
read [source-review checkpoints](references/source-review-checkpoints.md) for
scope, expiry and private recovery. This checkpoint is workflow memory, never
source qualification, a publication hold override or measured progress.

## Qualify and process a bounded batch

Read [source recipes](references/source-recipes.md) only for the relevant
producer/format: original USGS/NOAA grids, nested ArcInfo archives, CSUMB terms,
private MB-System preparation or measured-bin ingestion. Reuse original and
normalized caches. Preserve acquisition dates, datum uncertainty, interpolation
masks, effective resolution and independent acquisition lineage. A distributor
does not grant the producer's rights.

Use actual valid 0–91.44 m native pixels inside the target window. Original
sonar requires complete accepted beam tables and independently reconciled
count/median/dispersion grids. No fill, smoothing or decimation to create
coverage. Processing spacing is not native sampling accuracy, contributor count
is not independent observations, and dispersion is not calibrated uncertainty.
Scope legacy reader PROJ variables to that subprocess; Python GIS uses its own
compatible database. Preserve failed outputs and resume only completed stages.

Use existing slope/VRM/BPI/substrate rules and species fit 1–3. Unknown substrate
is not sand. Do not relax neighborhood-support thresholds to manufacture
rankings. Coarse data support broad features; finer-looking resampling cannot
support small piles. Rule changes require versioned science review and fixtures.

Process up to three useful reaches per source batch with the bounded tiled
runner. Estimate native pixels, memory, scratch and bytes first. Use the approved
processing host when local resources are inadequate. Keep private originals and
geometry there; aggregate receipts suffice for coordination. No routine
`--force`, blanket cache rebuilds or unrelated downloads.

```bash
PYTHONPATH=src:. python -m skippercast.seafloor run --reach REACH_ID --physical-only
```

Private source qualification and physical work can continue through publication
rights or legal holds. The detailed [execution and release contract](references/execution-and-release.md)
explains coverage checkpoints, cache identity, interrupted jobs and private
adoption. Physical caches exclude legal snapshot changes. Unknown datum limits
depth claims; it does not automatically stop nominal habitat research.

## Measure the result and change course

Compare the prior and new valid measurement unions in the same scope before
claiming additional area. Never add overlapping source or PR totals. Record:

- Additional deduplicated native support and source-only represented support.
- Ranked physical habitat, insufficient-support candidates and hold reasons.
- Screened habitat and verified public area/count, separately.
- Removed/revised candidates as well as additions; polygon splitting is not
  geographic expansion.

No-growth refreshes are maintenance. A downloaded source, document, adapter or
successful CI run is not new coastline. A pipeline fix is useful progress only
when a reproducible test or real-run receipt demonstrates the blocker removed.
If no new batch is runnable, inspect retained native gaps and qualify the next
original source instead of repeating maintenance as the expansion task.

After two unsuccessful attempts, change approach. After 20 active investigation
minutes without a usable batch or a demonstrated release-blocker fix, save the blocker and
switch to another executable task. Normally timebox an unresolved source to
45 active minutes; a prepared incremental batch may get one bounded 60-minute
test. If two batches add no usable coverage, rankings or screened search areas,
change source or delivery method immediately. Do not extend a long run merely
because more metadata or diagnostics can be produced. Report the visible-map
delta at each checkpoint. Ending a queue does not complete the mapping objective.
Do not repeatedly enlarge a sparse cruise. Let deterministic jobs run without
continuous model activity; use bounded completion checks rather than polling.

Provide concise meaningful updates and checkpoint the measured deltas,
commands/hashes, active jobs, ownership, blockers and next batch. A deadline is
an incomplete-work checkpoint, not a reason to claim the coastline complete.
If no independent executable work remains, explain the exact external need.

## Final screen, publication and verification

Apply reviewed source rights, current whole-polygon MPA/federal/security screens
before public map or fishing export. MPA-overlap candidates remain excluded.
Private physical outputs cannot publish merely because a screen exists. Retain
CSUMB/MBARI-specific credits and use restrictions; neither becomes government
public-domain by being hosted at NOAA. Trip-time season/gear notices remain
separate checks.

Use the existing scheduled workflow, per-region receipts and protected PR flow.
One coordinator dispatches/integrates; do not create a competing schedule.
Read [execution and release](references/execution-and-release.md) for commands,
failed-job resume, regional readback and exact validation. Before calling a
batch live, verify its current manifest, archive access and visitor map/export
behavior. Ledger bookkeeping alone is not publication.

Reconcile installed skills after changing the canonical repository version.
Historical baselines, resolved failures and old PR ordering are preserved in
[historical blockers](references/historical-blockers.md); read only the specific
entry relevant to a new diagnostic, never use that backlog as current state.
