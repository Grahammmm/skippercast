# Style kit file consistency

| Check | Result |
| --- | --- |
| R1. File digests | All three raw-byte pins and the fragment's canonical JSON pin match. Three files have no raw-byte pin (R1). |
| R2. Layer IDs | The 24 token families all occur in stacking and in the fragment by reference, not by identical IDs. The 57 fragment IDs are unique. `groups.json` classifies nearshore token keys, not all-layer IDs (R2). |
| R3. Documentation and readers | The generator check passes. The README overstates its check's version coverage; the Python loaders verify different inputs, and the browser does not rehash the kit (R3). |
| R4. Follow-up | One README-only clarification; no code or token changes proposed (R4). |

Evidence: local `origin/main` at `34761911d5c44a903873867426f316c7f1e5911c`, read offline on 2026-11-21. No private kit or live map was opened or run. Source locations below are at that commit.

## R1. File and group digests

The table is the scratch probe's output. To reproduce the raw column from a clean checkout, run `git ls-files style` and `sha256sum style/*.* style/generated/*.*`. For the fragment, parse JSON, serialize with sorted keys, compact `,`/`:` separators, `ensure_ascii=False`, `allow_nan=False`, UTF-8 and no trailing newline, then hash (`scripts/style/gen_style.py:320–326`). The raw hash of the indented file is not supposed to equal the canonical pin. The generator also checks that the checked-in file matches its indented output byte for byte (`scripts/style/gen_style.py:362–382`).

| File | Raw SHA-256 computed on checkout | Index digest (comparison basis) | Match? |
| --- | --- | --- | --- |
| `style/README.md` | `c77b78daebf91b2c60c6cf1fc2e194852afe28b2a112deb331f36de5d913eacd` | — | N/A (no file pin) |
| `style/generated/maplibre-layers-v1.0.0.json` | `7a65548057786c196aca98cef2c502ae6d8eab2478abfbf83da46fe96a626e76` | `b342f8394e6ef68261c06a9329afe90e6c80c29a9ac0bb918301a85c25609b72` (canonical; `style/index.json:31`) | Yes (canonical: `b342f8394e6ef68261c06a9329afe90e6c80c29a9ac0bb918301a85c25609b72`; raw differs) |
| `style/groups.json` | `eb07ae9c3f30d79cd3833e1b2c28dcf8b4c252cc756378aef497e7bfcb30a524` | — | N/A (no file pin) |
| `style/index.json` | `74ac6ed21d0aa36f5a13e2c3d6d588c45bbe140084e43644c73e203210e87156` | — | N/A (no file pin) |
| `style/layers-v1.0.0.json` | `11d8a2cf6efd6ccda696a353994fb5e823b9aa521bb7214f5a928d8ccdba9e04` | `11d8a2cf6efd6ccda696a353994fb5e823b9aa521bb7214f5a928d8ccdba9e04` (raw; `style/index.json:25`) | Yes |
| `style/nearshore-v1.0.0.json` | `fecc2af86e3313d16c630af22386d91567d7124753a48545f03f3f5271a786aa` | `fecc2af86e3313d16c630af22386d91567d7124753a48545f03f3f5271a786aa` (raw; `style/index.json:6`) | Yes |
| `style/stacking-v1.0.0.json` | `1967e569ff275d9d5504cacf18ceef818cf301caf86e8a25bcaf92b176c9c4c3` | `1967e569ff275d9d5504cacf18ceef818cf301caf86e8a25bcaf92b176c9c4c3` (raw; `style/index.json:27`) | Yes |

`style/index.json:2–31` selects `nearshore-v1.0.0` and `layers-v1.0.0`, pins the layers' base to `nearshore-v1.0.0`, and lists `deep-fixed-v1` as active/legacy with no token file. The two `kit_zip_sha256` values at lines 7 and 29 identify external archives, not local files. Although `groups.json` has no file pin, `load()` checks the four computed nearshore group digests against `style/index.json:8–13` (`src/skippercast/style/__init__.py:244–261`). Scratch output:

