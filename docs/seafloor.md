# Seafloor pipeline

Build a graded habitat planning map from original surveys, starting at Morro
Bay and extending from Monterey Bay to Point Conception. Completion means every
Central Coast reach is mapped or explicitly recorded as a hold or true gap, and
every reach with usable ≤4 m surveys has published habitat tiles. This describes
physical habitat suitability, never fish presence or catch probability.

## Current stage: M3 part 1, native coverage and terrain

The [candidate manifest](../catalog/surveys.json) contains 385 source products.
The runtime loader validates its [row schema](../catalog/survey.schema.json),
identities and lineage. Two original bathymetry products have native-adapter receipts; the other 383
remain candidates. Metadata alone cannot promote a source. `usable` means the
reviewed source window can be processed, not that its whole file envelope has
valid depth or that a reach has been mapped.

The [reach catalog](../catalog/reaches.json) partitions seven Central Coast
packages into **46 reaches**, approximately 10 km alongshore, ordered outward
from Morro Bay. The [new ledger](../dist/data/seafloor-ledger.json) contains
**55,544 disjoint 250 m cells and 3,307.514375 km² of provisional reference band**.
Cells start at tier 0. M3 now classifies original-survey coverage for the first
two Morro Bay reaches; current totals are in the ledger. Tier 2 remains zero
until habitat extraction and a fresh whole-polygon legal screen are complete. This does not
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
committed. There are no new habitat tiles or front-end changes in M3 part 1. The first
coverage runs update tier 1; all tier-2 totals remain zero.

## Original-survey ingestion

`add-survey` imports a hash-verified local original or fetches an approved USGS /
NOAA NOS URL with `--fetch`. It writes a private draft, never automatically
changes the manifest or grants reuse rights. Inspect the draft, review the
publisher's rights, and use `manifest.qualify_row` before committing a usable
row. A known SHA-256 permits offline reuse; a new unknown-hash discovery must
be reviewed and pinned before repeat fetches are guaranteed to download nothing.

```bash
PYTHONPATH=src python -m skippercast.seafloor add-survey \
  --url https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11953/BAG/H11953_MB_2m_MLLW_2of4.bag \
  --id h11953-mb-2m-mllw-2of4-bag-fd284baf0f \
  --bounds -120.73 34.5 -120.58 34.65 --fetch
```

Use `--local /absolute/path/to/original` to import a previously downloaded file;
its bytes and SHA-256 must match. Multi-GeoTIFF ZIPs require `--member` with the
exact native product name. The transport-file hash covers the ZIP, while a
separate private extraction receipt hashes its selected member. Original files,
COGs, drafts and full receipts stay in ignored `var/seafloor/`. The manifest
stores a small native inspection and rights receipt.

Adapters read native 512-pixel chunks with a 100 m seam margin, preserve no-data
and producer uncertainty, and write a native-resolution COG. Band 1 is **meters
positive down**; an optional band 2 is producer uncertainty in meters. Do not
feed these normalized COGs back into an original elevation adapter. No datum
conversion, reprojection, smoothing or interpolation is performed. The source
is already a producer-gridded product, not raw soundings. Neither verified
product supplies a separate interpolation mask; that remains explicitly unknown
and must be addressed by the coverage-stage eligibility rules. Unknown datum
alone does not block tiers 1–2.

Variable-resolution BAG overviews are rejected until a native-refinement adapter
exists. Coarse default overview pixels must never masquerade as fine native
depth. The legacy strict BAG metadata parser is unchanged for existing callers;
only this adapter permits unknown datum, dates and uncertainty metadata.

### Native checks, 2026-09-28

| Original product | Exact reviewed WGS84 window (west, south, east, north) | Native spacing / nominal datum | Valid 0–300 ft source pixels | Cached source / COG bytes |
| --- | --- | --- | --- | --- |
| [USGS Offshore Morro Bay](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9HEZNRO/7c8afd6a626a4054b41d268dbd18244d/Bathymetry_OffshoreMorroBay.zip), member `Bathymetry_OffshoreMorroBay.tif` | -121.04, 35.32, -120.91, 35.45 | 2 m / unknown | 12,104,254 | 45,090,088 / 20,599,206 |
| [NOAA H11953 2-of-4](https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11953/BAG/H11953_MB_2m_MLLW_2of4.bag), Point Conception | -120.73, 34.5, -120.58, 34.65 | 2 m / MLLW | 5,517,962 | 42,325,273 / 37,465,806 |

Counts exclude the seam margin and are source pixels, **not deduplicated habitat
or reach area**. Both full original hashes match the existing inspected cache.
Each stabilized second ingestion verifies hashes, downloads nothing and reuses
the normalized COG. Synthetic tests independently check orientation, depth sign,
no-data holes, uncertainty, archive selection, download caching and corruption.

