# Chop-period completeness (SP-15-v1 / SP1501-CHOP-COMPLETENESS)

## Bounded behavior

`web/score.ts` now requires a finite wind-chop period for `rateComfort`'s
full-detail path. Null, omitted, undefined, NaN and either infinity follow the
existing wind-and-combined-seas limited computation: `limited=true`, score at
most `THRESHOLDS.capLimited` (6.9), unknown chop represented by null, and no
invented short-chop charge. A directly invoked `comfortCosts` likewise charges
short chop only for a finite observed period. No threshold, boat factor,
complete-input arithmetic, window rule or forecast-domain rule is retuned.
Finite zero/negative periods retain their previous behavior; validating their
physical domain is outside this frozen missing/non-finite-period scope.

The complete unchanged `briefVerdict` consumer already propagates
`rating.limited` as partial forecast detail. Its Comfortable-to-Marginal hold,
marine advisory precedence and hazardous-bar hold need no product edits.
This is a comfort heuristic, not navigation, scientific or safety clearance.

## Producer-shaped synthetic coverage

The fixture `tests/fixtures/sp1501_chop_completeness/calm.json` contains invented
FeedHour values and a fixed clock. The new test constructs complete
ConditionsForecast model runs following `web/brief/verdict.ts` and the unchanged
`tests/test_brief_verdict.mjs`; actual complete modules are imported from this
clone, never copied planner implementations.

Acceptance mapping in `tests/test_sp1501_chop_completeness.mjs`:

- A1: `primary regression` checks null period yields limited 6.9; missing and
  undefined cases are also exercised. `healthy control` is the same calm feed
  with period 8 and remains complete at 10.
- A2: NaN and both infinities are limited; strong wind can still yield 0.
- A3: one-foot chop with valid periods 8, 6 and 4 retains scores 9.5, 8.7 and
  8.7, with the short penalty present only at or below the existing cutoff.
  Absent/non-finite periods use the limited path, and direct cost calls cannot
  invent zero-second waves.
- A4: the full `briefVerdict` and `feedReader` path tests complete, all-partial
  and mixed-hour forecasts, plus advisory, missing-alert-check and bar-hazard
  precedence for complete and partial data.
- A seventh test verifies the pre-import network/model/process/live-store
  sentinels. They allow only read-only regular source/fixture files resolving
  inside this clone for the Node ESM loader, deny writes and outside reads,
  and restore mocks after the dedicated test process. No database or live-store
  client belongs to the imported pure dependency closure. These application
  sentinels are not a hostile-code security sandbox.

## Baseline and retained history

Base: `8a805820c30895f5f037e26af9079fd3dc015b0f`.
Original score SHA256:
`51753eec1d0b5a6e3556f89ca5071496b013ae097938b835ecfdddc2e388d0f0`.

Run 1843's first harness failed at import because its openSync guard blocked
Node's loader. That FAILED_UNVERIFIED receipt remains under candidate
`out/author-baseline`; it is not semantic gap evidence or repair success.
The operator's standing admission/unblock permitted the bounded harness fix.
Run 1969 then reproduced the actual defect on unchanged product bytes under
`out/author-baseline-corrected/20261025T130037-2bbb78474cf74274b5daa0ed5fda0cdc`:
launcher exit 0, child exit 1, exactly two tests, primary semantic assertion
failed (actual complete 10 versus required limited 6.9), healthy control passed,
zero setup errors/skips. Label: BASELINE_GAP_REPRODUCED.

During static self-review, the separate strong-wind fixture was aligned with
the original score test's 35 kt / 45 kt gale control (without changing its
zero-score assertion or either primary/control test). The final test file was
then re-frozen by a fresh qualifying baseline on the original product bytes:
`out/author-baseline-frozen/20261025T130305-eb4cb08e3b42475eac669fad6e394ea7`.
It also returned BASELINE_GAP_REPRODUCED with exactly the same two semantic
results and zero skips; earlier receipts remain unchanged.

Frozen baseline test SHA256:
`5b1d600ad364aca67783db0fb8780f05620a9b5bea621c316f8895b4e47ea8dd`.
Frozen fixture SHA256:
`ebdd92280e4f8cd2d03158b5738c010b28eda571cd5d5b1a59b4304195c7de85`.
They are held identical for post-fix focused execution.

## Portable acceptance and evidence

From this repository root, invoke the file-based launcher with Python 3:

    python3 scripts/accept_sp1501_chop_completeness.py --suite focused --output ../out/author-focused

Other suite values: `baseline`, `regression`, `repository`, `typecheck`, `build`.
Baseline is exclusively for the unchanged pinned product, and registers only
the identical primary/control pair. Focused registers all seven tests with no
skips. Regression executes both original selectors unchanged, 12 tests each
(including 150 golden score cases in the original score test).

Repository mode uses the operator SOURCE-MANIFEST.json credential-scan Python
and checks its installed dependency before running unchanged check_repository.
There is no system-Python fallback. Typecheck runs three separate installed
pnpm/tsc commands for root, web and coast configs. Build runs the existing
local pnpm build, never a deploy. No dependencies are installed.

Every invocation creates a unique child directory and preserves separate raw
stdout/stderr, argv, cwd, runtime version, elapsed time, exit, selected counts,
source identity and SHA256s in receipt.json. Paths in committed deliverables
are derived from the script/clone, not a machine-specific home or live default.
After the signed-off final commit, rerun every green suite, then use `--suite
seal --output ../out/author-seal` to freeze all completed historical output hashes
and exact-head green evidence. A reviewer uses a separate `reviewer-*` output
root and does not rerun seal or change authored receipts/manifests.

Actual material author: gpt-6.1-sol / openai-codex, sol-reviewer runs 1843 and
1969. The final signed-off material commit is authored in run 1969. The sole
independent same-card reviewer is Claude Opus 5.5 on opus-coder-bopus, as admitted
on the card. Machine-valid scoped output is REVIEW REQUIRED, not full-release
or semantic acceptance.

## Retained gates

Only score.ts and this card's test, synthetic fixture, launcher and note change.
All original tests, dependencies, catalogs, real data and other product files
remain read-only. Full repository Node/Python discovery, survey/GIS skip
accounting, regional/search parity, credential/privacy/link checks,
web/client/copy/token checks, dependency audit, browser/e2e and exact-head CI
remain operator-owned OWED gates; the repository scan and scoped regressions
are not substitutes. No source acquisition, network/model request, publication,
push, merge, deployment or hold release is authorized by this offline candidate.
Existing human/legal and source/live holds remain with their owners.
