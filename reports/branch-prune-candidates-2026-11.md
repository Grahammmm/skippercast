# Branch prune candidates, November 2026 (read-only, stage 1)

This report lists which remote branches of `Grahammmm/skippercast` could be
deleted later. **Nothing was deleted or changed.** G's ruling of 2026-11-15
keeps the retire/delete HOLD in force, and deleting refs is a separate attended
step that waits for G to lift that hold (see "Stage 2").

Counts below describe `origin/main` at `7db22f216e2dc91cb0158d840091f9a1f5254156`.
A later reader should compare with their own `git rev-parse origin/main`.

## Method

Run on a fresh clone with read-only commands only: `git for-each-ref
refs/remotes/origin`, `git branch -r --merged origin/main`, `gh pr list --state
open` and `git grep` on main. A throwaway script (not committed) wrote the TSV.
No `git push --delete`, `gh api -X DELETE` or `git branch -d -r` was run.

A merged ref is a **candidate** only if both exclusions are clear:

1. It is not the head of an open PR (`open_pr_head`).
2. Its tip SHA is not cited in tracked text on main (`tip_sha_cited_in_tracked_text`).
   Any hex token of 7 to 40 characters in a tracked file that is a prefix of the
   tip SHA counts as a citation, so the check errs towards keeping refs. A merged
   ref can still be a receipt anchor, for example the branch retained for #738.

Protected and never listed: `main`, `conditions`, `data`.

## Counts on this main

| Measure | Count |
| --- | --- |
| Remote branches (excluding the HEAD alias) | 2112 |
| Merged into `origin/main`, including `main` | 1535 |
| Merged, excluding `main` (rows in the TSV) | 1534 |
| Candidates (`candidate=yes`) | 1518 |
| Merged but tip SHA cited in tracked text (`candidate=no`) | 16 |
| Merged and open-PR head | 0 (8 open PRs) |
| Unmerged, not `batch/*` | 562 |
| `batch/*` total / merged / unmerged | 17 / 2 / 15 |

The 16 cited refs are in the TSV with `candidate=no`: `claude/p1-02a-research-scripts`,
`claude/perf-baseline-1-t18f59404`, `claude/rules-2027-dates-v2`,
`claude/t06-governed-live-discovery`, `codex/coast-mvp-c4-t_43c627bd`,
`codex/fish-government-habitat`, `codex/scb-17-region-promotion`,
`codex/seafloor-rollout`, `feat/bopus-t_65fb17b8`, `feat/s-019-segment-receipt-schema`,
`feat/s-021-coast-recipe-schema`, `feat/s-029-receipt-checker`,
`hermes/fix-planner-screening-expiry`, `rb/uxfix-06-signed-2`,
`skippercast/t_0da2d434`, `skippercast/t_3bbf6e30`.

The #738 squash commit `050b242f…` is a commit on main, not a branch tip, so it
does not appear in the TSV.

## Corrected target

The 2026-10-31 plan aimed for `git branch -r` under 100. That cannot follow from
deleting merged refs: 2112 minus 1534 merged leaves 578 refs (562 unmerged
non-`batch` including `conditions` and `data`, 15 unmerged `batch/*`, plus `main`). The
2026-10-31 figures (922 branches, 475 merged) are also stale. Corrected target:
**every remaining ref is `main`, `conditions`, `data`, an open-PR head, or an
explicitly retained unmerged ref.** There is no numeric cap.

## `batch/*` refs are not candidates

Only 2 of the 17 `batch/*` refs are merged (`batch/20261027-232241`,
`batch/20261028-005823`) and they are in the TSV like any other merged ref. The
other 15 are unmerged, so the "merged" rule does not cover them; they would need
an explicit per-ref retirement statement. No file on main supplies one, so they
are **not candidates**:

`batch/20261027-202604`, `batch/20261027-211915`, `batch/20261027-214956`,
`batch/20261027-215815`, `batch/20261027-222351`, `batch/20261028-003737`,
`batch/20261028-004755`, `batch/20261028-020927`, `batch/20261028-021959`,
`batch/20261028-042331`, `batch/20261028-052451`, `batch/20261028-053508`,
`batch/20261028-054538`, `batch/20261028-055553`, `batch/20261028-060620`.

## Checks run

- TSV rows (1534) equal "merged excluding main" (1534); `origin/main`,
  `origin/conditions` and `origin/data` are not in it.
- No row has `candidate=yes` with `open_pr_head=yes`. A synthetic row with both
  set was flagged by the same check (1 flagged; 0 of the real rows).
- `git ls-remote --heads origin | wc -l` was 2112 before and after the work, so
  no ref was deleted. Concurrent pushes by others could move it by a few.
- Branch and PR counts move with every push; re-run before acting.

## Stage 2 (not part of this PR)

After G lifts the retire/delete HOLD, an attended operator re-runs the same
queries on the then-current main, re-checks `candidate=yes` rows against open
PRs and cited SHAs, and deletes in a separate, logged step. The TSV at this
commit is the input list, not authority to delete.
