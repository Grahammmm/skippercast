# Runbook: retain reversible regional relief releases

Before freeing space, check which generations the reviewed release history
still needs, then verify rollback against the live site. Neither check
approves deletion.

## 1. Run the retention plan

From the repository root with the relief tools installed, run
`scripts/relief/retention_plan.py` with Python. Pass the root of a clean,
full clone checked out at current `main` as `--repo` and the local pipeline
output root as `--out`. Omit region IDs to include both historical catalog
regions and regions found in that output root.

| Report entry | What it means |
| --- | --- |
| `keep` | A reviewed pointer in this region's history names this generation. Keep it even if it has no role label. |
| `live` | The newest reviewed pointer version names this generation. This label describes Git history, not what the site is serving. |
| `rollback` | The preceding reviewed pointer version names this generation, if there is one. Both role labels can apply to the same generation. |
| `unreferenced` | A local generation directory under `release/` or `review/` that no reviewed pointer in the region's checked-out history names. This is a candidate for owner review, not permission to remove it. |
| `missing-local` | A `keep` generation with no local directory in either location. It still must be kept; the report says nothing about whether the site has a usable copy. |

The plan does not write, move, or delete anything. Directory presence does
not prove the local artifacts are complete or that the archive is served.

## 2. Check rollback on the live site

After reviewing the plan, run `scripts/relief/rollback_ready.py` with Python
for each affected region. Use the same clone for `--repo`, pass the region ID
as `--region`, and use the live site (the default is `https://skippercast.com`).
Confirm the relevant release is deployed before relying on this check.

This checks the archive the actual rollback would restore. It uses the prior
catalog state, which can differ from the previous pointer version shown by
the plan (for example, after a contours-only change). `PASS` covers that
rollback target, not every historical archive. `rollback: removes relief
(no earlier release)` means there is no prior archive to check for that
rollback; it does not authorize cleanup. On a failed check or uncertainty
about a required copy, stop and bring the evidence to the release owner.
See [Roll back a regional relief release](relief-rollback.md) for an actual
rollback.

## 3. Leave any cleanup to the owner

**Deletion is never automated.** Only the release owner may free space, in
an attended action outside this repository's automation and with explicit
approval for the exact items. Recheck current history and the output root
before acting; if either has changed, rerun the checks. Never remove any
generation named by any reviewed pointer: keep live, rollback, and all older
reviewed generations. A report, a passing check, or an age cutoff cannot
override that rule. This runbook does not authorize R2 cleanup or lifecycle
changes; see [Coherent R2 feed publication](r2-snapshots.md#retention-and-verification)
for the separate feed retention guidance.