```text
Group digests (verified against index):
baked d568d2aee05dccfb26d626a33a7f26386238a415b2bf4d296db6a89d48beb20b
contours 83060cabb89fc1386bc31b41e57146eb30094d2eca222408523fba440f5ca572
habitat 53aa8cf5192d6b751328749208a255e3c0e7a1872b947bca41fb8fbb60da9115
paint 844f2d1fadaef7427fe499f7d396b8b4159dd9dddfee01d3b12b477accb5d084
```

## R2. Layer IDs and references

Exact-string inventory from the scratch probe. `—` means absent from that file's indicated field, not that the map lacks that feature. Paths are zero-based and relative to `style/groups.json` keys, `style/layers-v1.0.0.json` `layers` keys (also in `status.picks`), `style/stacking-v1.0.0.json` `z_order` IDs/members and preset `.layer` fields, and `style/generated/maplibre-layers-v1.0.0.json` `layers[].id`. Fragment `_z_order` separately repeats every stacking `z_order` path exactly (prefix `_`). The groups file has only dotted nearshore token prefixes (`style/groups.json:2–52`), so none of these literals is a group key.

| Exact ID or stacking member literal | Groups key | Layer token key | Stacking path | Fragment layer ID path |
| --- | --- | --- | --- | --- |
| `ais-fleet` | — | `layers.ais-fleet` | `z_order[5].members[2]` | — |
| `arrows-barbs` | — | — | `z_order[8].id` | — |
| `base-relief` | — | — | `z_order[0].id` | — |
| `chlorophyll` | — | `layers.chlorophyll` | `z_order[1].members[1]` | — |
| `clouds` | — | `layers.clouds` | `z_order[2].members[0]` | — |
| `color-field` | — | — | `z_order[1].id` | — |
| `currents` | — | `layers.currents` | `presets.STACK-A.layers[1].layer` | — |
| `currents.fill` | — | — | `z_order[1].members[5]` | — |
| `currents.streamlines` | — | — | `z_order[7].members[0]` | — |
| `depth-contours` | — | — | `z_order[4].id` | — |
| `isolines` | — | — | `z_order[6].id` | — |
| `kd490` | — | `layers.kd490` | `z_order[1].members[2]` | — |
| `kelp-habitat` | — | `layers.kelp-habitat` | `z_order[5].members[1]`, `presets.NEAR-D.layers[1].layer` | — |
| `labels` | — | — | `z_order[11].id` | — |
| `marine-zones-mpas` | — | `layers.marine-zones-mpas` | `z_order[5].members[0]` | — |
| `particles` | — | — | `z_order[7].id` | — |
| `places` | — | `layers.places` | `z_order[10].members[2]` | — |
| `points` | — | — | `z_order[10].id` | — |
| `polygons` | — | — | `z_order[5].id` | — |
| `precip-radar` | — | `layers.precip-radar` | `z_order[3].members[0]` | — |
| `pressure` | — | `layers.pressure` | `z_order[6].members[3]` | — |
| `radar` | — | — | `z_order[3].id` | — |
| `routes` | — | — | `z_order[9].id` | — |
| `routes-tracks` | — | `layers.routes-tracks` | `z_order[9].members[0]` | — |
| `salinity` | — | `layers.salinity` | `z_order[1].members[3]` | — |
| `sea-ice` | — | `layers.sea-ice` | `z_order[2].members[1]` | — |
| `skl-ais-fill` | — | — | — | `layers[20].id` |
| `skl-ais-label` | — | — | — | `layers[52].id` |
| `skl-ais-line` | — | — | — | `layers[21].id` |
| `skl-chlorophyll-fill` | — | — | — | `layers[1].id` |
| `skl-clouds-veil` | — | — | — | `layers[10].id` |
| `skl-currents-fill` | — | — | — | `layers[3].id` |
| `skl-currents-streamlines` | — | — | — | `layers[32].id` |
| `skl-hazard-fill` | — | — | — | `layers[13].id` |
| `skl-isobar-bold` | — | — | — | `layers[31].id` |
| `skl-isobar-label` | — | — | — | `layers[48].id` |
| `skl-isobar-minor` | — | — | — | `layers[30].id` |
| `skl-kd490-fill` | — | — | — | `layers[2].id` |
| `skl-kelp` | — | — | — | `layers[17].id` |
| `skl-leg-label` | — | — | — | `layers[54].id` |
| `skl-mpa-fill` | — | — | — | `layers[15].id` |
| `skl-mpa-label` | — | — | — | `layers[51].id` |
| `skl-mpa-line` | — | — | — | `layers[16].id` |
| `skl-pier` | — | — | — | `layers[41].id` |
| `skl-pier-halo` | — | — | — | `layers[40].id` |
| `skl-pressure-centers` | — | — | — | `layers[49].id` |
| `skl-radar` | — | — | — | `layers[12].id` |
| `skl-ramp` | — | — | — | `layers[42].id` |
| `skl-route` | — | — | — | `layers[38].id` |
| `skl-route-halo` | — | — | — | `layers[37].id` |
| `skl-salinity-fill` | — | — | — | `layers[5].id` |
| `skl-sea-ice-edge` | — | — | — | `layers[24].id` |
| `skl-sea-ice-veil` | — | — | — | `layers[11].id` |
| `skl-shore` | — | — | — | `layers[19].id` |
| `skl-shore-halo` | — | — | — | `layers[18].id` |
| `skl-spot-badge` | — | — | — | `layers[46].id` |
| `skl-spot-others` | — | — | — | `layers[45].id` |
| `skl-spot-rank` | — | — | — | `layers[56].id` |
| `skl-ssh-negative` | — | — | — | `layers[28].id` |
| `skl-ssh-positive` | — | — | — | `layers[27].id` |
| `skl-ssh-zero` | — | — | — | `layers[29].id` |
| `skl-sst-band-edge` | — | — | — | `layers[23].id` |
| `skl-sst-breaks-glow` | — | — | — | `layers[9].id` |
| `skl-sst-fill-fill` | — | — | — | `layers[0].id` |
| `skl-sst-iso-index` | — | — | — | `layers[26].id` |
| `skl-sst-iso-label` | — | — | — | `layers[47].id` |
| `skl-sst-iso-minor` | — | — | — | `layers[25].id` |
| `skl-station-chip` | — | — | — | `layers[55].id` |
| `skl-station-pin` | — | — | — | `layers[44].id` |
| `skl-subsurface-temp-fill` | — | — | — | `layers[4].id` |
| `skl-tide-pin` | — | — | — | `layers[43].id` |
| `skl-track` | — | — | — | `layers[36].id` |
| `skl-upwelling-ribbon` | — | — | — | `layers[22].id` |
| `skl-visibility-fog-fill` | — | — | — | `layers[8].id` |
| `skl-wave-arrows` | — | — | — | `layers[35].id` |
| `skl-waves-swell-fill` | — | — | — | `layers[7].id` |
| `skl-waypoint` | — | — | — | `layers[39].id` |
| `skl-waypoint-num` | — | — | — | `layers[53].id` |
| `skl-wind-barbs` | — | — | — | `layers[34].id` |
| `skl-wind-fill` | — | — | — | `layers[6].id` |
| `skl-wind-particles` | — | — | — | `layers[33].id` |
| `skl-zone-label` | — | — | — | `layers[50].id` |
| `skl-zone-line` | — | — | — | `layers[14].id` |
| `spots-marks` | — | `layers.spots-marks` | `z_order[10].members[3]`, `presets.NEAR-D.layers[2].layer` | — |
| `ssh` | — | `layers.ssh` | `z_order[6].members[2]` | — |
| `sst-breaks` | — | `layers.sst-breaks` | `z_order[6].members[0]` | — |
| `sst-fill` | — | `layers.sst-fill` | `z_order[1].members[0]`, `presets.STACK-A.layers[0].layer`, `presets.NEAR-D.layers[0].layer` | — |
| `sst-fill auto isotherms` | — | — | `z_order[6].members[1]` | — |
| `stations` | — | `layers.stations` | `z_order[10].members[0]` | — |
| `subsurface-temp` | — | `layers.subsurface-temp` | `z_order[1].members[4]` | — |
| `subsurface-temp.isotherms` | — | — | `z_order[6].members[4]` | — |
| `tides` | — | `layers.tides` | `z_order[10].members[1]` | — |
| `upwelling` | — | `layers.upwelling` | `z_order[5].members[3]` | — |
| `veils` | — | — | `z_order[2].id` | — |
| `visibility-fog` | — | `layers.visibility-fog` | `z_order[1].members[8]` | — |
| `waves-swell` | — | `layers.waves-swell` | — | — |
| `waves-swell.arrows` | — | — | `z_order[8].members[1]` | — |
| `waves-swell.fill` | — | — | `z_order[1].members[7]` | — |
| `wind` | — | `layers.wind` | `presets.STACK-A.layers[2].layer` | — |
| `wind.barbs` | — | — | `z_order[8].members[0]` | — |
| `wind.fill` | — | — | `z_order[1].members[6]` | — |
| `wind.particles` | — | — | `z_order[7].members[1]` | — |

