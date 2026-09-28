# Seafloor pipeline

Build a graded habitat planning map from original surveys, starting at Morro
Bay and extending from Monterey Bay to Point Conception. Completion means every
Central Coast reach is mapped or explicitly recorded as a hold or true gap, and
every reach with usable ≤4 m surveys has published habitat tiles. This describes
physical habitat suitability, never fish presence or catch probability.

## Current stage: M3 part 2, held habitat candidates

The [candidate manifest](../catalog/surveys.json) contains 385 source products.
The runtime loader validates its [row schema](../catalog/survey.schema.json),
identities and lineage. Three original bathymetry products have native-adapter receipts; the other 382
remain candidates. Metadata alone cannot promote a source. `usable` means the
reviewed source window can be processed, not that its whole file envelope has
valid depth or that a reach has been mapped.

The [reach catalog](../catalog/reaches.json) partitions seven Central Coast
packages into **46 reaches**, approximately 10 km alongshore, ordered outward
from Morro Bay. The [new ledger](../dist/data/seafloor-ledger.json) contains
**55,544 disjoint 250 m cells and 3,307.514375 km² of provisional reference band**.
Cells start at tier 0. M3 now classifies original-survey coverage for the first
three Morro Bay reaches and produces ranked, private habitat candidates; current totals are in the ledger. Tier 2 remains zero
until a fresh whole-polygon legal screen is complete. This does not
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
committed. There are no new habitat tiles or front-end changes in M3. The
coverage runs update tier 1; all tier-2 totals remain zero until screening.

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
is already a producer-gridded product, not raw soundings. No verified
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
| [USGS Offshore Morro Bay](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9HEZNRO/7c8afd6a626a4054b41d268dbd18244d/Bathymetry_OffshoreMorroBay.zip), member `Bathymetry_OffshoreMorroBay.tif` | -120.98, 35.28, -120.76, 35.46 | 2 m / unknown | 28,337,123 | 45,090,088 / 50,112,014 |
| [USGS Offshore Point Estero](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9ZSTUK1/379fedd24ed54b1d9a079e07c3e7f7e5/Bathymetry_OffshorePointEstero.zip), member `Bathymetry_OffshorePointEstero.tif` | -121.13, 35.37, -120.92, 35.55 | 2 m / unknown | 26,023,976 | 75,792,608 / 55,820,740 |
| [NOAA H11953 2-of-4](https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/H11953/BAG/H11953_MB_2m_MLLW_2of4.bag), Point Conception | -120.73, 34.5, -120.58, 34.65 | 2 m / MLLW | 5,517,962 | 42,325,273 / 37,465,806 |

Counts exclude the seam margin and are source pixels, **not deduplicated habitat
or reach area**. All three full original hashes match the existing inspected cache.
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

## Coverage, terrain and habitat runs (M3)

