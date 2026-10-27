# SP1408: retain the supplied lookalike rule

Spec: SP-14-v1. Base: 33734f90073a2150eac5a418564ea314c4a591ac.
Material author: gpt-6.1-sol / openai-codex, sol-reviewer, task t_df4e2d93,
run 1810. Sole independent reviewer: actual Claude Opus 5.5 on opus-coder-bopus.
This is a bounded offline candidate, not release or legal acceptance.

## Change and compatibility

`server/advisor/answers/fishid.ts` no longer returns early from `rulesText`
when the top candidate has no rule row. It appends the existing no-rule caveat
and its top-species link, then the already-supplied second rule sentence.
No new rule lookup, candidate, threshold, translation or legal inference is
introduced. No second rule still produces byte-identical text. A current top
still has its original rules/second/double-check sequence. A stale top still
places the second sentence before its stale caveat. All cases have one existing
rules link, not a second added link. A stale second uses existing stale wording
without numerical limits. Null top keys still take the existing generic-link
branch in `answerFor`, including the pre-existing second_rules metadata that
is not displayed there. Unknown nonnull keys use the regular no-rule branch.

## Acceptance mapping

The committed test is `tests/test_sp1408_lookalike_rule.mjs`.
All new inputs and file-based bootstrapping are under
`tests/fixtures/sp1408_lookalike_rule/`. `spec.json` pins the acceptance version;
`cases.json` contains synthetic FishId candidates, row defaults and literal
English/Spanish expected full reply text. No planner code or live data is imported.

- A1/A4: `primary regression` asserts complete English and Spanish `answerFor`
  replies for a missing top rule plus a current second bag-zero rule, including
  caveat, link, no-take sentence and unchanged source provenance.
- A4/control and A2/current behavior: `healthy control` asserts complete replies
  for a current top plus the same distinct current lookalike row and the
  double-check link. These are the only two registered baseline tests; there
  is no name filter hiding skips. Both run unchanged in focused mode.
- A2: `A2 stale second never quotes numeric limits` tests review-status and
  overdue-active rows in both languages, preserving existing stale wording;
  `A2 missing second keeps unchanged no-rule reply` checks complete text.
- A3: `A3 null top key keeps generic no-rule branch` preserves the generic
  link and pre-existing undisplayed metadata. The primary also covers an
  unknown nonnull key.
- A3: `A3 one candidate high and ask do not widen selection` covers one
  candidate, high at 0.85, ask at 0.599, needs-better-photo and empty candidates.
- A3: `A3 identical rules and same species suppress second sentence` preserves
  equality and duplicate-key suppression in both languages.
- A3: `A3 protected warning precedes caveat and lookalike rule` covers yelloweye
  at 0.3 and 0.299, plus a third protected candidate that never becomes the
  displayed second rule. No new protected-species conclusion is made.
- A2/compatibility: `A2 stale top keeps second before stale caveat with one link`
  preserves prior stale-top ordering.

The selected unchanged original tests are `tests/test_advisor_fishid.mjs` and
`tests/test_advisor_rules.mjs`. Their bytes are checked against the pinned base
before every acceptance invocation. They execute their existing recorded API
fakes, migration-backed in-memory SQLite and fixture-owned temporary cleanup;
no model, real photo or live database is used.

## Safety and portability

A file-based preload installs fetch/socket/subprocess sentinels before product
imports and their bound defaults. SQLite is restricted to `:memory:`. Focused
storage writes are refused. Original regression importer cleanup is allowed only
inside its invocation-owned temporary root; existing/shared links are unchanged.
New tests inject synthetic region globals before importing the complete public
module and restore globals between cases. Node's installed native TypeScript
stripping is used; no source extraction, inline interpreter source or dependency
installation is needed. This safety harness is not a hostile-code sandbox.

The Python launcher uses stdlib, derives paths from its own location and checks
fixture/output ancestry. Output must be a child of candidate `out`; each call
creates a fresh UUID directory. It verifies the staged source manifest and uses
its literal credential-scan interpreter, with no fallback to system Python.
Repository paths and committed inputs contain no machine-home dependencies.
The only machine-specific interpreter input is the operator's external staged
SOURCE-MANIFEST.json. No operator bundle or new package is required.

From the repo root, invoke `python3 scripts/accept_sp1408_lookalike_rule.py`
with `--suite MODE --output ../out/author-MODE`, separately for each mode.
Modes are baseline, focused, regression, repository, typecheck and build.
Baseline is only valid on the pinned untouched product and must not be rerun on
the fixed candidate. Reviewer runs use distinct `../out/reviewer-MODE` roots.
The launcher records exact argv, cwd, actual runtime, exits, TAP names/counts,
stdout/stderr bytes and hashes, source/spec/test/fixture hashes, actual HEAD,
material-author provenance and commit trailers. It does not reseal prior runs.

The original baseline receipt is retained at candidate-relative
`out/author-baseline/20261025T102719275833Z-401da08294ec45089548d9c63b52e88e/receipt.json`.
It records child exit 1, exactly `primary regression` failing with
`SP1408_PRIMARY_SEMANTIC_MISMATCH_en` / ERR_ASSERTION, `healthy control` passing,
and zero skips/cancellations/todos. The complete unchanged module returned the
caveat but omitted the supplied second sentence. The launcher reports
BASELINE_GAP_REPRODUCED, never a fix pass. There was no product exception or
setup failure to capture. Test/fixture hashes are retained in that historical
receipt and remain frozen for final focused execution. A later launcher-only
correction derives original-suite counts from verified unchanged original test
registrations rather than an initial guessed count; baseline evidence is not
rewritten. Scoped precommit execution passed 9 focused and 27 original tests;
exact signed-off-HEAD reruns and their frozen manifest are the handoff evidence.

## Remaining ownership

Scoped green means REVIEW REQUIRED, not semantic or whole-repository acceptance.
The existing operator owns PR publication before final code review, unchanged
local full-suite execution and required CI at the exact head. Full Node discovery,
Python non-GIS, strict survey/GIS skip accounting, regional/search parity,
credential/public-tree/link/privacy, web/client/copy/token checks, typecheck/build,
dependency audit and browser/e2e remain owed on their admitted surfaces. This
worker's selected tests do not waive those groups. No PR, network/model call,
source download, deployment, merge, source/live hold release, legal/scientific
acceptance or canonical data change is authorized. All existing protected and
bulk-download holds remain in force.
