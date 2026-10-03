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

Before downloading a new survey for a processed reach, narrow catalog searches
with its retained coverage checkpoint. The existing discovery tool accepts
zero-native-support planning cells instead of a whole reach envelope:

```bash
PYTHONPATH=src:. python research/scripts/discover_noaa_multibeam_footprints.py \
  --coverage-folder var/seafloor/reaches/REACH_ID \
  --max-cells 128 --max-groups 3 \
  --output var/seafloor/source-review/REACH_ID-gap-leads.json
```

The tool verifies `coverage-cells.json` against `coverage-checkpoint.json`, queries
exact EPSG:3310 polygons, excludes partial-support cells, and preserves the
coverage/input hashes. Reuse the receipt; `--resume-from PREVIOUS_RECEIPT`
continues at `next_group` only when the checkpoint, coverage hash and
`query_batch_cells` are unchanged. A changed snapshot starts a new search. These 250 m cells use a provisional reference depth band: they are
acquisition priorities, not verified shallow-water footprints or new measured
area. Partial-support gaps require native masks rather than a whole-cell query.
Catalog hulls still need actual local depth/support and same-acquisition checks.

When the useful gaps are inside partially supported cells, add
`--cache-root var/seafloor/cache` to the same command. This opt-in mode verifies
the retained `run.json` physical identity, the complete normalized source set
and every COG hash. It reuses `coverage.footprint` to union the valid nominal
0–91.44 m masks, then subtracts that union from owned planning cells. It does
not infer gap shapes from coverage percentages or query a whole partially
mapped square. The private `acquisition-support/` cache retains code, runtime,
cell and source identities; later searches reuse it without terrain extraction.
Missing files, incomplete source sets, inconsistent cell support or changed
resume identities fail before network queries. A legal-only refresh can reuse
the physical support cache. The uncovered planning geometry still has unknown
local depth and is never counted as new measured coverage or habitat.

For nominal 300 ft acquisition, optionally add `--exclude-measured-deep` with
`--cache-root`. The planning reference extends to 100 m, so some apparent gaps
are already measured deeper than 91.44 m. This option subtracts only valid native
depths above that ceiling from acquisition query polygons, clipped to reviewed
source bounds and owned cells. Masked, nonfinite and unmeasured pixels remain
unknown. `excluded_non_target_query_m2` records search reduction, never completed
shallow coverage or habitat. Datum, precision and unknown interpolation limits
remain explicit. Resume requires the same mode and checked mask identities;
do not rerun finished catalog searches just because the filter became available.

Timebox one unresolved source to about 45 minutes. Record `access-failed`,
`format-unsupported`, `license-unclear`, `no-valid-cells`, `coarse-only` or
`duplicate` with the evidence and next action. Source holds do not imply the
reach has no habitat. Retry transport failures when the source is available;
license or unsupported-format holds need review/code, not endless retries.
The scheduler processes usable sources only; it does not automatically resolve
held licenses or discover missing native formats.

### Original sonar leads without a finished grid

