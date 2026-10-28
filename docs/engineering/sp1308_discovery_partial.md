# SP1308: skipped discovery work is partial

Specification: SP-13-v2. Base: `2979d59bfbb7d724eb83b34a48102b914ee8eaa3`.
Material author: actual `gpt-6.1-sol`, provider `openai-codex`, profile
`sol-reviewer`. All new material is independently authored for this card;
planning diagnostic code is not imported or copied. Sole independent review:
Claude Opus 5.5 on `opus-coder-bopus`.

## Compatibility delta

A successful binding can retain usable candidates while skipping a page. Its
status remains `ok`, and its existing per-reason skip counts remain unchanged,
but `discover.json` now has boolean `complete: false`. Discovery accumulates
this fact monotonically across contributing bindings, independent of order.
It uses the actual binding-local skip slice, not an adapter's supplemental
report. Pre-existing skips from before discovery do not contribute.

The candidate payload, counts, per-source report fields, gap summary, status
vocabulary, failed-source behavior and not-implemented semantics are unchanged.
An empty/no-skip binding remains complete; a not-implemented binding remains a
known gap without changing completeness. Unsupported, unavailable and failed
bindings still make discovery incomplete. A net fake without a skip collection
still works. There is no change to refresh thresholds, persisted flag parsing,
adapters, sinks, or operational CLI/status policy. In particular, `ok` does not
by itself promise completeness. Refresh consumes the genuine boolean receipt;
it must not count partial discovery toward disappearance or retirement.

This delta supersedes one earlier expectation:
`tests/unit/test_fleet_known_gaps.py::test_a_skip_on_a_source_that_listed_boats_is_counted_not_a_gap`
asserted `complete: true` for exactly the A1 shape (usable candidates plus a
layout skip). It now asserts `complete: false`; its status, skip-count and
gap-summary assertions are unchanged.

## Acceptance mapping and observed runs

All tests use synthetic adapters/contexts, invented names and reserved example
URLs. No network object or sink is supplied to new discovery tests. The
history tests only call `discovery_history` and pure `detect`; proposed
operations are inspected, never applied.

- A1 and repaired A4: `RegressionTests.test_primary_regression` verifies the
  exact preserved candidate, `ok` status, one layout skip and false completeness.
  `RegressionTests.test_healthy_control` verifies the identical no-skip payload
  and true completeness.
- A2: `DiscoveryTests.test_mixed_success_order_and_skip_reasons` checks both
  successful-binding orders, eight skip-reason shapes and exact per-source
  identities/counts. `test_existing_outcomes_and_gap_summary` checks empty,
  unsupported, unsupported-list, unavailable, failed and not-implemented in
  both orders with a healthy source, plus the all-zero-candidate gap summary.
  `test_all_success_empty_and_no_skip_collection` checks ordinary successes,
  empty/no bindings and absent skip collection. The remaining named tests
  preserve pre-existing-skip scoping and supplemental scout report fields.
- A3: `HistoryTests.test_partial_current_run_cannot_finish_vanished_threshold`
  passes actual synthetic discovery receipts to `detect`: a partial receipt
  cannot supply the third complete run, while the no-skip positive proposes
  exactly the expected vanished review/change for the synthetic vessel.
  `test_partial_historical_run_does_not_count` verifies the independent history
  reader excludes boolean false and includes boolean true at that boundary.
- A4 historical evidence: on the pinned unedited product, only the two frozen
  RegressionTests were executed. Primary failed specifically with
  `AssertionError: True is not False : A1: usable candidate plus skipped layout
  is incomplete`; healthy passed. Child exit 1, two tests, one failure, no
  errors/skips. Parent returned `BASELINE_GAP_REPRODUCED`, not acceptance.
  The test/fixture bytes are unchanged in the repaired runs.

Initial repaired execution: focused 9 tests passed; unchanged compatibility
selectors `tests.unit.test_fleet_ingest.IngestTests` and
`tests.unit.test_fleet_refresh.RefreshTests` ran 13 tests, all passed, no
errors/failures/skips. The exact final committed identity and final executions
are bound by the external handoff manifest, not retrospectively assigned to
these initial runs.

## Portable runner and evidence

From this repository run each command separately:

    python3 scripts/accept_sp1308_discovery_partial.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp1308_discovery_partial.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp1308_discovery_partial.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp1308_discovery_partial.py --suite repository --output ../out/author-repository

Baseline is historical and intentionally rejects a repaired product: do not
rerun it as a green final row. Every invocation creates a fresh unique child
under its output label and preserves earlier runs. Newly authored fixture and
output ancestry may not contain symlinks. Tests, fixtures and this note derive
paths from their file/repository locations and do not depend on planning paths
or machine-specific home paths.

Parent runs under declared `python3`. Python test children use staged
`.venv/bin/python3`; repository mode uses only the operator manifest's
`runtime.credential_scan_python3`. That child runs the unchanged
`scripts/check_repository.py` as `__main__` using `runpy`, with its literal target
argv recorded separately from the actual file-bootstrap argv. No scanner,
original test, dependency or release policy is modified. No interpreter
fallback or install is attempted.

Before product/test imports, each fresh child sets synthetic temp/HOME/fleet
roots, suppresses bytecode, clears inherited credentials, and installs network,
subprocess/model-call and out-of-root write/SQLite tripwires. The file bootstrap
puts staged repo/src first on `sys.path`, verifies loaded product files are in
this checkout, and verifies repository/default fleet roots and `Run.var`'s
unbound default. All admitted stateful compatibility calls use the original
tests' explicit synthetic paths and fakes. Hooks are confined to the child,
never installed by test discovery. They detect accidents, not hostile code.
The unchanged compatibility tests alone may apply operations to their fresh
synthetic SQLite resources; new A3 tests never do so.

Each receipt records spec/card/phase, source manifest hash, staged base, actual
HEAD and working-tree state, material provenance/commit trailers, file hashes,
selectors, registered names and actual counts, child runtime/version, literal
argv/cwd/exit, raw stdout/stderr and their SHA256 values. Production exit gates
use explicit conditions rather than removable Python assertions. Baseline is
accepted only with the exact named semantic failure/control pair. Selected
skips, errors, missing tests or tripwire events cannot count as success.
Reviewer reruns must use separate output labels, never reseal author receipts.

## Limits and holds

Scoped offline success is REVIEW REQUIRED. Full repository suites, remote PR
publication, required exact-head CI and release remain OWED to the operator.
Repository mode is the mandatory unchanged privacy/link check, not a claim that
the entire repository test suite ran. No typecheck row applies to this Python
card. No live fleet/coastal records, credentials, source downloads, publication,
service/configuration/permission changes or hold lifts are authorized or done.
All existing scientific/legal/human, source/live and public-viewer gates remain.