The fragment's `layers[i]._token` and `layers[i].metadata["skippercast:layer"]` identify a family; `layers[i].metadata["skippercast:z"]` names a slot. The generator assigns slots per draw row, then sorts by stacking `z` (`scripts/style/layers_fragment.py:47–69,253–263`); it does **not** generate a row per stacking member. The probe joins each `_token`'s first key after `layers.` to the family and resolves the full `_token` path against the token file. Indices below refer to `layers[i]` in the fragment.

| Token family | Fragment layer IDs linked by `_token` |
| --- | --- |
| `ais-fleet` | `skl-ais-fill` [20], `skl-ais-line` [21], `skl-ais-label` [52] |
| `chlorophyll` | `skl-chlorophyll-fill` [1] |
| `clouds` | `skl-clouds-veil` [10] |
| `currents` | `skl-currents-fill` [3], `skl-currents-streamlines` [32] |
| `kd490` | `skl-kd490-fill` [2] |
| `kelp-habitat` | `skl-kelp` [17], `skl-shore-halo` [18], `skl-shore` [19] |
| `marine-zones-mpas` | `skl-hazard-fill` [13], `skl-zone-line` [14], `skl-mpa-fill` [15], `skl-mpa-line` [16], `skl-zone-label` [50], `skl-mpa-label` [51] |
| `places` | `skl-pier-halo` [40], `skl-pier` [41], `skl-ramp` [42] |
| `precip-radar` | `skl-radar` [12] |
| `pressure` | `skl-isobar-minor` [30], `skl-isobar-bold` [31], `skl-isobar-label` [48], `skl-pressure-centers` [49] |
| `routes-tracks` | `skl-track` [36], `skl-route-halo` [37], `skl-route` [38], `skl-waypoint` [39], `skl-waypoint-num` [53], `skl-leg-label` [54] |
| `salinity` | `skl-salinity-fill` [5] |
| `sea-ice` | `skl-sea-ice-veil` [11], `skl-sea-ice-edge` [24] |
| `spots-marks` | `skl-spot-others` [45], `skl-spot-badge` [46], `skl-spot-rank` [56] |
| `ssh` | `skl-ssh-positive` [27], `skl-ssh-negative` [28], `skl-ssh-zero` [29] |
| `sst-breaks` | `skl-sst-breaks-glow` [9], `skl-sst-iso-minor` [25], `skl-sst-iso-index` [26], `skl-sst-iso-label` [47] |
| `sst-fill` | `skl-sst-fill-fill` [0], `skl-sst-band-edge` [23] |
| `stations` | `skl-station-pin` [44], `skl-station-chip` [55] |
| `subsurface-temp` | `skl-subsurface-temp-fill` [4] |
| `tides` | `skl-tide-pin` [43] |
| `upwelling` | `skl-upwelling-ribbon` [22] |
| `visibility-fog` | `skl-visibility-fog-fill` [8] |
| `waves-swell` | `skl-waves-swell-fill` [7], `skl-wave-arrows` [35] |
| `wind` | `skl-wind-fill` [6], `skl-wind-particles` [33], `skl-wind-barbs` [34] |

