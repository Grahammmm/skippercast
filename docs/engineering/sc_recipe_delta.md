# Coast recipe delta (sc-recipe-delta-v1)

`scripts/coast_diagnostics/recipe_delta.py` explains what changed between two frozen
coast recipe snapshots **without running either recipe**. It is a read-only
diagnostic. It does not download anything, write into a workspace, or import the stage driver,
acquisition code or live settings.

## Inputs

Each side is one recipe file plus an explicit, staged metadata snapshot root:

```
python3 scripts/coast_diagnostics/recipe_delta.py \
    --left-recipe LEFT.json   --left-metadata LEFT_SNAPSHOT_ROOT \
    --right-recipe RIGHT.json --right-metadata RIGHT_SNAPSHOT_ROOT \
    --workspace-root ADMITTED_WORKSPACE --out NEW_REPORT.json
```

The same comparison is available in Python as
`compare_recipes(left_recipe, right_recipe, left_metadata_root, right_metadata_root, workspace_root)`.
It returns a JSON-compatible report or raises `RecipeDeltaError` (INVALID).

Each side is validated independently by the existing
[validate_recipe.validate_recipe](../../validate_recipe.py) against its own snapshot. The
tool loads that validator by file path from the same checkout (or relocated copy) and
never searches `sys.path`. While a side is validated, every metadata read the validator makes passes through a
bounded reader. That reader:

* accepts only these paths inside the snapshot root:
  `schemas/coast-recipe-v1.schema.json`, `catalog/sources.json`,
  `catalog/coastal-sectors.json` and `regions/<slug>/region.json`;
* rejects parent traversal and symlinks at any ancestry level, including dangling links, and also rejects special files,
  before it opens anything;
* applies a per-file cap of 2 MiB (the validator's tighter 2,000,000-byte limit still
  applies) and a 16 MiB aggregate cap across both sides;
* rejects duplicate JSON keys and non-finite numbers (`NaN`, `Infinity`, `1e999`);
* hashes exactly the bytes it parsed and hands that parsed document to the validator.

Strings inside a JSON document never select a file. The only metadata compared is
what the validator actually read, so a cache, payload or unstaged path is never
traversed.

The staged schema is checked before the validator hands it to jsonschema, because
jsonschema's reference resolver does not go through the bounded reader (it would
retrieve an unknown URI with urllib, for http(s) and file alike). Only
document-internal references are admitted: every `$ref`, `$dynamicRef` and
`$recursiveRef` must be a string starting with `#`; `$id` and `$schema` may appear only
at the schema root, and `$schema` only as the 2020-12 dialect. Anything else (an
http(s), `file:` or relative reference, a nested `$id` that rebases resolution, another
dialect) is INVALID before any resolution is attempted. The check looks at those keys
wherever they occur, so an unusual but harmless schema may be refused; that is the
intended fail-closed direction. The frozen schema (root `$id`, `#/$defs/...` references)
is accepted.

Imports made by the tool never write bytecode: the validator is loaded, and each side is
validated, with `sys.dont_write_bytecode` temporarily set (the caller's setting is
restored), and the standalone CLI turns it on for its whole process before loading the
validator.

## Report

The logical object compared on each side is
`{"recipe": <recipe document>, "metadata": {<relative path>: <document>}}`.
Every difference is one row, addressed by an RFC 6901 JSON Pointer:

```json
{"pointer": "/metadata/catalog~1sources.json/sources/1/review_status",
 "before_present": true, "before": "candidate",
 "after_present": true, "after": "approved"}
```

* Missing and null are different. If a side lacks the member, its `*_present` is `false`
  and its value is `null`. A present JSON `null` has `*_present: true`.
* Arrays are compared by position. Reordered `sources` (with matching region bindings)
  stay a change; nothing is sorted or normalised.
* Objects are compared by key. A metadata file read by only one side shows as one row
  at `/metadata/<path>`, with the whole document on the side that has it.
* Leaf comparison is type-exact: `true` differs from `1`, and `1` differs from `1.0`.
* Rows are sorted: object keys by code point, array indices numerically. At most 4096
  rows are allowed; more is INVALID.

The report top level holds:

* `schema` = `sc-recipe-delta-v1`;
* `status`, either `UNCHANGED_REVIEW_REQUIRED` or `CHANGED_REVIEW_REQUIRED`;
* `semantic_approval: false`, `execution_allowed: false` and `not_for_navigation: true`;
* `left` and `right`, each with `slug`, `recipe_sha256` and `metadata_sha256` (a map from
  each metadata file read to its sha256);
* `change_count` and `changes`.

The report contains no absolute paths, so the same inputs produce the same bytes wherever they are staged.
Serialisation is deterministic: sorted keys, two-space indent, ASCII, and no non-finite numbers.

## Output and exit codes

* Exit 0: one new, complete report file is published. The bytes are first written to a
  new exclusive `.<name>.incomplete-<pid>-<random>` file beside the target, fsynced and
  closed, and only then hard-linked to the requested name (`link` never replaces an
  existing name). The temporary name, created by that same call, is then removed. A
  one-line JSON summary with the report sha256 goes to stdout.
* Exit 2 (INVALID): any validation failure, duplicate key, non-finite number, unsafe or
  oversized input, refused schema reference, cap breach, refused output or report I/O
  failure (write, fsync, close or publish). No report is published under the requested
  name, and a JSON error object goes to stderr. If the failure happened after the
  temporary file was created, its incomplete bytes are kept under that distinct
  `.incomplete-` name as failure evidence, and the error names it.

The output must not already exist, and its parent directory must already exist. Its
ancestry must contain no symlinks. It may not lie inside either metadata snapshot or the
workspace root. The report is capped at 8 MiB. Inputs and existing files are never
modified.

## What v1 does not do

It admits no new slug and makes no compatibility judgement between the two sides.
It calculates no cache budget, modifies no recipe and changes no source permission. A valid
report means REVIEW REQUIRED. It is not semantic acceptance, source qualification or
permission to execute.

## Acceptance

`scripts/accept_sc_recipe_delta.py --suite focused|contract|negative --output DIR`
runs [the tests](../../tests/unit/test_sc_recipe_delta.py) in-process. It uses the tiny
synthetic fixtures in `tests/fixtures/sc_recipe_delta`. Before it imports pytest or any
project module, the runner turns off bytecode writing, sets its import path to this
repository, and installs DNS, socket, HTTP and subprocess sentinels. It writes a new run
directory with raw output and a receipt. The negative suite proves that an in-memory
double suppressing one real changed leaf makes the exact A1 row regression fail, that
the unchanged control stays green, and that a clean rerun passes. The new test module
is also collected by the normal `python -m pytest` discovery used by both Python CI jobs.
