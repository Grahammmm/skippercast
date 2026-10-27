# SP1406: marine advisory check completeness

Status: scoped offline implementation, REVIEW REQUIRED. Frozen contract: SP-14-v1.
Material author: gpt-6.1-sol / openai-codex, sol-reviewer run 1809.
Sole independent reviewer: opus-coder-bopus on actual Claude Opus 5.5.

## Product change and compatibility

Only `server/advisor/answers/planning.ts` changes product behavior. A daily
feed envelope is not evidence that its required marine zones were checked.
The private `advisoryCheckTime` requires a nonempty `regionZones(region)` list
and, for every required zone, a source object with status exactly `ok`, an
array at `data.alerts`, and a string `checked_at` parseable by `Date.parse`.
It returns the oldest required check by instant, preserving its source string.
There is intentionally no new elapsed-age/future-time threshold.

`advisories_checked` is true only for that complete check; `advisories_as_of`
is its oldest timestamp, otherwise null. Incomplete evidence adds the existing
could-not-be-checked note. Alert collection, warning sorting/lead, advisory
language and NWS closer remain independent of completeness. `advisoriesFrom`,
forecast/comfort/date handling, season/rules and all original tests are unchanged.
Known warnings remain visible even if a source has a non-ok status.

The baseline falsely reported checked true for a valid envelope with no alert
records. A successful check with empty arrays still means checked true and
empty advisories. Partial checks may now report false where callers previously
saw true; this is the intentional compatibility delta, not suppression of alerts.

## Exact assertion mapping

All new cases live in `tests/test_sp1406_alert_check.mjs` and import the COMPLETE
real planning module. Synthetic producer-shaped definitions and the frozen
spec are committed in `tests/fixtures/sp1406_alert_check/`. No plan/source-slice
code, external records, live feeds or additional dependencies are test inputs.

- A1/A4: `primary regression` exercises a valid daily feed with no alert records,
  asserting false, null as_of, the existing note and empty advisories. It emits
  the observed semantic fields before asserting. `healthy control` exercises
  two ok sources with empty arrays and equal valid checks, asserting true,
  empty advisories, that timestamp and no missing-evidence note.
- A1: `A1 one missing required zone and unrelated successful zone`,
  `A1 missing daily feed`, `A1 invalid status <JSON value>` (failed, retained,
  stale, unknown, OK, empty, null), `A1 missing status`,
  `A1 non-array alerts <JSON value>` (null, object, string, number),
  `A1 absent data or alerts and non-object source`,
  `A1 invalid checked_at <JSON value>` (bad/empty/null/numeric/object/array),
  and `A1 missing checked_at` cover the incomplete-evidence class.
- A2: `A2 oldest required check independent of source insertion and unrelated zones`
  checks reversed insertion order and an older unrelated zone.
  `A2 compare timestamp instants not lexicographic strings; no new elapsed-age threshold`
  checks timezone-offset ordering and intentionally old but parseable timestamps.
  `A2 no configured required zones is not a complete check` covers vacuous success.
- A3: `A3 warning survives missing evidence and complete check in en` and the
  identical `... in es` case exercise `planningBrief` using the existing
  migration-backed in-memory D1 adapter. They assert Gale Warning before Small
  Craft Advisory, exact translated lines, advisory-first field ordering and
  lead, NWS closer, unchanged planning/season/confidence and forecast fields
  between partial and complete inputs. `A3 known warnings survive a non-ok check status`
  asserts retained-source warnings are not erased.

Focused selection contains exactly 30 top-level tests. Baseline registration
contains ONLY the two A4 tests, not name-filtered/skipped peers. Full original
compatibility runs the unchanged `tests/test_advisor_tools.mjs` (31 tests),
including the real forecast golden cases and existing season/planning cases.

## Offline boundary and launcher

