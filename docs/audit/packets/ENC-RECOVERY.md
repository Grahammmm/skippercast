# ENC recovery: current-base integration

Canonical ID: `SC-FE422-body-14-03`. Repository: `Grahammmm/skippercast`.

Status: prepared first Claude batch; coordinator must confirm the three file reservations and actual fresh base before edits. This task excludes Flock digestion, installed mapping, all native/provider work, backup/Hermes, and other audit rows.

## Deliverable and files

Recover from a transient ENC tile failure only when a tracked currently loaded tile completes for the same source object, source ID and region/context. Clear only the chart warning, preserve other failures, reject stale region and away/back completions, and preserve destroy/lifecycle fences. The existing reviewed donor already implements this behavior; integrate it with current source instead of redesigning it.

Allowed product/test paths:

- `web/map/chart.ts`
- `web/map/engine.ts`
- `tests/test_map_layers.mjs`

The [exact approved code-only donor patch](enc-recovery.patch) is included for source integration; verify its hash before use. Original review/acceptance receipts remain with the coordinator; their engineering summary is retained below. Exact donor SHA256: `9275793dd2ebd2ccf7a0b148315098a75c2720b628e3c5709fbc32a7bfcdc3ad`, on historical base `26ed58a71b2b0966b886cb3030fc1c5ce5740372`. Do not invent a donor commit: it was an exact uncommitted patch. Retained independent source approval and 19/19 focused fake/component cases exist. That evidence is not current supported-runtime or real-browser acceptance.

## Work sequence

1. Read current AGENTS.md, CONTRIBUTING.md and the packet's confirmed issue. Check clean status and ownership before creating the isolated worktree. Ask the existing publisher for the accepted current main object when unavailable; do not fall back to the historical base as a release base.
2. Compare the three current files against the donor. Preserve all current theme assertions and unrelated behavior. Resolve only demonstrated integration differences; return a conflict requiring shared scope to the coordinator.
3. Seal exact base/head/tree, patch, owned paths and proof all other entries are preserved. Record source/context and overload controls retained. An independent non-author reviewer checks final compatibility using the original donor review; do not replay a full component audit.
4. Qualify the supported Node/dependency inputs from the current lockfile and available environment. Reuse the historical 19-case result where the exact input is unchanged. Do not rerun it merely to produce a fresh handoff receipt. If source/test changes invalidate it, identify the changed assertion boundary and ask the coordinator to bind the surviving test allowance before invoking. Stop on the first unexpected failure; no automatic retry, timeout inflation, skipped assertion or forced click.
5. The final eligible PR needs normal repository checks, actual metadata/DCO and any required current browser acceptance. Never use a provider request or synthetic result to claim real ENC ingestion/freshness.
6. Existing SkipperCast publisher owns protected merge/deployment. Claude can merge its assigned reviewed, green PR only after that task's release ownership is explicitly transferred and no other release is active. Otherwise provide the eligible exact head and leave the publisher to finish.

## Acceptance, evidence and rollback

The narrow regression retains overloads and source identity, stale/away-back region, unrelated/errored/untracked tiles, repeat error, warning isolation and lifecycle assertions. Existing focused result: 19 passed, zero failed/skipped, one approved Node execution after an ENOSPC log-open failure that launched no Node; earlier 17-pass/1-fail history remains. No historical or current model change resets attempts. No new focused runtime allowance is granted by this packet.

Attach concise original-versus-current evidence, exact changed check results and independent review. Record CI head and run, merge/deployment revision, relevant canonical site/artifact readback and remaining holds. Claim only what was checked. The task is source/integration acceptance, not installed coastal or native science acceptance.

Rollback: preserve donor and previous accepted refs; revert only this admitted three-path delta and its material-change note if needed. Never reset unrelated branches or delete datasets, originals, caches or failed evidence. On completion update the issue, hand off or finish reserved release verification, release file ownership, then take only the next coordinator-assigned ready task. If no such task exists, report exact vacancy rather than invent work.