USGS's cached original metadata credits USGS, CSU Monterey Bay's Seafloor Mapping
Lab and UC's Center for Integrated Spatial Research; the 2008 Fugro surveys were
processed and mosaicked into the released grid. Its public-domain source and
metadata must accompany reuse. A fresh fetch of the [publisher XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9HEZNRO/137e935afcd24506b6c8a2d23ff7a6d4/Bathymetry_OffshoreMorroBay_metadata.xml)
returned HTTP 403 during review; the cached publisher XML was inspected instead.
The NOAA [NOS archive license](https://www.fisheries.noaa.gov/inport/item/39979)
explicitly states CC0/public-domain reuse. NOAA H11953's embedded metadata records
2008-08-29 through 2008-09-05 and product uncertainty. Neither source supports
navigation clearance or independent corroboration just by being gridded.

**M2 acceptance location resolved on 2026-09-28.** After the owner delegated the
choice, Codex selected the original H11953 regular BAG near Point Conception to
validate the reader, retaining USGS for Morro Bay. [NOAA's survey record](https://www.ngdc.noaa.gov/nos/H10001-H12000/H11953.html)
confirms the survey, products and rights. Reading depth, masks and uncertainty is
a format test; it does not require co-location. Eight nearby regular BAG files
previously tested had no -100 to 0 m elevation cells in the bounded Morro search
[-121.15, 35.05, -120.6, 35.53]. That is not proof of a regional gap.

The benefit is progressing with usable originals without substituting a
compilation. The cost is that this check does not establish Morro Bay NOAA
coverage, cross-survey agreement or support for every BAG variant. H11953 is
credited only to its own inspected window. M3's actual coverage and real seam
checks and M4's legal screening remain required. PR #14 is merged and all 34
M2 seafloor checks passed on that main revision.

`fetch.py` also supplies tested, streaming private-object cache hooks accepting
an externally configured S3-compatible client. They have not been deployed or
connected to credentials. Weekly scheduling, R2 publication and the legal gate
remain M4 work.

## Coverage and terrain runs (M3 part 1)

```bash
PYTHONPATH=src python -m skippercast.seafloor run --reach morro-bay-r03
PYTHONPATH=src python -m skippercast.seafloor run --reach morro-bay-r04
PYTHONPATH=src python -m skippercast.seafloor ledger --region morro-bay
```

On a fresh checkout with a processed ledger, first run
`PYTHONPATH=src python -m skippercast.seafloor restore-reference --fetch`.
It rebuilds the pinned reference baseline in isolation and installs private
cells only when their exact hash and reach geometry match the committed
baseline. It never overwrites coverage totals. Omitting `--fetch` requires
cached reference assets. Original source caches can then be restored with the
M2 `add-survey --fetch` commands. Remote source access failures remain explicit.

Run reaches serially until M4 introduces coordinated scheduled publication.
`run` requires the hash-verified M1 reference-cell cache and the reviewed source
cache. It neither downloads sources implicitly nor expands the manifest's
inspected geographic windows. Missing or corrupt inputs fail the run. A repeat
verifies originals, COGs and output hashes, then skips footprint and terrain
computation. Removing a usable source invalidates the run and removes its credit.

Coverage uses source-resolution valid depth pixels from normalized original
surveys, not file envelopes. Depth is nominal 0–91.44 m; land, no-data and depths
beyond the limit are excluded. Pixel boundaries are polygonized and projected
to EPSG:3310 before intersection with disjoint 250 m cells. A cell qualifies
when one usable source covers at least 25% of its full square. Among qualifying
sources, finer spacing wins, then newer acquisition year, then stable source ID.
A fine sliver cannot hide a qualifying coarser source. Overlaps are never summed.

The ledger reports two deliberately distinct areas:

- `tier1_km2`: the provisional reference-band share of **qualified planning
  cells**. This threshold-based classification does not mean every square meter
  in those cells was surveyed.
- `selected_valid_km2`: actual selected native-footprint area inside all tested
  cells, including below-threshold partial cells. This is nominal-depth surveyed
  area; it is not guaranteed to match the approximate reference-band denominator.

The original products are producer-gridded surveys. Their absent interpolation
masks remain `unknown`, not a claim that every pixel is a raw sounding. The mask
contract excludes explicitly identified filled/interpolated pixels; it does not
invent flags where the publisher provided none. Preserve this limitation in all
later habitat evidence. Unknown source datum is recorded without conversion.

`var/seafloor/reaches/<reach>/cells.json` records source choice, valid area and
fraction for every cell. `terrain.json` holds private per-cell summaries of
slope, 3×3 VRM and fine/broad BPI. Derivatives use a nearest-sampled projection
at source spacing into EPSG:3310, with separate source neighborhoods and no
blending across surveys. BPI uses square windows approximating 25/100 m radii;
raised ground has positive BPI. Complete valid neighborhoods are required, so
holes and borders stay unknown. Coverage areas themselves use original pixel
footprints, not the derivative resampling. `run.json` hashes source rows, grids,
requirements, implementation and outputs. All detailed artifacts remain private.

**Remaining M3 work:** substrate joins, connected rough-bottom patches, existing
A/B/C terrain scoring and cited species fits, a genuine source-seam run, and
≥50% overlap comparison with the applicable legacy atlas polygons. The two
current Morro runs use one source and do **not** satisfy the seam requirement.
Unscreened candidate polygons cannot increase tier 2. M4 publishes only after
fresh MPA, federal and security checks. This part introduces no new fish spots.

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
| M2 | Cached original Morro USGS grid and Point Conception H11953 regular BAG usable in their own windows; second fetch downloads nothing. |
| M3 | One Morro reach and one survey-seam reach produce tiers 1–2, run receipts and a no-op repeat; report ≥50% overlap reproduction against the applicable 132 atlas areas and explain misses. |
| M4 | Fresh legal screen, dispatchable publishing workflow, live Morro PMTiles and nonzero ledger; no MPA overlap. Open “Seafloor tiers layer in the app” issue for Claude. |
| M5 | Batch remaining reaches; each has mapped coverage or explicit holds/true gaps, and usable fine sources yield habitat tiles. |
| M6 | Move unused receipts to private storage and retire scripts only after consumer/workflow/test checks; app asset checks pass. |

M1 regions: `santa-cruz-monterey-bay`, `monterey-point-sur`, `big-sur-coast`,
`south-big-sur-san-simeon`, `cambria-san-simeon`, `morro-bay`,
`point-arguello-conception`. The shared package is `src/skippercast/seafloor/`. `reaches`, `ledger`, `add-survey` and the coverage/terrain stage of `run` are
implemented. Habitat extraction and `publish` arrive at their milestone gates.

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