```bash
PYTHONPATH=src python -m skippercast.seafloor run --reach morro-bay-r03
PYTHONPATH=src python -m skippercast.seafloor run --reach morro-bay-r02
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
cache. `run --fetch` explicitly permits downloading missing reviewed depth and
substrate originals, still requiring pinned hashes. Without that flag no network
access is attempted. The runner never expands the manifest's inspected windows.
Missing or corrupt inputs fail the run. A repeat
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

### Habitat extraction and review

[Habitat rules](../catalog/habitat-rules.json) pin original substrate hashes,
reviewed class meanings, metadata URLs/digests, numerical rules and cited species
planning bands. Substrate bindings qualify categorical semantics separately from
the bathymetry adapter; their source rows remain candidates for that adapter.
Held/withdrawn substrate rows are excluded. Changed source hashes fail closed.
Both USGS character products use classes 1 (soft sediment), 2 (flat coarse
sediment/bedrock), and 3 (hard rugose boulder/bedrock), verified in the original
FGDC enumerations reviewed September 25. Their ZIPs lack raster value tables.
This run reverified cached original ZIP hashes; it does not claim a new successful
metadata fetch. Paired character and depth are **not independent evidence**.

Each source gets its own native-spacing EPSG:3310 derivative grid. A reach window
above 20 million pixels fails explicitly instead of downsampling. This is a
bounded pilot implementation; larger reaches will need tiled extraction with
halos and component stitching. Relative thresholds use all selected valid
0–300 ft pixels: VRM at/above the 80th percentile or fine BPI above one standard
deviation. Numerical zero tolerances keep a flat plane from qualifying merely
because its 80th percentile is zero. Soft-class pixels, invalid depth and depth
outside nominal 25–300 ft are excluded. Unknown substrate remains unknown.

The pipeline closes one-pixel gaps, clips again to eligible pixels, groups with
8-connectivity, drops patches below 0.1 ha and simplifies by at most half a pixel.
Clipping simplified polygons back to their original support prevents expansion
into no-data. Survey offsets are never differentiated across sources; patches
remain separate at survey boundaries.

The existing `atlas.scoring` formula supplies A/B/C. Metrics use a representative
point **inside each patch**: 210 m square relief and rugose fraction, detrended
plane RMS in a 250 m square, and extracted rough area within a 250 m radius.
At least 80% depth support in both squares is required; otherwise grade and fits
stay unknown with a separate hold. These are local-neighborhood metrics, not a
claim that every part of a large patch has identical terrain. Known class 3
supplies rugose cover; terrain supplies the proxy where substrate is unknown.
Nearby rough area is limited to the selected source/reach, so edges can score
conservatively. Thresholds and support fractions are retained for review.

Species fits are **physical planning heuristics**, with 3 strongest. Lingcod uses
the [ADF&G profile's typical 30–330 ft band](https://www.adfg.alaska.gov/index.cfm?adfg=lingcod.main),
explicitly transferred from general West Coast guidance. The reef-rockfish entry
uses the [CDFG NFMP copper-rockfish Big Sur observation band of 22–98 m](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=33863&inline=)
as a labeled proxy, not an optimum for all rockfish. The same document supplies
gopher's commonly occupied 9–37 m band and cabezon's broad 0–102 m occurrence
envelope. Cabezon's band cannot establish a shallow-versus-deep preference.
Grade A/B fully inside a band earns 3; overlap earns 2; outside earns 1 even
for grade C. Temperature, prey, season and fish presence are not inferred.

Private `habitat.geojson` contains held candidates (tier 1, `exportable:false`),
not screened tier-2 features. `atlas-comparison.json` reports overlap against
the **107 outline polygons attached to 132 atlas targets**, clipped to the reach.
Missing reviewed coverage remains a miss, not removed from the denominator.
`run.json` also pins the rule file, substrate rows, atlas and scoring code.

September 28 pilot results (each compared with the prior main ledger):

| Reach | Tier 1 km² before → after | Held patches | A / B / C / insufficient metrics | Old outlines reproduced ≥50% |
| --- | ---: | ---: | ---: | ---: |
| `morro-bay-r02` | 0 → 56.887500 | 769 | 7 / 202 / 536 / 24 | 19 / 33 |
| `morro-bay-r03` | 12.053125 → 31.651250 | 208 | 2 / 10 / 193 / 3 | 12 / 12 |
| `morro-bay-r04` | 5.125000 → 12.174375 | 57 | 1 / 1 / 54 / 1 | 2 / 2 |

Total classified coverage rises **17.178125 → 100.713125 km²**; actual selected
valid survey area is **98.151960 km²**, a separate measurement. All three reaches'
tier-2 totals remain **0 → 0** pending M4. The Morro survey window was expanded
to include its inshore grid; keeping the old narrow test window would have
artificially missed 11 of r03's 12 comparison outlines.

The r02 run uses both USGS products with a measured **1,812 m shared selected
boundary**. Of its 14 outline misses, one has incomplete selected survey
coverage; 13 remain below 50% under the new roughness/substrate/minimum-patch
rule. Older generalized substrate outlines and newly extracted rough terrain
are different products: these misses remain visible and were not tuned away.
This is algorithm comparison, not independent validation of fish habitat.
Repeat runs verify all original/output hashes and return unchanged without
recomputing. M4 must still test full polygons against fresh MPA, federal and
security layers before publishing any candidate.

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
| M3 | One Morro reach and one survey-seam reach produce tier-1 and tier-2 outputs and run receipts, with a no-op repeat; compare applicable legacy outlines at ≥50% overlap and explain misses. Held candidates do not satisfy this acceptance check. |
| M4 | Fresh legal screen, dispatchable publishing workflow, live Morro PMTiles and nonzero ledger; no MPA overlap. Open “Seafloor tiers layer in the app” issue for Claude. |
| M5 | Batch remaining reaches; each has mapped coverage or explicit holds/true gaps, and usable fine sources yield habitat tiles. |
| M6 | Move unused receipts to private storage and retire scripts only after consumer/workflow/test checks; app asset checks pass. |

**Owner-approved sequencing (2026-09-28).** Whole-polygon MPA, federal-area
and security-zone screening moves into M3. Publication and scheduling remain
in M4. No tier rule or acceptance check is waived. PR #16 is merged; M3 still
requires screened tier-2 outputs on main before M4 begins.

M1 regions: `santa-cruz-monterey-bay`, `monterey-point-sur`, `big-sur-coast`,
`south-big-sur-san-simeon`, `cambria-san-simeon`, `morro-bay`,
`point-arguello-conception`. The shared package is `src/skippercast/seafloor/`. `reaches`, `ledger`, `add-survey` and `run` are
implemented, including held habitat extraction. `publish` arrives in M4; the legal screen is part of M3.

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


## Whole-polygon spatial screen (M3)

The owner approved moving this prerequisite into M3 on September 28, 2026.
Publication and scheduled updates stay in M4. Tier thresholds are unchanged.

```
PYTHONPATH=src:. python -m skippercast.seafloor refresh-screen
PYTHONPATH=src:. python -m skippercast.seafloor run --reach morro-bay-r03
```

`screen_sources.py` reuses the complete-inventory CDFW MPA and NOAA federal-area
collectors. Its private snapshot points to content-addressed geometry files;
retrieval dates and file hashes are checked on every run. The first security
review covers only the three Morro Bay pilot reaches listed in
`catalog/seafloor-screen.json`. Other reaches remain held until their local
security restrictions are reviewed. The scope is explicit and is never inferred
from a provider's program name.

- CDFW: [original ds582 service](https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0),
  155 features retrieved September 28. Every MPA and special closure is excluded
  conservatively, even when particular fishing methods might be allowed.
- NOAA: [West Coast original federal-area service](https://maps.fisheries.noaa.gov/server/rest/services/WCR_SFD_GCA/NOAA_Fisheries_West_Coast_Region_Groundfish_Conservation_Area_service/MapServer),
  29 non-aggregate GEA/CCA/YRCA features retrieved September 28. All are excluded
  conservatively; this does not assert every category applies to every fishery.
  Commercial RCA geometry is not used to imply a recreational closure.
- Security: [33 CFR 165.1155](https://www.ecfr.gov/current/title-33/section-165.1155),
  fetched through the official eCFR versioner API using the titles endpoint's
  `up_to_date_as_of` date (September 24), not the retrieval date. The reviewed
  Diablo Canyon circle is 2,000 yards around the statute's NAD83 position.
  A geodesic boundary with a documented one-meter outward planning margin avoids
  chords cutting inside that circle. Changed legal text invalidates the reviewed
  hash and requires a new boundary review. These public government geometries and
  statutory facts retain publisher links; private raw receipts are not shipped.

Every full habitat polygon is intersected with the exclusions in EPSG:3310,
including boundary touches. A conflicting candidate is held in its entirety;
no centroid-only test or clipping-away of the conflict is used. CDFW's three
nested-shell MultiPolygons are normalized only by unioning their individually
valid parts, so excluded area cannot be removed. Invalid components still fail
closed. Original source files remain unchanged and their hashes are retained.

A missing layer, source-byte mismatch, changed policy, failed refresh,
future timestamp, snapshot older than 35 days, unreviewed reach or polygon
outside the reviewed coverage holds output. Current eCFR availability must also
be within 35 days. A failed refresh retains the previous snapshot for diagnosis
but writes a failure marker that prevents its use for promotion. A successful
refresh clears that marker. Freshness state enters the run hash, so an expired
snapshot cannot reuse yesterday's pass through the no-op path.

`candidates.geojson` retains extraction evidence, `habitat.geojson` contains only
screened tier-2 output, and `held.geojson` retains failures with reasons. All three
remain private until the M4 publication path. The ledger reports the union of
passed polygon areas (not a sum of overlapping sources), grade counts, held
reasons, source hashes and snapshot dates. Unknown grades cannot be promoted.

This screen covers permanent spatial restrictions in the reviewed scope. It is
not a declaration that fishing is currently open, a navigation clearance, or a
check of temporary USCG notices, moving-vessel security zones, seasonal depth
rules, gear, bag limits or species restrictions. Those still require the app's
trip-date regulations and current notices. The map/export planning label remains
required. No fish presence or catch probability is inferred.

### Pilot screening result — September 28, 2026

| Reach | Tier 1 km² (unchanged) | Tier 2 km² (previously zero) | Passed / held |
| --- | ---: | ---: | ---: |
| morro-bay-r02 | 56.887500 | 11.535873 | 745 / 24 |
| morro-bay-r03 | 31.651250 | 4.273268 | 205 / 3 |
| morro-bay-r04 | 12.174375 | 0.802624 | 56 / 1 |

Total tier 2 is 16.611764 km². All 28 held patches lack sufficient metric support;
none of the 1,006 passed polygons touches the screened restriction geometries.
All three repeat runs are no-ops, and the original 1,812 m r02 survey seam and
legacy-overlap comparisons remain recorded. The new ledger and private receipts
are proposed in the screening PR; M3 acceptance is satisfied on main only after
that PR merges. This result does not mean the layer is already served as tiles.

## Regional publication contract (M4)

M3 is accepted on main at `56ae67410f35336414b4efd989c72d4efe4f24cf`
(PR #17). M4 adds publication; it does not add surveyed area or change grading.
The initial ledger remains 100.713125 km² tier 1 and 16.611764 km² tier 2.
Only three of 46 Central Coast reaches are assessed. These are habitat planning
fits, not likelihoods of a catch.

```
reviewed catalogs + private original grids + fresh restriction inventory
  → per-reach run / hash-checked no-op → private recovery and review receipts
  → regional cells + screened habitat → pinned PMTiles encoder
  → isolated R2 bundle → held alias → archive byte read-back → ready manifest
  → Worker freshness/revision gate → public HTTP Range verification
  → small ledger PR (no direct push to main)
