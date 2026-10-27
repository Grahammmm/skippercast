# SC-METADATA-OBJECT: cached metadata must be a JSON object

## Defect

`skippercast.coastal.cached_inventory.read_metadata` reads a metadata descriptor
with a bounded verified read, checks its SHA-256, decodes the JSON and memoizes the
result by descriptor digest. Before this change:

- for the `cached-source-json-v1` contract the schema-member check was skipped, so an
  array, `null` or scalar document was returned **and inserted into the cache**; the
  consumer (`inventory`) then failed later with `TypeError` / `AttributeError`;
- for schema-bearing contracts (for example `coastal-discovery-lead-v1`) the check
  called `value.get(...)` on the non-object and raised `AttributeError` instead of a
  controlled `ValueError`.

## Change

One line in `read_metadata`, immediately after `json.loads` and before any schema
access or cache insertion:

    if not isinstance(value,dict):raise ValueError("metadata JSON object required")

Unchanged on purpose:

- pre-read descriptor, size, hash-format, path, suffix and allowance checks and their order;
- the bounded read and its accounting: bytes and files actually read stay charged on
  this rejection (no rollback);
- hash mismatch still fails first (`metadata hash changed`); malformed JSON still
  raises the decoder's `json.JSONDecodeError`;
- a valid object is cached and reused for an identical descriptor without another read.

A failed parse is never cached, so a corrected file is read through its own new
descriptor.

Out of scope (owned elsewhere): empty-object header/rights/scope semantics (audit
t_93db5d9b finding 8), cumulative byte accounting (HARDEN-COAST rank 3),
epoch/freshness (SC-CACHE-CLOCK), and `epoch`, inventory selection, source rights,
retry policy, URL admission and source-payload access.

## Tests and acceptance

- `tests/unit/test_sc_metadata_object.py`: `test_a1_*` positive contract,
  `test_a2_*` failure/preservation contract, `test_a3_*` mutation controls (test-local
  callables restore the old generic bypass, cache-before-check and refund-on-reject;
  each must fail its specific tagged assertion while a valid object passes).
  Synthetic JSON metadata under `tmp_path` only; network and model-client sentinels.
- `tests/fixtures/sc_metadata_object/nonobject-cases.json`: the non-object payloads.
- `research/scripts/accept_sc_metadata_object.py --suite focused|contract|negative --output DIR`:
  offline runner that calls the installed pytest API in-process and writes a
  write-once receipt. It needs pytest and jsonschema importable from the
  interpreter that runs it; if either is missing it exits 3 (`INPUT_UNAVAILABLE`)
  and runs nothing.

A pass is REVIEW REQUIRED, not full CI, source qualification or semantic acceptance.
