# SP77: full-precision nearest sea-cell selection

## Scope and behavior

`nearest_sea` compares each eligible distance to a separate unrounded
`best_km`. Only the public tuple's latitude/longitude (five decimals) and
kilometres (two decimals) are rounded. The inclusive radius, existing search
window, sea mask, row-major traversal, and strict-less-than tie rule are
unchanged. Consumers still receive `(row, col, grid_lat, grid_lon, km)` or
`None`; `collect` still consumes the same indices and presentation fields.

Previously, storing the rounded distance as the comparison threshold could
replace a nearer cell when it rounded up, or hide a later nearer cell when it
rounded down. It could also replace a first equal-distance cell after rounding
up. These are intentional selection corrections, not radius/grid redesigns.

## Claim-to-test mapping

All cases use the complete product module and synthetic numpy axes/boolean
masks shaped like `read_mask` output, without a GRIB decoder or acquisition.
Fixture kilometre offsets become longitudes along the equator. An independent
arc-length oracle orders them without calling the product distance helper.

- A1: `test_primary_round_up_selects_column_zero` orders 0.996/0.999 km,
  captures the observed column, and requires zero.
  `test_reversed_round_up_order_selects_later_nearer_cell` reverses them and
  requires column one. These cover both update/non-update branches.
- A2: `test_round_down_does_not_hide_later_nearer_cell` and
  `test_round_down_preserves_first_nearer_cell` cover both orders of
  1.004/1.002 km. `test_equal_distance_retains_first_row_and_column` requires
  the first row and column for exact ties with up/down/zero rounding.
  `test_radius_exact_and_adjacent_floats` covers inclusive radius and its
  immediately adjacent floats, plus radius zero. Here only, the exact product
  metric sets the boundary to avoid a false floating-point oracle mismatch.
  `test_land_cannot_win_even_when_closest`, `test_empty_axes_return_none`,
  `test_all_land_returns_none`, and
  `test_outside_radius_and_window_return_none` cover all filtering branches.
- A3: `test_presentation_tuple_and_ordinary_selection_unchanged` requires
  concrete rounded coordinates, tuple length/types, and the ordinary 2 km
  selection. `test_wrapped_longitudes_keep_existing_selection` preserves
  longitude wrapping. Every `sample` call compares input values, bytes,
  shapes and dtypes before/after; inputs must remain unchanged.
- A4: baseline runs exactly the primary and
  `test_healthy_mask_control_selects_column_zero`. Before the product edit,
  the pinned source produced column one and the named assertion failed;
  masking the later cell passed. Child exit 1 is retained with one failure,
  one pass and zero errors/skips. Wrapper exit 0 means only
  `BASELINE_DEFECT_REPRODUCED`, never product GREEN. The identical test/fixture
  hashes are required by all subsequent phases.

## Acceptance and evidence

From the candidate repository, invoke `python3 scripts/accept_sp77_sea_nearest.py`
with `--suite baseline`, `focused`, `regression` or `repository`, each with a
separate `--output` parent under the candidate's sibling `out/` directory.
The launcher allocates a unique child output on every invocation. No receipt
or output belongs in fixtures or the repository. Baseline must run on the
pinned product before editing it; final green phases must be rerun at the
signed-off commit after the last edit. Reviewer outputs use separate parents.

The helper verifies the operator-owned staging manifest and base ancestry,
records inspected local import/child-call closure, and fails closed on absent
selectors, unexpected skip/error, unavailable runtime or changed frozen tests.
Focused runs all 13 new methods. Regression runs exactly the unchanged
`tests.unit.test_forecast_ensemble.LocationTests` (four methods). Its region
lookup uses a synthetic committed region with the supported id/intelligence/
forecast_points shape, redirecting both `ROOT` and `region_points`' bound
default before invocation. Original assertions are unchanged.

Test children use the staged `.venv/bin/python3`, with repo and src placed on
`sys.path` inside the file entry, and bytecode disabled. Network/DNS/process
sentinels precede target imports; fetch/session/decoder/model/build/read entry
points are denied before tests. The inspected imports only define functions,
classes and constants; deferred decoder/build/feed imports are not exercised.
Child writes are restricted to the fresh output; temporary defaults derive
from that output. These sentinels are regression safeguards, not a hostile-code
sandbox. No model or service is called.

Repository mode runs the unchanged `scripts/check_repository.py` under
`runtime.credential_scan_python3` from the staging manifest, not the launcher
interpreter. This script is a stdlib-only offline link/private-material scan;
it is not a new scanner or a claim of exhaustive secret detection. Every phase
retains literal argv/cwd, Python version, base/head, source/test/fixture hashes,
counts, child/wrapper exits, stdout/stderr and hashes in `receipt.json`.

## Provenance and limits

All new material and this product delta are authored by actual gpt-6.1-sol /
openai-codex on the explicitly admitted Sol builder route, task t_8accd6b3,
run 1555. Fixtures and harness are newly authored, not copied Astra diagnostic
code. Existing repository material remains attributed to its pinned history.
The sole independent reviewer is actual Claude Opus 5.5 on opus-coder-bopus.
Machine-valid scoped output is REVIEW REQUIRED. Full-suite CI, PR, exact-head
shipping and release remain operator-owned and OWED; no push, merge, live run,
publication, source acquisition, scientific guarantee or hold release occurs.
