# Seafloor pipeline

Build a graded habitat planning map from original surveys, starting at Morro
Bay and extending from Monterey Bay to Point Conception. Completion means every
Central Coast reach is mapped or explicitly recorded as a hold or true gap, and
every reach with usable ≤4 m surveys has published habitat tiles. This describes
physical habitat suitability, never fish presence or catch probability.

## Current stage: M0, candidate inventory

[surveys.json](../catalog/surveys.json) inventories previously inspected files
and catalog leads. **Every row is a candidate**, not a usable survey or coverage
claim. The [row schema](../catalog/survey.schema.json) validates the seed now;
runtime ingestion and status transitions arrive in M1–M2. The existing
[coverage ledger](../dist/data/central-coverage-ledger-v1.json) is a legacy
research baseline, not the new tier ledger. Its chart-qualified counts cannot
be relabelled as habitat coverage.

M1 will introduce the shared `skippercast.seafloor` CLI. The published ledger
will be `dist/data/seafloor-ledger.json`, with band area, tier areas, holds,
surveys, timestamps and rule version by reach. Before that exists, new-tier
areas are **unmeasured**, not zero. M0 processes no area and publishes no tiles.

## Tiers and units

| Tier | Meaning and gate |
| --- | --- |
| 0 | No usable original survey established. |
| 1 | At least 25% of a 250 m cell has valid, non-interpolated depth from a usable survey. |
| 2 | Connected rough-bottom polygon ≥0.1 ha, nominal depth 25–300 ft, terrain grade A/B/C and species fit 1–3, passing a whole-polygon legal screen no older than 35 days. ≤4 m grids support pile-scale areas; 4–16 m grids support broad areas only. |
| 3 | Tier 2 plus datum-qualified depth, an independent confirming survey/sounding, a dated camera/sample within its positional error, or at least three opt-in trip reports. Future work. |

Cells carry tiers 0–1; polygons carry tiers 2–3. Compute in EPSG:3310 and publish
geometry in EPSG:4326. The provisional denominator uses BlueTopo's ≤100 m band
as a margin around 300 ft (91.44 m), not as measured habitat depth. Retain its
tile IDs and date. Never sum overlapping surveys or present their envelopes as
valid coverage. The ledger must distinguish cell coverage from habitat area.

Tier-2 depth is nominal in the source datum; an unknown datum remains
`"unknown"` and does not alone block tiers 1–2. Clip patches at 300 ft nominal.
Grids coarser than 16 m provide tier-1 context only. BlueTopo/NBS compilations
provide the reference band and original-source discovery, never habitat depth.

## One pipeline, in order

**Reach/grid → manifest → hash cache → format adapter → valid coverage → terrain
→ substrate → habitat grade/fit → legal screen → ledger and PMTiles.**

1. Split the seven existing regions into approximately 10 km reaches, ordered
   outward from Morro Bay. Assign fixed 250 m cells without overlapping ownership.
2. Qualify original survey files through one manifest. Download once, verify
   SHA-256, and cache sources and normalized rasters by hash. Read windows with
   a 100 m seam margin; preserve no-data, interpolation and uncertainty masks.
3. Choose the finest source, then newest, per cell. Compute slope, 3×3 VRM and
   fine (~25 m) and broad BPI. Join substrate only where valid classifications
   overlap; unknown substrate is not soft sediment.
4. Rule `seafloor-habitat-v1`: rough pixels have VRM at/above the reach's 80th
   percentile **or** fine BPI above +1 standard deviation, and are not classified
   soft where substrate exists. Form 8-connected patches; close one pixel without
   bridging no-data; discard <0.1 ha; simplify by at most half a native cell.
5. Reuse [atlas scoring](../src/skippercast/atlas/scoring.py) for A/B/C using
   `relief_210m_m`, `rugose_or_bedrock_fraction_210m`,
   `plane_residual_rms_250m_m` and `rough_habitat_within_250m_ha`. Species fit is
   **3 best**, 2 moderate, 1 otherwise: 3 requires a depth range within the cited
   core band and grade A/B; 2 covers band overlap or grade C. Start with reef
   rockfish, lingcod and shallow-reef cabezon. Fit is suitability, not abundance.
6. Screen full polygons against CDFW MPAs, NOAA federal areas and security zones.
   Failed polygons are held; stale screens hold the reach. No restricted source
   or private trip information is published. Refresh legal evidence separately
   from static surveys; the screen is planning information, not legal advice.
7. Publish `cells` and `habitat` layers to
   `/feeds/tiles/seafloor/seafloor-<region>.pmtiles`. Keep review receipts private
   under R2 `seafloor-review/` and cache under `seafloor-cache/`. Commit only the
   small new ledger. Rerun only when a survey hash, rule or screen changes.

Each habitat feature carries source IDs, survey year, resolution, datum,
nominal depth range, terrain metrics/grade, species fits, substrate provenance,
independent evidence, screen snapshot and rule version. Required label:
“Habitat candidate, unverified. Nominal depth (&lt;datum&gt;); verify on your
sounder.” Coarse products add “Broad area, not an individual pile.” Exports
also say “Planning only. Not a navigation chart. Check current CDFW regulations.”

