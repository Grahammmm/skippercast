# Sheet pointer ownership (SP-17-v1)

Scope: SP1710-SHEET-POINTER-OWNER. Only the initiating pointer may move,
finish or cancel an active sheet gesture. Additional downs (including a
repeated owner down) are ignored until the owner releases or cancels.
The existing drag math, detents, button click/keyboard behavior and temporary
style cleanup remain unchanged.

## Test-first evidence

The frozen regression test renders the complete staged Sheet component using
the installed Preact hooks and preact-render-to-string. A temporary Preact
vnode observer captures the actual rendered handle's event props. Synthetic
sheet/handle elements supply height, computed translation and pointer capture;
no copied handler text or planner snapshot is executed. The observer and all
global replacements are restored. Network/model/browser-storage sentinels are
installed before product import. Sheet has no live-store or I/O constants to
redirect. Generated bundles use the inherited temporary directory, never the
fixture input directory. The JSON fixture contains only synthetic gestures.

A1 is the frozen primary regression: pointer 1 starts at 300, moves to 220,
pointer 2 presses at 600, and pointer 1 releases at 220. The expected detent is
half. The unchanged pinned product selects full (ERR_ASSERTION). The separately
registered healthy control selects half and clears styles. The same immutable
test file/fixture pair is run after the repair. Baseline receipt identity is
historical, not rewritten as evidence for a later head.

Coverage:

- A1: interleaved down cannot replace the owner's origin or capture pointer 2.
- Healthy control: ordinary drag, style reset and one-click suppression.
- A2: foreign move/up/cancel each leave styles, commit and capture unchanged;
  the owner subsequently finishes. Repeated owner down is ignored too.
- A3: cancellation abandons without commit, clears styles, ignores stale events,
  and admits a fresh pointer drag/tap; stale cancel cannot swallow or unsuppress
  the wrong gesture's click.
- A4: signed thresholds just below/at minimum and at/above far threshold,
  clamped translation, both tap boundaries, all click-cycle detents, supported
  keyboard actions and ignored keys/non-primary button.

This is a rendered-component inert-element harness, not browser/e2e evidence.
Capture calls and subsequent gesture availability are checked. Actual browser
implicit capture release and native Enter/Space click synthesis remain browser
obligations; this test does not pretend to implement or qualify the browser.

## Offline acceptance

Run from the repository root:

    python3 scripts/accept_sp1710_sheet_pointer_owner.py --phase baseline --output ../out/author-baseline
    python3 scripts/accept_sp1710_sheet_pointer_owner.py --phase focused --output ../out/author-focused
    python3 scripts/accept_sp1710_sheet_pointer_owner.py --phase regression --output ../out/author-regression
    python3 scripts/accept_sp1710_sheet_pointer_owner.py --phase repository --output ../out/author-repository
    python3 scripts/accept_sp1710_sheet_pointer_owner.py --phase typecheck --output ../out/author-typecheck
    python3 scripts/accept_sp1710_sheet_pointer_owner.py --phase build --output ../out/author-build

Baseline must be run BEFORE modifying the pinned Sheet source. It requires
primary exit 1 with the named assertion (full versus half), and control exit 0,
with one executed test each and zero skips/cancellations/todos. Focused repeats
that exact pair green, then executes all five registered tests (A1-A4 plus
control). Regression executes all 15 original app-shell tests unchanged.
Repository invokes the unchanged repository checker using the standard staging
manifest's full-suite credential-scan interpreter. Typecheck executes three
separate project invocations; build executes the existing local pnpm build.
No phase installs, downloads or deploys anything.

The runner validates the adjacent standard SOURCE-MANIFEST.json stage identity
and creates a unique evidence child for each invocation. Receipts retain argv,
cwd, runtime paths, selectors, source hashes/status/head, child exits, exact TAP
counts or repository text-file counts, and raw stdout/stderr paths and SHA256.
A failed child fails the phase explicitly; acceptance does not rely on Python
asserts. The committed code derives paths from its own clone. The operator
manifest supplies installed tool paths, not a custom input bundle. Reviewers
must use separate output roots, leaving author receipts unchanged.

## Provenance and retained gates

Base: 8a805820c30895f5f037e26af9079fd3dc015b0f.
Material author for this card's signed commits: gpt-6.1-sol, provider
openai-codex, profile sol-reviewer, kanban run 2097. This is the explicitly
admitted Sol builder route, not a self-review. Sole independent reviewer:
Claude Opus 5.5 on opus-coder-bopus.

Scoped offline success is REVIEW REQUIRED. Operator PR/publication and
full-repository/exact-head CI remain OWED, including discovery, dependency
audit and browser/e2e gates. No source/live hold, public-viewer, legal-preview,
terrain-mask, SC#1/PR846 or SC-5b hold is released. No scientific, legal,
navigation or fish-presence acceptance is supplied. No worker push/merge,
service/configuration change or outbound communication is admitted here.