The file-based `bootstrap.mjs` is loaded before product imports. It provides
network/model/process and filesystem-write sentinels; localStorage reads are
an inert null-returning fake. No live storage binding is supplied. Injected
feed readers, fixed clock and synthetic region configuration precede product
imports; per-case region globals and in-memory DBs are restored/closed, and
the authored test's final hook restores the process globals and built-ins.
Original compatibility runs in its own test process, with its recorded fakes
and memory DB. These sentinels detect accidental calls, not hostile code.

Run from the staged repo using the installed `python3`:

    python3 scripts/accept_sp1406_alert_check.py --suite focused --output ../out/author-focused

Run each suite separately: `baseline` (unchanged pinned product only), `focused`,
`regression`, `repository`, `typecheck`, `build`. Each invocation creates a
unique child beneath the candidate-local output argument. Reviewer reruns use
separate reviewer output roots; never modify or reseal author receipts.

The stdlib launcher derives all committed locations from its own script path.
It verifies staging schema/repo/head and unchanged original compatibility,
package, lock and repository-scanner bytes. It preserves .venv/node_modules
links; missing staging is an operator problem, never an install/fallback.
Node uses repository-supported type stripping and the pre-import bootstrap.
`repository` uses exactly the staging manifest's lexical venv interpreter
`runtime.credential_scan_python3` for unchanged `scripts/check_repository.py`;
its resolved executable is logged too, not substituted for the venv entrypoint.
Typecheck runs the three tsconfig commands separately. Build invokes only the
existing `pnpm build`; generated ignored build outputs are not hand-edited.

Every receipt records spec/card/phase, source manifest hash, staged base and
actual HEAD, worktree status, material commit messages with runtime provenance,
source/spec/test/fixture hashes before/after, installed runtime identity,
child argv/cwd/exit, TAP names/counts and raw stdout/stderr file hashes.
Explicit exit/count/name checks reject missing tests, skips, cancellations,
unexpected failures and setup errors. Baseline requires child exit 1 with only
`primary regression` failing specifically `ERR_ASSERTION`, actual true versus
expected false; healthy control must pass. Its launcher exit 0 means only
BASELINE_GAP_REPRODUCED. It cannot run baseline on changed product bytes.

## Retained evidence and limitations

Base commit: `33734f90073a2150eac5a418564ea314c4a591ac`.
Original primary SHA256:
`569cac7d016d92822a13a24a847341f4003ffe12e8b12b85bce3b6e6c4662647`.

The first focused run found two setup errors in added A3 integration cases:
the synthetic region lacked `species`, required by `dailyInputs`. The failed
receipt is retained. Only fixture closure was corrected (species rockfish);
the A4 test file/assertions were not changed. Before applying the same product
delta again, the complete unchanged pinned planning module was restored and
the two-test baseline was repeated, again reproducing exactly its semantic
failure plus healthy pass. This second baseline freezes the submitted fixture
and test hashes. Both historical baselines remain evidence, not fix passes.

Final receipts and the separate candidate-local frozen manifest identify the
signed-off HEAD and preserve the entire run history, including that failure.
No original tests, thresholds, CI, catalogue, package/lock files, source assets
or shared helper were changed. No download, install, live run, push/merge,
publication, service/timer/config change or hold release is part of this work.

Scoped green is not full-repository or semantic/release acceptance. The existing
operator owns PR publication before final code review, unchanged local full
suite and exact-head required CI: complete Node discovery, Python non-GIS,
full survey/GIS with strict skips, regional/search rebuild parity, all privacy/
credential/link/public-tree, web/client/copy/token, typecheck/build, dependency
audit and browser/e2e groups remain OWED to their respective owners. The
separate DeFlock public-tree check is not applicable to this SkipperCast-only
change. SC#1/PR846, SC-5b, terrain-mask, public-viewer, legal-preview,
source/live and bulk-download holds remain. This provides no legal, navigation,
safe-water, fish-presence or other human/scientific conclusion.
