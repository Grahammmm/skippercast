# SC-CATALOG-ROWS: unique literal candidate identities in frozen catalog diffs

Status: REVIEW REQUIRED. Scoped local tests only; not full CI, source
qualification, live discovery or semantic acceptance.

## Defect

`skippercast.coastal.live_discovery._candidates` built its identity map with a
plain dict comprehension over `candidates[*].source_id`. Two rows with one ID
collapsed silently to the LAST row, so `diff` reported an ambiguous inventory
exactly like a unique one. Rows that were not objects, or that had a missing,
null, boolean, list, numeric or empty ID, crashed with `KeyError`/`TypeError`
(or sorted mixed key types) instead of being refused as bad catalog input.

## Contract (frozen API, unchanged names)

`_candidates(document, label="catalog")` still accepts only the two supported
schemas (`coastal-frozen-discovery-catalog-v1`, `coastal-source-v1`) and a list
of candidates, with the original messages for those two checks. It then
validates every row BEFORE using it as a key:

| Row condition | `ValueError` message |
| --- | --- |
| not an object | `<label> candidate <i> must be an object` |
| `source_id` absent, not a string, or `""` | `<label> candidate <i> needs a nonempty string source_id` |
| `source_id` already seen (identical or conflicting row) | `<label> candidate <i> duplicates source_id '<id>' first seen at candidate <j>` |

`diff` passes `label="previous"` / `"current"`. `previous=None` still means "no
previous catalog"; an explicit but malformed previous (`{}`, `[]`, `""`, `0`,
`False`, ...) is validated and refused, never treated as missing. Valid IDs are
literal: no stripping, case-folding, repair or invention, so `"a"`, `" a"`,
`"A"` and `"a "` are four distinct candidates. Original row objects (with any
extra fields) are returned unchanged, and the diff output shape, sorting,
`DIFF_FIELDS` and the "no candidate is accepted" note are unchanged.

`run()` keeps its existing `_candidates(previous_doc)` pre-check (default
label `catalog`), so a previous catalog with ambiguous rows is now refused with
`ValueError` before the output directory is created or any request is made.
Request dispatch, allowlists, caps, `_freeze`, `DIFF_FIELDS`, catalog selection,
admission, the coordinator and listing adapters are untouched.

## Tests and acceptance

`tests/unit/test_sc_catalog_rows.py` imports the complete production module
under a scoped offline sentinel (sockets, subprocesses and model-client imports
are refused while it imports and while its tests run):

- `test_a1_*` positive contract: empty catalogs, one/many unique rows, both
  schemas, reordering, add/remove/change/no-op, `previous=None`, literal IDs and
  no input mutation.
- `test_a2_*` failure contract: duplicates in previous or current (identical,
  conflicting in either order), bad IDs, non-object rows, invalid containers and
  malformed-but-explicit previous catalogs, all `ValueError`.
- `test_a3_*` negative control: a test-local `last_wins_double` (the original
  mapping, container checks unchanged) replaces ONLY the row gate. The duplicate
  regression must then fail with pytest's `DID NOT RAISE`, while unique-row diff
  controls stay green.

Fixtures: `tests/fixtures/sc_catalog_rows/{unique,duplicate-conflicting}.json`
(synthetic, `.invalid` hosts).

Runner: `research/scripts/accept_sc_catalog_rows.py --suite focused|contract|negative --output DIR`
derives the repository from its own path, disables bytecode, puts the staged
`src` first on `sys.path` in code, installs the audit sentinel and calls the
installed pytest API on literal test files (plugin autoload off, cache off,
`--basetemp` inside the run directory). For the pytest window it also points
Python's default tempfile root (the cached `tempfile.tempdir` and the
`TMPDIR`/`TEMP`/`TMP` defaults children inherit) at a fresh
`tempfile-root/` inside the run directory and restores the ambient values on
exit, so the original `test_research_scripts_compile` `TemporaryDirectory()`
and its `.pyc` writes stay inside the run. An audit witness records every
`tempfile.mkdtemp`/`mkstemp`, `os.mkdir`, `os.rename`/`os.replace` destination
and write-mode `open` path in that window (receipt `temp_witness`; the null
device that pytest's capture opens is the only exemption) and the run fails if any resolves outside the
run directory, if a default-`TemporaryDirectory` + `py_compile` probe escapes,
or if the ambient tempfile state is not restored. It needs an interpreter with pytest and
jsonschema; without them it exits 3 (INPUT_UNAVAILABLE), never a skip. Each run
writes a new `DIR/<utc>-<pid>-<token>/` with `receipt.json`, `stdout.txt` and
`stderr.txt`. Expected collected counts are frozen: focused 60, contract 15
(the original `tests/unit/test_coastal_live_discovery.py` 7 +
`tests/contract/test_research_boundary.py` 8), negative 4 plus a runner-level
replay of the mutation.

The tests are also collected by the existing `pyproject.toml` `testpaths` in the
unit layer. Full-suite and exact-head CI remain operator-owned.
