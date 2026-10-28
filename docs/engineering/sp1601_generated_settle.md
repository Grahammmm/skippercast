# Generated publication settling (SP1601-GENERATED-SETTLE)

Spec: SP-16-v1. Staged base: `8a805820c30895f5f037e26af9079fd3dc015b0f`.
Material author: actual `gpt-6.1-sol`, provider `openai-codex`, profile
`sol-reviewer`, task `t_44bbb967`, run 1996. The independent reviewer is actual
Claude Opus 5.5 on `opus-coder-bopus`; this author does not approve this material.
The signed commit message repeats the actual author runtime.

## Product delta

Only `server/trip-queue.ts` changes among existing files: the upload-settling
clock now selects `published_at || completed_at || generated_at`. This is the
same existing truthiness precedence, with the already-supported generated-only
publication marker now covered by the settling guard. No timestamp validation
policy is broadened. The marker still uses completed then generated, not
published. The two-minute constant, owner paging, queue/consumer configuration,
claim/release behavior, deduplication and delivery policy remain unchanged.

## Frozen baseline and self-test history

Before the product edit, the launcher ran exactly `primary regression` and
`healthy control` against the unchanged real product. The first failed only on
`A1_GENERATED_RECENT_MUST_SETTLE` (actual enqueued, expected settling); the second
sent exactly one synthetic owner from a generated-only feed ten minutes old.
Child exit 1, tests 2, pass 1, fail 1, no skips/cancellations/todos; wrapper exit
0 and `BASELINE_GAP_REPRODUCED`. This is negative evidence, not repair success.

Historical output directory: `../out/author-baseline/baseline-23s7hd7l` (relative
to this repository, not a Markdown link). The receipt SHA256 is
`c7351ef3e5e7469fad1f517183938db343d4ad395be89a30c5f2b487778f1997`.
The fixture `baseline-contract.json` is a verbatim copy of the historical hash
snapshot. The baseline test module, feeds, offline guard and regression preload
bytes remain unchanged. Focused mode executes the identical baseline pair.

Two pre-signoff harness mistakes and their failed receipts are retained:

- The supplementary focused-only default-reader safety assertion expected a
  no-feed result, but the intentionally synchronous fetch sentinel throws before
  a promise is returned. It now asserts that exact rejection, preserving the
  no-I/O and no-DB assertions. This file is not imported in baseline mode. The
  historical snapshot retains its original hash; focused receipts separately
  record the original and current supplemental hashes. The launcher enforces
  the frozen baseline pair's actually imported dependency closure, not this
  nonbaseline addendum. Failed output: `../out/author-focused/focused-qjfkxjey`.
- The launcher initially expected 11 original tests; the unchanged selector
  actually executes 10, all passing. The count was corrected to the measured
  original source/test output, without editing or skipping original tests.
  Failed wrapper output: `../out/author-regression/regression-hxy4gn78`.

The fixture module's historical comment about SQLite's current date is
inaccurate: the actual producer DUE predicate checks enabled and undelivered
status, not the date. The inserted far-future date is synthetic and irrelevant
to owner selection; the real unmodified predicate and migrations are executed.
That baseline comment is retained rather than altering its frozen bytes.

## Claim-to-test map

- A1: `primary regression` asserts settling before any DB prepare, state access,
  owner query or queue send, preserving the generated publication identity.
- Healthy control: ten-minute-old generated-only publication enqueues exactly
  one synthetic owner and persists its claim.
- A2: settle threshold minus one, exactly, plus one millisecond, and future
  marker. Eligible boundary cases send once and stay unchanged on replay.
- A3: opposing old/recent published/completed/generated precedence, recent
  completed marker, empty fallback fields, null/absent/malformed/no-identity
  inputs. Publication identity is asserted independently of the selected clock.
- A4: unchanged publication, absent queue and DB, failed sends restoring both
  absent and existing claims, recovery with a working synthetic queue, and a
  sentinel check of the actual default feed reader.

Focused mode has 22 tests including the identical baseline pair; regression
runs all 10 unchanged tests in `tests/test_trip_queue.mjs`, separately.

## Offline execution and portability

Run from the staged repository with its existing node_modules and shared venv:

```
python3 scripts/accept_sp1601_generated_settle.py --suite focused --output ../out/reviewer-focused
python3 scripts/accept_sp1601_generated_settle.py --suite regression --output ../out/reviewer-regression
python3 scripts/accept_sp1601_generated_settle.py --suite repository --output ../out/reviewer-repository
python3 scripts/accept_sp1601_generated_settle.py --suite typecheck --output ../out/reviewer-typecheck
python3 scripts/accept_sp1601_generated_settle.py --suite build --output ../out/reviewer-build
```

Baseline mode is only for unchanged pinned product code. Do not revert repaired
source to recreate or reseal historical negative receipts. Every invocation
creates a new unique directory beneath its output root, including failure.
Receipts record exact child argv, cwd, installed runtime versions, wall time,
exits, counts, source identities and separate stdout/stderr SHA256 hashes.
Repository mode uses only the manifest's credential-scan Python, without a
system-runtime fallback. Typecheck uses three separate pnpm exec commands;
build runs only the existing candidate-local pnpm build. No install, shell
child, external endpoint, deployment or service operation is introduced.
The stage manifest is required at the repository parent's standard location;
paths and fixture imports derive from the repository, never planning inputs.

The tests load full actual TypeScript modules with supported Node stripping.
Before product import, reversible network/model sentinels intercept fetch and
native network transports; product configuration is synthetic. Feed arguments
are injected explicitly for every behavior test. The safety control exercises
the implicit reader without reaching an endpoint. DB instances are exclusively
`:memory:` and apply every actual migration. Queue writes stay in arrays, never
Cloudflare or real owners. Product feed-bucket binding is explicitly null.
Globals/sentinels are restored after the tests; regression preloading is scoped
to its dedicated child, leaving the original test bytes intact. These are
cooperative offline sentinels, not a general hostile-code sandbox.

## Boundaries and remaining gates

All results are scoped and REVIEW REQUIRED. This is not independent approval,
full repository test discovery, exact-head CI, scientific/legal/navigation
acceptance, publication authority or permission to release a hold. The operator
retains PR publication and the full release gates: complete Python/Node
inventory, survey/GIS skip accounting, regional/search parity,
credential/privacy/link and web/client/copy/token checks, dependency audit and
browser/e2e. The local repository wrapper is only the unchanged repository
checker, not all those separate gates. No source acquisition, live run, real
fleet/coastal data, settings, canonical store, raw receipt, timer, service,
secret or external network is touched. All existing source/live/bulk-download,
legal-preview, public-viewer, terrain-mask, SC#1/PR846 and SC-5b holds remain.
