# SP107-WATCH-DECODE: UTF-8 failure isolation

Specification: SP-10-v1. This change is limited to decoding failures while reading an AIS watch file.

## Contract delta

`read_watch` converts invalid UTF-8 into the existing `WatchFileError` path with a fixed, bounded diagnostic (`watch.json is not valid UTF-8`). `WatchFile.poll` therefore rejects the changed bytes, records its existing `last_error`/`errors` fields and retains its last accepted `WatchList`. It does not retry the same bad file on every unchanged poll. A later valid file is accepted normally and clears `last_error`.

No JSON/schema, MMSI, listener scheduling, subscription, source, or live-file behavior is changed.

## Case-to-claim mapping

- A1, `test_primary_regression`: valid watch -> invalid leading UTF-8 byte -> `poll()` returns `False`, no exception, exact accepted object/set retained, nonempty error recorded. The test catches `UnicodeDecodeError` as observed data before asserting the required result.
- A2, `test_invalid_sequences_preserve_prior_state_and_repeat_is_bounded`: malformed bytes at the start and inside JSON, plus repeated bad polls, preserve the accepted object and do not increment failures repeatedly.
- A2/A3, `test_invalid_initial_read_and_recovery`: invalid first read with no prior file is safe; replacing the same path with valid content loads it, clears the diagnostic, and then an unchanged poll is a no-op.
- A3, `test_malformed_json_and_schema_rejection_still_retain_state`: malformed JSON and unsupported schema still use the existing rejection behavior without changing the accepted watch.
- A4, `test_healthy_control`: valid initial and changed watches load exact sets. On the pinned pre-edit source, only A1 is expected to fail semantically; this red run is retained as `BASELINE_DEFECT_REPRODUCED`, not product acceptance.

Fixtures are synthetic schema-version-1 producer documents in `tests/fixtures/sp107_watch_decode/`; invalid bytes are written only into per-run temporary watch paths. No live listener or real watch data is read. The acceptance runner redirects temporary roots under each unique candidate output run and checks that imports resolve to this staged repository.

## Verification limits

Scoped baseline, focused, original `WatchTest` regression, and repository-check receipts are stored in unique children beneath the supplied output roots. A scoped green run is review-required. Full-suite, exact-head CI, publication, and shipping remain owned by the operator; this note does not confer live/source permission or semantic acceptance.