```

### URLs and layers

For a catalog region such as `morro-bay`:

- `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles`: PMTiles v3, MVT,
  zooms 8–15; supports HTTP Range. Layer names are `cells` and `habitat`.
- `/feeds/tiles/seafloor/manifest-morro-bay.json`: publication status, absolute
  `expires_at`, source-run input hashes, archive SHA-256/size and feature counts.
- `/feeds/tiles/seafloor/regions/morro-bay/ledger.json`: regional reach summaries;
  the committed counterpart is `dist/data/seafloor-ledger.json`.

`cells` contains the entire region's provisional reference band, including
unassessed cells, with `id`, `reach`, `tier`, `source_id`, `band_area_m2`,
`reference_band` and a planning notice. It is not a measured depth contour.
`habitat` contains only passed tier-2 polygons, with stable `id`, nominal depth
range, source IDs/year/resolution/datum, terrain grade/score, species planning
fits and screening provenance. `terrain_grade`, `terrain_score` and
`fit_lingcod` / `fit_rockfish_reef` / other `fit_<group>` scalars support styling.
Nested evidence objects (`terrain`, `fit`, `screen`, `substrate`, source IDs,
independent evidence and hold reasons) are canonical JSON strings in MVT;
parse them when displaying provenance. Unknown values remain unknown.

Show **“Habitat candidate, unverified”** and **“Nominal depth; verify on your
sounder.”** with the required planning notice. Terrain A/B/C and species fit
1–3 are separate assessments; do not relabel them catch probability. Same-survey
bathymetry and substrate remain one independent evidence family.

Tiles retain tiny polygons and unsimplified edges, but MVT quantizes geometry
to its tile grid and may split polygons across tiles. Deduplicate by `id`.
**Tile geometry is for display, not navigation or GPX boundary export.** Use
canonical screened geometry through a separately reviewed export path.

### Failure behavior and storage

The publisher re-runs input validation and checks output hashes before encoding.
The alias is held during refresh and upload, and is promoted only after the
uploaded archive's full SHA-256 matches. R2 object metadata records that hash;
the Worker requires it to match the ready control manifest. An interrupted job
leaves the layer unavailable, not falsely fresh. No archive falls back to bundled
assets. Seafloor responses use `no-store` so caches cannot bypass the expiry
check; R2 still supports efficient range requests.

Expiry is the earliest of the snapshot, layer retrieval dates and eCFR's actual
availability date plus the existing 35-day policy. An expired/missing/updating
manifest or mismatched archive returns 503. Internal archive copies are not
served by the Worker. This is a permanent-spatial-screen freshness rule, not a
claim that seasonal regulations or temporary notices are current.

Raw originals, normalized grids, held candidates and review receipts stay in
private `seafloor-cache/` and `seafloor-review/` R2 prefixes. They are never feed
keys. Use the private bucket bound as `FEEDS`; do not enable a public R2 bucket
URL, which would bypass the Worker gates. Restore inventories allow only known
pipeline paths and their owning scope, reject traversal/symlinks, and verify
content hashes. Existing correct local files are not downloaded again.
Regional public synchronization uses its own prefix and cannot delete other
regions or existing app tile layers. Credentials use the existing CI secret
names (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`); absent or invalid
credentials fail the job visibly.

