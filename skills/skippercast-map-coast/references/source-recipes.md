# Source Recipes

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
is needed. When processing originals remotely, the coordinator can save the
`groups` and `coverage_snapshot` returned by native `gap_sectors` as a private
JSON query. Pin its SHA-256 in the task receipt and transfer just that mask to
the processing host, rather than copying/rebuilding the entire raster cache:

```bash
PYTHONPATH=src:. python research/scripts/triage_multibeam_beams.py \
  --beam-table PRIVATE_ALL_GOOD_TSV --beam-receipt PRIVATE_READER_RECEIPT \
  --table-kind all --native-gap-query PRIVATE_NATIVE_QUERY_JSON \
  --native-gap-query-sha256 COORDINATOR_PIN \
  --output PRIVATE_AGGREGATE_RECEIPT_JSON
```

Do not combine saved-query mode with coverage/cache/deep-filter options; the
selected mask already fixes that policy. Hashes preserve snapshot identity,
not freshness. Before gridding or publication, verify the retained run and
source inputs still match. Keep the query geometry private and return only
aggregate coordination evidence. Original format IDs other than 57 require a
bounded official-reader test with independently matching `mbinfo` good counts;
changing the ID alone does not qualify a new sonar source.

Good-beam points in gaps establish a useful acquisition lead, not
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

After that unchanged parity check, store the order-statistic depth from the
complete printed beam table with its contributor extrema. The official grid and
beam readers can print depths at different precision; mixing their medians and
extrema can fail the strict range check even for a single sounding. Preserve the
supplied grid and table hashes, record the maximum median difference and stored
depth basis, and retain the existing parity tolerance. This does not recover
unprinted source precision, improve accuracy or repair source positions.

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
[release contract](../../../docs/archive/seafloor-csumb-release-contract-2026-09-30.md).

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

## Original bathymetric lidar: test usefulness before building an adapter

Verify the original point file, delivered CRS/datum and publisher class semantics.
For NOAA/USACE collections, a related DEM can be interpolated, and similarly
dated collections can contain different topographic versus bathymetric members.
Inspect tile headers and publisher elevation extrema before acquiring a bounded
member. Related point files/DEMs and renamed aliases share acquisition lineage.
Pulse frequency, point count and output bin spacing do not establish resolution.

Use a pinned LAS reader and preserve source record order, integer XYZ, scales,
offsets, classification/flags, original point-source ID and raw GPS encoding.
Check decoded/header counts and declared-coordinate quantization separately from
survey accuracy. Resolve adjusted GPS encoding before interpreting timestamps:
negative adjusted time alone is valid; unexplained date inconsistencies remain
explicit. Never invent an acquisition epoch or change coordinates to fit a grid.

Before normalization, diagnose COMPLETE quality-accepted contributors, including
above-datum and deeper-than-limit returns. Record duplicate handling against
original identities; do not call a return count independent observations. The
research-only `research/scripts/inspect_point_bins.py` provides `bin_points`,
`verify_reference` and `supported_bins` for a bounded metric-coordinate test.
It uses a fixed, zero-anchored half-open lattice, positive-down upper depth
median and independently checked count/min/max/residual RMS. This is a distinct
point diagnostic, not MB-System grid parity or a product LAS adapter.
Residual RMS around the median is neither sample standard deviation nor
calibrated uncertainty. The diagnostic does not select classifications or prove
that its caller supplied a complete source; bind the reader/cache receipt first.

Apply count and nominal depth limits AFTER binning. Any above-datum, zero-depth
or too-deep contributor excludes its entire bin from nominal shallow support.
Do not fill holes or coarsen a sparse source to force terrain rankings. Use the
unchanged habitat depth band, derivative masks and neighborhood requirements.
Intersect represented bin geometry with the verified existing native-support
gap, but do not label occupied/represented bins as fully measured area or
credit them to the product ledger. A snapshot hash proves identity, not freshness.

Preserve useful shallow measurements, outlines and source knowledge even when
they do not support boat-reef rankings. They may support later shore-fishing or
spearfishing habitat research. Retain depth/datum, resolution, support, source-age
and rights limitations; do not infer shore access, dive safety, fish presence or
method-specific legal clearance. Final public recommendations still require
source qualification and current whole-polygon restrictions.

If the bounded test shows no adequate habitat support, retain a negative boat-
ranking receipt and the shallow recovery objects, then select another source.
Only build a lidar-specific reviewed preparation/product adapter when an actual
test demonstrates useful support. Never label lidar as measured multibeam to
bypass a format-specific provenance gate.
