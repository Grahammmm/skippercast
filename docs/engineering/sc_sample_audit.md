# Coast sample composition report (SC-SAMPLE-AUDIT)

`scripts/coast_diagnostics/sample_coverage.py` explains which source grids a fixed
`coast-sample-v1` review sample includes. It is read-only: it does not choose, change,
top up or qualify a sample.

## What it reads

The original output of `coast_sample.sample` (fields `method_version`, `seed`, `target`,
`size`, `map_done`, `eligible`, `selected` and nothing else) plus the plan and bridge
SHA256 bindings that produced it. It recomputes the selection with the unchanged
producer function only to reject a document that is not exactly that function's output
for those bindings. The recomputed selection is never emitted as a new sample.

Window keys are decoded with the producer grammar `source_id#grid_sha256#index`, split on
the last two separators, so a source ID may itself contain `#`. A key is rejected unless
the grid is 64 lowercase hex characters, the index is canonical ASCII decimal (no sign,
spaces or leading zeros) and `window_key` rebuilds the identical string.

## What it reports

One row per exact `source_id` + `grid_sha256` that appears in `map_done`, sorted. Each row
has sorted key arrays and separately named counts for `map_done`, `eligible`, `selected`,
`eligible_unselected` and `ineligible`. A group with eligible windows but nothing
selected is shown with `selected_count: 0`; a group with no eligible windows is shown with
all of its windows under `ineligible`. `populations` labels each input population
`EMPTY` or `PRESENT`, so an empty eligible population is distinct from a missing field
(which is INVALID). The report also carries the original `selected` list unchanged,
totals that reconcile across groups, the SHA256 of the canonical input document, and a
warning: composition is not source quality, coverage, eligibility proof or scientific
acceptance. The verdict is always `COMPOSITION_REPORTED_REVIEW_REQUIRED`.

There are no quotas, per-source minimums, resampling or model calls.

## Usage

    python3 scripts/coast_diagnostics/sample_coverage.py --sample SAMPLE.json \
        --plan-sha256 HEX --bridge-sha256 HEX --out NEW_REPORT.json

Python API: `audit_sample(sample_document, plan_sha256, bridge_sha256)` returns the
report dict or raises `SampleAuditInvalid` with a `reason` code.

Exit codes: 0 report written; 3 INVALID (for example `missing_field`, `duplicate_key`,
`malformed_key`, `method_mismatch`, `seed_mismatch`, `target_mismatch`, `size_mismatch`,
`selected_not_eligible`, `selected_mismatch`, `eligible_not_in_map_done`,
`row_cap_exceeded`, `bad_json`); 4 refused (symlink in the path, non-regular input,
oversized file, existing output); 2 usage error.

## Bounds

Tool-local limits for this report only: 2 MiB input file, 16 MiB aggregate input,
4096 keys per population and 8 MiB output. The input path must have no symlink in any
component and must be a regular file. The output is created exclusively (never
overwritten) with deterministic JSON; non-finite numbers are refused. These limits do
not change any coast run, download or model cap, or `coast_sample.py` itself.

## Tests

`tests/unit/test_sc_sample_audit.py` uses the tiny synthetic fixture in
`tests/fixtures/sc_sample_audit/` and inputs generated through the unchanged producer.
The test functions do not import pytest, so `scripts/accept_sc_sample_audit.py` can run
them offline with the installed `python3` (`--suite focused|contract|negative --output
DIR`). The runner installs network, subprocess and model-import sentinels, keeps
temporary files inside a new run directory, records hashes and per-test results, and for
the negative suite proves that an in-memory double omitting the zero-selected group is
caught. A passing run is review-required local evidence, not full CI.
