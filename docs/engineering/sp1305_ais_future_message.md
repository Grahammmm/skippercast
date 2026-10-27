# AIS last-message decision-clock bound (SP1305)

Specification: SP-13-v2 / SP1305-AIS-FUTURE-MESSAGE.
Base: `2979d59bfbb7d724eb83b34a48102b914ee8eaa3`.
Material author: actual `gpt-6.1-sol`, provider `openai-codex`, high effort,
profile `sol-reviewer`, card `t_3c7b5c38`, run 1778. No copied planning
implementation or delegated material. Sole independent reviewer: actual
Claude Opus 5.5 on `opus-coder-bopus`. This note is not that review.

## Compatibility delta

Only `server/fleet/admin/ais-health.ts` changes product behavior. A parsed
`last_message_at` strictly later than the caller's `now` now projects
`last_message_age_s: null` and `stale: true`, retaining the original string.
There is no skew tolerance. Exact now remains zero/fresh; past ages retain
integer-second flooring and the unchanged `age > 10800` stale rule. Invalid,
missing and non-string values retain null-age/stale behavior. The shared
`ageS` clamp, heartbeat and processor projections, region selection, counters,
watch totals, gaps, outages, uptime, and authentication/feature gates are
unchanged. No migrations, dependencies, original tests or CI files change.

## Executed claim-to-test map

All tests call the actual `aisHealth` module with `advisorDatabase()` applying
every committed migration to an in-memory `node:sqlite` database. Inputs use
the producer-shaped heartbeat fields in the original fleet coverage `seedAis`
and synthetic `999...` watch identities. All SQL writes are fixture preparation,
not listener/processor execution. Databases are closed in `finally` blocks.

- A1 / A4: `primary regression` checks tomorrow's timestamp and records the
  observed projection before its age assertion. `healthy control` checks the
  otherwise-identical five-minute-old message (age 300, not stale), exact
  heartbeat/processor/watch data, counters, uptime, gaps/outages, and unchanged
  input tables. Baseline registers only this pair; no name filter creates skips.
- A2: `A2 future instants offsets flooring and exact stale threshold` checks
  one-millisecond future, far future, equivalent positive/negative UTC offsets,
  exact now, fractional-second flooring, exact three-hour threshold,
  fractional-second beyond it, and one full second beyond it. Each case also
  checks preservation invariants and the original input rows.
- A2: `A2 missing null non-string and malformed clocks preserve a healthy peer`
  checks absent, null, numeric, boolean, object, array, empty, and invalid string
  fields while the independently healthy CA peer remains fresh and unchanged.
- A2: `A2 shared heartbeat and processor future-age behavior stays unchanged`
  independently moves those other clocks into the future and verifies their
  existing zero-age clamp is untouched.
- A3: `A3 admin route preserves stores reports and authorization gates` calls
  the actual Worker in-process using synthetic sessions, ASSETS, and D1. The
  clock is fixed before Worker imports and restored after tests. Synthetic
  sessions are prepared separately. A SELECT-only D1 wrapper rejects health
  handler writes; complete heartbeat/counter/watch snapshots before/after
  healthy and future requests must match. Only last-message projections differ
  between reports. Non-admin, anonymous, fleet-off, and advisor-only controls
  retain original denial behavior. There is no HTTP server or real token lookup.

## Historical evidence and preflight correction

The initial `out/author-baseline` correctly recorded one semantic assertion
failure (`0 !== null`) and one healthy pass on the pinned original product.
The first repaired focused run exposed a test-harness omission: the direct
Worker call lacked the synthetic `IDENTITY_PROVIDER: 'skippercast'` binding
used by session preparation, and returned 401. This was not a product failure
or permission to weaken authentication. Only that fixture binding was added;
no assertion, baseline pair, or product/auth gate was weakened.

Every prior receipt remains. Before reapplying the repair, the product was
restored byte-for-byte to its pinned original and the corrected complete
file/fixtures were frozen by `out/author-baseline-v2`. That baseline again
exited 0 only after the primary semantic failure and healthy pass (child 1,
no skips). The same unchanged test and fixture hashes pass after repair.
The historical baseline remains `BASELINE_GAP_REPRODUCED`, never final green.
The first corrected focused run passed all six registered tests. Final-head
receipts supersede preliminary green runs without overwriting them.

## Portable commands and evidence

From the staged repository, invoke each mode separately with an absolute fresh
output directory directly under its candidate's `out` directory:

    python3 scripts/accept_sp1305_ais_future_message.py --suite baseline --output <candidate>/out/<fresh-baseline>
    python3 scripts/accept_sp1305_ais_future_message.py --suite focused --output <candidate>/out/<fresh-focused>
    python3 scripts/accept_sp1305_ais_future_message.py --suite regression --output <candidate>/out/<fresh-regression>
    python3 scripts/accept_sp1305_ais_future_message.py --suite repository --output <candidate>/out/<fresh-repository>
    python3 scripts/accept_sp1305_ais_future_message.py --suite typecheck --output <candidate>/out/<fresh-typecheck>

Baseline is historical test-first execution ONLY on the original pinned product;
a reviewer of the repaired candidate runs the other modes in separate roots.
The helper derives roots from its own file and validates the operator manifest;
it never manufactures one. A final focused run requires matching historical
baseline test/fixture hashes. Existing evidence paths and symlinked fixture or
output ancestry are rejected. Temporary roots are candidate-local; no generated
resource is written into committed fixtures. Child environments are allowlisted
and carry no ambient provider/API credentials. Network/model tripwires precede
product/test imports, including import-time clocks and endpoint bindings.
These are accident detectors, not a hostile-code sandbox.

Node uses the installed executable, native test execution and type stripping.
The unchanged `tests/test_fleet_coverage.mjs` runs all its original tests, not a
name-filtered subset. Repository mode uses only the operator manifest's
`runtime.credential_scan_python3`, through a file bootstrap that sets staged
repo/src import roots and verifies the unchanged checker's path. No Python
test child is used by this Node card. Typecheck runs each unchanged tsconfig
separately via the manifest's installed `pnpm exec tsc --noEmit -p ...`.
All declared program exits are retained and must pass. The helper records
literal argv, cwd, interpreter/runtime, raw stdout/stderr and hashes, actual
native test names/counts, source/test/fixture identity, material provenance,
and historical baseline references. Explicit checks, not removable Python
assert statements, determine acceptance exits.

Final green modes are rerun on the signed-off commit with clean git status,
then the unique final evidence manifest is frozen outside the repository.
The manifest binds those receipts, raw outputs, complete bounded diff, commit
and source hashes. Reviewer output cannot overwrite/reseal author evidence.

## Scope and release limits

Scoped offline green means REVIEW REQUIRED, not independent approval, full
repository-suite acceptance, shipping, legal/scientific/navigation acceptance,
or proof of a deployed incident. The operator still owns unchanged full suites,
remote PR publication, exact-head required CI and any release decision.
No live listener, processor, database, source acquisition, network request,
publication, merge, deployment, credential change, service/timer change, hold
lift or canonical-store write was performed or authorized. Existing source,
live, public-viewer, terrain-mask, SC#1/PR846, SC-5b and legal-preview boundaries
remain with their owners.
