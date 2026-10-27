# SP82: identity snapshot framing

## Scope and baseline

Frozen contract: SP82-SNAPSHOT-LENGTH version 1, acceptance A1–A4.
Base: `a1f648632e64561d82dcbeb20d9bda19f812560a`.
Original `dist/coastal-offline-core.js` SHA256:
`bcb499097ad9b7014e30496ba376ed98d7c5d1844b2f591699d3461bd7603a45`.

The complete original module accepted valid product JSON despite a declared
identity Content-Length of 1. This is a synthetic framing defect, not evidence
of a deployed transport incident. All three products are derived from the
actual report/ocean/history shapes in `validProduct` and the existing offline
suite; the fixture contains only synthetic multibyte labels and empty arrays.

The sole product edit is after bounded consumption and reader release, before
allocating the combined byte array. If a Content-Length exists and
Content-Encoding is absent or is identity (case/outer whitespace normalized),
the received byte count must equal the valid declaration. A disagreement throws
`Snapshot declared byte length disagrees with received bytes`.
The saver therefore follows its existing uncommitted-candidate cleanup path;
the reader's existing catch returns null. No pointer/store transaction logic is
changed. Gzip/br-labelled decoded responses are not compared to encoded length.
All existing declared and streamed byte budgets, clocks, MIME requirements,
offline-origin refusal and 20-second deadlines are unchanged.

## Claim-to-assertion map

All cases are in [the new complete-module tests](../../tests/test_sp82_snapshot_length.mjs)
and use [committed synthetic products](../../tests/fixtures/sp82_snapshot_length/products.json).

| Contract | Named cases and asserted behavior |
| --- | --- |
| A1 | `A1 ... declared length shorter/longer rejects`: absent, identity, uppercase identity and whitespace-padded identity all reject valid multibyte JSON when length differs by one. `A1 character count ...` specifically rejects the JavaScript character count. `A1 ... matching length accepts` and `... no length accepts` read back all three exact original bodies and actual byte counts. |
| A2 compression | `A2 gzip/br encoded length may differ ...`: encoded length 1 with decoded complete valid products remains accepted and readable. |
| A2 unchanged guards | `A2 malformed or over-budget ...`: negative, fractional, exponent, nondigit, unsafe huge and limit-plus-one declarations still refuse, including compressed responses. `A2 ... streaming over budget ...` proves cancellation with absent/gzip/br encoding. Wrong MIME, offline-origin, read failure and mid-body abort each exercise their own refusal and candidate removal. The fixture case asserts unchanged exact product/total budgets and timeout. |
| A3 transaction | `A3 mismatch in product 1/2/3 ...`: request order stops at the affected product; byte-for-byte in-memory images of the prior index, metadata, products and unrelated cache are unchanged; exactly the failed candidate is deleted; the complete prior snapshot remains readable. |
| A3 reader | `A3 reader returns null for tampered absent/identity length`: change only the stored length/encoding header, keeping the otherwise-valid body, descriptor byte count and stamp. |
| A4 sensitivity | `A4 primary ...` captures a return or exception as data before requiring a framing refusal. Before repair it is the sole named assertion failure because the saver returned. `A4 healthy ...` is a matching-length complete-products positive control. The same two tests are included unchanged in focused acceptance. |

The focused command runs 41 named top-level tests. The regression command runs
exactly the 17 existing tests in `tests/test_coastal_offline.mjs`, unchanged.
It imports that literal selector after guard setup and compares the executed TAP
names and counts with all literal original test registrations. No copied
function or copied regression assertion is used.

## Evidence and invocation

Run from the staged repo using [the acceptance helper](../../scripts/accept_sp82_snapshot_length.py):

    python3 scripts/accept_sp82_snapshot_length.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp82_snapshot_length.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp82_snapshot_length.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp82_snapshot_length.py --suite repository --output ../out/author-repository

