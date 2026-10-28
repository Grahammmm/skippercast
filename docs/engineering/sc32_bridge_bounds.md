# SC32-BRIDGE-BOUNDS: malformed geographic boxes never plan a coast catalog bridge

Scope (operator refreeze 2026-10-24 18:52 PDT, option 1):
`src/skippercast/coastal/coordinator/catalog_bridge.py`, the new local
`_crs84_bbox` contract helper, the `check_plan` segment bbox precondition, and the
single candidate-extent condition line in `_decide`. `_overlaps` is byte-identical
to the frozen base.

## Defect (base 59fca09)

- `_overlaps` converted every coordinate with `float(...)`, so numeric strings
  (`"-120.6"`) and booleans were accepted as coordinates, and there was no range
  check: a catalog extent with an east of 200 or a west of negative infinity still
  "overlapped" a segment and was selected. A huge integer such as `10**400` raised
  an uncaught `OverflowError` out of `evaluate` instead of holding the candidate.
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
- `check_plan` keeps its original `plan segment_id and bbox_crs84 required`
  refusal, then refuses a segment box that breaks the contract with a
  `ValueError` naming `bbox_crs84`. This runs before any candidate decision,
  cached-source check or output directory.
- `_decide` holds a candidate whose extent breaks the contract, using the existing
  `catalog_extent_does_not_overlap_segment` reason, before calling `_overlaps`.
  A valid extent is still selected only on a positive-area overlap; edge- or
  corner-only contact is not an overlap.

## Why `_overlaps` itself is unchanged

`_overlaps` is also the window-footprint test inside `_expected_windows`, which
decides the exact window set a window-set plan must carry. A computed footprint
may legitimately reach past the world edge: a 512-cell tile anchored at
longitude 179 with 0.001-degree cells ends at 180.024. The round-1 candidate put
the contract inside `_overlaps`, which silently dropped such a tile from the
required set. A complete plan was then refused and a plan omitting a required
intersecting window was accepted. That was not fail-closed, and it changed the
frozen window counts. The contract therefore applies to the two external boxes
(plan segment and catalog extent) only, and computed footprints keep the base
predicate. `test_a1_world_edge_window_set_keeps_baseline_completeness` covers an
east-edge and a south-edge tiling: the complete set is selected with one acquire
job per window, and the plan omitting the edge-crossing tile is refused, exactly as
on the frozen base.

Unchanged: `_overlaps`, tiling, affine checks, window counts and caps, byte caps,
allowlists, source hashes, acquisition, enqueue and every hold reason.

## Evidence

`tests/unit/test_sc32_bridge_bounds.py` (A1-A4) and
`research/scripts/accept_sc32_bridge_bounds.py --suite focused|contract|negative`.
Producer-shaped catalogs and plans come from `tests/_coastal_catalog_fixture.py`.
The box and world-edge tiling table is `tests/fixtures/sc32_bridge_bounds/boxes.json`.
Cached sources are tiny placeholder files that the bridge only lstat-checks. The
negative suite runs two in-memory mutations of the staged module:

- `legacy-bbox-gate` replaces `_crs84_bbox` with a test-local no-contract gate (the
  pre-SC32 decision path). The numeric-string, infinity, out-of-range, huge-integer
  and malformed-segment detectors must fail with their SC32 markers, while the
  valid-overlap, edge-adjacency and world-edge controls stay green.
- `round1-strict-overlaps` replaces `_overlaps` with the round-1 strict predicate.
  The world-edge completeness cases must fail with `SC32-WINDOW-OMITTED`, while
  the valid-overlap and edge-adjacency controls stay green.

Scoped local evidence only: REVIEW REQUIRED, not full CI, source or live acceptance.
