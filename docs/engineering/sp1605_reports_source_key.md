# SP1605 Reports charter-source identity

Spec: SP-16-v1. Pinned staged base:
`8a805820c30895f5f037e26af9079fd3dc015b0f`.

## Bounded change

Only `web/app/views/Reports.tsx` changes product behavior. Its settled key,
pending key and view admission use the same JSON tuple of region, target and
charter source (including null). A per-request object prevents an obsolete
A-B-A completion from passing a same-key check. Returning to matching settled
data also supersedes an unrelated pending load. Identical requests remain
coalesced. No loader policy, source availability/scoring, seasonal watch,
catch-card policy or other product file changes.

## Test-first evidence

Before any product edit, exactly `primary regression` and `healthy control`
ran through the full real Reports and reports-data modules. The primary
asserted the corrected null-to-path result and failed with
`A1_SOURCE_IDENTITY`, actual null versus expected Synthetic A. Changing target
with a valid source passed. Node child exit 1; tests 2, pass 1, fail 1;
skipped, cancelled and todo all zero. The wrapper recorded
`BASELINE_GAP_REPRODUCED`, exit 0, not repair success.

Historical receipt under the candidate's `out/author-baseline/`:
`20261025T131131Z-1bb93687aaec4a0ea944a9fbbaa3fa38/receipt.json`.
Receipt SHA256:
`66b0a7a7a1de87638f14a2895dc4c4e9367b4e121db9fd093a099051788b2b9a`.
Raw stdout SHA256:
`240b89e60d652521a47068f4525355bfa55a01c5b698f45434db74b4b7500d46`.
Raw stderr was empty. Initial launcher-format failure is separately retained
under `20261025T131051Z-13f0181b314c42a79be9086aafd3f9dd`; it rejected the
same semantic result because it expected a single-line rather than multiline
TAP assertion. Only the launcher parser was corrected before the successful
baseline; neither tests nor product were changed for that correction.

`tests/fixtures/sp1605_reports_source_key/baseline-pins.json` freezes the
baseline test and all its fixture bytes. Focused mode checks these exact
hashes before executing the identical pair plus six additional test cases.
Baseline mode intentionally requires original product bytes; do not run it
against repaired product or reinterpret the historical red receipt as green.

## Coverage and execution

From the staged repository cwd, run each separately:

    python3 scripts/accept_sp1605_reports_source_key.py --suite focused --output ../out/reviewer-focused
    python3 scripts/accept_sp1605_reports_source_key.py --suite regression --output ../out/reviewer-regression
    python3 scripts/accept_sp1605_reports_source_key.py --suite repository --output ../out/reviewer-repository
    python3 scripts/accept_sp1605_reports_source_key.py --suite typecheck --output ../out/reviewer-typecheck
    python3 scripts/accept_sp1605_reports_source_key.py --suite build --output ../out/reviewer-build

Each invocation creates a unique child directory, sets candidate-owned TMPDIR,
and records head, source hashes, argv/cwd, elapsed time, exits, test counts,
raw stdout/stderr and their hashes. No shell child or fallback interpreter.
The standard-stage manifest is read relative to this clone, not a plan or
operator input bundle. Repository scan uses its credential-scan interpreter.

Focused: eight cases, zero skips; the frozen pair covers A1/healthy target
changes. A2 covers A-to-B-to-null, delimiter collision avoidance and identical
pending/settled coalescing. A3 covers obsolete success/rejection in both
completion orders, null/path pending transitions, same-key ABA, return to
settled data, and a current source transport failure. A4 renders actual
Reports with the installed Preact string renderer, injects only its effect
scheduler and App's regionInfo host, executes the actual effect callbacks,
and checks stale evidence is withheld before effects and matching evidence
appears afterward. Real state, loader, source mappers, ReportsBody and section
components are not copied. Seasonal freshness/unavailable rules are asserted.
A malformed synthetic source deliberately triggers an old load rejection;
this does not claim to fix malformed-source validation.

The fixture uses invented boats/grounds and reserved example URLs, shaped
from the existing committed Reports tests. No real records are read. Guards
load before product execution, deny socket/HTTP/model/live fetch operations,
and allow only a synthetic unavailable coastal directory. Explicit fetch
doubles serve charter payloads and feed failures. Guards/globals restore on
process exit or the end of the scoped component test. They are accidental-I/O
sentinels, not a hostile-code sandbox. No DOM/browser installation/navigation.
All bundle/temp output is under that invocation's unique output root.

Regression: the unchanged `tests/test_reports_view.mjs` runs separately with
all eight original tests, zero skips. Typecheck: separate pnpm invocations for
each of root, web and coast tsconfigs. Build: existing `pnpm build`, normal
candidate-local outputs only, no deployment. The repository row is exactly
`check_repository.py` (documentation/privacy/fixture scans), not a claim that
all repository tests or separate credential-audit gates have executed.

## Provenance and retained gates

All new material authored by actual gpt-6.1-sol, provider openai-codex,
profile sol-reviewer, task t_19c86d75, run 2002, under explicit author-route
admission. Every material commit is signed off and identifies that runtime.
Sole same-card independent reviewer: actual Claude Opus 5.5 on
opus-coder-bopus. No self-review approval. Final exact-head receipts and
complete changed-file hashes are provided in the candidate output packet;
pre-commit exploratory receipts remain historical and are not exact-head
acceptance. No other card artifacts or plans are runtime dependencies.

Scoped success is REVIEW REQUIRED only. Operator retains PR publication,
complete Node/Python discovery, survey/GIS skip accounting, regional/search
parity, credential/privacy/link checks, web/client/copy/token checks,
dependency audit, browser/e2e and required exact-head CI/release gates. No
network/source download, outbound communication, push, merge, publication,
live run or hold release was performed. All existing source/live/legal,
public-viewer, terrain-mask, SC#1/PR846 and SC-5b holds remain unchanged.
