# Map style releases

`nearshore-v1.0.0.json` is byte-identical to the owner-approved kit's
`style-guide/style-tokens.json` (design card `t_a37142cd`). Kit ZIP SHA-256:
`5e0ff9968a6c905e583aeb8da7c129e890fee89ce453d718053ce29a95958b39`.
Only the derived tokens are included from the kit. The unlicensed kit archive,
fixtures, goldens, images and reference scripts stay private.

- Released version files and their raw-byte SHA-256 pins are immutable. A new
  look needs a new file and index entry. `index.json` selects the default; a
  render tool can load an explicit version without changing the default.
  `deep-fixed-v1` is a rollback ID for the legacy ramp-B builder, not a token file.
- `groups.json` maps dotted key prefixes to groups. The longest matching
  prefix wins; there is no default group. Arrays are assigned as whole values
  by their containing key (including ordered stops and tiers). Digests hash
  the UTF-8 canonical JSON of each group's subset, retaining the nested
  object shape, sorting keys and using no extra whitespace. `meta` is not
  hashed into rendering; QA may read its acceptance criteria.
- Checkout-based Python render tools use `skippercast.style.load()` and retain
  its immutable snapshot for a render. Each stage takes the digest of what it
  reads: tiles use `baked`, contours use `contours`, habitat uses `baked` and
  `habitat`. These digests identify style inputs, not survey data provenance.
  Render code reads tokens only through `Style.view(*groups)`, which raises
  `StyleGroupError` outside those groups; `load()` refuses a `groups.json`
  that no longer yields the index digests. `load(root=...)` reads another
  style directory (tests).
- The web map gets non-colour values and CSS variable names from
  `web/map/nearshore-style.gen.ts`; the palette bridge resolves colours. Both
  themes inherit the same `--skn-*` colours from `:root`. The Coast 3D renderer
  gets its nearshore ramp, contour ink and no-data colour from the generated
  block in `packages/coast/src/palette.ts`.

For a new version, classify its keys and register its raw SHA-256 and kit
provenance in the index. Run `python scripts/style/gen_style.py` to update the
four group digests and regenerate the default style's CSS and TypeScript.
Commit the inputs and outputs together. `python scripts/style/gen_style.py
--check` checks all indexed token files and projections without writing them;
its smoke test runs in the existing Python core tier. Do not edit generated
blocks or add local style overrides in render tools.

## All-layers style

`layers-v1.0.0.json` and `stacking-v1.0.0.json` are byte-identical to the
owner-approved all-layers kit's `layer-tokens.json` and `stacking.json`.
The kit ZIP hash and both raw-byte pins are in `index.json`. The same licence
boundary applies: only derived tokens are included from the kit; the kit
archive, fixtures, goldens, images and reference scripts stay private.

`layers_default` selects the version; `skippercast.style.load_layers()` returns
the resolved, read-only tokens with the `stacking` table and uses the indexed
nearshore version for `base:` references. Layer releases do not enter relief
generation keys. The same generator writes the `--skl-*` CSS block, the web
projection and the MapLibre reference fragment. `--check` also verifies the
fragment against the kit's pinned canonical JSON digest.
