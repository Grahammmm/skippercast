# Seafloor pipeline

Build a graded habitat planning map from original surveys, starting at Morro
Bay and extending from Monterey Bay to Point Conception. Completion means every
Central Coast reach is mapped or explicitly recorded as a hold or true gap, and
every reach with usable ≤4 m surveys has published habitat tiles. This describes
physical habitat suitability, never fish presence or catch probability.

## Current stage: M1, reproducible coverage baseline

The [candidate manifest](../catalog/surveys.json) contains 385 source products.
The runtime loader validates its [row schema](../catalog/survey.schema.json),
identities and lineage. Candidates remain unprocessed; metadata alone cannot
promote them to usable survey coverage.

The [reach catalog](../catalog/reaches.json) partitions seven Central Coast
packages into **46 reaches**, approximately 10 km alongshore, ordered outward
from Morro Bay. The [new ledger](../dist/data/seafloor-ledger.json) contains
**55,544 disjoint 250 m cells and 3,307.514375 km² of provisional reference band**.
Every cell starts at tier 0. Tier 1 and tier 2 are **0 km² in every reach** because
original-survey adapters and habitat processing arrive in M2–M3. This does not
mean surveys or fish habitat are absent. The [legacy ledger](../dist/data/central-coverage-ledger-v1.json)
remains a separate research receipt; it is not reclassified as new coverage.

### Run and reproduce

Install the pinned `requirements-survey.txt` and `requirements-test.txt`, then:

```bash
PYTHONPATH=src python -m skippercast.seafloor ledger --region central-coast
PYTHONPATH=src python -m skippercast.seafloor ledger --region morro-bay --json
PYTHONPATH=src python -m skippercast.seafloor reaches --region central-coast --fetch
PYTHONPATH=src python -m skippercast.seafloor reaches --region central-coast
PYTHONPATH=src python -m unittest discover -s tests -p 'test_seafloor_*.py'
```

`ledger` reads the committed artifact without GIS packages or network access.
`reaches` builds the shared grid, even when a single regional view is requested.
Network access requires `--fetch`. A repeat verifies cached hashes and returns
without rebuilding when inputs, implementation and output hashes match. Do not
edit the generated reach catalog or ledger: edit [scope configuration](../catalog/seafloor-scope.json)
and rebuild. A later processed ledger cannot be overwritten by this baseline
command. Future survey runs will reuse cell IDs `3310:<x-index>:<y-index>`.

### What the denominator measures

[NOAA BlueTopo](https://nauticalcharts.noaa.gov/data/bluetopo.html) is a compilation,
not an independent original survey. We pin the 2026-09-24 tile scheme by SHA-256
and select all 252 tile footprints intersecting the configured search box.
Per-tile delivered dates, URLs and publisher checksums are in the ledger.
Four bounded workers read elevation overviews at approximately 32 m spacing;
no full native tile download is required. Local derived samples are separately
hashed. Their source checksums are **identifiers, not claims that range reads
verified the full source file**. An access failure stops publication.

Sampled elevations from -100 m through less than 0 m form a **provisional** band,
leaving a margin around 300 ft / 91.44 m. Classifications are reprojected with
nearest-neighbor sampling to aligned 25 m EPSG:3310 pixels; 100 subpixels make
one 250 m planning cell. The ledger counts only the band fraction, not every
cell's full square. Fine valid samples replace coarse ones; no-data never
replaces valid coverage or becomes zero-depth water. Overview averaging,
compilation interpolation and mixed vertical datums can shift this approximate
boundary. None of these reference pixels establishes a survey or habitat tier.

Missing reference water stays outside the denominator and remains unknown.
The 5.018125 km² of no-data within band-touching cells may include land; it is
not a measured water gap. Cells with no sampled shallow water are not evidence
that the original survey inventory has no coverage. Bathymetry acquisition and
survey-valid masks must resolve that separately in M2–M5.

The ownership spine comes from [Natural Earth's generalized coastline](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-coastline/),
whose “10m” means **1:10 million scale**, not 10 m resolution. Its geometry is
[public domain](https://www.naturalearthdata.com/about/terms-of-use/); credit:
Made with Natural Earth. The pinned ZIP was downloaded and hash-verified.
This spine assigns work only: it is not a land mask, exact shoreline, legal
boundary or navigation geometry. Explicit planning anchors divide existing
regional packages; Monterey Bay's package includes the coast north to Pigeon
Point. Bays follow the generalized coastal line. Cell centers are assigned by
nearest alongshore projection and half-open intervals, so adjacent reaches
cannot share a cell. Centers projecting to terminal endpoints are excluded.

Full cell assignments, sample receipts and run hashes stay in ignored
`var/seafloor/reference/`; only reach geometry and the small summary ledger are
committed. There are no habitat tiles or front-end changes in M1. Next is M2:
cache and open original USGS and NOAA BAG depth with format-specific adapters.

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
`point-arguello-conception`. The shared package is `src/skippercast/seafloor/`. `reaches` and `ledger` are
implemented; `add-survey`, `run` and `publish` arrive at their milestone gates.

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