```text
Layer families: 24; fragment layers: 57; stacking slots: 12; stacking members: 30; exact matrix rows: 102
All fragment _token paths resolve; stacking z_order equals fragment _z_order; layer picks agree.
```

- Stacking names some variants rather than their parent keys: `currents.*`, `wind.*`, `waves-swell.*` and `subsurface-temp.isotherms`. `sst-fill auto isotherms` is prose in `z_order[6].members[1]`, not a literal token key; that rule is described in `precedence[4]`, and the `NEAR-D` preset requests it. Neither `subsurface-temp.isotherms` nor SST-fill auto isotherms has a dedicated fragment row; the separate `skl-sst-iso-*` rows are wired to `layers.sst-breaks.isolines`, not `sst-fill` (`style/layers-v1.0.0.json:688`, `style/stacking-v1.0.0.json:58–69,194–197,232–243`, `scripts/style/layers_fragment.py:81–103,116–131`). The 12 slot IDs are labels, not concrete renderer IDs; for example, the base and house contours are stacking entries but not rendered by this reference fragment.
- The fragment groups `skl-sst-breaks-glow` in `color-field`, although that slot's member list does not name `sst-breaks`; it puts the sea-ice edge in `isolines`, while the member list names `sea-ice` in `veils`. `skl-sst-band-edge` is also sorted into `isolines` without being a member literal. These are differences between a slot's member list and its draw rows, not digest failures or evidence of what the running app enables (`style/stacking-v1.0.0.json:10–34,58–69`; `scripts/style/layers_fragment.py:101–128`).

