# SC34 terrain CLI JSON fixtures

Tiny, synthetic, portable inputs for `tests/unit/test_sc34_terrain_json.py`.

- `style-producer.json`: a terrain style control object with every key of
  `terrain_only.DEFAULT_STYLE`, mixing JSON integers, exponent floats and a
  negative zero. `style_controls()` accepts it.
- `acceptance-reference.json`: a `coastal-terrain-only-input-v1`-shaped metadata
  object. Its artifact references repeat the same key names in sibling objects,
  and it has nested nulls, Unicode text (escaped and unescaped) and negative zero.
  The hashes and paths are placeholders. No raster or source exists behind them.

The tests copy these bytes into a per-run temporary directory before they read
them. Malformed variants are built from these bytes inside the tests. Nothing
here comes from a real source, payload or receipt.
