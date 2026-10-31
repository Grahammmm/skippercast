# Seafloor error correction (EC): shared contract

`src/skippercast/platform/seafloor_ec.py` (EC0, stdlib only) fixes the contract every EC tool imports: provenance
codes, thresholds, the tolerance and shoal rules, the independence rule, receipt schemas and the GeoJSON properties.
Depths are elevation-up metres (water is negative). The one rule: **the chart never shows water deeper than the
evidence supports.** Fills use the shallowest neighbour, conflicts show the shallower survey, and a receipt with
any deepened cell is refused.

A machine-valid receipt is review-required, not acceptance; nothing here converts a datum or certifies navigation.

## Provenance codes (`CODES`, `EC_VERSION = '1.0'`)
| Code | Name | Class (tens digit, `CLASS_OF`) | `REASON_OF` |
| --- | --- | --- | --- |
| 0 | `nodata` | nodata | `nodata` |
| 10 / 11 | `measured` / `measured-suspect-shoal` | measured | `measured` / `suspect-shoal` |
| 20 / 21 | `filled-hole` / `filled-pit` | filled | `hole` / `pit` |
| 30 | `verified` | verified | `verified` |
| 40 / 41 / 42 / 43 | `unresolved-hole` / `-conflict` / `-ring-range` / `-datum-suspect` | unresolved | `hole` / `conflict` / `ring-range` / `datum-suspect` |
| 50 | `masked-sentinel` | masked | `sentinel` |

`block_class(codes)` (one builder block): `unresolved` if any code is unresolved, nodata or masked; else `filled` if
any is filled; else `verified` if every code is verified; else `measured`. Empty or unknown codes raise `ValueError`.

## Thresholds (`THRESHOLDS`; each also a module name)
- `hole_max_cells(cell_m) = min(9, int(64 // cell_m²))`: 9 at 2 m, 4 at 4 m, 1 at 8 m, 0 at 16 m.
- `hole_ring_max_range_m(d) = max(2.0, 0.10 × |d|)` (ring shallowest); `outlier_min_m(d) = max(3.0, 0.20 × |d|)` (ring median); `OUTLIER_MAX_CELLS = 2`.
- `SENTINELS` = −9999, 9999, −999999, 1e6, 5000, ±32767, ±3.4028234663852886e38; `PLAUSIBLE_M = (−3000, 100)`.
- Fixture refusal: `FIXTURE_PATH` (pytest-basetemp, `/fixture(s)/`, `/scratch/`, synthetic, invented, generated-template, `sample.tif`), `FIXTURE_MIN_PIXELS = 4096`, `FIXTURE_MAX_DISTINCT = 3`.
- Sign refusal: `SIGN_POSITIVE_FRACTION = 0.99`. Datum suspect: `DATUM_SUSPECT = {min_cells: 1000, max_mad_m: 0.5}`.

**Tolerance** `tol_m(d) = 2 × sqrt(0.5² + (0.013 × |d|)²)` m: 1.0 at 0 m, 1.64 at 50 m, 2.79 at 100 m (IHO S-44
Order 1a TVU, doubled; an assumption). It compares two depths; it never corrects one.
**Shoal rule** `shoal_pick(values)` = the shallowest (largest elevation-up) value. **No-deepening** `no_deepening(before, after, treated)`
lists treated indices that got deeper and untreated indices that changed at all (NaN to NaN is unchanged); `[]` is PASS.

## Independence (`acquisition_key`, `independent`)
- Key: `bag` / `noaa-native-vr-bag` → survey id from the file name (prefix before the first `_` after an optional
  `BAG__`, `^[A-Z]\d{5}$`, else unknown); every other adapter → the catalog source id.
- `independent(a_entry, a_file, b_entry, b_file, duplicate=False)` → `(bool, reason)`, checked in this order:
  `compilation:<adapter>` (`COMPILATION_ADAPTERS`: bluetopo-geotiff-source-review, nbs-modeling-geotiff,
  gebco-grid-deep-fill, gmrt-gridserver-deep-fill, ncei-footprint-discovery), `duplicate`, `unknown-acquisition`,
  `same-acquisition:<key>`, else `(True, 'ok')`. There is no override.

