# Explicit transient index retry (SP-15-v1 / SP1503-LAND-WATER-RETRY)

## Contract and scope

`loadLandWater(region, fetchFn, {retryTransient: true})` permits exactly one
request for that call, but only after the selected region's settled index load
failed through a rejected/thrown fetch, HTTP 429, or HTTP 500–599. Concurrent
callers share the in-flight job. Another failed transient attempt can be retried
only by another explicit call; there is no automatic retry, timer, backoff or loop.

The options argument defaults to an empty object. Only boolean `true` grants a
retry. Existing callers, including `ensureLandWater`, retain once-only behavior.
Ready products and permanent failures (including 404, malformed JSON, invalid
schema, region mismatch and an explicitly unavailable product) remain memoized.
JSON decoding/validation failures are product failures, not retryable fetch
rejections. Switching region or resetting forgets retry eligibility, and a stale
job may change neither the selected state nor its retry eligibility.

All classifications remain unknown/withheld during failure and retry. The lines
loader, shoreline/source validation, SHA256 byte check and ranking rules are
unchanged. This API enhancement deliberately narrows the old load-once contract;
it does not add a retry button or change any caller's behavior.

Only `web/land-water.ts` is a changed product file. The original land/water tests
are unchanged. All new fixtures are synthetic. No real source acquisition,
network/model calls, external stores, service changes, publication or deployment
are part of this work.

## Synthetic fixture and execution boundary

`tests/fixtures/sp1503_land_water_retry/products.json` follows the schema consumed
by the complete actual module and the shapes exercised by the original committed
tests. It models a world tile clipped to a tiny synthetic region, with clean water
or mixed cells, a vertical shoreline and land east of that line. The test serializes
the synthetic lines and computes their actual SHA256 into the in-memory index;
the fixture's descriptive hash placeholder is never passed to the loader.
Hash-tamper controls change only bytes. Source/region/schema controls recompute the
byte hash first so they isolate the validation gate rather than failing its hash.
No fixture is navigation, geographic coverage or scientific evidence.

The new test installs fetch, HTTP(S), socket/TLS/DNS and child-process accidental-I/O
sentinels before dynamically importing the complete loader. Requests are injected
producer-shaped `Response` objects. Globals and built-in exports are restored after
the test process. This is an offline guard, not a hostile-code sandbox. Regression
mode imports the original `tests/test_land_water.mjs` unchanged under those guards;
it reads only its existing committed fixture/static products.

## Claim-to-test mapping

| Requirement | New test(s) and assertions |
| --- | --- |
| A1 | `primary regression`; transport rejection, synchronous throw, 429 and all 100 HTTP 5xx statuses recover to ready/water only on explicit true. |
| A2 | Concurrent explicit retries plus ordinary load/ensure share one extra request and wait for settlement. Late success/transport/HTTP completions cannot overwrite another region, reset, or a fresh A-B-A job. |
| A3 | `healthy control`; defaults, ensure, false and truthy non-booleans never retry. Ready, permanent HTTP, invalid JSON/schema, wrong region and unavailable products are memoized. Failed retries remain once-only until another explicit call; a permanent retry result clears eligibility. |
| A4 | Every synthetic point is withheld on failure/in flight; recovered mixed cells still require lines. Exact-hash positives classify water/land/edge; independent byte/source/region/schema/transport negatives fail closed. Lines remain once-only. |

Focused mode runs nine named tests, including the identical frozen baseline pair,
with no skips. Original regression mode runs all sixteen original tests unchanged.
The loops in those named tests additionally cover the full HTTP 5xx class, three
stale completion outcomes across three selection/reset sequences, and six lines
validation outcomes. TAP receipts report named-test counts, not fabricated counts
for individual assertions or loop cases.

## Acceptance and evidence

Run from the candidate repository with the installed runtimes:

```
python3 scripts/accept_sp1503_land_water_retry.py --suite baseline --output ../out/author-baseline
python3 scripts/accept_sp1503_land_water_retry.py --suite focused --output ../out/author-focused
python3 scripts/accept_sp1503_land_water_retry.py --suite regression --output ../out/author-regression
python3 scripts/accept_sp1503_land_water_retry.py --suite repository --output ../out/author-repository
python3 scripts/accept_sp1503_land_water_retry.py --suite typecheck --output ../out/author-typecheck
python3 scripts/accept_sp1503_land_water_retry.py --suite build --output ../out/author-build
```

Baseline is historical red evidence ONLY: execute it before editing the pinned
product at base `8a805820c30895f5f037e26af9079fd3dc015b0f`. The launcher requires
exactly `primary regression` failing at `SP1503_A1_EXPLICIT_TRANSIENT_RECOVERY`,
`healthy control` passing, child exit 1, zero skips/cancellations/todos, and no
stderr/setup errors. Its successful result is `BASELINE_GAP_REPRODUCED`, never
repair success. Re-running baseline on the repaired head must be refused. The
unchanged pair is included in final green focused execution instead.

Every invocation creates a fresh unique child directory beneath the output root;
reviewers must use separate output roots. Receipts retain actual argv, cwd,
interpreter/runtime probes, durations, exits, TAP counts or scan count, raw stdout
and stderr hashes, staged-manifest identity, and before/after source hashes.
Typecheck is three separate existing `pnpm exec tsc --noEmit -p` commands for the
root, web and coast configurations. Build is the existing local `pnpm build`, not
a deploy. Repository checks use exactly the staged manifest's credential-scan
Python; there is no missing-package/system-Python fallback. No shell bodies or
inline interpreter source are used. Nonzero/unexpected child results fail closed.

The candidate's external `out` handoff manifest is frozen after final signed-head
acceptance and includes all tracked source hashes, baseline/final receipts and raw
output hashes. Historical dirty/base-head results remain labelled as such and are
not reused as final-head evidence. The test and fixture hashes from baseline must
match final focused execution. No evidence is written into committed fixtures.

## Provenance and retained gates

Material author: actual `gpt-6.1-sol`, provider `openai-codex`, profile
`sol-reviewer`, run 1851, task `t_088092ea`; operator admission on this same card
explicitly assigned the Sol builder route. The material commit is signed off and
records that runtime in its message. This is author self-review, not independent
approval. Sole independent reviewer: actual Claude Opus 5.5 on `opus-coder-bopus`.

Scoped green is `REVIEW REQUIRED`, not semantic or full-repository acceptance.
Operator-owned PR publication, complete required-suite/skip accounting, exact-head
CI, browser/e2e checks, release and any merge remain owed under the admitted brief.
No human/legal/scientific/navigation/fish-presence conclusion is supplied. All
source/live/public-viewer/terrain/legal-preview and existing unrelated holds,
canonical-store/raw-receipt ownership, service/profile boundaries remain intact.
