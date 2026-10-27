C4 bounded regional QA

NOT FOR NAVIGATION. Every packet is review_required, not semantic, scientific,
rights or publication acceptance. No source acquisition or model calls.

From the repository root (stdlib fixture path):

    python research/scripts/coast_mvp/coast_qa.py --region-config research/tests/fixtures/coast_mvp/qa/region.json --output /absolute/fresh/packet

One directory per region contains qa.json, QA.txt, and a native-size gray+alpha
hillshade PNG per segment. Existing directories are never overwritten. The
JSON packet contains per-segment stats, four-connected hole components (pixel
bounding boxes, size and boundary flag), and every source-pair overlap RMS,
mean signed difference and jointly valid cell count. No overlap means
unavailable/null, never zero error. Single-source segments have no pairs.
Holes include land and unsurveyed water; there is no water mask. RMS is an
overlap-grid difference, not a vertical datum accuracy or seam continuity claim.
Hillshade follows the tier-1 screener's azimuth 315/altitude 45 and PNG encoding
approach, adapted without its model or unreleased pipeline dependency. Invalid
pixels are transparent; nodata neighbours do not create artificial cliffs.

Fixture input contract:

    {"region":"synthetic-central","segments":[{"id":"fixture","mosaic":"mosaic.asc","sources":[{"id":"a","path":"a.asc"},{"id":"b","path":"b.asc"}]}]}

ASCII fixtures must be aligned ESRI ASCII corner grids, horizontal metres,
elevation-positive-up metres. The committed 4x4 mosaic selects source A first,
source B second, with one interior void and three overlaps of constant 3 m.
Identifiers are safe unique names. Relative paths resolve against the config.
Inputs/config are hashed into the packet. No live datum conversion is inferred.

C1 adapter contract (requires existing survey interpreter):

    {"region":"synthetic-central","segments":[{"id":"fixture","manifest":"manifest.json"}]}

Reads the coast_mosaic.py schema_version=1 manifest's outputs.elevation and
sources (path, sha256, value_convention, vertical_offset_m). Verifies hashes,
warps each original source nearest-neighbour onto the mosaic grid, then applies
its explicit sign and constant offset. Uses source valid masks, not contributor
boundaries, to measure overlap. Preserves C1 limitations. Missing originals,
changed hashes and unsupported grids fail before producing a normal packet.
C1 deletes warped intermediates; this adapter does not assume they survive.

Current scope is tiny fixture qualification: at most 1,000,000 target cells per
segment, materialized arrays and native-size PNGs. Real C1 (130M cells) is
intentionally refused; a streaming/scaled region run is not qualified by these
tests. This card's latest conductor brief explicitly prohibits real-source runs.

Acceptance:

    python -m pytest tests/contract/test_test_layout.py research/tests/test_coast_mvp_qa.py -q
    python -m pytest research/tests/gis/test_coast_mvp_qa_c1.py -q
    git diff --check

The ordinary tests require only stdlib. GIS tests create tiny EPSG:3310 TIFFs
from the committed ASCII pair and verify the actual manifest adapter, sign and
offset handling, hash failures, holes and unavailable-overlap semantics.
