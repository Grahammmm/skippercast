# Scoped regulation coverage assessment (SP-18-v1)

SP1808-REG-SCOPE-STATUS is an additive reporting change to
`skippercast.pipeline.regulation_review.coverage`, not a legal decision or a
change to collection, fingerprints, source decisions, or approval gates.

## Contract

Only when `source_scope_ids` is not `None`, each species and area row adds:

- `out_of_scope_sources`: omitted dependencies in original dependency order.
- `assessment_status`: `not-evaluated` if all nonempty dependencies are omitted,
  `partial` if some are omitted, or `evaluated` if none are omitted.

An empty dependency list is evaluated with an empty omitted list. The existing
real snapshot rejects empty species dependencies; this patch preserves that
validation. Empty area dependencies exercise the valid empty-row behavior.
An empty scope is different from no scope: it omits every source. Unknown scope
IDs still fail through the unchanged real snapshot.

Evaluated means checked, not passed, approved, current law, clearance, or
permission to fish. Changed, unavailable, unreviewed, identity-mismatched and
normalization-mismatched sources can all be evaluated and still require review.
The legacy `required_sources` and `issues` lists retain their exact values and
ordering, including out-of-scope issues. Unscoped report shape and values are
unchanged. `review_required`, snapshot checks, jurisdiction/date fields and area
`live_clearance_required` remain unchanged. Inputs are not mutated.

## Test-first evidence and acceptance

The synthetic fixture follows the registry and receipt shapes used by the real
snapshot and existing contract suites. It contains no real legal records.
The tests import complete real modules, not slices or copied algorithms.
The primary regression first validates healthy prerequisites, then fails at
`A1_MISSING_SCOPED_ASSESSMENT` on the unchanged pinned product. The independent
healthy control verifies exact unscoped row shapes, including a failed source.
The baseline launcher exits zero only for that specific assertion failure plus
the passing control; its receipt retains the original child exit one.

Run from the repository root, using a fresh output location outside the repo:

    python3 scripts/accept_sp1808_reg_scope_status.py --phase baseline --output ../out/author-baseline
    python3 scripts/accept_sp1808_reg_scope_status.py --phase focused --output ../out/author-focused
    python3 scripts/accept_sp1808_reg_scope_status.py --phase regression --output ../out/author-regression
    python3 scripts/accept_sp1808_reg_scope_status.py --phase repository --output ../out/author-repository

Baseline is only for the unchanged pinned product; do not rerun it against the
repair and mislabel the result. Preserve the original red evidence separately.
Every invocation creates a unique output child and records source hashes/HEAD,
actual argv/cwd, runtime, exits, counts and raw stdout/stderr SHA256s. The focused
phase runs the identical frozen pair green and all five focused test methods;
A2 additionally checks five real failure statuses using subtests.
Regression runs each unchanged compatibility suite separately. The bootstrap
uses the staged `.venv/bin/python3`, anchors imports to this repo, guards sockets,
subprocesses and filesystem access before product imports, and redirects the
repository root before constants and function defaults bind. Audit hooks are
confined to fresh acceptance child processes; test discovery installs none.
Scoped socket/default patches restore on exit. The old pure review-gate tests
remain enabled; no collect/apply CLI or operational action is executed.

Repository acceptance uses the standard source manifest's admitted scanner
runtime to execute the unchanged repository checker. It separately executes
three `pnpm exec tsc --noEmit --project` invocations and the existing local
`pnpm build`, never deploys or installs. No shared runtime link is modified.
Normal build products stay in the candidate clone. No external source fetches
or model calls are part of this acceptance.

## Authorship, scope and release limits

Base: `67ff9bcf34257698a41585bc2ad163171dc68259`.
Material author: actual `gpt-6.1-sol` high, provider `openai-codex`,
profile `sol-reviewer`, kanban run 2156. All material commits are signed off.
The first commit contains tests, launcher and fixture before product changes;
the subsequent commit contains the additive implementation and this note.

The original baseline receipt is retained outside the repository under the
candidate's `out/author-baseline` directory. Final exact-head acceptance and the
handoff inventory are likewise retained under `out`, not fixture inputs.
Reviewer reruns must use separate fresh output roots and preserve that evidence.

Scoped pass means REVIEW REQUIRED only. Sole independent reviewer for this
Sol-authored material is actual Claude Opus 5.5 on `opus-coder-bopus`.
Operator publication, full-repository gates, exact-head CI and release remain
owed. This offline change supplies no scientific, legal, navigational, source,
live-run, download, publication, terrain-mask or other hold release.