Use the producer's [MB-System reader](https://github.com/dwcaress/MB-System),
not a guessed binary decoder. Its official
[MBARI image](https://github.com/dwcaress/MB-System/blob/master/docker/README.md)
can provide `mbinfo` and `mblist` on a suitable Linux host. Pin the image digest,
record actual reader version and binary hash, and retain original compressed and
native file checksums. A task-local reader environment avoids replacing system
packages. Do not bulk-download a cruise before a bounded file test.

`mbinfo -F57 -I ORIGINAL_FILE -V` checks format 57 depth/quality statistics.
For actual sounding positions, use `mblist -F57 -I ORIGINAL_FILE -MA -OXYzFMN#`:
longitude, latitude, positive-down meters, beam flag, epoch time, ping and beam.
`-MA` is essential: the default coordinates describe vessel navigation rather
than all seafloor beam positions. Default validity checking excludes bad/null
beams; `-U2` retains those for a separate quality audit. Never use `-W` (feet),
decimation or ping averaging in a table labeled with this contract.

Retain a private table receipt with those exact `columns`, reader command/hash,
`stdout_sha256` and `rows`. A separately filtered nominal 0–91.44 m good-beam
subset needs its own `shallow_sha256` and `good_nominal_shallow_rows`. The shared
offline triage verifies decompressed bytes/counts and the existing gap checkpoint:

```bash
PYTHONPATH=src:. python research/scripts/triage_multibeam_beams.py \
  --beam-table PRIVATE_SHALLOW_TSV_GZ --beam-receipt PRIVATE_READER_RECEIPT \
  --coverage-folder var/seafloor/reaches/REACH_ID \
  --cache-root var/seafloor/cache --exclude-measured-deep \
  --output var/seafloor/source-review/REACH_ID-beam-triage.json
```

Use `--table-kind all` for a complete reader table. No network or terrain rebuild
is needed. Good-beam points in gaps establish a useful acquisition lead, not
gridded coverage, habitat area, fish presence or publication permission. Do not
buffer points, accept a survey hull or fill between tracks to claim measured
area. The next stage must review gridding/valid support, sampling resolution,
navigation, datum, sound-speed corrections, source rights and normal adapters.
Overlapping files from one cruise remain one survey evidence line.

### Private original-beam grid reconciliation

For a raw-swath lead, first reconcile a bounded grid against the complete good
original beam tables. Do not filter those tables to 91.44 m before gridding:
a bin can contain both shallow and deep contributors. Keep every input and
output hash, no background grid, no spline fill, ping decimation or averaging.
Run this research stage beside the retained originals on a suitably sized host;
it is not a product adapter or catalog promotion.

The currently tested MB-System `mbgrid` executable has SHA-256
`9ebca2e54b861c333e97ac0bdf89d3f89b7bcc2d8bfe50f496ba17d540ceea33`.
Use recorded `-A2 -F2 -C0 -G4 -M -P1 -U0`, exact square-meter bins with
`-E...meters!`, explicit UTM zone and a bounded geographic `-R` window.
The corresponding all-good `mblist -F57 -MA -OXYzFMN#` executable is pinned in
the normalizer. These options are specific to the tested executable, not a
portable prescription for another MB-System build.

A real two-file test found that this pinned median-topography executable,
without `-U`, admitted 702,695 of 719,469 good soundings inside the window. The
original-epoch first-contributor 300-second diagnostic reproduced that admitted
total. A separate `-U0` run retained all 719,469; independent count, upper-median
and dispersion reconciliation then passed. Preserve the failed prototype and
its receipt. Never alter its receipt, silently fit registration to its output,
or waive a parity mismatch. Recheck this behavior for any different binary.
The original [median gridding source](https://github.com/dwcaress/MB-System/blob/master/src/utilities/mbgrid.cc)
is a diagnostic reference; the executable test establishes the pinned behavior.

```bash
PYTHONPATH=src:. python research/scripts/prepare_multibeam_grid.py \
  --topography PRIVATE_ROOT.asc.gz --count PRIVATE_ROOT_num.asc.gz \
  --dispersion PRIVATE_ROOT_sd.asc.gz --grid-receipt PRIVATE_GRID_RECEIPT \
  --beam PRIVATE_FULL_BEAMS_TSV_GZ PRIVATE_BEAM_RECEIPT \
  --native-root PRIVATE_ORIGINAL_FOLDER --output PRIVATE_SUPPORT_COG
# Repeat --beam once per original input, in datalist order.
```

The grid receipt records `command`, `binary_sha256`, `returncode`, original
`inputs` (`path`, `bytes`, `sha256`) and `outputs` (`path`, `sha256`); missing datum
stays unknown. ASCII output roles must match the command's `-O` root. The
normalizer reopens native bytes and verifies full decompressed table/grid hashes,
then independently checks occupied-bin support, sounding counts, the upper
order-statistic median and sample RMS dispersion. Dispersion is not calibrated
uncertainty. ESRI corners and the writer's ten-significant-digit rounding are
explicit: all plausible neighboring boundary bins are withheld, not shifted.

The private five-band COG retains positive-down depth, good-sounding count,
median dispersion, and contributor minimum/maximum depth. Missing cells,
registration ambiguity and bins crossing zero or 91.44 m are masked. Grids
retain deeper noncrossing support for later reviewed derivatives; only positive
bins with all contributors at most 91.44 m qualify for the nominal target band.
Derived bin spacing is not native sonar resolution or accuracy. A passing
receipt still says `source_qualified=false`, `exportable=false` and reports
zero new coverage/candidates/public locations. Navigation, acquisition processing,
sampling adequacy, rights and the production adapter must be reviewed separately
before physical coverage can be credited. MPA/closure screening remains last,
before publication or fishing export.

### Import a reviewed private measured-bin grid

The `measured-multibeam-grid` adapter connects the preceding private support COG
to the existing physical terrain pipeline. It is deliberately local/cache-only:
`--fetch` never downloads a dataset landing page or invents a derived artifact.
Do not label it `usgs-geotiff`, use its sounding-count band as uncertainty, or
claim its bin spacing is native sonar resolution.

Review a candidate row with the original source landing URL, derivative COG
`sha256`/`bytes`, `resolution_m` equal to the processing bin spacing, unknown
vertical datum where applicable, and explicit `grid_preparation` fields:
`profile=measured-multibeam-grid-v1`, `preparation_receipt_sha256`,
`preparation_code_sha256`, `native_sampling=irregular-original-soundings`,
`grid_spacing_m` and `minimum_good_soundings=3`. The same-stem JSON beside the
private COG must be the unchanged preparation receipt. Import the pair through
`skippercast.seafloor.source_ingest.ingest(row, bounds, root=..., local=...)`, retain its reviewed draft, and use
`promote-survey --physical-only` before `run --physical-only`.

Three good contributors is a conservative sparse-bin policy for this profile,
not proof of independent samples, calibrated accuracy or complete insonification
of the bin. The adapter excludes sparse, nonfinite, masked and mixed-depth bins,
retains all five diagnostic bands and exact registration, and does no smoothing,
resampling or fill. The receipt explicitly separates `native_resolution_m=unknown`
from `grid_spacing_m`; downstream derivatives use the latter as processing scale.
Coverage measures represented valid bins, not sonar beam-footprint area.
The gateway preserves the original native adapter and its cache keys. Derived
keys bind the private adapter, shared window helper and raster-identity code;
unchanged native inputs do not require a blanket COG rebuild.

New source rows and private products stay in the isolated processing root until
source review is complete. This initial format permits only candidate/private
status with unqualified release rights. Publication/export and government
public-domain relabeling are rejected. Producer attribution, compatible derivative
license, navigation/accuracy limits and whole-polygon spatial screening need a
separate reviewed release contract. Sparse-bin holds must not prevent processing
other sources. Record source-only represented area separately from new area
deduplicated against the existing coverage union.

## Reviewed originals awaiting publication rights

Do not mislabel non-government data as public domain. When a native original
has been reviewed for personal/research processing but public redistribution is
not yet qualified, use explicit private qualification:

```bash
python -m skippercast.seafloor promote-survey --draft REVIEWED_DRAFT \
  --rights-url ORIGINAL_TERMS_URL --physical-only
python -m skippercast.seafloor plan --physical-only --max-new 3 --json
python -m skippercast.seafloor run --reach REACH_ID --physical-only
```

`physical-only` source status requires the same checked native receipt and
shallow valid pixels, but grants no rights. Default planning/processing excludes
these sources. Their outputs live in `var/seafloor/private-reaches/<reach>/`,
are retained by checked private recovery, and do not overwrite public reach
outputs or advance the committed public ledger. Report their measurements
separately. Publication rejects private-source receipts even if a legal snapshot
is available. Public qualification still requires reviewed publication rights.

Original CSUMB gzip-tar grids hosted at NOAA's reviewed `harold_heath` archive
use `--format arcgrid` and the exact grid directory. Existing archive caches and
catalog IDs should be reused. Consult the current producer policy alongside the
original metadata; public-use and for-profit restrictions are different from
an original-metadata "to be determined" placeholder. Do not infer a license
from NOAA hosting or treat a format fix as measured geographic expansion.

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
[native terrain support](../../docs/engineering/native-terrain-support.md).
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

## Original-producer publication terms

The reviewed NOAA-hosted CSUMB grids have a distinct
`csumb-public-use-noncommercial` profile; distributor hosting does not grant
federal public-domain rights. Bind `rights_review` to the original source SHA,
actual review date and official CSUMB policy, retaining producer acknowledgment,
noncommercial use and the navigation/for-profit restrictions. The shared
`source_rights` feature/export metadata and manifest attribution preserve mixed
source terms. Unknown or conflicting contributors block release. A for-profit
deployment profile cannot use this permission without express producer approval.

Do not promote private CSUMB rows until map and export consumers display the
credits/notices. Then transfer hash-verified private physics without recomputing
unchanged scientific inputs, apply current whole-polygon spatial screening,
and verify live features and export notes. A source-use contract is independent
of MPA clearance, measured coverage and proof of fish presence. See the
[release contract](../../docs/archive/seafloor-csumb-release-contract-2026-09-30.md).

After rights-only promotion in place (preserve catalog source ordering), use:

```bash
python -m skippercast.seafloor adopt-private-physics --reach REACH_ID
python -m skippercast.seafloor run --reach REACH_ID
```

Adoption requires a complete private receipt, unchanged reference, scientific
source metadata, rules, substrate, dependencies and all numerical implementation
hashes, plus checked original/normalized bytes. It preserves candidate geometry
and ranking, updates only physical cache identity, and leaves the copied receipt
explicitly private until the normal runner applies the current screen. It never
updates the public ledger or publishes. Existing destination caches are refused
to preserve prior work; changed scientific inputs require normal recomputation.
Do not remove or overwrite a destination just to force adoption.

## Nested original ArcInfo products

Reviewed NOAA `ventresca` survey bundles, including BigCreek and SCC, contain
original bathymetry ZIPs inside their gzip tar. Use the shared `arcgrid` adapter
with an exact virtual member path: `ZIP_MEMBER/GRID_DIRECTORY`. For example:
`BigCreek2010/BigCreekN.2010_2m.5m.10m_bathygrids.zip/ArcViewGrids/bc_n_2mbathy`.
Inspect and select each native 2 m/5 m bathymetry grid; never select hillshade,
slope or interpolated all-depth composites. Only one explicitly named nested
ZIP is supported. Archive/member/expansion limits, path/link checks and checksums
apply before extraction. The original archive stays the private recovery object.

A successful adapter proves native access, not publication permission or
coverage. Record exact embedded acquisition dates/datum, inspect valid pixels,
retain unknown per-cell uncertainty/interpolation and shared lineage, qualify
the source, then process real reference intersections. Use private qualification
when release review is pending; whole-polygon restrictions remain the final
public/export stage. Do not replace an inspected ZIP with an ad hoc extracted
file hosted elsewhere. Recheck existing normalized raster identities when the
adapter implementation changes, and update the reviewed cache-key pin only
after parity proof. See the dated BigCreek nested-adapter proof.

Use the CI Node major (22) for client validation. On macOS, temporary Vite build
checks need a canonical TMPDIR path rather than the `/var` symlink alias; retain
the real checks and do not weaken modulepreload assertions to mask this.

Regional publishers retain a batch-bound result under the private publication receipt prefix. The ledger job names ready, held and failed regions from those receipts; missing receipts are incomplete, and measured ledger totals never prove live publication. A failed-jobs-only retry reuses the prepared batch; rerunning all jobs creates a new batch and may repeat processing.
