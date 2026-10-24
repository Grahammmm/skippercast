---
name: coast-segment-close
description: Close a coast segment by archiving its full retained provenance, verifying the archive without the hot tree, and proposing an operator-only cache release.
---

# Purpose

Closing a segment has three steps (design rev4 sections 4.2-4.4 and 7.8):

1. archive the segment's full retained provenance graph;
2. prove the archive is complete using only the archive and the raw mirror;
3. propose a hot-cache release that only the operator may execute.

A bounded worker prepares the archive and the release list. Only the operator
deletes anything. These are draft offline helpers. Closure is not map acceptance,
and structural validity is never scientific acceptance.

# Runs on

The bounded worker admitted on the card runs `archive_segment.py` and
`verify_archive.py`. `release_hot_cache.py` is OPERATOR ONLY and is never run
by a headless agent. Tests may unlink only their own synthetic temporary files.

# Inputs

- An accepted, closed campaign inventory. Every current plan's latest verdict
  must be `accept`, with no pending correction or replacement. Every final window
  must be `map_done`, or held/failed_terminal/cancelled with an explicit accepted
  closure cause.
- Operator root bindings (`--roots`): `queue:<segment>` -> C, `repo:<commit>`,
  `archive:<segment>:<close-id>` -> A, and `raw:campaign` -> ARCHIVE_ROOT/raw.
  Use absolute paths. Roots come from the card binding, never from receipts.
- A quiescent campaign: no active execution leases, controllers or admissions.
  The operator must supply the existing PC9 `COAST_EXCLUSIVE_WRITER=C` assertion
  covering all controllers, other admissions and consumers. A lock alone is not
  proof of ownership. Both archive and release acquire the actual coordinator
  lock plus close lock; a read-only private Store snapshot refuses all leases
  (expired included), unsafe states and queued non-render consumers. Store is
  never opened/recovered/mutated to make this check pass. Release holds these
  locks plus both ledger locks through unlink and receipt finalization.
- A unique, never-reused close-id and an empty destination A.
- Enough SanDisk capacity, keeping a reserve of at least 200 GB
  (`--reserve-bytes`, default 200e9). Closed segments go to
  `/mnt/agentorange-backup/skippercast-campaign/`.
- A card-authenticated runtime header JSON (`--header`) with these fields:
  created_utc, author_profile, author_model, card_id, code_commit and
  skill_commit.

# Exact commands

Archive (bounded worker):

```
"$SC_PY" skills/coast-segment-close/scripts/archive_segment.py --roots "$ROOTS" \
  --allowed-root-id "queue:$SEG" --allowed-root-id "repo:$COMMIT" \
  --allowed-root-id "archive:$SEG:$CLOSE_ID" --allowed-root-id raw:campaign \
  --campaign "$C/campaign.json" --src "$C" --dest "$A" --close-id "$CLOSE_ID" \
  --ledger "$C/ledger.jsonl" --campaign-ledger "$COAST_ROOT/campaign-ledger.jsonl" \
  --header "$HEADER"
```

The archive step runs in this order and appends no row early:

1. Copy and re-hash every retained object.
2. Write `ARCHIVE-MANIFEST.json`. This maps each `source_ref` to a `retained_ref`
   with identical hash and bytes. It excludes the manifest itself, the ledger
   snapshots and the release artifacts.
3. Append the `archived` row through `coast_ledger.append`.
   `archive_segment.py` is the only writer of `archived` rows.
4. Copy the final segment and campaign ledger snapshots.

An identical same-writer retry may reconcile a manifest-durable crash using
the immutable original header, inventory, graph and ledger prefixes. It finishes
only missing index/snapshots, never overwrites bytes or duplicates rows. A crash
before the manifest, changed payload, mismatched snapshot or later ledger write
stays refused for attended reconciliation; do not reuse the close-id for a new
close. No archive success is announced before both index and snapshots exist.

Products keep their lease ID in their archive path, so retry evidence is never
overwritten. Runner scratch, live leases and live SQLite are excluded. If a
required reference points to excluded scratch, the archive step stops.

Verify (bounded worker; reads only the archive and the raw mirror):

```
"$SC_PY" skills/coast-segment-close/scripts/verify_archive.py --roots "$ARCHIVE_ONLY_ROOTS" \
  --allowed-root-id "archive:$SEG:$CLOSE_ID" --allowed-root-id raw:campaign \
  --archive "$A" --forbid "$C" --original-queue-roots "$QUEUE_ROOTS" \
  --header "$HEADER" --out "$C/close/$CLOSE_ID/release-list.json"
```

