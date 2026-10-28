# Terminal discovery-sector endpoint counts

Spec: SP-18-v1 / SP1807-SECTOR-ENDPOINT. Offline candidate only.
Base: 67ff9bcf34257698a41585bc2ad163171dc68259.
Author: actual gpt-6.1-sol, provider openai-codex, profile sol-reviewer,
kanban run 2161. This is authored implementation and self-review, not independent
approval. Sole independent reviewer: actual Claude Opus 5.5 on opus-coder-bopus.

## Rule

Internal latitude bands remain south-inclusive and north-exclusive. Only a
coast's terminal band may include its exact north endpoint. That endpoint stays
with an existing half-open northern sector when that sector includes the same
package, covers the point's longitude, and passes the existing strict package
bounding-box overlap rule. The lookup is independent of catalog ordering.
Interior points, including unrelated overlapping coast interiors, are not
otherwise deduplicated. No epsilon, rounding or geographic expansion is used.
The original package-overlap filter still applies to the southern sector too.
Metadata, order, discovery status and the legal/scientific disclaimer stay intact.

## Test and fixture closure

The JSON scenario projects the actual consumed field shapes of the coastal
sector catalog, coast catalog, published-region index, region assets mapping and
atlas target list. It is synthetic and is not a complete publishable regional
package. URLs under example.org are inert strings, never source acquisition.
The full staged compiler and contracts are imported, not copied or sliced.

BaselineTests.test_primary_regression is A1: counts [1, 2] for targets at
34, 35 and 36. BaselineTests.test_healthy_control isolates south-edge and internal
seam ownership. The exact baseline failure is retained as
BASELINE_GAP_REPRODUCED with child exit 1, not a repaired or shipping success.
The same pair is included in the green focused suite.

FocusedTests maps A1 to count/metadata assertions, A2 to exact binary-float
neighbors and longitude edges, A3 to shared-owner, reordered, missing-package,
longitude-ineligible and package-overlap cases, and A4 to one-band edges and
unchanged validation failures. The unrelated-interior positive prevents broad
deduplication. All assertions are explicit; no skips are used.

Test patches are scoped with ExitStack. Socket/DNS and child-process sentinels
precede product imports. Compiler constants and its bound root default are
redirected before use; compiler reads/writes are confined to fixture-owned
unique temporary trees. contracts has no import-time I/O; its other defaults
remain anchored to the staged checkout, not a fixture that later disappears.
Direct discovery and cached-module use restore ambient globals and defaults.
Temporary fixture cleanup is not retained-evidence cleanup authority.

The unchanged compatibility file tests/contract/test_coastal_sectors.py runs in
a dedicated child. Its committed static catalog/config/atlas closure is copied
to that child's evidence work tree; both its ROOT and the compiler's constant
and bound default are redirected before test import. All old writes and
TemporaryDirectory lifetimes remain fixture-owned. No live records are read.

## Portable acceptance

Only standard staging is required: this checkout, its shared read-only .venv and
node_modules links and the adjacent SOURCE-MANIFEST.json. No planning directory
or other candidate is imported. Each invocation creates a fresh child under its
output argument. From the repository cwd, run each phase separately:

    python3 scripts/accept_sp1807_sector_endpoint.py --phase baseline --output ../out/author-baseline
    python3 scripts/accept_sp1807_sector_endpoint.py --phase focused --output ../out/author-focused
    python3 scripts/accept_sp1807_sector_endpoint.py --phase regression --output ../out/author-regression
    python3 scripts/accept_sp1807_sector_endpoint.py --phase repository --output ../out/author-repository

Baseline is only for unchanged pinned product bytes. Do not run it expecting a
red result from the repaired HEAD. Preserve baseline receipts; reviewer green
reruns use reviewer-specific output roots. A baseline source replay must retain
the candidate separately and restore it, without amending saved receipts.

The launcher validates manifest identity and uses the staged .venv interpreter
for test children, an explicit script bootstrap anchoring sys.path before
imports, checked unittest results, positive counts and zero skips. Repository
checks use the manifest's credential_scan_python3, never a silent substitute.
Typechecks are three separate pnpm exec tsc --noEmit --project invocations, then
pnpm build (local assets only). Build dependencies are already installed; no
install, download or deploy is admitted. The existing build replaces its own
candidate-local build outputs, not source or retained receipts.

Receipts record exact HEAD and source/test/fixture hashes, argv, cwd, runtime,
child exit/count, elapsed time and raw stdout/stderr paths and SHA256 hashes.
The final green phases must run on the signed-off, clean frozen HEAD. A source
change during a phase fails that phase. Typecheck/build are compiler/build
checks, not invented unit-test counts.

## Limits and ownership

SCOPED_PASS_REVIEW_REQUIRED is not independent approval, full-repository CI,
scientific/legal/navigation acceptance or evidence of current fish presence.
Operator owns PR publication before final code review, the remaining complete
Python/Node discovery and GIS skip accounting, regional/search parity,
credential/privacy/link, client/copy/token, dependency-audit and browser/e2e
release gates and exact-head required CI. Those gates remain OWED unless their
owner supplies exact-head evidence; these scoped checks do not replace them.
No push, merge, extra deploy, service change, source acquisition, bulk download,
outbound communication or hold release is supplied. All existing holds remain.
