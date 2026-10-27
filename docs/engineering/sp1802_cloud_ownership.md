# SP1802 cloud overlay ownership

Acceptance: SP-18-v1 / SP1802-CLOUD-OWNERSHIP / amendment 1.
Base: `67ff9bcf34257698a41585bc2ad163171dc68259`.
Material author: actual `gpt-6.1-sol` / `openai-codex` on `sol-reviewer`.
Sole independent reviewer: actual Claude Opus 5.5 on `opus-coder-bopus`.
This is a bounded offline candidate, REVIEW REQUIRED, not release approval.

## Behavior and scope

`createClouds` already retained the engine on which it last drew. It now clears
that engine's `clouds` overlay before drawing on a replacement, clears it when
the engine becomes null, and clears it on destroy. The shared cleanup resets
the drawn overlay, engine identity and exported layer IDs. The existing alive
check and disposers still prevent late index replies from repainting and make
repeated destroy inert. Only the controller's `clouds` registry entry is removed;
unrelated overlays are not changed.

No change to fetch/index policy, timing, frame age, frame selection, opacity,
reduced motion or the viewer's loop hold. No source acquisition or deployed
incidence claim. The recording engines are inert; the compatibility suite also
exercises the real engine with a fake MapLibre implementation, and renders the
legend/rail with the installed Preact renderer.

Operator disposition on task `t_3ab22572` at 08:44 PDT, refrozen before edits:
previously the compatibility test required the retired engine's last frame to
remain visible after A -> null. That conflicts with required removal. The only
compatibility edit removes that obsolete assertion; neighboring no-label and
no-step assertions, and every other original compatibility assertion, remain.
New A2 coverage explicitly requires no residual cloud sources/layers after the
null transition. No other existing test/helper is changed.

## Test-first evidence and assertion map

The fixture is synthetic FE-44 `goes-times.json` / CloudImage-shaped data, based
on the original compatibility fixture shape. It is never downloaded or mutated.
Tests dynamically import the full real product modules with installed signals;
there are no source slices, copied algorithms or planner runtime dependencies.

Before product edits, baseline required exactly one A1 assertion failure with
ID `SP1802_A1_RETIRED_OWNER_NOT_CLEARED`, child exit 1, and a separate healthy
control with child exit 0. The launcher returned `BASELINE_GAP_REPRODUCED`, not
repair success. These original receipts are retained under the candidate's
`out/author-baseline/baseline-2vv7i8ov/` directory, with their original base and
source hashes. The tests/fixture/launcher were then signed off in test-first
commit `2b083db7` before changing the product.

The unchanged tests and fixture are used for candidate green runs:

- A1: healthy draw on A; cleanup of A precedes exactly one draw on B; current IDs.
- Healthy control: exactly one healthy overlay draw; all timers/listeners clear.
- A2: A -> null -> B and engine reuse, empty retired ownership and unrelated
  overlay preservation; repeated null is inert.
- A3: active owner teardown, label/rail/IDs reset, double destroy inert,
  timers/listeners gone; pending index resolution after destroy cannot repaint.
- A4: full controller with real signals, recorded opacity, exact loop durations,
  hold across replacement, hidden page, reduced motion and off/on restoration.
- Original compatibility: ten cases including frame age/index refresh, day and
  presentation gates, actual engine removal and rendered legend/rail.

## Reproduce from the staged repository

The only non-repository input is the operator's automatically staged
`../SOURCE-MANIFEST.json`, schema `agentorange.source-manifest/v1`, matching the
repo/base/card. Standard installed runtime links remain read-only. The launcher
uses its explicitly supplied `runtime.credential_scan_python3` for the unchanged
repository checker, never a scanner fallback. All paths derive from this repo
and manifest; planning files and another candidate are not runtime dependencies.

Run each command separately from the staged repo. `--output` must be beneath
its sibling `out` directory; every invocation creates a unique retained child.
Baseline runs only on the original pinned product source and base HEAD, with
these tests present; do not reset the finished candidate to replay it.

```text
python3 scripts/accept_sp1802_cloud_ownership.py --phase baseline --output ../out/author-baseline
python3 scripts/accept_sp1802_cloud_ownership.py --phase focused --output ../out/author-focused
python3 scripts/accept_sp1802_cloud_ownership.py --phase regression --output ../out/author-regression
python3 scripts/accept_sp1802_cloud_ownership.py --phase repository --output ../out/author-repository
python3 scripts/accept_sp1802_cloud_ownership.py --phase typecheck --output ../out/author-typecheck
python3 scripts/accept_sp1802_cloud_ownership.py --phase build --output ../out/author-build
git diff --check 67ff9bcf34257698a41585bc2ad163171dc68259 HEAD
git status --porcelain
```

Focused runs the identical baseline pair green (one test each), then all six
focused tests. Regression runs the ten compatibility tests separately. Node
suites require positive exact counts and zero skips/cancellations/todos.
Typecheck invokes three separate `pnpm exec tsc --noEmit --project` children
for root, web and coast projects. Build invokes only local `pnpm build`.

For Node tests, a pre-import `?guard` mode installs external fetch/socket
sentinels before product evaluation, including compatibility module imports.
Controller options explicitly bind synthetic fetch, page, clock, document,
motion, reported data and engine rather than using live defaults. Tests restore
browser globals and timer mocks after each case; sentinel restoration is scoped
to the new suite's process. Compatibility guard mode lives only for its isolated
child process. No model, DB, live store or real map is used. Compatibility
temporary renderer outputs use a unique evidence-owned `TMPDIR`.

Each `receipt.json` retains source before/after identity, source/fixture/test
hashes, exact child argv/cwd, installed Node version, launcher Python runtime,
elapsed time, child exit, counts and raw stdout/stderr hashes. Exit-zero
non-test commands are recorded as command invocations, not invented tests.
The final handoff outside the repo binds final green receipts to the full
signed-off head with clean status and preserves baseline red evidence separately.
Reviewer reruns must use separate output roots and never overwrite evidence.

## Limits and remaining owners

The local build emits non-fatal dynamic-import and chunk-size warnings; they
are retained in raw stderr, not suppressed. Scoped checks do not qualify the
whole repository, public site, scientific/legal/navigation claims or live data.
Operator publication, final independent review, exact-head CI, full-repository
Python/Node and GIS skip accounting, browser/e2e, dependency audit and all other
release gates remain OWED. Existing source/live/bulk-download, legal-preview,
public-viewer, terrain-mask, SC1/PR846, PR816 and SC-5b holds remain intact.
No push, merge, publication, deployment, credential/service change or hold lift
is supplied by this candidate or its machine-valid receipts.
