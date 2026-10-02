# Bounded regional worker groups

The H11952 production run scheduled 32 reach jobs. At 04:48 UTC on October 2,
five completed reach jobs had taken 37–63 seconds each, while several-minute
GitHub-hosted runner waits separated their starts. The bottleneck was repeated
runner acquisition rather than failed scientific processing.

Group up to three assignments from the same region into one runner job. Applying
the grouping to that exact 32-reach matrix produces **13 runner jobs**, preserving
every assignment exactly once. This removes 19 runner starts (59%); it does not
promise a measured wall-time improvement until production runs the new workflow.

The original prepared reach matrix remains authoritative for publication and
ledger reconciliation. The derived worker matrix changes only scheduling:

- At most three worker jobs run concurrently, each processing its reaches
  sequentially. Regional grouping also permits existing checked source files to
  be reused on the same filesystem.
- Every reach runs the existing single-reach command in its own Python process
  with a 60-minute timeout. The group has 195 minutes for three maximum-length
  reaches plus job setup and cleanup.
- A failed source, computation, subprocess or receipt upload does not stop later
  reaches in the group. An incomplete group exits unsuccessfully.
- Original per-reach recovery objects and current-batch receipts are unchanged.
  The group never invents a successful receipt or publishes anything.
- Publishers consume the original matrix and require checked current-batch
  results. Missing or mismatched results hold their region. Other regions can
  still complete through the existing independent publishers.
- A failed-job retry retains the prepared batch ID. Already completed work still
  passes the normal cache/native-byte checks; no routine forced rebuild is added.

Catalog selection, source rights, native resolution, coverage and terrain
algorithms, rankings, spatial screening, publication revision checks and archive
verification are unchanged. The scheduling module is outside the physical
implementation hash, so this change alone does not invalidate terrain caches.

Validation includes exact assignment preservation, empty/tail groups, rejection
of duplicate/unknown/cross-region assignments before processing, real per-reach
failure receipts, continuation after transport failure and timeout, CLI failure
status, original retry identity and unchanged publisher matrix. The focused
orchestration/publication/workflow suite passes 39 tests and 28 subtests.

Existing commands and the daily workflow remain the entry points. The grouped
worker's internal command is:

```sh
python -m skippercast.seafloor.jobs run-group --region REGION_ID \
  --reaches '["REACH_1","REACH_2"]' --batch EXISTING_PREPARED_BATCH
```

Do not manually invent a production batch or run a competing publisher.

## Avoid duplicate check-suite queues

The prior CI triggers started the same four full-check jobs on both a branch
push and its pull-request update. This created eight jobs for one PR revision,
in addition to the separate sign-off check. Restrict the push trigger to `main`;
retain the unrestricted pull-request trigger and the manual dispatch needed for
bot-created ledger PRs. All test jobs, permissions and required check names are
unchanged. This removes four duplicate runner jobs per ordinary PR revision.

PR-number concurrency cancels obsolete revisions of that PR only. Main and
manual-dispatch runs are not interrupted; the seafloor production lock also
retains `cancel-in-progress: false`. Runs queued before this policy do not gain
retroactive cancellation. This follows GitHub's documented
[event filters](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#using-filters)
and [workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
