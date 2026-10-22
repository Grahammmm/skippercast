# Mapping publication receipts

`mapping_claim_guard.py` requires three distinct regular JSON files before a
job may have state `published`. File names carry no authority. The job retains
`receipt_paths` (three strings) and adds `receipt_sha256`, mapping each exact
path string to the independently pinned SHA256 of that file's raw bytes.
Relative paths resolve against the checkpoint directory.

Each file is at most 64 KiB and contains an object such as this synthetic example:

```json
{"schema":"mapping-publication-receipt-v1","role":"rights","job_id":"synthetic-job","status":"PASS","holds":[],"holds_added":[]}
```

Exactly one file must declare each role: `rights`, `restriction`, `live_readback`.
Every schema, job ID, status and raw-byte pin must match. Missing/duplicate roles,
failed statuses, nonempty or malformed holds, symlink leaves, aliases/hardlinks,
missing files, malformed JSON and changed bytes are refused. Existing unpinned
filename-only checkpoints must supply valid role receipts and independently
recorded pins; merely renaming or hashing a failed receipt cannot clear it.

These are coordinator attestations of recorded checks, not signatures or
scientific, legal or publication authorization. No receipts are generated and no
live publication occurs during checkpoint validation.
