# Native-grid C1 QA (private research only)

The reviewed fixture CLI in `coast_qa.py` keeps its 1,000,000-cell cap.
`--regional` opts into `coast_qa_regional.py`, a separate bounded native-grid
backend for one cached C1 segment per regional packet. No acquisition, filling,
smoothing, contours, release integration or publication is performed.

```sh
python research/scripts/coast_mvp/coast_qa.py --regional \
  --region-config /path/to/region.json --output /path/to/new-packet
```

The config is `{ "region": "central-c1", "segments": [
{ "id": "morro-bay", "manifest": "/local/path/manifest.json" } ] }`.
Original native rasters must still exist at the manifest paths. All three C1
outputs and every source are SHA256-checked before processing. The regional
path currently supports local, single-band, unscaled GeoTIFFs only.

Bounds: 150,000,000 cells, 20,000 per side, 16 sources, 64-row numerical strips,
256 MiB GDAL cache, 64 MiB per warp and two GDAL threads. A 250 GiB disk reserve
plus 2 GiB output allowance is checked. The whole-raster boolean void mask and
int32 connected-component labels are materialized; the numeric source arrays
are not. Label counting may make an additional int64 regional temporary.
This is bounded regional processing, not an unbounded statewide streamer.

Measurements use every native target cell, not the display overview:

- Valid/invalid cells, elevation statistics, overlap support, and contributor
  coverage by the source codes in the actual manifest, not historical notes.
- Four-connected hole components across strip boundaries. Pixel boxes are
  half-open `[left, top, right, bottom]`; boundary voids are included. These are
  not automatically ocean gaps because no land/water mask is available.
- All source pairs reprojected nearest-neighbour onto the same target grid,
  followed by explicit sign/constant normalization. No-overlap RMS is null,
  never zero. Bias is first source minus second. Maximum-difference pixel,
  spread and unknown-datum caveats accompany RMS.
- Independent-in-the-run checks against the supplied C1 support counts,
  contributor masks, selected source elevations (rounded to C1 float32),
  manifest totals and per-source contributor counts. `consistency.passed`
  summarizes those checks, not scientific acceptance. Failed consistency is
  retained in the diagnostic report and must not be treated as acceptance;
  the command also exits non-zero when `consistency.passed` is false.
- The free-disk reserve defaults to 250 GiB; override it with the
  `COAST_QA_RESERVE_BYTES` environment variable or `--reserve-bytes`.

PNGs use azimuth 315 degrees, altitude 45 degrees and vertical factor 1, with
transparent nodata and a one-cell halo. The full PNG retains every target
pixel. Overview PNGs are nearest-neighbour display samples of that hillshade
and contributor map. Detail PNGs show the largest absolute overlap difference
and one deterministic winning-source location per source. Their pixel boxes,
source colors and grid georeference are in `qa.json`; the PNG itself is not a
georeferenced navigation product. Fixture parity tests compare every native
PNG pixel against the original C4 implementation and verify cropped halos.

`qa.json` and `QA.txt` remain `review_required`. Unknown datums, producer
attribution and rights caveats are preserved per source. Offsets are not datum
conversions, RMS is not accuracy, and no 10 m navigation precision is claimed.
The reviewer must inspect the images and the findings as well as machine
consistency. Partial output directories are not overwritten or resumed.

Tests (survey interpreter, offline):

```sh
python -m pytest tests/contract/test_test_layout.py \
  research/tests/test_coast_mvp_qa.py \
  research/tests/gis/test_coast_mvp_qa_c1.py \
  research/tests/gis/test_coast_mvp_qa_regional.py -q
```

Implementation provenance: the unchanged fixture algorithm and original tests
come from reviewed C4 PR #836, head
`4f8f6282a60cc0e05dbde182ac62e3961ea23013`. The regional code is a new opt-in
extension, not inherited real-data qualification from that fixture review.
