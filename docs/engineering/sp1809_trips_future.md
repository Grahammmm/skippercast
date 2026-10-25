# Charter trip report-date upper bound (SP1809)

Spec: SP-18-v1 / SP1809-TRIPS-FUTURE.

## Bounded change

Only `server/advisor/tools/get_trips.ts` changes product behavior. Both SQL reads
now bind the same `today = localDate(ctx.now)` on the existing Pacific calendar.
Published reports after today cannot affect boat recency, ordering, the twelve
boat limit or observed trip types. Last-report recency retains all historical
published reports at or before today, without a sixty-day lower bound. Trip types
retain the existing inclusive sixty-day lower bound and include today.

Verification status, port resolution, alphabetical ties, booking-link policy,
boat-page placeholders, few-boats wording and the unranked result shape remain
unchanged. Future-only verified boats still qualify, with null recency and no
future-derived types. No timezone policy or schema is redesigned.

## Test-first proof and focused coverage

Before changing product source, the acceptance launcher ran the healthy control
and primary regression separately against the pinned unchanged base
`67ff9bcf34257698a41585bc2ad163171dc68259`. The control passed (one test), and
`SP1809_A1_FUTURE_INVARIANCE` failed as an assertion (one test, child exit 1).
The launcher classified this only as `BASELINE_GAP_REPRODUCED`. The original raw
receipts retain the test/fixture/launcher hashes and original source identity;
they are not repaired or re-labelled as success. The same test bytes pass after
the SQL change. Baseline mode intentionally refuses a repaired product checkout.

The new suite imports the full real staged TypeScript modules using installed
Node type stripping and runs their SQL through the existing migration-backed
`advisorDatabase` in-memory adapter. Synthetic rows follow the existing
`seedTrips` schema, not planner stubs or copied SQL. The committed JSON fixture
contains no real contacts, records or boat data.

The nine tests are the healthy control, the primary A1 regression, and rows A1–A7:

- A1: yesterday/today inclusion, tomorrow/much-later exclusion and a UTC-next-day
  instant that is still today in Pacific time.
- A2: latest eligible mixed report and historical recency older than sixty days.
- A3: future-only/no-report verified boats and alphabetical null-recency ties.
- A4: inclusive since/today, one-day-before exclusion, distinct/null trip types.
- A5: pending/rejected boats and unpublished reports excluded.
- A6: a future report cannot displace an eligible boat under LIMIT twelve.
- A7: real port aliases, other-port exclusion, HTTPS/no-booking/insecure controls,
  boat-page/landing fields, few/empty wording and unranked output.

Each run uses isolated processes. The preload fixture installs network/model
sentinels before product imports; the focused context binds only the synthetic DB
and inert feed/model dependencies. There is no live D1 or file-backed DB default
in this path. Actual static catalog inputs and Worker globals follow the existing
advisor test shapes. The hooks restore patched globals in their own process and
make even a caught network attempt fail at teardown. These sentinels are an
accidental-side-effect guard, not a hostile-code sandbox. Existing compatibility
suites use their own synthetic inputs and recording channel engines. No UI test
or renderer is required for this SQL-only change.

## Portable acceptance and evidence

From repository cwd, invoke the script file:

    python3 scripts/accept_sp1809_trips_future.py --phase PHASE --output OUTPUT

PHASE is baseline, focused, regression, repository, typecheck or build. OUTPUT
must be outside the repository. Every invocation makes a new uniquely named child
with `receipt.json` and each child's raw stdout/stderr. Receipts include explicit
argv, cwd, selected tests, runtime versions, exits, test/check counts, elapsed
time, source identity and SHA256 of raw outputs. A changed source identity during
execution fails the phase. Nonzero statuses and incomplete TAP summaries fail
closed; skipped/cancelled/todo tests never qualify.

The script derives repository paths from its own location and reads the operator
staging `SOURCE-MANIFEST.json` beside the repository. It validates schema, staged
repo, card and pinned base, preserves the unchanged compatibility/scanner hashes,
and uses `runtime.credential_scan_python3` for the unchanged repository checker.
There is no scanner interpreter fallback, install, shell invocation or plan-path
runtime dependency. The runtime manifest remains an external staging input.
Credentials are not inherited by child tests/build tools. No interpreter-path
overrides are added.

Focused mode runs the identical primary/control pair and then all nine tests.
Regression runs unchanged `tests/test_advisor_tools.mjs` and
`tests/test_advisor_skippers.mjs` separately; the initial candidate run passed 31
and 19 tests respectively, with zero skips. Repository mode retains the existing
privacy, local-documentation-link and fixture checks. Typecheck runs each of
`tsconfig.json`, `web/tsconfig.json` and `packages/coast/tsconfig.json` in a separate
`pnpm exec tsc --noEmit --project` invocation. Build runs existing `pnpm build`,
which writes only normal candidate-local build outputs; it never deploys.

## Provenance, review and limits

All new material and the product delta were authored by actual gpt-6.1-sol,
provider openai-codex, on sol-reviewer under this card's explicit builder-route
admission. Each material commit records that provenance and is signed off.
Claude Opus 5.5 on opus-coder-bopus is the sole independent reviewer; this document
is author self-review, not approval. Reviewer reruns use separate output roots.

Scoped test success is REVIEW REQUIRED, not full-repository CI, deployed incidence
proof, semantic/legal/scientific/navigation acceptance or release authority.
Operator-owned PR publication, full repository gates, exact-head CI and release
remain owed. No network acquisition, push, publication, merge, live run, service
change, model-setting change or hold release is supplied. All existing holds and
source/data boundaries remain intact.
