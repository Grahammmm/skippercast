# SP1302: withhold conflicting landing report identities

Specification: SP-13-v2. Scope: offline candidate, REVIEW REQUIRED.
Base: `2979d59bfbb7d724eb83b34a48102b914ee8eaa3`.
Material author: actual `gpt-6.1-sol`, provider `openai-codex`, profile
`sol-reviewer`. Sole independent reviewer: actual Claude Opus 5.5 on
`opus-coder-bopus`. This author has not independently approved this candidate.

## Product delta

Only `server/fleet/pairing.ts`, within `landingRows`, changes product behavior.
An ID maps to its first otherwise eligible normalized name, canonical port and
date. A disagreement changes that map entry to a sticky null until this call
ends. Filtering null entries after all feeds have been collected makes conflict
omission independent of input order, without resurrecting A after A-B-A.
Agreeing duplicates retain one row in first-seen order. All existing eligibility
checks, return fields, feed availability accounting and normalization remain.
The next independent call starts with a fresh map.

The SQL pairing and pruning functions are unchanged. Omitted conflicting IDs
create no new landing pairs, but a previously stored landing pairing for an
omitted ID is deliberately retained, just like an unavailable report. This
patch does not repair historical attribution or authorize a cleanup. No advisor,
price, source attribution, rights, scientific/legal threshold or catalogue delta.

## Executed acceptance mapping

The full new file runs six named tests, without skips:

- A1: `A1 every A-B-A permutation is withheld and A-A agrees` covers each of the
  three unique orderings, consistent duplicates and equivalent normalized names
  through the real `landingRows` export.
- A2: `A2 independent name port date conflicts within and across two valid feeds`
  isolates each field, both feed orders, repeated conflicting IDs, canonical port
  aliases, and recovery on a later independent call.
- A2: `A2 eligibility and distinct healthy IDs survive conflict and unavailable feeds`
  covers irrelevant ports, out-of-window/invalid dates, empty names, invalid IDs,
  two valid feeds, distinct healthy IDs, unreadable/malformed feeds and no ports.
- A3: `A3 D1 conflict omission preserves stored pairs and healthy ranking and advisor attribution`
  uses the real public pairing/pruning APIs and the unchanged migration-backed
  in-memory D1 adapter. It asserts exact report/trip identities, match and
  confidence, omission of a fresh conflicted ID, retention of an existing
  conflicted pair, visible-report reranking with fishing-time and time ties,
  published/withdrawn advisor behavior and unavailable-report retention.
- A4: `primary regression` and `healthy control` are the same unchanged tests
  before and after the repair. Healthy control asserts one landing row and one
  new pair for two agreeing inputs, followed by an idempotent repeat.

The unchanged original `tests/test_fleet_pairing.mjs` runs all six original
named tests, including its Worker request path, advisor behavior, feed counters,
source attribution and one-report-one-trip ranking. It is hash-pinned by the
acceptance helper and is not modified. No live request or socket is made.

## Historical test-first evidence

Before product edits, baseline mode registered only `primary regression` and
`healthy control`. It produced child exit 1, exactly one ERR_ASSERTION failure
and one healthy pass, zero cancellations/skips/todos. The assertion observed
`conflict-example` attributed to `ALPHAEXAMPLE` instead of omission. No product
SQL exception was observed; the primary test can record an observed baseline
exception before the deciding assertion, but the final acceptance helper rejects
any such diagnostic in repaired runs.

Historical receipt relative to the candidate:
`out/author-baseline/20261025T094157-31366a24a9af/receipt.json`.
Its SHA256 is `eb8699f6c1ef61087a961aa30482c10b909b5ef32f3669d4b7d2ff0449061f16`.
This is BASELINE_GAP_REPRODUCED, never final green evidence.

Frozen test SHA256:
`7dcbb930ab88cd3df2a2f6572d4e1d17c78ea4d06461d0a27628edb2659922e1`.
Frozen reports fixture SHA256:
`699e799b8b232c148a292f829c4bdfdee147851f9c03fb8d9efc1f589b362884`.
Frozen offline preload SHA256:
`3e9dfc520d398ddf9df48b8afc76a53041d2b2255542f99e8629345da4161a6e`.
These tests and fixture bytes were not changed after baseline.

One preliminary regression receipt is FAIL because the new helper mistakenly
expected seven original tests. Its raw child actually ran all six, successfully,
without skips. That diagnostic remains preserved at
`out/author-regression/20261025T094239-235f64a9e5c9/receipt.json`.
The helper was corrected to pin the six exact original names, without changing
any original test, new test, fixture or product behavior. A subsequent preliminary
regression receipt passes. This was a local author harness correction, not a
review return or a guard refusal. All final green rows are rerun after commit;
preliminary results are not relabeled as exact-head results.

## Portable runner and safety boundary

From the staged repository, run the helper as a script file:

    python3 scripts/accept_sp1302_landing_conflict.py --suite focused --output ../out/reviewer-focused

Modes are `baseline`, `focused`, `regression`, `repository`, `typecheck`.
Each creates a new unique child below the candidate's out directory, retaining
literal child argv/cwd/exits, measured runtime, names/counts, raw stdout/stderr and
SHA256 hashes. Receipts bind source/test/fixture hashes, staged base, actual HEAD,
manifest hash, spec and material-author declarations per commit. Baseline refuses
non-base HEAD or changed primary bytes. Do not rerun baseline against the repair.
Reviewer runs use distinct output roots, never overwrite/reseal author receipts.

The helper derives repository/candidate locations from its own file and requires
the operator source manifest. Authored fixture/output ancestry is checked for
symlinks. Outputs and synthetic temporary HOME/TMP roots are outside committed
fixtures. Children receive a small allowlisted environment, not ambient secrets,
service settings, live default roots or API credentials. The Node preload runs
before product/test imports and rejects fetch/WebSocket, TCP, TLS, HTTP, HTTP2,
UDP and DNS paths, including loopback sockets. This detects mistakes; it is not
a hostile-code sandbox. The test file installs in-memory feed seams before calls.
`server/config.ts` captures the injected globals on import; the new file injects
only synthetic feed URLs. `server/feeds.ts` has public endpoint constants but no
import-time feed request; the original Worker tests' URLs are inert behind their
existing fakes. No stateful API uses a filesystem/live store: D1 is `:memory:`.

There are no Python product tests on this Node card, so no editable-install Python
imports occur. Repository mode runs the unchanged location-derived
`scripts/check_repository.py` under the manifest's credential-scan interpreter,
with no system-Python fallback. Its import-time ROOT is the staged repo; the
checker is read-only and has no network/model call. Typecheck runs the three
unchanged programs separately using installed pnpm/TypeScript, with no install,
no emission and no network. Actual versions are retained in receipts.

## Release limits

Final local evidence is sealed only after signed-off commit, exact-head green
focused/regression/repository/typecheck rows, diff-check and clean status. The
candidate's out directory retains the baseline, diagnostics, preliminary runs
and final receipts separately. The handoff identifies the final evidence
manifest and exact commit; the note intentionally does not backdate baseline.

Scoped success remains REVIEW REQUIRED. Unchanged full-repository suites,
remote PR publication, exact-head required CI and release are OWED to the
operator. No live feeds, actual fleet/coastal records, downloads, model calls,
credentials, canonical stores, service/timer changes, worker push/merge or
publication occurred. All source/live, legal/scientific and other retained holds
remain with their existing owners. No claim of historical repair, safe-water,
fish-presence, navigation, human or legal acceptance is made.
