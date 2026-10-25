# Offline chart inventory presentation (SP1502-PACK-INVENTORY)

Spec: SP-15-v1. Admitted base: `8a805820c30895f5f037e26af9079fd3dc015b0f`.
This is an offline implementation proposal, not release or navigation acceptance.

## Behavior and scope

`ChartPack` in `web/app/Trip.tsx` keeps enumeration loading/success/error
separate from its last successfully read listing. Initial rejection says:
“Saved regions could not be checked. Offline storage may be unavailable.”
Only a successful empty enumeration says “Nothing saved on this device yet.”
An error or pending refresh retains the last successful rows, when present,
with “Last checked listing; not rechecked.” A subsequent successful response
replaces that listing, including clearing it for an empty result. An increasing
request identity prevents either a stale fulfillment or rejection from changing
the newest inventory result. Effect cleanup invalidates the pending request.

No storage, downloads, pack format, deletion, coastal-readings, or planner
implementation is changed. The existing save/delete callbacks still request
an inventory refresh; tests substitute synthetic callbacks and storage only.
The existing `listPacks` API is the boundary: a resolved empty result is treated
as empty, including its existing absent-CacheStorage fallback. This card does
not change that API or claim browser CacheStorage integration qualification.

## Synthetic producer-shaped fixtures and execution boundary

The new test bundles the complete real `Trip.tsx`, its unchanged pure
`dist/offline-core.js`, installed Preact JSX, and installed
`preact-render-to-string`. It imports the real exported `Trip`, not an extracted
function or replacement implementation. The bundle's metafile is checked to
exclude unadmitted product imports. I/O-capable imports (trip actions, app/state,
PortDialog) are redirected before module execution. Deterministic injected hooks
provide state slots, refs and effect scheduling; public button callbacks exercise
refresh after synthetic save/delete. Test globals are restored after each test.
Network/model fetch, browser networking and live-store sentinels precede import.
The bundle is written to a fresh directory under this candidate's `out`, never
fixtures. The original regression selectors run unchanged in separate Node test
processes with the file-based pre-import offline guard.

`packs.json` follows the metadata producer in `dist/offline-pack.js` and the
`web/trip.ts` v2 extras/PackMeta interface: schema version, synthetic region/cache
identity, saved time, byte count, files, tiles, missing items, and optional v2
shell/basemap metadata. Every region and address is synthetic. No source download,
real browser storage, or source-payload read is used by the new component tests.

These hooks and SSR are deterministic presentation evidence, not real DOM,
Preact browser batching/effects, or CacheStorage permission/rejection integration.
Those browser/e2e gates remain UNVERIFIED and operator-owned.

## Acceptance mapping

- A1: `primary regression` rejects initial enumeration, requires the unknown
  message and forbids the empty message. The observed initial HTML is retained.
- A2: `healthy control` requires the exact successful-empty message; the nonempty
  case checks both fixture region names, timestamps, chart/base-map counts,
  missing-item annotation and unchanged metadata wording.
- A3: nonempty success -> error retains both rows and the not-rechecked qualifier;
  a successful empty refresh clears both rows and the error. A prior successful
  empty listing followed by error must not assert that the device is empty now.
- A4: deferred initial loading, stale initial success after newer empty success,
  stale rejection after newer nonempty success, and overlapping refreshes where
  an older success must not erase the newest error/retained listing.

Baseline mode registers exactly `primary regression` and `healthy control`,
without skipped tests. On the complete unchanged pinned product the first test
must fail specifically with `A1_INITIAL_REJECTION_IS_UNKNOWN_NOT_EMPTY`, and the
second must pass. Child exit 1, 2 tests, 1 failure, 1 pass, zero skips is recorded
as `BASELINE_GAP_REPRODUCED`, never repair success. The focused mode includes
this identical pair plus all seven A2–A4 tests. All nine must pass.

The first focused development run exposed an author error in the new A2 text
assertion (the unchanged base-map clause precedes the zoom clause). Only that
assertion's word order was corrected; no product metadata wording, baseline pair,
or fixture changed. The initial red receipts remain intact. A fresh unchanged-
product baseline was then run with the corrected, refrozen whole test file,
before restoring the candidate verbatim. Its test/fixture hashes are compared
with final green evidence; the older baseline is not relabeled as final evidence.

## Launcher and receipt identity

From this clone run `python3 scripts/accept_sp1502_pack_inventory.py --suite MODE
--output OUTPUT`, with MODE one of `baseline`, `focused`, `regression`,
`repository`, `typecheck`, or `build`. OUTPUT must resolve under the sibling
candidate `out` directory. Every invocation allocates a unique child directory
and saves each actual argv, cwd, start time, elapsed duration, exit, raw stdout
and stderr separately with SHA256, plus source/test/fixture hashes, HEAD,
git-index digest and worktree status before/after. It checks exit/counts with
explicit conditions, not removable Python assertions. Runtime versions are
captured from installed executables. Receipts and generated bundles are never
committed fixtures and reviewer reruns never overwrite author receipts.

The operator's sibling `SOURCE-MANIFEST.json` must match its v1 schema, admitted
repo and base. The repository check uses exactly its
`runtime.credential_scan_python3`, with no system-Python fallback. There are no
runtime imports from a plan, other worktree, or operator input bundle. Committed
paths derive from the launcher/test clone. Staged dependency links are preserved.

Regression mode runs `tests/test_trip.mjs` and `tests/test_offline.mjs` unchanged,
separately, on the installed Node runtime. Repository mode runs the unchanged
`scripts/check_repository.py`. Typecheck runs each of `tsconfig.json`,
`web/tsconfig.json` and `packages/coast/tsconfig.json` separately with
`pnpm exec tsc --noEmit -p CONFIG`. Build runs the existing `pnpm build` only.
All selected assertions must execute with zero errors/failures/skips; typecheck
and build are command checks, not test-count claims. Final signoff also requires
clean `git status --porcelain` and `git diff --check BASE HEAD` at the signed head.
Final external handoff receipts bind that exact head and the author runtime.

## Remaining gates

Author: actual gpt-6.1-sol / openai-codex, sol-reviewer, run 1977, under the
operator's explicit Sol-builder admission. Sole independent reviewer: actual
Claude Opus 5.5 on opus-coder-bopus. This document is self-review, not approval.
Scoped green is REVIEW REQUIRED. Operator owns PR publication, exact-head CI,
full Node/Python discovery, survey/GIS skip accounting, parity, credential/privacy/
link, web/client/copy/token, audit and browser/e2e closure. None is silently waived.
No push, merge, publication, download, live run, hold release, provider change,
service change, or human/legal/scientific/navigation acceptance is authorized.