`ARCHIVE_ONLY_ROOTS` supplies the archive and raw roots only. `--forbid` takes
the entire hot tree C. The verifier writes only to the admitted `--out` path and
takes its cache identity evidence from archive preparation. Post the SHA-256 of
`release-list.json` externally for the operator.

Release (OPERATOR ONLY; never run by an agent):

```
"$SC_PY" skills/coast-segment-close/scripts/release_hot_cache.py --roots "$ROOTS" \
  --allowed-root-id "queue:$SEG" --allowed-root-id "archive:$SEG:$CLOSE_ID" --allowed-root-id raw:campaign \
  --list "$C/close/$CLOSE_ID/release-list.json" --expected-list-sha256 "$RELEASE_LIST_SHA256" \
  --ledger "$C/ledger.jsonl" --campaign-ledger "$COAST_ROOT/campaign-ledger.jsonl" \
  --header "$OPERATOR_HEADER" --execute
```

Without `--execute` the release step deletes nothing.

# Acceptance checks

- `verify_archive.py` traverses the whole retained graph. It checks the ledger
  hash chain, the closed inventory, the latest verdicts, result-to-output
  bindings, raw and derived mappings, and every retained object, all without
  reading C.
- The release step runs a full preflight before deleting anything:
  - checks the list hash against the posted SHA;
  - re-hashes the manifest and both ledger snapshots;
  - reruns archive/raw closure with hot reads disabled;
  - confirms the hot ledger tips are unchanged since close;
  - opens and hashes every candidate without following symlinks, and checks
    device, inode, size, mtime and `st_nlink=1`;
  - confirms every candidate sits under `<segment>/cache/`;
  - compares the candidate set to the verified inventory.
- The release step then unlinks one file at a time. Before each unlink it repeats
  the identity checks, then unlinks relative to the directory FD. It never
  deletes a directory or uses a wildcard. It writes `release-receipt.json` next
  to the list. Before the first unlink it reserves that exact write-once receipt
  destination and fsyncs `release-accounting/intent.json`. Every candidate has
  a durable `NNNNNN-before.json` marker before unlink and an `-after.json` marker
  after it. An unmatched before marker means UNKNOWN outcome, not permission to
  retry. Existing receipt/journal evidence refuses without deletion. If final
  receipt I/O fails, the command fails and the journal preserves the prefix;
  an empty/truncated reserved receipt is NOT a completed release.

# Failure modes

These all exit 3, emit no release list and delete nothing:

- a missing product, missing raw source, unmapped cache/source/auxiliary
  reference or changed config;
- an altered ledger line;
- a latest verdict that is `must_fix`, rejected or pending;
- an unresolved inventory item;
- an unknown historical reference;
- insufficient disk;
- a reused close-id with different payload or unverifiable crash residue;
- any overlap with `--forbid`.

Preflight refusals also leave every cache file in place. These include a changed
list, archive, ledger or cache file, a symlinked parent, a hardlink alias, a path
outside `<segment>/cache/`, a failed observation, and a ledger write after
close.

A race or I/O failure after some authorized unlinks stops the release and writes
an honest partial receipt. Multi-file rollback is not promised. Recovery after
any correction needs a new close-id.

# Metrics emitted

- `archive_segment.py` stdout: retained file count, copied bytes, number of
  cache candidates, and `metrics` (`coast-close-metrics-v1`). The latter is
  recomputable from the pinned manifest, without hot reads.
- Release list: proposed `total_bytes` and candidate count.
- Release receipt: actually released files, `released_bytes`,
  `proposed_release_bytes`, and the recomputed `archive_metrics`.

`archived_bytes` categories are logical retained bytes, deduplicated per exact
retained object (root/path/hash/bytes) WITHIN each category: `raw_equivalent`
is cache mapped byte-identically to raw (not newly copied archive bytes),
`derived` is other retained cache input, `products` is retained job lineage
under var/coastal/jobs, and `metadata` is all remaining receipts/config. They
are not physical disk allocation, compression or content-wide dedup claims.
Proposed/actual release counts each listed cache path separately, even for
content-identical copies. `copied_bytes` deduplicates all archive destinations.

`peak_hot_cache` explicitly emits status=unavailable, bytes=null and a reason:
no campaign-wide high-water telemetry is pinned. A close-time candidate total
cannot be substituted for a historical peak. No measured peak is claimed.

Verified booleans in the release list are explanatory only. They never authorize
a release by themselves.

# Never

- Remove or change raw-mirror or archive bytes.
- Assume exFAT permissions.
- Run live deletion as an agent, or delete directories.
- Rewrite receipts or embedded references to force closure.
- Write raw board, Store or Flock ledger rows.
- Publish or send outbound email.
