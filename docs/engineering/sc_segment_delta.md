# SC-SEGMENT-DELTA: explain two frozen segment receipts

`scripts/coast_diagnostics/segment_receipt_delta.py` compares two original
`coast-segment-receipt-v1` JSON files for the same coast segment and explains
what changed. It is a read-only, offline, metadata-only diagnostic. A report is
REVIEW REQUIRED, never semantic, scientific, closure or publication acceptance.

```
python3 scripts/coast_diagnostics/segment_receipt_delta.py --left BEFORE.json --right AFTER.json --out NEW-REPORT.json
```

## What it does

1. Reads exactly the two named files and the pinned local schema
   `skills/coast-campaign-shared/schemas/coast-segment-receipt-v1.schema.json`
   (SHA-256 `73dc8b02...6550`; a different schema is refused). Strict JSON:
   duplicate keys, `NaN`/`Infinity` and overflowing numbers are refused.
2. Validates each receipt's shape (Draft 2020-12). Every `format` the schema
   names must have an enforced local checker (today only `date-time`: strict
   RFC 3339 section 5.6 with ASCII digits, a real calendar date, hour 00-23,
   minute 00-59, second 00-60 and a valid offset). jsonschema's optional
   third-party format packages are never relied on. A schema format with no
   enforced checker is refused as a `capability:` error (exit 2) rather than
   silently skipped. The schema may not contain `$ref`; any remote retrieval
   attempt raises. No network is used.
3. Recomputes each `determinism_digest` with the frozen S-019 v1
   `content_identity` projection: SHA-256 of sorted, compact UTF-8 JSON with no
   trailing newline (the producer `object_digest` convention). A mismatch is
   INVALID. Raw file hashes (`input_files.*.raw_sha256`) are recorded separately
   from this canonical digest.
4. Refuses a different `segment_slug`, `campaign_segment_id` or
   `coordinator_segment_id` as `NOT_COMPARABLE`.
5. Otherwise writes an `sc-segment-delta-v1` report.

It does not call `validate_receipt()` or `Resolver.read()` and never stats or
opens any file, archive or raw source named by a Ref; every Ref is inert
declared text. It never reruns, resumes, hashes payloads, accepts outputs or
verifies closure (S-019, S-022, S-024 and S-026 keep those duties).

## Report

| Field | Meaning |
| --- | --- |
| `status` | `DIAGNOSTIC` or `NOT_COMPARABLE` |
| `content_changes` | ordered RFC 6901 leaf changes inside `content_identity` |
| `bookkeeping_changes` | ordered leaf changes in the excluded envelope: `created_utc`, `author_profile`, `author_model`, `card_id`, `run`, `closed`, `signoff`, `archive` |
| `facets` | the same rows grouped as code, tool, parameters, recipe, source, output, qa, tier and reference (each row adds `section`) |
| `producer` | `changed` and pointers of code/tool/recipe content changes |
| `determinism_digest` | declared and recomputed digest per side, and `changed` |
| `input_files` | raw file SHA-256 and byte count per side (`supplied=false` when the API got parsed objects) |
| `declared_closed` | the declared `closed` value before and after; no verdict is issued or revoked |
| `identity_changes` | NOT_COMPARABLE only: the differing identity fields |

Each change row has `pointer`, `before_present`, `before`, `after_present` and
`after`. A missing value (`*_present=false`) is distinct from JSON `null`.
Object keys are walked in sorted order and arrays by index, so reordering is
shown, never normalized away. Scalars are compared by their canonical JSON
encoding, exactly as the digest sees them: a changed numeric type (`1` versus
`1.0`) and a changed zero sign (`0.0` versus `-0.0`) are changes, while equal
encodings are not. After diffing, every content field whose canonical bytes
changed must have rows under its pointer and no other field may have rows;
otherwise the input is refused.

Every report carries `evidence_scope=declared_metadata_only`,
`referenced_bytes_verified=false`, `semantic_approval=false`,
`closure_verified=false` and `semantic_comparability=UNVERIFIED`. A changed
producer is shown; a matching producer still does not prove scientific
comparability.

## Exit codes and bounds

`0` valid same-segment diagnostic, `1` NOT_COMPARABLE (report still written),
`2` malformed or unsafe input; nothing is written.

Tool-local bounds (this new tool only; no existing production cap changes):
2 MiB per input file, 16 MiB aggregate input, 4096 change rows, 8 MiB output,
nesting depth 64 containers and 2,097,152 JSON values per receipt. The depth,
node and JSON-type gate runs iteratively before any recursive step (schema
validation, copying, diffing) on both the raw-bytes and parsed-object API
paths. Deep, cyclic, shared-subtree or non-JSON input is therefore exit 2 with
no partial output, never an uncaught `RecursionError`.
Paths must be normalized; every ancestor and the file itself are opened without
following symlinks; inputs must be regular files (FIFOs and devices are refused
without blocking). `--out` must not exist and is created exclusively, with
deterministic sorted JSON and nonfinite values forbidden.

## Acceptance

`scripts/accept_sc_segment_delta.py --suite focused|contract|negative --output DIR`
runs `tests/unit/test_sc_segment_delta.py` in-process with only the standard
library and jsonschema, after disabling bytecode, installing offline sentinels,
pinning the import path to this checkout and redirecting temporary and work
files into a new write-once run directory. `DIR` must be normalized. It is
opened from `/` one component at a time without following symlinks, and a
symlink or non-directory anywhere in it is refused with exit 2 before anything
is created. Missing trailing components are created relative to the verified
parent descriptor. The run directory is created exclusively, and evidence files
are written relative to its descriptor with no overwrite and no symlink
following. The negative suite also proves each
regression check fails against an in-memory broken double and passes once it
is removed. The test module is written to be collectable by pytest as well, but
local pytest collection is UNVERIFIED (pytest is not installed in the staged
runtime; full discovery is operator-run). Local success is not full CI.
