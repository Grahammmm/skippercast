# Species-page rule selection by jurisdiction

Spec: SP-15-v1 / SP1504-RULE-JURISDICTIONS.

## Behavior and scope

`speciesRules` selects own-species versus parent-group rows independently for
 each jurisdiction. Every returned own row is retained; parent rows are retained
only where that jurisdiction has no active/review own row in the query results.
The existing SQL, row limit, species-key resolution, default-jurisdiction ordering,
regional ordering, row content, group flag, and stale/review copy are unchanged.
A regional own row still suppresses a global parent row in the same jurisdiction;
this does not introduce a new within-jurisdiction regional fallback policy.

Only `server/advisor/pages/species.ts` changes product behavior. The public pure
`speciesRules` API and actual `speciesPage` request function run from the complete
module with real catalog resolution. There are no extracted planner functions or
replacement rule-selection implementations.

## Offline fixtures and safety

The synthetic JSON rows follow the existing advisor page test and `RuleRow`
columns. The unchanged `_advisor_d1.mjs` applies all committed migrations to
`:memory:` SQLite. Tests seed rows, expose only SELECT to product code, and close
the synthetic DB in `finally`. No real D1, records, services, or legal facts are used.

The file-based pre-import sentinel is installed before product initialization.
Importing the fixture alone patches nothing, and it does not import the test
runner, so it stays outside Node test discovery. The focused suite calls
`installOffline()` before its dynamic product import and registers the returned
restore/check in its own `after` hook. The acceptance launcher also preloads the
fixture with `--import` and `SP1504_OFFLINE=1`, which installs it before the
original regression suite's imports; an exit hook then restores the bindings and
fails the process if any boundary was attempted, even when the attempt was caught.
The sentinel rejects fetch, network sockets and child-process/model commands, so
bound fetch defaults cannot
capture a live implementation. The complete species-page import closure consists
of local catalogs, resolution, time, configuration and rendering; no I/O-capable
store initializer or bound live-store default exists in that closure. Page tests
pass a store-sentinel Env containing only the in-memory DB and a fixed injected
clock. Every other Env binding fails. These sentinels are process-local test
boundaries, not a hostile-code sandbox. New test globals and sentinel replacements
are restored in test finalizers; no global hooks are installed in product code.

## Acceptance mapping

The baseline defines exactly `primary regression` and `healthy control`. It runs
before any product change at the pinned base, requiring child exit 1, exactly one
semantic assertion failure identifying `A1_JURISDICTION_FALLBACK`, and the northern
parent-only healthy control passing, with no setup failures/skips. Its accepted
label is `BASELINE_GAP_REPRODUCED`, not repair success. The identical pair is part
of the focused suite; test and fixture hashes remain frozen across the repair.

Focused mode registers eight tests:

- A1: southern vermilion own plus northern rockfish parent, complete row content
  and correct group flags (the primary regression).
- Healthy control: northern parent only, complete row content and group=true.
- A2: mixed same-jurisdiction own/parent rows; regional and global own rows survive,
  southern parent alone is suppressed, northern parent survives.
- A3 parent-only: full row preservation, northern default first, regional first,
  and reversed insertion ordering.
- A3 own-only: every own row and regional ordering survive both input orders.
- A3 mixed: input-order invariance and southern, northern and null default order.
- A3 empty/unrelated/retired: no unrelated or retired rows; retired own rows must
  not suppress active/review parents.
- A4: actual species page in both languages, jurisdiction and region headings,
  four expected rule articles, exact source links, reviewed date, group qualifier,
  review-state and expired-active wording intact; suppressed parent is absent.

Regression mode executes all original `tests/test_advisor_pages.mjs` selectors
unchanged, checks their pinned hash and derives the expected test count from that
frozen source. Repository mode uses only the staged manifest's credential-scan
Python to run the unchanged `scripts/check_repository.py`; it has no interpreter
fallback. Typecheck runs the root, web and coast tsconfigs separately. Build runs
only the existing candidate-local `pnpm build`, never deployment.

From this clone's root, invoke the helper separately for each suite:

    python3 scripts/accept_sp1504_rule_jurisdictions.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp1504_rule_jurisdictions.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp1504_rule_jurisdictions.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp1504_rule_jurisdictions.py --suite repository --output ../out/author-repository
    python3 scripts/accept_sp1504_rule_jurisdictions.py --suite typecheck --output ../out/author-typecheck
    python3 scripts/accept_sp1504_rule_jurisdictions.py --suite build --output ../out/author-build

Baseline is historical evidence and is not rerun at the corrected head. Every
invocation creates a fresh uniquely named child directory, records actual child
argv/cwd/runtime, counts, exits, separate raw stdout/stderr and SHA256 hashes, and
records all versioned/authored source bytes before and after execution. Outputs
must remain under this candidate's `out`; nothing is written to fixtures. Runtime
fixtures and imports resolve relative to the clone, never to planning artifacts.
Reviewer reruns use separate fresh output arguments and preserve author receipts.
The final evidence manifest is frozen after exact-head acceptance, outside Git to
avoid circular receipt/commit identity. Historical red receipts keep their actual
old source identity rather than being relabelled as corrected-head output.

## Provenance and retained gates

Builder: actual gpt-6.1-sol, provider openai-codex, profile sol-reviewer, task
`t_d57c273b`, run 1838, under the card's explicit operator author-route admission.
All authored material in the repair commit is Sol material; unchanged upstream
files are provenance, not mixed authoring. The sole independent reviewer is actual
Claude Opus 5.5 on opus-coder-bopus. This note is self-review, not approval.

Scoped green remains REVIEW REQUIRED. Full repository Node/Python discovery,
survey/GIS skip accounting, regional/search parity, credential/privacy/link checks,
web/client/copy/token checks, dependency audit, browser/e2e checks, PR publication,
exact-head CI and release remain with the existing operator. No group is waived.
Actual browser behavior and human/legal/scientific/navigation/fish-presence
acceptance are not established by these synthetic rendering tests. No network,
source acquisition, publication, merge, hold release, service/profile alteration,
or canonical-store write is admitted by this artifact. All retained card holds
remain unchanged.