## R3. README claims and consumers

### Claims, in README order

| README quote | Check |
| --- | --- |
| 3–5: “`nearshore-v1.0.0.json` is byte-identical to the owner-approved kit's `style-guide/style-tokens.json` (design card `t_a37142cd`). Kit ZIP SHA-256: `5e0ff9968a6c905e583aeb8da7c129e890fee89ce453d718053ce29a95958b39`.” | The local bytes and quoted ZIP pin agree with the index (R1; `style/index.json:5–7`). The private original, ZIP bytes and approval were not independently checked. The private driver has those hash comparisons (`scripts/style/kit_parity.py:235–253`). |
| 6–7: “Only the derived tokens are included from the kit. The unlicensed kit archive, fixtures, goldens, images and reference scripts stay private.” | No original archive, fixtures, goldens, images or reference scripts in the seven-file `style/` inventory. There is also a derived fragment and there are repository-owned generation and parity scripts, so “only” is not an inventory of all outputs. No conclusion about licence, private storage or material outside this checkout (R1; `scripts/style/gen_style.py:362–370`, `scripts/style/kit_parity.py:235–253`). |
| 9–12: “Released version files and their raw-byte SHA-256 pins are immutable. A new look needs a new file and index entry. `index.json` selects the default; a render tool can load an explicit version without changing the default. `deep-fixed-v1` is a rollback ID for the legacy ramp-B builder, not a token file.” | Consistent as a release rule, not a write lock: a byte edit under an unchanged pin fails, but these checks don't enforce history-wide immutability if both change. Explicit selection and legacy dispatch are real (`src/skippercast/style/__init__.py:27–36,244–261`; `src/skippercast/relief/render_config.py:35–51`; `src/skippercast/relief/tiles.py:31–51,67–68`; `web/map/relief-data.ts:26–36`). |
| 13–18: “`groups.json` maps dotted key prefixes to groups. The longest matching prefix wins; there is no default group. Arrays are assigned as whole values by their containing key (including ordered stops and tiers). Digests hash the UTF-8 canonical JSON of each group's subset, retaining the nested object shape, sorting keys and using no extra whitespace. `meta` is not hashed into rendering; QA may read its acceptance criteria.” | Confirmed for the four group hashes, not the raw-file pin. `acceptance` is `meta`; full snapshots expose it but render views exclude it. “May read” is permitted by the API, not a claim that the current QA actually reads it (`style/groups.json:2–5`; `style/nearshore-v1.0.0.json:622`; `src/skippercast/style/__init__.py:47–82,170–201,218–261`). |
| 19–26: “Checkout-based Python render tools use `skippercast.style.load()` and retain its immutable snapshot for a render. Each stage takes the digest of what it reads: tiles use `baked`, contours use `contours`, habitat uses `baked` and `habitat`. These digests identify style inputs, not survey data provenance. Render code reads tokens only through `Style.view(*groups)`, which raises `StyleGroupError` outside those groups; `load()` refuses a `groups.json` that no longer yields the index digests. `load(root=...)` reads another style directory (tests).” | Confirmed for the nearshore build stages: retained snapshots/views and separate raster/survey inputs. Legacy dispatch does not load a token snapshot. A group view rejects a known token outside its allowed groups; a nonexistent key still raises `KeyError`. Alternate root and mismatched group coverage are tested (`src/skippercast/relief/tiles.py:31–64`; `src/skippercast/relief/contours.py:173–181`; `src/skippercast/relief/nearshore_vectors.py:23–38`; `src/skippercast/style/__init__.py:190–197,237–261`; `tests/unit/test_nearshore_style.py:44–72`). |
| 27–31: “The web map gets non-colour values and CSS variable names from `web/map/nearshore-style.gen.ts`; the palette bridge resolves colours. Both themes inherit the same `--skn-*` colours from `:root`. The Coast 3D renderer gets its nearshore ramp, contour ink and no-data colour from the generated block in `packages/coast/src/palette.ts`.” | Confirmed for the nearshore projection, not every map layer. Coast selects a look from the generated table and uses its values when matched (`web/map/nearshore-paint.ts:1–12`; `web/map/palette.ts:34–54`; `web/tokens.css:220–256`; `scripts/style/gen_style.py:350–368`; `packages/coast/src/palette.ts:56–78`; `packages/coast/src/coast3d/shading.ts:5–15`; `packages/coast/src/coast3d/viewer.ts:106–118`). |
| 33–39: “For a new version, classify its keys and register its raw SHA-256 and kit provenance in the index. Run `python scripts/style/gen_style.py` to update the four group digests and regenerate the default style's CSS and TypeScript. Commit the inputs and outputs together. `python scripts/style/gen_style.py --check` checks all indexed token files and projections without writing them; its smoke test runs in the existing Python core tier. Do not edit generated blocks or add local style overrides in render tools.” | **Overbroad:** it checks raw pins and group hashes for every non-legacy nearshore entry, but checks all-layer raw pins, stacking and fragment only for `layers_default` (currently the only all-layer entry). It also projects active/rolling nearshore look tables, not just the default's paint. Write mode updates the group hashes and regenerates outputs; it does not automatically bless new raw or canonical pins. Check mode writes nothing. The smoke test is in the non-GIS CI run. Committing inputs/outputs together and avoiding hand edits/overrides are instructions; drift checks cover the generated files, not every possible local override (`scripts/style/gen_style.py:267–272,320–382`; `tests/unit/test_nearshore_style.py:144–147,247–313`; `.github/workflows/ci.yml:359`). |
| 43–47: “`layers-v1.0.0.json` and `stacking-v1.0.0.json` are byte-identical to the owner-approved all-layers kit's `layer-tokens.json` and `stacking.json`. The kit ZIP hash and both raw-byte pins are in `index.json`. The same licence boundary applies: only derived tokens are included from the kit; the kit archive, fixtures, goldens, images and reference scripts stay private.” | Pins and inventory confirmed (R1; `style/index.json:23–31`), including the derived reference fragment. No independent claim about private original bytes, approval, licence or storage; the private runner checks the three checkout token files against a private manifest, not a freshly hashed all-layers ZIP (`scripts/style/kit_layers_parity.py:24–28,58–89,181–188`). |
| 49–54: “`layers_default` selects the version; `skippercast.style.load_layers()` returns the resolved, read-only tokens with the `stacking` table and uses the indexed nearshore version for `base:` references. Layer releases do not enter relief generation keys. The same generator writes the `--skl-*` CSS block, the web projection and the MapLibre reference fragment. `--check` also verifies the fragment against the kit's pinned canonical JSON digest.” | Confirmed with two qualifications: explicit selection and `stacking:` references are also supported; `--check` hashes the regenerated fragment's canonical JSON against the index, then independently compares the committed pretty bytes. It does not open the private kit. Relief generation uses nearshore digests, as shown by the stage plans above (`src/skippercast/style/__init__.py:264–305`; `src/skippercast/relief/rebuild_plan.py:71–92`; `scripts/style/gen_style.py:267–327,350–382`). |

