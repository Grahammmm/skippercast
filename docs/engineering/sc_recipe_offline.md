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
     anchor;
   - `schema reference not admitted: embedded resource identifier at ...` for
     a nested `$id`, which would rebase later fragments onto another resource;
   - `schema reference not admitted: malformed reference at ...` for a
     non-string reference that passed the metaschema check.
   The root `$id` and `$schema` are identifiers, not fetch instructions, and
   stay admitted. Reference keywords inside data positions (for example
   `const` or `enum` values) are refused conservatively.
4. The validator is built with a `referencing` registry whose only retrieval
   callback, `_refuse_retrieval`, raises without any I/O; jsonschema combines
   it with its bundled specifications only. Releases of jsonschema without
   `referencing` use a `RefResolver` whose `resolve_remote` is the same
   callback. Any resolution failure becomes
   `schema reference unresolvable offline: ...`.
5. Every refusal is a `RecipeError`, so the CLI prints one deterministic
   `INVALID` result and exits 1 instead of a traceback. Successful output and
   all CLI arguments are unchanged; missing jsonschema still fails closed with
   `jsonschema is required for recipe validation`.

The committed v1 schema bytes, its constraints, the optional dependency policy
and `validate.check` (not used here) are unchanged.

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

[`scripts/accept_sc_recipe_offline.py`](../../scripts/accept_sc_recipe_offline.py)
runs `--suite focused|contract|negative --output NEW_DIR`. The contract suite
runs [`tests/unit/test_coast_recipe.py`](../../tests/unit/test_coast_recipe.py)
unchanged together with the new file. The runner starts one child under the
staged repository's `.venv` interpreter, installs sentinels before importing
pytest, the validator or jsonschema, traces imported modules and writes a
write-once receipt with hashes and counts. Both test files match the existing
`pyproject.toml` `testpaths`/`python_files`, so normal CI discovery collects
them; full-repository discovery and remote CI are separate gates.

Valid still means REVIEW REQUIRED: no source-use, navigation or semantic
approval follows from a passing validation or test run.
