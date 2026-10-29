# Advisor daily skipper calendar window (SP1407)

Contract: SP-14-v1, with the operator's 2026-10-25 04:41 PDT standing admission adopting the minimal original-test amendment requested on task t_773f91c6. Scoped green remains REVIEW REQUIRED.

## Behavior and scope

For an answer dated D, skipper reports cover D, D-1 and D-2 inclusive, using local calendar date keys, not a rolling 72-hour interval. The only product delta is the lower SQL bound in `server/advisor/answers/reports.ts`: `addDays(date, -DAILY_DAYS)` becomes `addDays(date, 1 - DAILY_DAYS)`.

The upper inclusive bound, published-state and port filters, descending date/ascending ID order, eight-row cap, report identity/version hashing and unverified-boat anonymity are unchanged. The landing seven-day confidence ladder and public `get_port_report` fourteen-day history window remain unchanged. The complete original tools suite still exercises these separate windows.

## Frozen compatibility amendment

Before implementation the existing `tests/test_advisor_tools.mjs` planning assertion expected September 27, 26 and 25 for a September 28 answer. The new calendar contract excludes September 25. The original source/admission owner adopted the recommended amendment: remove only `['2026-09-25', 'Example Boat One', ['vermilion']]` from that expected array. The seed, all other assertions, every other original-test byte and `tests/test_advisor_daily.mjs` remain unchanged. This is an explicit old/new acceptance delta, not a skipped test or an exemption. Original baseline source hashes and the earlier conflict dossier remain in candidate evidence.

## Requirement-to-test map

All new tests use complete real modules, the existing migration-backed in-memory D1 adapter and committed synthetic `tests/fixtures/sp1407_daily_window/cases.json`. No planner extraction is imported.

- A1/A4: `primary regression` inserts eligible reports for October 21–26, 2026 and asserts exactly October 25, 24, 23, including report IDs and order. The unchanged full module demonstrably fails only the semantic three-date assertion; its paired `healthy control` passes.
- A2/A4: `healthy control` requires the report exactly two calendar dates earlier and excludes draft/pending/other-port rows. The pair is registered alone in baseline mode, without name filtering or skips, and is unchanged in focused mode.
- A2: `A2 today, boundary, anonymity, filters and empty fallback` checks both inclusive endpoints, anonymity, filters and exact empty composition. `dailyAnswer` runs with `generate: false`, with no API key and a throwing model dependency; empty composition writes no cached answer.
- A3: five `A3 calendar boundary: ...` cases use explicit independent expected date lists for month, year, leap day and both Pacific DST transitions. Frozen epochs are converted to local date keys by the public calendar helper; the fall case deliberately differs from its UTC date.
- A3: `A3 hash identity/version recompute and unchanged eight-row ordering cap` verifies identities and tie order for ten reports, unchanged hash under excluded old/future/draft additions, a version-triggered new hash, recomputation versus synthetic stale cache and reuse of matching cache. Hashes are independently calculated by Node crypto over real complete inputs.
- A3: `A3 downstream planning uses corrected daily inputs, not the future or fourth date` calls the complete public `planningBrief` with injected synthetic feeds and checks the corrected dates and boat identities.
- Safety control: `offline network, model and storage controls are active` exercises throwing sentinels. No network request is attempted beyond the replaced global function.

## Offline execution and portability

`tests/fixtures/sp1407_daily_window/bootstrap.mjs` is a file-based preload installed before product imports, including bound defaults. It replaces global fetch/WebSocket, Node HTTP(S)/TCP/TLS entry points, browser storage mutation and Worker cache APIs with throwing sentinels, and supplies repository-owned region/build globals. The new suite restores case-local globals and closes only its in-memory databases after every case, then restores its preload. Original suites keep their recorded API fakes and complete migration/feed import closure. This is an offline test guard, not a hostile-code sandbox. No live storage bindings or real provider keys are supplied by the new suite.

The Python launcher derives all committed paths from its own location. It validates candidate output and fixture ancestry, rejects linked/non-directory output ancestors, creates a fresh UUID/time child per invocation and never rewrites old receipts. The shared operator-staged venv and dependencies are not edited. The source manifest remains an external staging/admission record, not a committed fixture or operator input bundle. `runtime.credential_scan_python3` is mandatory for the unchanged repository checker; there is no system-Python fallback.

From the repository root, invoke the helper separately for each suite:

    python3 scripts/accept_sp1407_daily_window.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp1407_daily_window.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp1407_daily_window.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp1407_daily_window.py --suite repository --output ../out/author-repository
    python3 scripts/accept_sp1407_daily_window.py --suite typecheck --output ../out/author-typecheck
    python3 scripts/accept_sp1407_daily_window.py --suite build --output ../out/author-build

Baseline is historical only: it requires the pinned unchanged product hash and must not be rerun at the corrected final HEAD. It returns success only for two selected tests, exactly one semantic assertion failure and a passing healthy control, child exit 1, zero skips/errors/cancellations. That result is BASELINE_GAP_REPRODUCED, not a fix pass. Final focused mode must pass all eleven tests; regression must pass all forty-seven original tests with only the admitted expected-array amendment. Typecheck runs all three configurations separately, followed by the existing build. Build uses only the normal local build, not deploy.

Every run retains literal child argv/cwd, runtime versions, exits, test names/counts, stdout/stderr with hashes, staged base, actual HEAD/tree, working-tree state, source/test/fixture hashes, frozen spec hash and author/runtime provenance. Source drift makes the invocation fail. The full unchanged tree remains identified by its Git object, with advisor/migration/selected-fixture closure additionally file-hashed. Historical baseline remains tied to its original source and test/fixture hashes. Reviewer reruns use separate output roots and do not reseal author evidence.

## Limitations and release ownership

Actual material author: gpt-6.1-sol / openai-codex, sol-reviewer run 1962. Sole independent reviewer: actual Claude Opus 5.5 on opus-coder-bopus. Commits carry sign-off and actual author-model/provider trailers.

Local scoped success is neither whole-repository CI nor semantic/legal/scientific/navigation or release approval. The existing operator owns PR publication, unchanged full-suite execution, strict skip accounting, the complete CI matrix (including GIS/survey, regional/search parity, audits and browser/e2e), exact-head required CI and release. No worker push, merge, source acquisition, live action or service/hold change is admitted. SC#1/PR846, SC-5b, terrain-mask, public-viewer, legal-preview, source/live and bulk-download holds remain. Machine-valid output remains REVIEW REQUIRED.
