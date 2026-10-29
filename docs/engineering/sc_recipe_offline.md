# Offline coast recipe schema references (SC-RECIPE-OFFLINE)

[`validate_recipe.py`](../../validate_recipe.py) validates a coast recipe against
[`schemas/coast-recipe-v1.schema.json`](../../schemas/coast-recipe-v1.schema.json)
read from an operator-supplied `--metadata-root`. Before this hardening the
validator was built with jsonschema's default registry, which retrieves any
unknown `$ref` target over the network. A metadata root whose schema named an
external resource could therefore start name resolution and fail with a
traceback. Validation is now unconditionally offline for every metadata root.

## Behavior

1. The schema file is read with the existing strict JSON reader (duplicate
   keys, `NaN`/`Infinity` literals) and then checked for non-finite numbers
   such as `1e999` (`schema document non-finite numeric value`).
2. The schema is checked against the bundled Draft 2020-12 metaschema with the
   same first-error rule and format checker as `check_schema`, through an
   offline resolver (`schema document invalid at <pointer>: ...`).
3. Before any instance evaluation, the WHOLE schema is walked, including
   branches no instance would traverse. Only same-document fragments are
   admitted for `$ref` and `$dynamicRef`: `#`, a JSON pointer `#/...` that
   resolves exactly inside the document, or `#name` matching an `$anchor` or
   `$dynamicAnchor` in it. Everything else is refused with a stable reason and
   the JSON pointer of the offending keyword:
   - `schema reference not admitted: external resource at ...` for any
     reference that needs another resource: `http(s)`, `file`, relative
     names, `../` traversal, protocol-relative, URN, empty references, the
     metaschema URI itself, and dynamic external references;
   - `schema reference not admitted: unresolved local fragment at ...` for a
     missing, traversal (`#/..`, `#/%2e%2e`), badly escaped, badly
     percent-encoded or out-of-range pointer and an unknown or malformed
     anchor. An array-index segment must be a canonical decimal (`0` or no
     leading zero) of at most `len(str(sys.maxsize))` digits, checked before
     any integer conversion, so an impossible index such as 5000 digits is
     refused here and never reaches the interpreter's integer-string limit;
   - `schema reference not admitted: embedded resource identifier at ...` for
     a nested `$id`, which would rebase later fragments onto another resource;
   - `schema reference not admitted: malformed reference at ...` for a
     non-string reference that passed the metaschema check.
   The root `$id` and `$schema` are identifiers, not fetch instructions, and
   stay admitted. Reference keywords inside data positions (for example
   `const` or `enum` values) are refused conservatively.
   Every admitted local reference is then resolved, still before evaluation
   and still for unused branches, through an offline resolver built exactly
   like the validator's (retrieval refused). Its target must be a usable
   schema:
   - `schema reference not admitted: local target is not a schema at ...`
     when it resolves to a string, array, number or null (for example
     `#/title`, `#/required`, `#/examples/0`);
   - `schema reference not admitted: local target is not a valid schema at ...`
     when it resolves to an object the Draft 2020-12 metaschema rejects;
   - `unresolved local fragment` also covers an anchor that only appears in
     a data position (such as inside `examples`), which the resolver ignores.
   Boolean and object schema targets keep their normal local semantics.
4. The validator is built with a `referencing` registry whose only retrieval
   callback, `_refuse_retrieval`, raises without any I/O; jsonschema combines
   it with its bundled specifications only. Releases of jsonschema without
   `referencing` use a `RefResolver` whose `resolve_remote` is the same
   callback. Any resolution failure becomes
   `schema reference unresolvable offline: ...`. A traversed same-document
   reference cycle that never consumes the instance becomes
   `schema reference cycle does not terminate`; any remaining library
   `AttributeError`/`TypeError` during evaluation is a backstop
   `schema evaluation failed offline: ...`, never a traceback.
5. Every refusal is a `RecipeError`, so the CLI prints one deterministic
   `INVALID` result and exits 1 instead of a traceback. Successful output and
   all CLI arguments are unchanged; missing jsonschema still fails closed with
   `jsonschema is required for recipe validation`.

The committed v1 schema bytes, its constraints, the optional dependency policy
and `validate.check` (not used here) are unchanged.

The recipe-delta acceptance test and runner pin the hardened `validate_recipe.py`
bytes (`31b62ce0d0ac4926a9d47ab820eb6699c45a2572335ec2759b0247baf837901a`)
in place of their original producer pin. This is an intentional producer revision,
not a change to the frozen recipe/schema fixtures or their pins. The delta
behavior and producer-contract tests still run against the actual validator.

