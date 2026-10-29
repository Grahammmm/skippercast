# SP101 beach cache clock

Specification: SP-10-v1. The `due` polling decision treats a cache entry as due unless its first source is successful and has a parseable timezone-aware retrieval timestamp in the existing interval `0 <= age < POLL_MINUTES`.

Contract delta: timezone-naive timestamps are due, not fresh, and cannot raise from the aware/naive comparison. Malformed cache inputs remain due. Frequency (55 minutes), source outcomes, zero-inclusive and interval-exclusive boundaries, future-time rejection, bindings, collection, publication and water-quality interpretation are unchanged. No real data is a fixture.

Claim-to-test map (all methods are in `RegressionTests`):

- A1: `test_primary_regression` isolates a naive timestamp in an otherwise valid successful producer-shaped source, captures exceptions as observed data, checks unchanged bytes and requires normal `True`.
- A2 timestamp gates: `test_invalid_and_naive_timestamps_are_due` covers null, non-string, empty, invalid, date-only and naive date/time strings. `test_missing_timestamp_is_due` removes only fetchedAt.
- A2 source gates: `test_malformed_sources_are_due` covers missing/empty/malformed source collections, non-object first entries and malformed top-level documents. `test_error_or_missing_outcome_is_due` changes only outcome while retaining a valid aware timestamp.
- A2 file gates: `test_invalid_files_are_due` covers a missing file, invalid UTF-8/JSON and an unreadable directory. `test_unreadable_file_is_due` injects PermissionError on the specific synthetic file (portable even under privileged CI). All readable cache bytes are compared after `due`.
- A3: `test_aware_offsets_and_poll_window` checks equivalent offset and Z forms, age zero, interval minus one microsecond, exact interval, older and future by one microsecond, plus unchanged bytes. `test_publish_keeps_healthy_cache_with_injected_fake` passes a fake session, synthetic root and fixed clock, checking no calls and unchanged output.
- A4: baseline executes exactly `test_primary_regression` and `test_healthy_control`, on the pinned product SHA256. It requires one named semantic AssertionError containing the observed naive/aware TypeError and one healthy-control pass, no errors/skips, child exit 1. Wrapper exit 0 means only historical `BASELINE_DEFECT_REPRODUCED`, never product acceptance. Final focused mode runs the same test/fixture bytes.

Synthetic fixture definitions are committed in `tests/fixtures/sp101_beach_cache_clock/cases.json`; URLs use a reserved example domain and invented source identities. Source structure follows `collect`'s sources array (outcome/fetchedAt). Unchanged original PublishTests and CollectTests additionally check the actual producer and injected FakeSession integration.

## Offline runner

Run `python3 scripts/accept_sp101_beach_cache_clock.py --suite MODE --output OUTPUT`, with MODE baseline, focused, regression or repository and OUTPUT a child of the candidate's out directory. The operator-written source manifest is mandatory; no manifest generation, runtime fallback or package installation occurs. The test child uses `.venv/bin/python3` without resolving away the venv invocation. Repository mode uses only the manifest's credential scanner interpreter and executes unchanged `scripts/check_repository.py` with runpy inside that child; receipts distinguish actual process argv from runpy target argv. Every child has a unique temporary root beneath its unique evidence directory.

Before target imports, the child disables bytecode writes, sets synthetic temp/cache roots and the staged package root, and installs socket/process/model-import tripwires. It verifies the imported target identity, contracts root and bound defaults. Hooks are child-process-only; ordinary test discovery has no irreversible hooks or environment changes. These are accidental-call tripwires, not a hostile-code sandbox.

Original compatibility selectors and source bytes stay unchanged. Their TemporaryDirectory constructors inherit the fresh synthetic temp root; selected tests create no SQLite sink. One original missing-file assertion uses a fixed nonexistent-path sentinel. A narrow test-module-local Path adapter maps only that sentinel to a fresh synthetic missing path before `due` sees it; other paths are untouched. The receipt records this redirect. No operational/default filesystem path is exercised.

Each invocation records actual HEAD/base, source-manifest and source/test/helper/note/fixture hashes, material provenance, interpreter identity/version, actual argv/cwd, structured named outcomes/subtests and counts, exits, raw output paths/hashes, and an explicit review-required or historical-defect verdict. Nonzero child, skips, missing selectors/imports, tripwire attempts or source changes fail acceptance. Outputs use fresh unique children; reviewer runs must not overwrite or reseal author evidence. An external frozen manifest binds completed author runs after exact-head checks.

## Provenance and remaining gates

Initial uncommitted material was authored by gpt-6-luna on openai-codex/luna-worker. The preserved continuation, expanded tests, acceptance corrections and final commit are by gpt-6.1-sol on openai-codex/sol-reviewer. No Luna material commit exists; the final signed-off commit has mixed Luna+Sol Codex provenance. Sole independent reviewer: actual Claude Opus 5.5 on opus-coder-bopus under the operator's continuation disposition. This note is not independent approval.

Scoped offline focused, regression and repository checks are worker-owned evidence, not full-suite or shipping approval. The operator still owes full repository CI, exact-head required CI, PR publication and release gates. No legal/scientific, safe-water, navigation, source/live, publication, deployment or hold-release authority is supplied. Existing holds and service/profile boundaries remain unchanged.
