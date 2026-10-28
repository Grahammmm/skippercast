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
        --sample-sha256 HEX --plan-sha256 HEX --bridge-sha256 HEX --out NEW_REPORT.json

Python API: `audit_sample(sample_document, plan_sha256, bridge_sha256)` returns the
report dict or raises `SampleAuditInvalid` with a `reason` code.

Exit codes: 0 report written; 3 INVALID (for example `missing_field`, `duplicate_key`,
`malformed_key`, `method_mismatch`, `seed_mismatch`, `target_mismatch`, `size_mismatch`,
`selected_not_eligible`, `selected_mismatch`, `eligible_not_in_map_done`,
`row_cap_exceeded`, `invalid_sample_sha256`, `sample_hash_mismatch`, `bad_json`
including numbers beyond the interpreter's integer
string-conversion limit, `bad_type` including non-finite or non-integer counts);
4 refused (symlink or `..` in the path, non-regular input, oversized file, existing
output); 2 usage error.

## Bounds

Tool-local limits for this report only: 2 MiB input file, 16 MiB aggregate input,
4096 keys per population and 8 MiB output. Input and output paths are checked
component by component as supplied, before any open or creation: a symlink at any
existing component and any `..` component are refused (no lexical normalization can
erase a `link/..`), and the input must be a regular file. The acceptance runner applies
the same rule to its `--output` root before creating any directory. The output is
created exclusively (never overwritten) with deterministic JSON; non-finite numbers are
refused. The interpreter's global integer-digit limit is never raised. These limits do
not change any coast run, download or model cap, or `coast_sample.py` itself.

Trusted sample hash (operator rule-29 checkpoint disposition 2026-10-24 15:30 PDT,
option A): the CLI requires `--sample-sha256`, the caller's trusted expected SHA256 of
the sample file bytes. It must be 64 lowercase hex characters (otherwise INVALID
`invalid_sample_sha256` before anything is read). After the bounded read and before
any parse or write, the digest of the bytes read is compared with it; a mismatch is
INVALID `sample_hash_mismatch` (exit 3) with inputs and existing outputs unchanged and
no output created. The report records `sample_file_sha256` and
`sample_file_sha256_check: MATCHED_SUPPLIED_EXPECTED`. The Python API
`audit_sample(sample_document, ...)` takes an already parsed document and is unchanged.

## Tests

`tests/unit/test_sc_sample_audit.py` uses the tiny synthetic fixture in
`tests/fixtures/sc_sample_audit/` and inputs generated through the unchanged producer.
The test functions do not import pytest, so `scripts/accept_sc_sample_audit.py` can run
them offline with the installed `python3` (`--suite focused|contract|negative --output
DIR`). The runner installs network, subprocess and model-import sentinels, keeps
temporary files inside a new run directory, records hashes and per-test results, and for
the negative suite proves that an in-memory double omitting the zero-selected group is
caught and that disabling the sample-hash comparison is caught. A passing run is
review-required local evidence, not full CI.