## Tests and acceptance

[`tests/unit/test_sc_recipe_offline.py`](../../tests/unit/test_sc_recipe_offline.py)
uses synthetic edits from
[`tests/fixtures/sc_recipe_offline`](../../tests/fixtures/sc_recipe_offline/reference-cases.json)
applied to staged copies of the metadata. External addresses use the reserved
`.invalid` domain and are never contacted: an autouse fixture replaces DNS,
socket, HTTP, urlopen and subprocess entrypoints with refusing doubles and the
retrieval callback with an in-memory counter. Test names carry the acceptance
row: `a1_` (focused), `a2_` (transport and read boundary, using an audit hook
to prove every open stays inside the staged roots on the error path too) and
`a3_` (negatives and the mutation control). The mutation control disables only
the reference gate; the regression must then fail on the retrieval counter,
and pass again once the gate is restored.

[`research/scripts/accept_sc_recipe_offline.py`](../../research/scripts/accept_sc_recipe_offline.py)
runs `--suite focused|contract|negative --output NEW_DIR`. The contract suite
runs [`tests/unit/test_coast_recipe.py`](../../tests/unit/test_coast_recipe.py)
unchanged together with the new file. The runner starts one child under the
staged repository's `.venv` interpreter, installs sentinels before importing
pytest, the validator or jsonschema, traces imported modules and writes a
write-once receipt with hashes and counts. Both test files match the existing
`pyproject.toml` `testpaths`/`python_files`, so normal CI discovery collects
them; full-repository discovery and remote CI are separate gates.

### Runner input/output contract

These bounds apply only to the new runner's own diagnostic reads and report
writes; no production API, coast run, download or model budget changes.

- Reads: every path is checked from its allowed root (the staged repository
  or the run directory) to the leaf with `lstat` before it is opened: no
  `..`, no symlink anywhere, directories above, a regular file at the leaf
  (FIFOs, devices and directories are refused without opening, so nothing can
  hang). The size is checked first, the file is opened with
  `O_NOFOLLOW|O_NONBLOCK` and its inode re-checked. Limits: 2 MiB per file and
  16 MiB aggregate.
- Identity before use: code and fixture inputs must equal their committed
  HEAD blob ids (`git ls-tree`), the unchanged schema and coast test also
  their pinned sha256; `pyproject.toml` is parsed only after that check. The
  child prints one `child-report-sha256=` line; the parent reads the report
  only under that hash and the JUnit file only under the hash in the report.
- Rows: at most 4096 fixture entries (symlinks/special files refused, not
  skipped), committed tree rows, git output lines and JUnit test cases.
- Writes: deterministic sorted JSON with non-finite values refused, created
  with `O_EXCL|O_NOFOLLOW` in a validated write-once run directory, at most
  8 MiB of report bytes per run. The 8 MiB is divided before the child starts
  into fixed reservations that sum to exactly 8 MiB: `stdout.txt` 1 MiB,
  `stderr.txt` 1 MiB, `junit.xml` 2 MiB, `child-report.json` 2 MiB,
  `receipt.json` 2 MiB - 64 KiB and a 64 KiB fallback receipt (written only
  when the primary receipt is refused). Each write is refused before it
  happens when it would exceed its share; a later artifact can never spend an
  earlier one's share. The child's stdout and stderr are pipes the parent
  drains within their shares (the child is killed on overflow and the run
  fails; excess bytes are discarded, never written). The child runs with
  `RLIMIT_FSIZE` = 2 MiB, which is exactly the share of each artifact it
  writes itself, plus a 900 s timeout. `tmp/` holds pytest's synthetic
  staging and is bounded per file by the same limit, not counted as report
  output.

The `a3_runner_*` tests exercise these rules on synthetic trees: exact and
one-over boundaries, aggregate and row overflow, symlink leaf and ancestry,
FIFO and directory, outside-root and `..` paths, hash/blob mismatch, the
report identity marker, no overwrite and unchanged inputs after refusal. The
composed tests drive the parent's real capture and settle functions with
`os.pipe` streams and synthetic child artifacts (no subprocess): exact fit,
capture overflow, oversized child artifacts refused unread, and the fallback
receipt within its own share, always within the aggregate.

Valid still means REVIEW REQUIRED: no source-use, navigation or semantic
approval follows from a passing validation or test run.