## Receipts (`SCHEMAS`, `check_receipt(kind, doc) -> list[str]`)
Kinds `ec-detect-v1`, `ec-apply-v1`, `ec-verify-v1`, `region-correct-v1`. Each problem names its key
(`provenance_sha256: missing`, `counts.bogus: unknown code`). Enforced: every listed key is present (a type word
ending in `?` may be null when the value is unavailable, never absent), numbers are finite (the canonical writer uses
`allow_nan=False`), `schema == kind`, `ec_version == EC_VERSION`, `counts` keys are `CODES` names, sha256 fields are
64 lowercase hex, `disposition` (and a source `status`) in `PASS|FIX|VERIFY|UNRESOLVED|REFUSED`, `deepened_cells == 0`
for apply. Only two records may omit keys: a hole above `hole_max_cells` (`disposition: 'hole'`) carries only `cells`,
`bbox`, `disposition`, and a `REFUSED` source carries only `receipts.detect`. Extra keys are allowed.

**`bbox` convention (every receipt, every EC tool):** `[col0, row0, col1, row1]` in native pixel indices,
**end-exclusive** like numpy slices: the box covers rows `row0 … row1 − 1` and columns `col0 … col1 − 1`, so one
cell at row `r`, column `c` is `[c, r, c + 1, r + 1]`. `check_receipt` accepts only four non-negative integers with
`col0 < col1` and `row0 < row1`, so an inclusive one-cell box such as `[5, 5, 5, 5]` is refused. ec_detect writes
this form, ec_apply reads it, and `tests/gis/test_ec_bbox_contract.py` feeds one tool's receipt to the other.

## Run folder (private, outside the repository)
`ec/<source_id>/{EC-DETECT.json, EC-APPLY.json, EC-VERIFY.json, corrected.tif, provenance.tif, ENTRIES.json, DONE}`,
then `EC.json` (`region-correct-v1`), `EC.md` (one line per source plus `Operator asks`) and `INTAKE-EC.csv`: all
INTAKE columns verbatim plus `ec_status`, `ec_path` (`ec/<id>/corrected.tif`, or the original `local_path` when not
corrected) and `provenance_path` (`ec/<id>/provenance.tif`, or empty). A `REFUSED` row has `use` `skip` and
`held_reason` `ec-refused:<reason>`.

## CLI contracts (as the EC1–EC4 specs state them)
- EC1: `python scripts/ec_detect.py PATH --source-id ID --receipt OUT.json [--adapter geotiff] [--max-pixels N] [--strip-rows 1024]`.
  Exit 0 with one JSON line `{"disposition": ..., "receipt": OUT}`; exit 2 on refusal with
  `detect refused: <field>: <reason>` on stderr.
- EC2: `python scripts/ec_apply.py PATH --detect EC-DETECT.json --out-dir DIR`. Exit 0 with one JSON line; exit 2 on
  refusal; exit 3 `apply refused: deepened <n> cells` when the no-deepening check fails (outputs deleted).
- EC3: `python scripts/ec_verify.py --a DIR_A --a-source ID_A --b PATH_B --b-source ID_B [--b PATH --b-source ID …]
  --catalog-entries ENTRIES.json --a-datum TEXT --b-datum TEXT [--b-datum …] --out-dir DIR [--max-pixels 120000000]`.
  Zero `--b` yields `pairs: []`, `disposition PASS`. Exit 0 / 2 as EC1–EC2.
- EC4: `skills/skippercast-region-correct/scripts/region_correct.py <region_id> --run <dir> --author-runtime <id>
  --author-family <family> [--python <exe>] [--batch 3]` and `region_correct.py --check <dir>`. Prints
  `EC <id> <disposition> filled=<n> pit=<n> verified=<n> conflict=<n> unresolved=<n>`, `EC BATCH-DONE <treated>/<total>`,
  `EC ALL-DONE <n> rows`, `EC OK <n> rows`; any subprocess failure exits 1 with `EC STOP <source_id> <tool> <stderr tail>`.

## GeoJSON property contract (EC5 writes, EC6 draws, EC8 reviews)
- Contour runs carry `properties.provenance` in `PROVENANCE_CLASSES = ('measured', 'filled', 'verified')`, only when
  provenance input was given.
- Unresolved blocks become `kind: 'unresolved-area'` (`UNRESOLVED_KIND`) polygons with `reason` in
  `UNRESOLVED_REASONS = ('hole', 'conflict', 'ring-range', 'datum-suspect', 'nodata')`, an integer `blocks`, and
  `shoal_hint_ft` (`SHOAL_HINT_KEY`, the shallower reading in feet) only when `reason` is `conflict`.
- Unresolved areas are drawn as areas, never as contours.
