# SC32-BRIDGE-BOUNDS: malformed geographic boxes never plan a coast catalog bridge

Scope: `src/skippercast/coastal/coordinator/catalog_bridge.py`, the `_overlaps`
predicate (plus its local `_crs84_bbox` contract helper) and the `check_plan`
segment bbox precondition only.

## Defect (base 59fca09)

- `_overlaps` converted every coordinate with `float(...)`, so numeric strings
  (`"-120.6"`) and booleans were accepted as coordinates, and there was no range
  check: a box with an east of 200 or a west of negative infinity still
  "overlapped" a segment. A huge integer such as `10**400` raised an uncaught
  `OverflowError` out of `evaluate` instead of holding the candidate.
- `check_plan` required only a four-element `bbox_crs84` list. A segment box with
  strings, null, NaN, infinities, out-of-range or reversed/zero extents passed, the
  candidates were then inspected (`cached_source` lstat) and `dry_run` created its
  output directory before the NaN case failed at receipt serialization.

## Change

- `_crs84_bbox(box)` is the bridge's existing CRS84 contract, made explicit and
  checked as submitted: a `list` of four finite non-boolean `int`/`float`
  coordinates `[west, south, east, north]`, longitude within -180..180, latitude
  within -90..90, `west < east` and `south < north`. Exact comparisons are used,
  so a huge integer is refused without a float conversion. No wrapping or
  anti-meridian reading is introduced, and nothing is coerced or replaced.
- `_overlaps(a, b)` is false unless both boxes satisfy that contract, then true
  only for a positive-area overlap. Edge- or corner-only contact is still not an
  overlap. A malformed catalog extent therefore keeps the existing
  `catalog_extent_does_not_overlap_segment` hold.
- `check_plan` keeps its original `plan segment_id and bbox_crs84 required`
  refusal, then refuses a box that breaks the contract with a `ValueError` naming
  `bbox_crs84`. This runs before any candidate decision, cached-source check or
  output directory.

Unchanged: tiling, affine checks, window counts and caps, byte caps, allowlists,
source hashes, acquisition, enqueue and every hold reason. `_overlaps` is also the
window-footprint test inside `_expected_windows`. For valid geographic tilings
the result is the same. A footprint computed outside -180..180 / -90..90 (only
possible for a source that itself extends past the world bounds, or by float
rounding at the exact world edge) now counts as not intersecting, which is
fail-closed: the plan's declared windows must then match that stricter expectation.

## Evidence

`tests/unit/test_sc32_bridge_bounds.py` (A1-A4) and
`research/scripts/accept_sc32_bridge_bounds.py --suite focused|contract|negative`.
Producer-shaped catalogs and plans come from `tests/_coastal_catalog_fixture.py`.
The box table is `tests/fixtures/sc32_bridge_bounds/boxes.json`. Cached sources are
tiny placeholder files that the bridge only lstat-checks. The negative suite swaps
the test-local pre-SC32 predicate (`legacy_overlaps`) into the module in memory.
It requires the numeric-string, infinity, out-of-range and huge-integer detectors
to fail with their SC32 markers, while the valid-overlap and edge-adjacency
controls stay green.

Scoped local evidence only: REVIEW REQUIRED, not full CI, source or live acceptance.