Baseline MUST precede the product edit. The successful historical receipt is in
`out/author-baseline/baseline-r_678n8y/receipt.json` relative to the candidate
root. It records the pinned original source, 1 passing healthy control, 1 named
semantic failure, 0 errors/skips, raw child exit 1 and wrapper exit 0 with status
`BASELINE_DEFECT_REPRODUCED`. It is not GREEN. The test hash was
`9576c72526d5ad2ed0ea34fafecb71687990206c9f40a0f23264a1fc89d853e2`
and the fixture hash was
`10e9400297c72610d2cf2199335459fecec5ce763a11e3fef7969b3c714847fb`.
Both are frozen across repair. Earlier unsuccessful launcher receipts remain
retained at `baseline-cen1eg5g` (overbroad closure-token check matched prose
"require browser") and `baseline-5z0zb09p` (skip detection matched TAP's
`todo 0` summary). They are explicitly FAILED_UNVERIFIED, not qualifying baseline
runs. The launcher was corrected before the successful baseline; no source,
test, fixture or historical receipt was rewritten to obtain that result.

Every invocation creates a fresh unique output child, keeps temporary output
inside it, and records source/test/fixture/helper hashes, actual HEAD, staged
base, runtime/version, exact child argv/cwd, counts, exits and raw output hashes.
Focused/regression require a retained successful baseline with identical test
and fixture hashes. Unknown suites, absent prerequisites, changed original
selectors/scanner, missing named tests, unexpected failures/skips and wrong
baseline failure fail closed through explicit checks, not Python assert.

The helper reads the operator's `SOURCE-MANIFEST.json` above the repo, verifies
its exact base and Git ancestry, and requires the staged shared venv and Node
dependencies. Repository scanning uses only the manifest's
`runtime.credential_scan_python3`, logs its literal path, resolved path and
version, and executes the unchanged `scripts/check_repository.py` through the
helper's file-based `--scan-child` entry. This entry installs Python socket and
child-process guards before runpy and sets repo/repo-src imports in code with
bytecode suppressed. There is no interpreter fallback or dependency install.

For final-head evidence, the helper additionally admits `typecheck`, `build`,
`diff` and `status` suites. They execute respectively the exact `pnpm typecheck`,
`pnpm build`, pinned-base `git diff --check` and `git status --porcelain` commands,
with separate raw-output receipts. The latter two require empty output. Build
outputs are normal generated files in this candidate, not hand-edited sources.
These ancillary modes add evidence capture, not any new shipping authority.

## Offline boundary, provenance and limits

Before importing the complete product module, new tests install process-local
fetch/model-transport, HTTP(S), socket and child-process sentinels plus in-memory
CacheStorage and Web Lock doubles. The original regression import closure is
`node:test`, `node:assert/strict` and the same complete product module; it has no
child commands. The source has no import-time I/O. Tests explicitly supply the
synthetic origin, fetcher, cache, lock and clock before any saver/reader call.
No browser/profile cache, real host or provider is accessed. Sentinels measure
attempts on these inspected paths; they are not a hostile-code sandbox. The
new test runs in its own Node test process during normal repository discovery,
so its irreversible process-local guards do not modify unrelated peer suites.

All new SP82 material and the product edit are authored by actual gpt-6.1-sol
on openai-codex, profile sol-reviewer, under the operator's explicit Sol build
admission. There were no Luna material commits or preserved candidate edits
at handoff to this builder; staging HEAD was exactly the base with clean status.
No Astra diagnostic code is copied. The sole independent code reviewer is
Claude Opus 5.5 on opus-coder-bopus via same-card review.

Scoped green results mean REVIEW REQUIRED. The operator still owns the PR,
full repository suite, strict skips, all required exact-head CI, DCO and shipping.
Those obligations are OWED, not passed by these local commands. No push, merge,
publication, live/source acquisition, policy/permission/cap change or hold lift
is performed by this card. Unrelated files, existing tests, package/lock files,
CI and CHANGELOG remain unchanged.
