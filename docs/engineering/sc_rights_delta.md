# SC-RIGHTS-DELTA: compare two frozen rights observations

`scripts/coast_diagnostics/rights_delta.py` is an offline diagnostic. It shows how the
source rights and attribution rows emitted by
[`skippercast.seafloor.rights`](../../src/skippercast/seafloor/rights.py) differ between
two frozen observations. It does not generate attribution content and does not render it.
The rights page and viewer keep their existing owners. The tool also does not decide whether
a change is legally better, infer public-domain status from a host or label, retrieve a
policy, or grant any permission.

Every report carries `semantic_approval: false`, `publication_allowed: false`,
`permission_effect: "none"` and `coverage_claim: "observed-rows-only"`. A report is
REVIEW REQUIRED evidence. It is not a rights attestation.

## Input: `sc-rights-observation-v1`

This envelope is new and offline. It is not an existing rights attestation, and the
synthetic fixtures are not retrospective approval evidence. It has exactly these fields:

| field | contract |
| --- | --- |
| `schema` | `sc-rights-observation-v1` |
| `producer` | exactly `code_commit` (40 lowercase hex), `module_path` (`src/skippercast/seafloor/rights.py`), `module_sha256` (64 lowercase hex), `function` (`source_rights` or `feature_rights`) |
| `source_use` | `noncommercial` or `for-profit` |
| `rows` | at most 4096 objects using only the keys `source_rights` emits: `source_id`, `license`, `source_url`, `policy_url`, `attribution`, `notice`, `commercial_use`, `navigation_use`, `reviewed_on`. Values are strings, booleans or null |
| `canonical_rows_sha256` | SHA-256 of `json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8, plus one LF. This is not the hash of the enclosing file |

`build_observation(rows, producer=..., source_use=...)` wraps producer rows in this envelope.

## Outcomes and exit status

| status | exit | when | output |
| --- | --- | --- | --- |
| `COMPARED` | 0 | both sides are valid, both producer objects are complete and identical, and `source_use` is identical | report with `changes` |
| `UNVERIFIED` | 3 | a producer is absent or incomplete, the producers differ, `source_use` is absent, or `source_use` differs | report with `binding_mismatches` and `unverified_reasons`, and `changes: null` (no delta is computed) |
| `INVALID` | 2 | wrong schema, missing or unknown (authority-bearing) fields, a malformed producer, an unsupported value shape, a duplicate `source_id`, too many rows, a hash mismatch, duplicate JSON keys, NaN/Infinity, or bad UTF-8. Usage errors also exit 2 | nothing written; a diagnostic goes to stderr |
| `REFUSED` | 4 | a symlink anywhere in the path, a non-regular input (FIFO, directory), a missing file, more than 2 MiB per file or 16 MiB in total, an expected-hash mismatch, an output that already exists or has a symlinked ancestor, or a report over 8 MiB | nothing written |

`INVALID` on either side takes precedence over `UNVERIFIED`, which takes precedence over
`COMPARED`. Inputs are never modified.

## Comparison

- Rows are matched on the exact `source_id`. IDs that differ only in case are different
  sources; the report also records them as a `SOURCE_ID_CASE_VARIANT` note.
- Each change row has `source_id`, `pointer` (a JSON Pointer into the row), `before_present`,
  `before`, `after_present` and `after`. A missing key, an empty string and null are three
  different states.
- Values are compared exactly and by type. Credit and notice strings are never normalized,
  so a difference only in whitespace or letter case is still a change.
- An added or removed source keeps every one of its fields as a change row and is also
  listed in `sources_added` or `sources_removed`. When a term field (license, policy URL,
  attribution, notice, commercial use, navigation use or review date) is removed, or a
  whole source is removed, the report flags it `*_NOT_A_GRANT`. The removal is a diff, never
  a permission.
- Changes are sorted by (`source_id`, `pointer`) in code-point order. When only the row
  order changes there are no field changes, and the report sets `row_order_changed: true`.
- The output is deterministic ASCII JSON. Raw strings are kept, JSON-escaped and never
  executed or rendered.
- `input_pins` records, for each side, the producer, the `source_use`, the
  `canonical_rows_sha256` and the row count. The CLI adds the raw envelope file SHA-256 and
  its byte size.

## CLI

```
python3 scripts/coast_diagnostics/rights_delta.py --left A.json --right B.json --out NEW.json \
    [--left-sha256 HEX] [--right-sha256 HEX]
```

The tool reads only the two named files and never follows a path that appears inside a
document. It writes one new file with exclusive create, so an existing output is never
replaced.

## Acceptance

```
python3 scripts/accept_sc_rights_delta.py --suite focused|contract|negative --output <new-run-dir>
```

The runner pins `sys.path` to this repository and turns off bytecode writing. Before it
imports any project module, it installs sentinels for DNS, sockets, HTTP, subprocesses and
model clients, plus an audit hook that limits file access. Reads are confined to the
repository's `src/skippercast`, `scripts` and `tests` trees, the stdlib and the run
directory, and writes are confined to the run directory. It then runs the plain test functions in
[`tests/unit/test_sc_rights_delta.py`](../../tests/unit/test_sc_rights_delta.py) in-process,
and pytest collects the same functions. The contract suite checks that opening
deployment policy and catalog files is denied. The negative suite uses in-memory doubles
that normalize credit text, disable the producer binding, or disable the unknown-field gate.
Each double must make its exact regression fail and leave an unrelated control passing.
Each run writes `receipt.json` and `console.txt` into a new directory.

The synthetic producer inputs in
[`tests/fixtures/sc_rights_delta`](../../tests/fixtures/sc_rights_delta/producer_inputs_left.json)
are passed through the real `source_rights` with `today=2026-10-24`. The resulting
observations are byte-frozen and bound to the measured producer module hash. A changed
`rights.py` is a different producer and yields `UNVERIFIED`.
