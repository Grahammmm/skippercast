# SP107-WATCH-DECODE: UTF-8 failure isolation

Specification: SP-10-v1. This change is limited to decoding failures while reading an AIS watch file.

## Contract delta

`read_watch` converts invalid UTF-8 into the existing `WatchFileError` path with a fixed, bounded diagnostic (`watch.json is not valid UTF-8`). `WatchFile.poll` therefore rejects the changed bytes, records its existing `last_error`/`errors` fields and retains its last accepted `WatchList`. It does not retry the same bad file on every unchanged poll. A later valid file is accepted normally and clears `last_error`.

No JSON/schema, MMSI, listener scheduling, subscription, source, or live-file behavior is changed. The repair is the two-line exception translation only; `WatchFile.poll` is unchanged.

## Case-to-claim mapping

- A1, `test_primary_regression`: valid watch -> invalid leading UTF-8 byte -> `poll()` returns `False`, no exception, exact accepted object/set retained, bounded diagnostic and one failure recorded. The test catches `UnicodeDecodeError` as observed data before asserting the required result.
- A2/A3, `test_invalid_sequences_preserve_prior_state_and_repeat_is_bounded`: four encoding classes (leading invalid byte, invalid continuation mid-document, encoded surrogate and trailing truncated sequence) preserve accepted object/set on rejection and on repeated polls. Correcting the same file loads the exact new set, clears the error and then no-ops.
- A2/A3, `test_invalid_initial_read_and_recovery`: the same four classes fail safely without previous accepted state, remain bounded on repeated polls, then recover and no-op.
- A3, `test_malformed_json_and_schema_rejection_still_retain_state`: malformed JSON and unsupported schema retain accepted state with their exact existing diagnostics. All other producer fields remain valid in the schema negative.
- A3, `test_read_error_still_retains_state`: a synthetic mocked `PermissionError` preserves state and its existing diagnostic; a newly changed valid file recovers.
- A4, `test_healthy_control`: valid initial and changed watches load exact sets. On the pinned pre-edit source, only A1 is expected to fail by `AssertionError` reporting the captured decoding exception. This red run is historical `BASELINE_DEFECT_REPRODUCED`, not product acceptance.

Fixtures are complete synthetic schema-version-1 producer documents in `tests/fixtures/sp107_watch_decode/`. Every encoding negative is derived from a validated complete fixture; invalid bytes are written only into per-run temporary watch paths. No live listener or actual fleet watch data is read. Original compatibility runs the unchanged `tests.unit.test_fleet_listener.WatchTest`: format/schema round-trip, bad-file state retention and fake-socket watch reload/resubscription/routing. Its `make_listener` binds watch, store and heartbeat paths beneath each freshly created temporary directory; it supplies fake connectors and never calls the operational `build_listener` CLI.

## Portable runner and evidence

The helper derives its repository and candidate roots from its own location and validates the operator source manifest, pinned base source hash and ancestry. The `.venv` link is the explicitly admitted staged runtime. Repository mode uses only `runtime.credential_scan_python3`, records its real argv/version and never falls back.

The dedicated test child suppresses bytecode, installs offline network/DNS/bind, subprocess and model-import tripwires before product imports, redirects package/fleet roots and temporary storage, and verifies imported product/test files belong to the staged repository. `WatchFile` and `AisStore` take explicit paths; no operational filesystem function with an implicit live root is called. These tripwires are mistake detectors, not a hostile-code sandbox. They are deliberately not installed in imported test modules, so ordinary suite discovery does not poison unrelated tests or alter their environment.

Every invocation creates a fresh unique child under candidate `out`, refuses symlink fixture/output ancestry before access, and retains parent/child argv, cwd, Python version, duration, named test/subtest outcomes, source/fixture/import hashes and raw stdout/stderr hashes. Structured unittest results, exact expected test IDs/counts and explicit exit checks control acceptance; arbitrary printed names or removable `assert` statements cannot approve a run. Baseline additionally requires pinned product bytes and exactly the named semantic assertion failure plus the healthy pass. Final focused/regression/repository modes require a clean candidate tree.

The original Luna-authored commit and receipts remain preserved. Sol's continuation strengthens tests/helper/docs without changing the product repair. Since test bytes changed, a new honest pinned-product baseline is required before restoring that repair; old baseline evidence is not relabeled. New baseline and final runs use identical test, fixture, helper and note bytes. A baseline receipt records both actual HEAD and dirty status during the temporary pinned-product replay; its product hash, not that HEAD label, identifies the baseline source. Final evidence is rerun after the signed-off continuation commit and frozen separately; reviewer reruns must use separate fresh output roots without resealing author evidence.

## Verification limits

Scoped green is REVIEW REQUIRED, not independent acceptance. Actual material authors are Luna (`gpt-6-luna`, openai-codex) and Sol (`gpt-6.1-sol`, openai-codex); the assigned independent reviewer is Claude Opus 5.5 on `opus-coder-bopus`. Full-suite, exact-head CI, PR publication and shipping remain OWED to the operator. This note confers no source/live permission, hold release, or semantic/legal/scientific acceptance.
