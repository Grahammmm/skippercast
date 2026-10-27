# SC34: strict JSON in the terrain CLI metadata reader

`skippercast.coastal.render.terrain_only.bounded_json` reads the two external
files the internal terrain diagnostic CLI takes: `--acceptance` and `--style`.
This change only affects how those bytes are decoded. The descriptor checks
(`O_NOFOLLOW`, regular file only, non-blocking open), `MAX_CLI_JSON_BYTES`
(2,000,000 bytes) and the object-root rule are unchanged. So is the CLI's
`held` result for any `ValueError`/`OSError`.

## What was wrong

The reader used `json.loads(..., parse_constant=reject)`. That refused the
literal `NaN`, `Infinity` and `-Infinity` tokens, but:

- a duplicate key kept its **last** value without any error, at any depth
  (`{"x": 1, "x": 2}` became `{"x": 2}`). The same happened when the second
  spelling was escaped (`"\u0078"`);
- a number such as `1e999` is valid JSON grammar but parses to `inf`, so a
  caller received an object containing a non-finite float.

Either way, the acceptance context digest and the style controls would
silently describe something other than what the file says.

## What the reader does now

| Input | Result |
|---|---|
| duplicate key in any object, at any depth, compared after unescaping | `ValueError('cli_json_duplicate_key')` |
| `NaN`, `Infinity`, `-Infinity` token | `ValueError('cli_json_nonfinite:<token>')` (unchanged) |
| a number that overflows to ±infinity (`1e999`, `-1.8e308`, `0.1e310`) | `ValueError('cli_json_nonfinite:overflow')` |
| invalid UTF-8, BOM, malformed JSON | `ValueError` (unchanged; `UnicodeDecodeError`/`JSONDecodeError`) |
| non-object root | `ValueError('cli_json_object_required')` (unchanged) |
| over the byte bound | `ValueError('cli_json_byte_bound')`, before any decoding (unchanged) |

The reasons are fixed strings. They never echo file content.

A document without these problems parses exactly as before. Key order,
`int` versus `float`, negative zero, Unicode (NFC and NFD spellings are
different keys), `null` leaves and array order are all preserved. The float
hook is `float()` itself, the same as the default. The object hook builds the
same `dict` in the same order.

Two behaviours are deliberately **not** changed:

- **Underflow.** `1e-400` still becomes `0.0`, and `-1e-400` becomes `-0.0`.
  These are finite values, so they are out of scope.
- **Lone surrogate escapes.** A string such as `"\ud800"` is still accepted,
  as `json.loads` allows. Raw bytes that are not valid UTF-8 are refused.

## Scope

Only `bounded_json` (plus helpers nested inside it) changed. `handoff.common.load`
and its byte-reference loader belong to SC-HANDOFF-JSON. Schemas, the renderer,
masks, imagery and limits are untouched. This is not terrain-mask
qualification, scientific acceptance or a publication step.

## Tests and acceptance

- `tests/unit/test_sc34_terrain_json.py` covers:
  - valid documents, including round-tripping the producer-shaped fixtures in
    `tests/fixtures/sc34_terrain_json/`;
  - number boundaries and the preserved size, root and file-type gates;
  - every malformed class above;
  - CLI holds that happen before any preview starts. A stub that fails replaces
    `preview`, so a regression cannot render.
- `test_mutation_controls` swaps a test-local `json` stand-in into
  `terrain_only`. The stand-in calls `json.loads` with only the original
  `parse_constant` setting. The duplicate and overflow assertions must then fail
  because the document is *accepted*, while the healthy fixture still passes.
  No submitted file is modified.
- `research/scripts/accept_sc34_terrain_json.py --suite {focused,contract,negative} --output DIR`
  runs the literal pytest selectors through the installed pytest API. It sets
  up sentinels and temporary paths before any import and writes a write-once
  receipt. The contract suite runs the two unchanged
  `research/tests/test_check_terrain_acceptance_dependencies.py` selectors,
  `tests/contract/test_research_boundary.py` and
  `tests/contract/test_test_layout.py`.

A passing receipt means REVIEW REQUIRED. It is not full CI: the operator runs
full discovery and exact-head CI.