### Who reads what, and what happens on disagreement

| Consumer | Input and mismatch handling |
| --- | --- |
| `src/skippercast/style/__init__.py:27–36,244–261,308–333` (`load` and convenience helpers) | Reads the index, selected nearshore bytes and groups. Raises `ValueError` for raw or recomputed-group mismatch; no fallback. `deep-fixed-v1` is refused by `load()` itself. |
| `src/skippercast/style/__init__.py:264–305` (`load_layers`) | Raw pins for layers, stacking and the indexed base are mandatory; raw mismatch raises `ValueError`, before reference resolution. Also refuses inconsistent base version or broken references. Does not read groups or the fragment. |
| `src/skippercast/relief/render_config.py:35–51`; `src/skippercast/relief/tiles.py:31–64`; `src/skippercast/relief/contours.py:173–181`; `src/skippercast/relief/nearshore_vectors.py:23–38` | Resolver calls `load()`; a mismatch prevents stage planning. No implicit fallback to ramp B. The later index reads collect provenance pins; a valid explicit legacy selection is the separate no-token path. |
| `src/skippercast/platform/depth_contours.py:85–92,478`; `src/skippercast/relief/qa.py:29,72`; `scripts/build_depth_contours.py:630–635` | The FT-v3 validation/QA lookup requires a known active/rolling contours digest, then calls `load()`; malformed, unknown or mismatching values raise. The v3 builder resolves a verified style and does not substitute v2 on mismatch. This QA digest lookup is not a parity-receipt lookup. |
| `scripts/relief/run_region.py:466–488` | Dry-run reports `REFUSE tiles style` on loader failure; marks tiles inputs missing if tiles are in the requested chain. Real stage planning uses the resolver above. |
| `src/skippercast/relief/rebuild_plan.py:71–92`; `scripts/relief/rebuild_plan.py:61–69,95–105`; `scripts/relief/style_preview_plan.py:16–35,76–79`; `scripts/relief/style_diff.py:36,85–96` | Rebuild, preview and diff read the verified selected style. Loader mismatch aborts planning/comparison; the CLIs report the exception. Preview's per-region invalid-row handling is separate from its top-level version verification. |
| `scripts/style/gen_style.py:267–272,320–382,385–398` | Raw, group, canonical fragment and output-byte checks described above. Prints diagnostic and exits 1 on mismatch in `--check`; no write. In write mode only computed outputs and group digests are regenerated; raw and canonical pins still gate it. |
| `scripts/relief/label_lint.py:50–58,125–171` | Reads indexed fragment paths and checks label inputs, not manifest hashes. A digest mismatch alone does not stop it. |
| `scripts/style/make_synthetic_goldens.py:105`; `scripts/style/kit_parity.py:229–253,262–288,303–321` | Synthetic golden tool takes verified `baked`; a mismatch stops the load. Private nearshore parity runner exits 1 on loader/ZIP/reference/fixture mismatch before comparison; it binds the comparison to the verified style and reference inputs. Neither tool was run. |
| `src/skippercast/style/parity.py:14–36,39–68`; `src/skippercast/relief/tiles.py:60–64`; `scripts/style/kit_parity.py:263–275,303–321` | `parity.py` builds identity keys, not kit-file verdicts. It validates digest **shape**, runtime fields and epoch, hashes engine/loader code, and binds oracle identity to ZIP, manifest, reference code, runtime and case arguments. The parity key also binds engine digest/epoch/runtime, `baked` and the oracle key. A well-formed changed input gives a different key; the module does not read the style index, fragment or parity receipts. Tiles records engine identity, not a parity verdict; the private runner verifies bytes and writes the report. The module docstring's QA lookup description is not demonstrated by current callers (`git grep -nE 'parity_key\(|parity\.json|engine_digest\(' -- src scripts`). |
| `scripts/style/kit_layers_parity.py:24–28,73–89,181–188,236–240` | Separate private all-layers comparison: aborts if repository token bytes or staged kit bytes differ from the manifest. Records the index's ZIP digest as identity metadata; does not use that field as a direct ZIP-byte check. |
| `web/map/nearshore-paint.ts:7`; `web/map/depth-contours.ts:30`; `web/map/legend-model.ts:43,79–99`; `web/map/palette.ts:11,48–54`; `web/map/sst-bands.ts:1–6`; `web/map/sst.ts:43–49`; `packages/coast/src/coast3d/shading.ts:5–15` | Read generated modules/CSS, not kit files. No raw kit digest validation at runtime. Pointer baked digests are look selectors, not rehashes; absent pointer style means legacy, malformed or unknown looks do not silently get the new ramp (`web/map/relief-data.ts:26–45`; `web/map/legend-model.ts:79–99`; `packages/coast/src/coast3d/viewer.ts:106–118`). The standalone SST case export also uses a generated constant, not the raw kit (`scripts/style/export_cases/01-sst-fill.mjs:2`). |
| Test readers | `tests/unit/test_nearshore_style.py:23–72,119–147,247–371` covers raw/group refusals, deterministic keys, no-write generation drift, layer pins and reference integrity. `tests/unit/test_label_lint.py:32,148–169` uses synthetic index/fragment shape cases, and `tests/test_field_texture.mjs:69` reads the fragment as a texture/paint fixture without hashing it. Other direct fixture/setup hits in the card's search: `tests/gis/test_relief_contours.py:613,709`, `tests/gis/test_relief_nearshore_vectors.py:32–38,91`, `tests/unit/test_relief_package.py:125,151–159`, `tests/unit/test_relief_render_config.py:39`, `tests/unit/test_style_preview_plan.py:29–31`. These are test setup/expectations, not independent runtime digest checkers. |

To reproduce consumer discovery: `git grep -ln 'style/index.json\|layers-v1.0.0' -- tests scripts web packages`; then `git grep -nE 'style\.load\(|load_layers\(|resolve_style\(|v3_view\(|nearshore-style\.gen|layers-style\.gen|NEARSHORE_COAST_LOOKS' -- src scripts web packages tests`. This is repository evidence, not a claim about deployed software. `python -B scripts/style/gen_style.py --check` returned exit 0 and `nearshore-v1.0.0 + layers-v1.0.0: style tokens and projections match` on 2026-11-21.

## R4. One optional follow-up

Update **only** `style/README.md` (estimate: 30–45 minutes, separate scope) to distinguish all non-legacy nearshore versions from the single selected all-layers version in `--check`, and spell out the canonical-then-byte-for-byte fragment checks. Keep private-kit and licence language as-is. Offline acceptance: `python scripts/style/gen_style.py --check`, `python -m pytest -q tests/unit/test_nearshore_style.py`, and `git diff --check`; require a README-only diff. No regeneration or pin change is warranted by R1.
