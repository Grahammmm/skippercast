# Point Conception native batch — September 30, 2026

## Completed work

Qualified the three original NOAA H11952 BAG depth bands from open #104 using the
current native adapter and scientific raster identity merged in #123. Reused
checksum-verified original files; metadata identifies NOAA NOS OCS Hydrographic
Surveys Division and August–September 2008 acquisition. The 2022 processing
creation dates are not new sounding dates. Recomputed r06/r07/r08 from current
sources, incorporating #97's H11953 source without copying either old ledger.

| Measure | Before (Point Buchon batch) | After | Added |
| --- | ---: | ---: | ---: |
| Reference-cell measured coverage, km² | 352.531250 | 428.854375 | 76.323125 |
| Selected valid native footprint, km² | 348.409823 | 420.034382 | 71.624559 |
| Spatially screened habitat, km² | 15.578340 | 15.578340 | 0 |
| Physical patches in three newly assessed reaches | 0 | 1,079 | 1,079 |
| Supported species ranks | 0 | 979 | 979 |
| New public/exported locations | 0 | 0 | 0 |

All patches are held privately. One hundred have incomplete metric support;
these remain unranked. Fourteen of 46 catalog reaches now have physical
assessments; this catalog includes reaches north of the requested Monterey
boundary, and partial measured footprint is not complete coastal coverage.

## Evidence and limits

[Native source review](../../research/receipts/seafloor-h11952-native-batch-review.json)
contains exact original links, hashes, bytes, MLLW datum, acquisition metadata,
reviewed footprint, source-pixel counts, semantic identities, native resolution
and per-reach grades. [NOAA licensing](https://nauticalcharts.noaa.gov/data/data-licensing.html)
was opened September 30; the originals identify Coast Survey as producer, rather
than treating a NOAA distribution URL as permission for all contributors.

Retain 2/4/8 m native spacing; the 8 m product describes broad terrain, not small
rock piles. Its 53,692 nominal shallow pixels do not imply all of the 200–300 ft
band is surveyed. Bands of one acquisition are one evidence line. Unknown
interpolation mask remains unknown. ProductUncert is retained; resolution is
not quantitative sounding accuracy. Suitability grades do not imply fish
presence. No current spatial clearance or live publication is claimed.

## Commands and verification

Pinned `.venv`, `PYTHONPATH=src:.`:

```bash
python -m skippercast.seafloor promote-survey --draft var/seafloor/drafts/SURVEY_ID.json --rights-url https://nauticalcharts.noaa.gov/data/data-licensing.html
python -m skippercast.seafloor run --reach point-arguello-conception-r06 --physical-only --fetch
python -m skippercast.seafloor run --reach point-arguello-conception-r07 --physical-only --fetch
python -m skippercast.seafloor run --reach point-arguello-conception-r08 --physical-only --fetch
python -m research.lib.receipts
python -m pytest tests/gis/test_seafloor_*.py tests/contract/test_seafloor_*.py tests/contract/test_receipt_manifest.py -q
python -m skippercast.platform.build
python scripts/build_search_plans.py
python scripts/check_repository.py
python scripts/check_web.py
```

100 tests and 2,980 subtests passed. All three repeated runs reused physical
outputs (`unchanged: true`). Checked every candidate for nominal 0–300 ft depth,
actual native spacing, non-exportable status and empty public habitat outputs.
Generated product builds introduced no unrelated changes; repository/web checks
passed. Linux PR CI remains the merge gate.

## Remaining work and exact next step

Whole Monterey–Point Conception goal remains active, not complete. Next process
qualified Morro r05/r06 and Cambria r02, reconciling #91/#94. Discover actual
native coverage for Carmel/Big Sur and the northern Arguello reaches; do not
repeat the already empty Carmel NOAA NOS query. Inspect USGS original Point
Conception depth/substrate as the next source batch. Expand regional permanent
spatial reviews separately, including Vandenberg (#110), then rescreen saved
physical outputs and verify the live regional layer. Source/legal holds cannot
block successful physical work in other reaches.

Normalization recovery #123 supersedes the earlier uncertain diagnosis in the
Point Buchon archive. Production run 36746523237 was queued at the last check;
its success and measured/public deltas must be checked before claiming live
expansion. Private receipts remain in `var/seafloor/reaches/` and
`var/seafloor/point-arguello-conception-r0[678]-batch.json`.