### Run and schedule

```
# Local build; no network publication or credentials needed after source recovery:
PYTHONPATH=src:. TIPPECANOE=/path/to/tippecanoe python -m skippercast.seafloor publish --region morro-bay
# Main only, with existing R2 credentials; explicit upload:
PYTHONPATH=src:. TIPPECANOE=/path/to/tippecanoe python -m skippercast.seafloor publish --region morro-bay --upload
```

`.github/workflows/seafloor.yml` runs Mondays at 10:23 UTC, on relevant main
changes, or by manual dispatch. Dispatch `region=morro-bay` for the pilot;
blank means all processed regions. Optional `reach` reprocesses that reach and
its region's assessed peers. Fresh restriction inventories change the screening
input; unchanged original surveys reuse the content-addressed cache. Matrix
workers are limited to three. Publishing is serialized and main-only.

A cold runner restores private state or fetches reviewed original files and
reconstructs the pinned reference baseline. A different baseline checksum stops
publication rather than silently replacing it. Recovery currently needs about
1 GB of pilot survey/state storage (including originals and derived grids);
the first bootstrap may take substantially longer than subsequent cached runs.
The encoder is [felt/tippecanoe](https://github.com/felt/tippecanoe) v2.82.0,
pinned to commit `4f2621186acfec33b63ddf636f665623c0fef2dd`.

The pipeline opens a ledger-only PR showing before/after tier areas. GitHub must
allow Actions to create pull requests. PRs created by the default Actions token
do not trigger another Actions run automatically; a maintainer must trigger
normal PR checks through a new authorized push, or configure a separately
scoped PR-creation token before unattended ledger review. They are never
auto-merged. R2 permissions and the production Worker's
`FEEDS` binding must be configured. The live probe uses the existing `CLOUDFLARE_SITE_URL` repository variable
(or skippercast.com if unset) and records the exact URL in its receipt. As
documented in [Cloudflare hosting](cloudflare.md), the .com site remains on
Sites pending its separate migration. A staging Worker pass proves that
endpoint only; it does not mean the layer appears in the .com app. The app
integration issue must identify the actual tested feed host. The final probe
checks the public manifest,
PMTiles v3 header, 206 range response, byte size and Worker cache policy; private
R2 success alone does not count as a successful website deployment.

### Local validation and remaining live acceptance

The September 28 local archive is 6,941,072 bytes, with 10,101 cells and 1,006
habitat polygons. Decoding zoom 15 reproduces every input habitat ID. Rebuilding
with the pinned encoder gives the identical SHA-256
`153b7f61381270128d0f7d6ef479e70f90ed49f661a0c649ee7c13eb9e2128a1`.
Offline tests cover stale/held inputs, corruption, interrupted promotion, private
scope/path restrictions, missing credentials and public response verification.

**M4 is not accepted yet:** after this implementation merges, deploy the Worker
from main, dispatch `morro-bay`, and verify the live URL and nonzero regional
ledger. Local credentials are unavailable; no R2 upload is claimed here. Once
that passes, open “Seafloor tiers layer in the app” for Claude, linking this
contract, before beginning M5 reach expansion.
