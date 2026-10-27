# Native C1 rights and hillshade fallback

`coast_c1_preview.py` consumes the C1-native mosaic manifest without pretending it
has the stricter, separately reviewed C5 `rights` object. Native C1 has `id`,
`code`, `contributor_cells`, `citation`, and a free-text `rights` notice. Missing
licence/terms/CSUMB declarations are not filled with invented clearance fields.
The output is an offline, review-required inventory, not a legal decision.

This is the reset task's **C1 fallback**, not the C3 terrain-RGB/MVT viewer. The
three views are distinct north-up spatial extents, not three 3D camera angles.
C2 generation, C3 integration, datum reconciliation and scientific acceptance
remain outside this fallback. No product page, production assets or canonical
cache is changed. Real-data outputs stay private; do not commit them or attach
them to a public PR while source rights/publication remain held.

## Run

From the repository root, using the existing survey Python (numpy/rasterio):

```sh
python research/scripts/coast_mvp/coast_c1_preview.py \
  --manifest /admitted/c1/manifest.json --output /task-owned/new-preview
python research/scripts/coast_mvp/capture_c1_preview.py \
  --preview /task-owned/new-preview --browser /installed/chromium
```

The output directory must be new and outside the input directory. The renderer
verifies the exact elevation/contributor hashes, grid metadata, actual source
counts and total contributors before writing the page. It never opens the source
paths or downloads citation URLs. Only the three named C1 files are read.

The capture tool uses an already installed browser, no server, no scripts,
local file URLs and blocked remote DNS. It refuses existing screenshot files,
and records the hashes of both HTML and actual browser PNGs. A default sandbox
failure is a host capability problem, not authorization to change host settings.
The explicit `--no-sandbox` option, if admitted for self-generated local pages,
is disclosed in the receipt; it changes only that disposable browser process.
Do not use this option with remote or untrusted pages.

## Rendering limits

- Physical-slope hillshade, NW sun at 45 degrees, no vertical exaggeration.
- Fixed elevation-positive-up colour scale 0 to -1700 metres across all views.
- The source grid is 10 m; display sampling is recorded independently per view.
- Bounded strip reads; at most 1300 samples per display side. Native centre
  elevation is retained without depth averaging. A display block is withheld
  if **any** native cell has missing support or a different source code.
- Gradient stencils never cross invalid cells or contributor changes. Native
  per-source datum offsets are not adjusted. Narrow source seams and coverage
  cutouts stay visible. Blanks are not a land/water classification.
- North is EPSG:3310 grid north, not a navigation heading. The receipt records
  the exact source raster window, stride and sampled elevation range. Partial
  blocks at the display extent edges are omitted, not filled.
- Source-resolution, coverage and datum limits remain visible; an attractive
  hillshade is not measured uncertainty, seam QA or a navigation chart.
- All four source credits refer to the parent mosaic; the linked rights page
  lists every actually contributing source with native-cell counts and hashes.

## Acceptance

```sh
python -m pytest tests/contract/test_test_layout.py \
  tests/contract/test_research_boundary.py \
  research/tests/test_coast_c1_preview_rights.py \
  research/tests/gis/test_coast_c1_preview.py -q
```

Offline synthetic tests cover fail-closed metadata, HTML escaping, no secret
source paths in pages, native counts/hash/grid checks, hidden subpixel holes,
mixed-source blocks, unchanged nearest depths, absence of false edge gradients,
RGBA/PNG round trips, and overwrite/cache-write refusal. These tests do not
substitute for the separately executed real C1 build and three real screenshots.

Review requires the exact code head, input/output hashes, executed command logs,
rights page, render and browser receipts, and three screenshots. Independent
Opus review is required for Astra/OpenAI authors. Neither machine PASS nor task
completion grants semantic/source acceptance or publication permission.
