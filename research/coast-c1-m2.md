# C1 lane M tile-zero pilot: acquire held

Dated 2026-10-20; task t_6fe43227. Evidence only, review required.
No product, publication, navigation, habitat or scientific acceptance.

The single official Cal DIG I v2 bathymetry archive was downloaded once
from the USGS CMGDS release. Its original TIFF was extracted unchanged.
The frozen discovery catalog is pinned in the summary receipt. Sources,
producer metadata, package code, controller records and raw observations
remain in the task-local evidence archive, not in product outputs.

The source-origin-anchored row-major 512 x 512 tile zero intersecting C1
is [6656, 0, 512, 512]. There are 440 bbox-intersecting tiles, not 440
qualified or surveyed tiles. Tile zero has zero valid native cells.
The next index is 1, window [7168, 0, 512, 512]; this is a name only,
not authorization to run it or to skip the empty first window.

The initial coordinator submission never dispatched: its 3,600-second
job request exceeded the regional remaining time after elapsed overhead.
The original receipt and zero-attempt queue entry remain intact. A second
immutable bridge plan reduced only the per-job wall cap to 240 seconds.
It used the same regional budget file, unchanged caps, original source,
window and gates. No refund, reset, re-download or shared ledger write.

The production acquire stage returned a committed held result with:

- native_support_empty
- vertical_sign_unobserved
- vertical_units_unobserved

G3 permits the unstated vertical datum, tagged datum_offset_unbounded,
not-for-navigation and without a required uncertainty bound. That does not
make planned sign/units observed facts or override the holds. The raw
observation and declared vertical block are both preserved for review.
The producer's filled-void caveat also remains; the composite is not
blanket evidence of raw measured soundings.

As required for a vertical hold, qualification and mapping stopped here.
Band counts, deepest mapped cell, product-uncertainty histogram, map
handoff hashes and the map's native_valid_support mask hash are null,
not invented zeros. R-C1-F1 has no mask exclusion set to pin from this
run: it must not interpret the absence as empty qualified support.

The first post-run readback used a nonexistent result-reference column;
schema-grounded read-only inspection verified the successful stage commit
without replaying it. This was a receipt-writer error, not an acquire error.

Sanitized receipt: research/receipts/coast-c1-m2-held.json.
Offline validation (no network or stage replay):

    python research/scripts/check_coast_c1_m2.py
    python research/scripts/check_coast_c1_m2.py --receipts /absolute/task/receipt-dir

The existing local screen, tier-two packet and independent different-model
verification children own acceptance. Machine-valid evidence is not semantic
acceptance. No next-tile card, render, merge or live publication was performed.
