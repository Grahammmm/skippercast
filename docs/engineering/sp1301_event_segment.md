# SP1301-EVENT-SEGMENT: an event's segment must belong to the event's own trip

Specification SP-13-v2, card SP1301-EVENT-SEGMENT. Staged base: `main` at
`2979d59bfbb7d724eb83b34a48102b914ee8eaa3`. Status: offline candidate, REVIEW REQUIRED.

## Gap and repair

`POST /api/fleet/jobs/activity` (`server/fleet/activity.ts`, `applyActivity`) checked that an
event's `segment_id` was one of the request's segments (set membership) but not that the
segment belonged to the event's `trip_id`. So in a two-trip request, an event of trip A that
named a valid derived segment of trip B was accepted and stored with the mismatched pair.

The repair replaces the segment-id set with a map from segment id to its trip id, filled in the
same loop that already validates derived segment ids and repeats. Each event now needs:

1. its trip and its segment in the request (unchanged message
   `events[i]: trip or segment not in this request`), then
2. the segment's trip equal to the event's trip (new message
   `events[i]: segment belongs to another trip`), then
3. the existing region/source/vessel and derived event-id checks.

This all happens before the vessel lookup, the first database read, so a refused request makes
no D1 `prepare` or `batch` call. Derived ids, duplicate rejection, source/vessel checks, request
caps, the statements and the single-batch transaction are unchanged. No new activity kinds,
schema changes or classifier policy.

Compatibility delta: a request with a cross-trip event that used to return 200 and write rows now
returns 400 with nothing written. Correctly paired requests produce the same answer and rows as
before.

## Acceptance map

`tests/test_sp1301_event_segment.mjs` calls `activity` directly with a migration-backed in-memory
D1 (`tests/_advisor_d1.mjs`). Refusal cases wrap it in a spy that counts `prepare`/`batch` calls.
Every case starts from a seeded database: two invented vessels, a prior trip outside the test
window, and a segment label on that trip.

| Row | Test | What it asserts |
| --- | --- | --- |
| A1 | `primary regression`, `A1: cross-trip segment refused ...` | Trip A's event naming B's segment returns `400 {error: "events[1]: segment belongs to another trip"}`. It is also checked in the reverse direction at index 0, and with both events crossed (the first one is reported). Each case makes 0 prepare/batch calls and leaves table state identical. |
| A2 | `healthy control`, `A2: correctly paired two-trip request ...` | 200 with the exact `changes`. Each stored event joins to a segment of its own trip. Reversing the trips, segments, events and windows gives the same answer and rows. Replaying gives the existing idempotent result (deletes and re-inserts) with identical rows. The label and the trip outside the window survive. |
| A3 | `A3: missing trip, missing segment, duplicate derived segment and isolated cross-trip segment ...` | Each case gets an exact 400 message, 0 D1 calls and unchanged state, including the label and rows outside the window. The cases: an event of a trip not in the request; a segment id not in the request; a repeated derived segment; a single cross-trip event (the only defect in the request); and a segment row claiming trip A while carrying B's derived id. |
| A4 | `primary regression` + `healthy control` | Test-first evidence. On the unchanged base, the primary failed by `ERR_ASSERTION` (observed status 200, 15 prepares, 1 batch, rows written), the control passed, and the child exited 1 (`BASELINE_GAP_REPRODUCED`). The same unchanged tests pass after the repair. |

"Isolated cross-trip segment" is read as "the cross-trip reference is the request's only defect".
The mislabelled-segment row covers the other reading, a segment row attached to the wrong trip.

Frozen test-first hashes (sha256, commit `6ae4b777`; unchanged by the repair commit):

- `tests/test_sp1301_event_segment.mjs` `4ef19306e3b3538f3e57f4536d205398aa9ce17be2a947262a3ebae4e0ba11cf`
- `tests/fixtures/sp1301_event_segment/request.json` `753615fa4ed52f670d974a47aadcaf3b0ea238e00578d92d366886524fa5e0b7`
- `tests/fixtures/sp1301_event_segment/tripwire.mjs` `2dcb043dbcfdf0c04e284f73fe9f9e75e74a80da0ef4a4acf2d8a7869ef3d7e0`

## Acceptance helper

`python3 scripts/accept_sp1301_event_segment.py --suite MODE --output DIR`, where MODE is one of:

- `baseline`: only the A4 pair (`SP1301_SUITE=baseline` registers just those two), on the base
  bytes of `server/fleet/activity.ts`. This is historical evidence; after the repair it reports
  `SOURCE_DRIFT` by design.
- `focused`: the whole new file against the named A1–A4 case map. Zero skips allowed.
- `regression`: `tests/test_fleet_activity.mjs`, which must be unchanged from the base. All of
  its tests run, with zero skips.
- `repository`: the unchanged `scripts/check_repository.py`, under the operator manifest's
  `runtime.credential_scan_python3`.
- `typecheck`: `pnpm exec tsc --noEmit -p` run separately for `tsconfig.json`,
  `web/tsconfig.json` and `packages/coast/tsconfig.json`.

The helper derives the repository from its own location and reads the candidate's operator
`SOURCE-MANIFEST.json`. Each run writes to a new unique `run-*` child of DIR, and symlinked
ancestry is refused. Node children get a scratch HOME/TMPDIR, no inherited credentials, and
`tests/fixtures/sp1301_event_segment/tripwire.mjs` preloaded, which fails any fetch, socket, DNS
or http(s) attempt. The tripwire catches mistakes; it is not a sandbox. Each run records argv,
cwd, exit codes, runtime versions, test names and counts, raw stdout/stderr with their hashes,
file hashes, and per-commit `Material-Author` trailers in `manifest.json`, and writes its hash
to `manifest.json.sha256`.

## Limits

- Only covers the activity relational checks. The full Worker route (auth, gate) is exercised by
  the unchanged `tests/test_fleet_activity.mjs`, not by the new file.
- Full repository suites, full discovery and exact-head required CI belong to the operator. They
  remain OWED.
- Synthetic data only. No real fleet records, network, model calls, live paths or deploys.
