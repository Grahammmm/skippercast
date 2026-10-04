# Resume completed source tests

Use this when an original source has already produced a bounded negative or
duplicate result. It prevents each new session from treating that lead as an
untested survey. Keep the original scientific receipts and caches.

1. Complete the useful native-window or access test first. Write a concise JSON
   receipt under `var/seafloor/`, recording the original identity, target reach,
   before/after support and candidates, or exact missing input. Do not mark a
   source tested from its title, a bounding box or an unfinished download.
2. Record the decision, covering only the reaches actually reviewed:

```bash
PYTHONPATH=src:. python -m skippercast.seafloor review-source \
  --source EXISTING_CANDIDATE_ID --reaches REVIEWED_REACH_IDS \
  --outcome no-incremental-support --evidence var/seafloor/BATCH/proof.json \
  --note 'Complete original source compared against the current source set.'
PYTHONPATH=src:. python -m skippercast.seafloor plan --region REGION_ID --json
```

Other outcomes are `no-valid-shallow-support`, `already-qualified`,
`needs-original-input` and `access-failed`. These are human-reviewed discovery
decisions, not automatically inferred scientific findings. The private
checkpoint embeds a bounded evidence document and its hashes. The source row,
rights, physical receipts, rankings and public map are untouched.

Only a matching completed review that covers the whole requested planning scope
is deferred. A region-specific decision cannot hide a lead for the whole coast.
Deferred leads remain visible separately, including the reason and expiry.
Unchanged negative results expire after seven days; materially new publisher
input or a different useful method can justify an earlier review. A new record
replaces only the same source ID. One coordinator owns checkpoint writes across
both chats; source workers supply evidence and do not overwrite shared state.

The conservative identity covers the full physical source catalog, native
reference, reach partitions, habitat rules, atlas, processing code and pinned
survey requirements. Any change reopens the lead. Unrelated source changes may
also reopen it; avoiding false suppression takes priority over perfect reuse.
Legal-snapshot refreshes alone do not reopen a physical source test. Invalid,
incomplete, corrupt or expired reviews leave leads actionable. Neither a saved
negative nor an empty queue establishes that the coast is complete.

For a processing host with the existing private R2 environment, append
`--save-private`. This saves only
`var/seafloor/source-review/checkpoint.json` in its own `source-review` recovery
scope. Scheduled preparation restores it before planning. It cannot overwrite
the separate reference, screen or reach inventories. Without that flag the
checkpoint persists in the current checkout only. Do not copy credentials,
create another scheduler or dispatch a publication merely to save a review.

If all remaining source tests are deferred or require unavailable original
measurements, switch to an independent useful task or report the precise missing
producer input. Do not rerun maintenance or issue another broad audit as mapping
progress. A checkpoint saves work; it adds zero mapped area by itself.