## Reading and extending the seed

The inventory records its input commit, all registry/queue/review/gap files
examined, and per-row evidence as repository paths plus JSON Pointers. A field
reference may point to the value itself or its containing source record.
`inspection_level` distinguishes native-file inspection, metadata inspection
and catalog leads; even a native inspection is not new-pipeline acceptance.

- One row identifies a transport URL, product kind and, when recorded, its archive member.
  `sha256` and `bytes` describe the downloaded transport file, not the extracted
  member. Bundles with unrecorded member paths remain candidate rows with
  unknown member/resolution; adapters must expand and identify them before use.
  Multi-file grid directories have unknown transport hash/size until
  the adapter records their components. Different resolutions remain separate.
- Native cell measurements take precedence over metadata spacing. A VR BAG's
  overview spacing cannot stand in for refinement resolution; leave the scalar
  resolution unknown until the adapter resolves it. Resampled grid spacing does
  not prove native sounding detail. Vectors have no assumed raster resolution.
- Missing or conflicting values stay `"unknown"`. Acquisition year differs from
  release year. This inventory does not revalidate access or grant reuse rights.
  `public-domain-us-gov` is copied only from existing explicit rights evidence;
  unknown rights must be reviewed before promotion or publication.
- `derived_from` links recorded shared acquisitions. `lineage_status: unknown`
  means independence is unresolved, **not** that the source is independent.
  Terrain and substrate from one acquisition are one line of evidence. Publication
  families and alternate grids need lineage review during ingestion.
- Backscatter is evidence of acoustic response, not depth or automatically rock.
  Video, samples and uncertainty-only companions are not depth/substrate rows;
  attach them to reviewed sources in the later adapters/evidence workflow.
- No new per-survey scripts or public review dumps. New locations are manifest
  rows and reaches; new formats may justify an adapter. An unresolved source gets
  about 45 minutes, then a hold and a concrete retry condition.

Hold codes: `access-failed`, `format-unsupported`, `license-unclear`,
`no-valid-cells`, `coarse-only`, `duplicate`, `datum-unknown`. The last is a
tier-3 depth limitation only, never a reason by itself to block tiers 1–2.

## Delivery gates

Each milestone must pass on main before the next starts. One branch/PR per step,
following [AGENTS.md](../AGENTS.md); the owner merges. Every PR reports tier-1 and
tier-2 km² before/after **by reach**, including explicit reasons for no increase.

| Milestone | Acceptance |
| --- | --- |
| M0 | This document and candidate seed; offline schema and evidence checks. |
| M1 | Seven Central Coast regions subdivided into reaches; disjoint grid, manifest loader and tier-0 ledger with band km². |
| M2 | Cached original Morro/Estero USGS grid and local NOAA BAG usable through two adapters; second fetch downloads nothing. |
| M3 | One Morro reach and one survey-seam reach produce tiers 1–2, run receipts and a no-op repeat; report ≥50% overlap reproduction against the applicable 132 atlas areas and explain misses. |
| M4 | Fresh legal screen, dispatchable publishing workflow, live Morro PMTiles and nonzero ledger; no MPA overlap. Open “Seafloor tiers layer in the app” issue for Claude. |
| M5 | Batch remaining reaches; each has mapped coverage or explicit holds/true gaps, and usable fine sources yield habitat tiles. |
| M6 | Move unused receipts to private storage and retire scripts only after consumer/workflow/test checks; app asset checks pass. |

M1 regions: `santa-cruz-monterey-bay`, `monterey-point-sur`, `big-sur-coast`,
`south-big-sur-san-simeon`, `cambria-san-simeon`, `morro-bay`,
`point-arguello-conception`. The shared package will be `src/skippercast/seafloor/`;
its commands are `reaches`, `add-survey`, `run`, `ledger`, `publish`.

The later workflow runs weekly, on dispatch, and relevant main input changes.
It restores cached files, processes changed reaches in a matrix with a 60-minute
limit per reach, refreshes screens, publishes tiles privately reviewed by the
pipeline, and proposes changed ledger totals through a PR. A timeout is a
performance problem to fix, not permission to skip validation.

Reuse the tracked [BAG reader](../scripts/inspect_noaa_bag_grids.py),
[USGS reader](../scripts/inspect_usgs_native_grids.py),
[substrate importer](../scripts/import_usgs_seafloor_character.py),
[MPA collector](../scripts/collect_cdfw_mpas.py),
[federal collector](../scripts/collect_noaa_groundfish_areas.py),
[tile builder](../scripts/build_map_tiles.py) and
[R2 publisher](../scripts/publish_r2.py). These paths were verified at M0;
extract reusable logic without breaking their tests. See also the
[regional pipeline](region-pipeline.md).

Validate M0 offline with `python -m pip install -r requirements-test.txt`, then
`python -m unittest discover -s tests -p test_seafloor_manifest.py`. The full CI
also runs this validation; core-only tests check inventory invariants without
requiring GIS or JSON Schema packages. M0 changes no map UI or existing release
gates. Revisit tier rules only with the owner's decision.
