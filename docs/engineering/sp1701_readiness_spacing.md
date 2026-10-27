# SP1701 readiness grid-spacing predicate

Spec: SP-17-v1 / SP1701-READINESS-SPACING. This is an offline candidate,
REVIEW REQUIRED, not scientific, legal, navigation, source-acquisition or release
acceptance. The pinned base is 8a805820c30895f5f037e26af9079fd3dc015b0f.

## Change and preservation

Only the candidate-resolution predicate in `src/skippercast/platform/readiness.py`
changes. Its existing nonboolean int/float check now also requires the ordered
comparison `0 < resolution <= 10`. For these numeric types the finite interval
excludes both infinities and NaN without converting integers to floats (including
integers too large for a float). No additional tolerance or lower cutoff is added.
The existing 10 m boundary remains inclusive.

Access status, inspected provenance, bounds, need IDs, sector validation, source
IDs and the all-deep native-screen exclusion are unchanged. So are input
completeness checks, thresholds, status wording and remaining promotion gates.
The one-line delta changes which impossible-resolution candidates may reach
those existing policies, not those policies themselves.

## Synthetic input closure and assertions

`tests/fixtures/sp1701_readiness_spacing/root-inputs.json` is authored synthetic
input, shaped from the complete pinned compiler's catalog/report accesses and
its existing atlas-readiness contract tests. It contains the required 19-sector
roster, 35 map-area entries, empty but complete source audit inventories, and one
otherwise-eligible grid candidate. The two required bounded deepwater survey IDs
are contract identifiers, not downloaded survey records. Timestamps, bounds,
sector IDs and source inventory contents are synthetic. There are no real source
receipts, fleet inputs or planner-algorithm slices in the fixture.

Each test materializes a fresh root outside fixture inputs and binds the actual
inventory/depth/metadata/character file hashes before compilation. It calls the
complete staged `compile_readiness` and actual JSON reader and atomic writer.
The output report is read back before assertions.

- A1: the baseline primary-regression selector excludes the 0 m grid identity.
- Healthy control: the otherwise-identical 4 m candidate remains a fine lead.
- A2: negatives, signed zero, booleans, null, text, above-boundary values and a
  huge integer are excluded. Positive integer/float 4 m, integer/float 10 m and a
  small positive spacing qualify. JSON exponent overflow exercises both
  infinities through the real JSON reader. A reader seam injects only NaN into
  the candidate for full-compiler predicate coverage: literal JSON NaN is already
  rejected by the unchanged strict parser, and that rejection has its own test.
- A3: inaccessible, uninspected, missing bounds and irrelevant-need candidates
  stay excluded; a valid all-deep 4 m source appears only in depth-excluded IDs.
  One eligible native cell preserves the fine lead instead.
- A4: the synthetic complete roster is preserved, complete reports at 4 and 10 m
  are identical, invalid spacing equals an otherwise inaccessible-source report,
  and existing public status/gate and completeness/unknown-sector checks hold.

Before product imports, scoped guards deny network/process/live-store calls and
`SKIPPERCAST_ROOT` redirects the contracts constant and bound compiler default
to the synthetic root. Product modules are loaded from this clone, then the
original module map, import path, environment and mocked functions are restored.
The test module has no irreversible import-time hooks. A peer-state test checks
restoration. This is a scoped offline regression fixture, not a hostile-code
sandbox or a qualification of unrelated model/vision tooling.

## Reproduction and retained evidence

Run from the staged clone. The standard operator `SOURCE-MANIFEST.json` must
exist next to `repo`, with the pinned repo/base identity and scanner interpreter.
No package installation or custom operator input bundle is required.

Commands (each separately):

    python3 scripts/accept_sp1701_readiness_spacing.py --phase focused --output ../out/author-focused
    python3 scripts/accept_sp1701_readiness_spacing.py --phase regression --output ../out/author-regression
    python3 scripts/accept_sp1701_readiness_spacing.py --phase repository --output ../out/author-repository
    git diff --check 8a805820c30895f5f037e26af9079fd3dc015b0f HEAD
    git status --porcelain

The focused child uses `python3 -m unittest` with the new module. The original
compatibility selector remains exactly `tests.contract.test_atlas_readiness`,
unchanged on disk. It runs alone through the launcher's file-based
`--unittest-child` bootstrap of the standard unittest module entry point. That
bootstrap adds this clone's repository and src paths before product imports;
it does not rely on the shared venv's editable package pointing to another
checkout, change installed packages, or set an environment import-path override.
Its actual script argv, not a fictitious literal `-m` subprocess, is retained in
the receipt. A fresh-process offline audit sentinel precedes imports, and the
original suite's fixture-owned temporary lifecycle inherits its output root.

Repository phase executes unchanged `scripts/check_repository.py` with the
manifest's `runtime.credential_scan_python3`. It is the specified repository
privacy/link/fixture scan, not a full-repository test-suite or dependency audit.
This Python-only card does not claim Node typecheck/build results.

Every phase creates a unique UTC/UUID output child, preserving exact cwd, argv,
source identity and owned-file hashes, exit, actual unittest/scan counts, zero-skip
checks and raw stdout/stderr hashes. Green receipts on the final signed head
live outside the git tree; reviewer reruns must use separate output roots.

Historical baseline: signed test-only head
`43d0743e06d5ac75e788052493896066200e8e57`, product byte-for-byte at base.
The frozen baseline selectors run separately and retain A1's exact semantic
assertion failure (one test, exit 1) plus the healthy control (one test, exit 0).
The diagnostic phase itself exits 0 only when that exact red/green contract
holds. Its durable receipt is under
`out/author-baseline/20261025T160134-ef520fb8cb954cd0be6103f65a57cb31/receipt.json`
relative to the candidate root. Its SHA256 is
`367d09634281d6caa60e6c89539bcbaf4c9bea3f15c7b9e616449d8789661e1f`.
Baseline mode intentionally refuses the repaired product. Do not rerun baseline
against final HEAD, rewrite its historical identity, or weaken the assertion.
The identical frozen test file is exercised green by final focused acceptance.

Two earlier preflight defects and their receipts are retained, not resealed:

- `out/author-focused/20261025T160051-9dcf5453591d4b84b3b9ddd480dc0b25`:
  the overflow-input replacement expected decimal notation instead of JSON's
  exponent spelling. The test now derives the original token via `json.dumps`;
  assertions remain unchanged. The product was returned to its pinned bytes,
  the corrected tests committed and the frozen pair re-baselined before repair.
- `out/author-regression/20261025T160148-9a43d9492b034a309067429fdc49ae5f`:
  the file bootstrap initially omitted the repo root from its import path. The
  original module did not import. Adding the clone root fixed the harness;
  neither original tests nor the shared environment were changed.

Earlier preflight green and red receipts remain historical, with their own
source hashes. Only final-head green receipts support the review request.

## Authorship and remaining owners

All material commits for this candidate are authored by actual gpt-6.1-sol /
openai-codex on sol-reviewer (run 2293) and signed off. Luna authored no candidate
material. The operator's latest same-card admission assigns actual Claude Opus
5.5 on opus-coder-bopus as sole independent reviewer. Self-review is not approval.

PR publication, required full-repository/exact-head CI, dependency audit,
regional/search parity, browser/e2e and other existing release gates remain OWED
to the operator and normal CI surfaces. This candidate neither executes nor
waives them. No push, merge, network acquisition, deploy, credential/service
change or hold lift is supplied. All source/live/bulk-download, public-viewer,
legal-preview, terrain-mask, SC#1/PR846 and SC-5b holds remain in force.
