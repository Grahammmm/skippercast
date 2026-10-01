# Bounded regional publication and checked recovery

Production run 36785181101 completed all 24 reach workers but its single
publisher was cancelled at the 60-minute job boundary. The finish step ran
22:48:39–23:47:08 UTC September 30. Big Sur, Morro and Monterey public feeds were
ready with working PMTiles HTTP206 responses afterward; southern Big Sur and
Arguello/Conception were still updating. This is partial publication, not a
successful full rollout. No precise inner-stage timing was available.

Previously one publisher restored every region's original/normalized surveys
and sequentially built every regional archive under that shared time limit.
Now each region gets an independent publisher with the existing 60-minute
bound and full scientific/source/spatial checks. The matrix does not fail fast.
Successful region receipts and archives survive another region's timeout.
The change is not a claim that an individual region can never exceed its limit.

The small final ledger job reopens current-batch worker receipts, restores their
hash-checked result files and applies summaries; it skips original survey cache
objects and cannot build/upload. No scientific processing/publication path uses
that shortcut. Missing, changed or failed current-batch results remain failures.
Regional publication failures make the aggregate workflow fail after saving
the bookkeeping PR, rather than presenting partial publication as success.

Prepare pins the batch ID across all later jobs. GitHub's failed-job-only retry
retains the successful prepare output and therefore successful worker receipts;
the new attempt number cannot silently invalidate them. A full rerun creates
a new batch as before. Stage diagnostics go to stderr so machine JSON outputs
remain valid and operator logs identify the last active restore/build stage.

Acceptance tests demonstrate isolated southern publication despite an absent
northern result, no northern restore, ledger-only replay without uploads or raw
survey downloads, rejection of corrupt recovered receipts, and workflow wiring
for regional isolation, failure reporting and retained batch identity. Existing
publication tests retain complete polygon, expiry, checksum and native validation.

Merge requires independent review and exact-head CI. After merge, use the normal
main workflow to republish the two held regions; inspect the regional jobs,
canonical export hashes, HTTP ranges and actual map behavior. Do not report this
tested orchestration change as production recovery before those checks pass.
