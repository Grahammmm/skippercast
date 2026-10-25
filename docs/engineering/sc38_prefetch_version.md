# SC38: integer schema_version for coast prefetch plans

`skippercast.coastal.prefetch.load_plan` reads the raw-campaign inventory plan.
It used to check only `plan.get('schema_version') != 1`. In Python `True == 1`
and `1.0 == 1`, so a plan whose JSON said `"schema_version": true`, `1.0` or
`1e0` was accepted as version 1.

The check now also requires `type(schema_version) is int`. A plan whose
version is anything other than the integer 1 raises the existing
`Hold('Expected schema_version=1 and files array')`. The hold happens before any
file row is checked: `session.check_url` and `filename()` are not called, and
nothing is written. Valid plans behave exactly as before. That includes
duplicate-URL segment merging, conflicting-duplicate refusal, ordering and the
dry-run totals. No new schema, version migration, transfer, retry, allowlist or
cap change is part of this.

## Tests

`tests/unit/test_sc38_prefetch_version.py` reads real JSON plans from
`tests/fixtures/sc38_prefetch_version/` through the complete `load_plan`. It
uses an explicitly supplied offline `Session` with a synthetic one-host
allowlist and a recording `check_url`. The resolver, connection, proxy, cache
and `request` all refuse. An autouse fixture redirects `MOUNT`, `RAW`, `MIRROR`,
`RETRY_STATE`, `STATUS` and the `Prefetch` bound defaults under `tmp_path`. It
also makes `Prefetch`, `TransferSession`, `default_allowlist`, DNS and socket
connect raise. No test constructs `Prefetch` or runs a transfer.

- A1: an integer-1 plan loads. The duplicate-URL segment union, conflicting
  duplicate refusal and dry-run totals are unchanged.
- A2: `true`, `false`, `1.0`, `1e0`, `"1"`, `null`, `{}`, `{"major": 1}`, `[]`,
  `[1]`, `0`, `2`, `-1` and an absent version are each held before
  `check_url`, normalization or output. Version-1 plans with a non-array
  `files` or an empty `files` stay independent controls.
- A3 (`test_mutation_controls`): the baseline function is rebuilt in-process
  from the genuine `load_plan` source by removing only the new type gate. Its
  source hash must equal the recorded baseline `load_plan` source hash. That
  baseline accepts `true`, `1.0` and `1e0`, so the same rejection assertion
  fails under it. Integer 1 is accepted identically by both. The production
  file is not edited.

## Acceptance runner

```bash
python3 research/scripts/accept_sc38_prefetch_version.py --suite focused  --output OUT/author-focused
python3 research/scripts/accept_sc38_prefetch_version.py --suite contract --output OUT/author-contract
python3 research/scripts/accept_sc38_prefetch_version.py --suite negative --output OUT/author-negative
```

- `focused` runs every case in the new file.
- `contract` runs the four unchanged input-plan selectors in
  `tests/unit/test_coast_prefetch.py`, plus `tests/contract/test_research_boundary.py`
  and `tests/contract/test_test_layout.py`.
- `negative` runs `test_mutation_controls`.

The runner disables bytecode writing. If the invoking interpreter lacks pytest,
it re-executes once with the checkout's own `.venv/bin/python3` and records both
interpreters. Before any product import, it points `HOME` and `TMPDIR` into a
new write-once run directory and puts this checkout's `src/` first on
`sys.path`. It also installs audit-hook sentinels for network,
subprocess/exec, model-client imports and writes outside the run directory.
It then checks that the `Path.home()`-derived prefetch constants landed inside
that directory.

Each run writes `receipt.json`, `stdout.txt` and `stderr.txt`. The receipt
records argv, cwd, interpreter, package versions, source and fixture hashes,
collected node IDs and per-test outcomes. The runner exits 0 only when the
collected IDs equal the frozen list and every test passed with no skip, xfail,
collection error or sentinel violation.

A pass is review-required evidence only. It is not full CI, source/live
qualification or semantic acceptance. The full suite stays with CI.
