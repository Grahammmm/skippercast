# Execution And Release

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

For reviewed native depth with unresolved acquisition artifacts, consult
[native terrain support](../../../docs/engineering/native-terrain-support.md).
The optional source-bound original rough/smooth interpretation restricts both
shared threshold calibration and habitat extraction while retaining measured
depth. It is not independent substrate evidence or a license/quality override.
Keep source and quality holds until separate review; compare all affected
calibration contributors, not only polygons bearing the newly bound source ID.
Use the existing physical-only runner and a focused source PR after the method
and original binding are verified. Do not guess masks or tune thresholds to
increase counts.

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

Publication is bounded by region: independent matrix jobs restore and validate
only their region's current-batch receipts, then build, screen and verify the
complete regional archive. `fail-fast: false` lets neighboring regions finish.
A separate ledger job restores hash-checked result files without source archives;
it never builds or publishes. It reports unsuccessful regional jobs explicitly.
The prepare output pins `SEAFLOOR_BATCH` for workers, publishers and ledger so
retrying failed jobs keeps the successful workers' original receipt identity.
Retrying the whole workflow runs prepare again and creates a new batch.

For diagnosis on the approved main runner, a region can resume from retained
current-batch receipts using `jobs finish --matrix MATRIX --region REGION
--batch ORIGINAL_BATCH`. Publication still revalidates native source bytes,
implementation and current whole-polygon screens; bookkeeping-only
`--ledger-only` cannot publish. Never confuse a restored ledger or completed
regional job with verification of every region. stderr stage messages show
restore and regional build/read-back progress while stdout stays machine JSON.


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

