# SC-SCHEMA-CLOSURE: static JSON Schema dependency closure

`scripts/coast_diagnostics/schema_closure.py` explains which JSON Schema documents a set of
explicitly listed schema files depends on, before any provenance check runs. It is a static,
offline, stdlib-only inventory. It is **not** instance validation, not proof of semantic
compatibility and not permission to change CI. Every result is REVIEW REQUIRED.

## Use

```
python3 scripts/coast_diagnostics/schema_closure.py \
    --manifest manifest.json --input-root <staged-root> --out <new-report.json>
```

The manifest (`sc-schema-closure-input-v1`) has exactly two keys:

```json
{"schema": "sc-schema-closure-input-v1",
 "files": [{"path": "schemas/common.schema.json", "sha256": "<64 lower-case hex>"}]}
```

`path` is a normalized relative POSIX path ending in `.json` under the explicit input root (no
`..`, `.`, empty segments, leading `/`, backslashes or control characters; case-insensitive
duplicates refused). At most 128 files. The public API is
`inspect_closure(manifest, input_root)`, which returns the report or raises `ClosureInputError`.

## What it reads and never does

* Only the manifest files. Before any read, mkdir or write, every path component from `/` down
  is checked with `lstat` (no follow): every ancestor of the input root, of the manifest file
  and of the report must be an existing real directory, never a symlink, including ancestors
  above the explicit root. Below the root, no directory between the root and a manifest file
  may be a symlink and the file itself must be a regular non-symlink file. The 2 MiB per-file
  cap and the 16 MiB aggregate cap are checked before reading. (Use a physical path on
  platforms whose temporary directory is reached through a symlink.) A component swapped by
  another process between check and use is not defended against (no hostile-local sandbox).
* Each file's SHA256 is verified before parsing. JSON must be strict UTF-8 with no duplicate
  keys, no NaN/Infinity, no lone surrogate escapes (`json_invalid_unicode`, exit 2) and nesting
  of at most 256 levels.
* `$id`, `$ref`, `$dynamicRef` and `$schema` values are data. They are resolved only against
  resources declared inside the manifest documents; nothing is fetched, no other file is opened,
  `file:` references are reported as `unbound_file_reference`, and `$schema` values are reported
  as dialect text and never followed. Schemas are parsed, never executed; no validator is used.
* A document without a top-level `$id` gets an opaque internal base
  `urn:sc-schema-closure:path:<logical path>`. Fragment-only references inside that document
  resolve; relative path references under it are `unbound_relative_reference`, and other
  documents cannot reach it through that internal name.
* The report is written once to a new file (`O_EXCL`, every ancestor a real directory, 8 MiB
  cap). Unsafe or malformed input writes nothing and leaves inputs and existing outputs untouched.

## Report (`sc-schema-closure-v1`)

Deterministic JSON (sorted keys and rows; byte-identical for relocated copies and for any manifest
row order). Fields: `execution_allowed: false`, `review_required: true`, `status`
(`closed`/`open`), `exit_code`, `input` (per-file path, sha256, bytes and a digest), `limits`,
`dialects`, `nodes` (declared `$id` resources), `anchors`, `references` (every occurrence, never
deduplicated, with its classification and `resolution_target`), `edges` (resolved and
UNVERIFIED-dynamic references with source and target JSON Pointers), `document_edges`, `cycles`,
`findings` and `counts`.

Walking follows Draft 2020-12 subschema keywords (plus the older tuple `items`,
`additionalItems`, `definitions` and `dependencies` forms). A `$ref` key inside a non-schema
location such as `const`, `enum` or an unknown keyword is listed with classification
`outside_schema_location` and an informational finding, and is not an edge, as long as nothing
reaches that location. When a resolved JSON Pointer lands on an object outside the keyword
structure, that object becomes a schema location and is analysed with the enclosing base (a
worklist visits each location once, so cycles terminate): its references are classified and
can keep the closure open. `$id`, `$anchor` and `$dynamicAnchor` declared inside such a
pointer-reached object are not registered as resources or anchors; they are reported as
`promoted_scope_unverified`.

Fragments are percent-decoded exactly once (strict UTF-8) and only then dispatched: a decoded
value starting with `/` is a JSON Pointer, anything else must fully match the anchor grammar
`[A-Za-z_][-A-Za-z0-9._]*`. The raw reference text is kept in the report. Double-encoded
fragments therefore do not resolve. All grammar checks (anchors, array indices, SHA256, URI
scheme) are whole-string matches, so a trailing newline or control character is malformed.
An array-index token whose digit count exceeds that of the array length is out of range
without any integer conversion, so arbitrarily long decimal indices are ordinary
`missing_pointer_target` findings; the interpreter's integer-string digit limit is never
raised or disabled.

| Severity | Codes |
| --- | --- |
| error (exit 1) | `duplicate_id`, `aliasing_id`, `duplicate_anchor`, `ambiguous_resource`, `unresolved_resource`, `unbound_file_reference`, `unbound_relative_reference`, `unbound_relative_id`, `missing_pointer_target`, `missing_anchor`, `pointer_target_not_schema`, `invalid_reference`, `invalid_percent_escape`, `invalid_fragment`, `malformed_id`, `malformed_anchor`, `malformed_dynamic_anchor`, `malformed_reference`, `malformed_dialect` |
| unverified (exit 1) | `dynamic_resolution_unverified`: a `$dynamicRef` whose plain-name fragment meets a `$dynamicAnchor`; only the static initial target is shown. `promoted_scope_unverified`: an identifier or anchor inside a pointer-reached non-keyword object |
| info (exit unaffected) | `cycle`, `unused_schema` (no other manifest document references it), `reference_outside_schema_location` |

`aliasing_id` means two declarations differ textually but are the same identifier after
normalization (case-folded scheme and host, dot segments removed, unreserved percent escapes
decoded). Exit status: 0 fully resolved static closure, 1 unresolved, unsupported or
conflicting closure, 2 unsafe or malformed input. The 4096-row cap applies to every emitted
row collection (declared `$id` nodes, anchors, dialects, references and findings; edges,
document edges and cycles are bounded by references) and is enforced while the collections
grow, so an excess is refused with `row_cap_exceeded` (exit 2) and no report.

## Pinned real families (base 59fca09b)

`tests/fixtures/sc_schema_closure/real/` holds the manifest of the direct `*.schema.json` children
of `schemas/` and `skills/coast-campaign-shared/schemas/` generated from git objects at the
pinned base, plus expectations from an independent oracle (the `referencing` library from the
python-jsonschema project, run once outside the tool): 303 `$ref` occurrences, all resolvable; 54
declared `$id` values. Several shared-family schemas declare the same `$id` in more than one
`oneOf` branch (9 declarations), so the real closure is `open` with exit 1. That nonzero status
is expected evidence frozen in the contract test, not an exemption, and it does not by itself
claim that any validator misbehaves today. The contract test fails if those schema files or their
listing change; refreshing the pinned fixtures is a reviewed change.

## Acceptance

`python3 scripts/accept_sc_schema_closure.py --suite {focused,contract,negative} --output <new-dir>`
runs the matching unittest class in-process with network, process and model sentinels installed
first, temporary files redirected into the run directory, and a receipt of argv, cwd, interpreter,
counts and code and fixture hashes. The negative suite also proves that the closure-completeness
assertion rejects a report with one real edge removed by an in-memory double, while every other
field stays identical. The same tests run under pytest as `tests/unit/test_sc_schema_closure.py`.
