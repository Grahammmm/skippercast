# SP-17: stored fleet redirect destination controls

Spec: SP-17-v1. This offline candidate rejects an embedded ASCII C0 control or DEL in a stored fleet destination after applying the existing outer-whitespace trim policy and before WHATWG URL parsing. The parser must not silently erase a control and transform malformed stored input into a navigable target.

`safeTarget` retains the existing HTTPS-only, host, credential and maximum-length checks. Existing URL query/fragment and UTM behavior, vessel selection, redirect status and GET/HEAD click-count behavior are unchanged. Correctly percent-encoded URL bytes are not decoded or rejected by the raw-control check.

Verification is scoped: `tests/test_sp1708_destination_controls.mjs` contains the expected-red A1 baseline assertion, a healthy clean-target control and A1-A4 candidate checks using synthetic SQLite data and the real migrations/Worker route. `scripts/accept_sp1708_destination_controls.py` records child argv, cwd, exit, test counts and raw stdout/stderr hashes in unique output directories. The baseline receipt is historical evidence tied to unchanged product source; candidate results are separate.

No production incident is asserted. A scoped test pass is review-required, not semantic acceptance, full-repository CI, source/live approval, PR publication, merge or release authorization. Existing fleet, legal, public-viewer and operational holds remain in force.
