# SP1611-LAND-QUANTISATION (SP-16-v1)

## Scope and behavior

`assemble` now validates `provenance.display_quantisation_m` before using it in the existing uncertainty sum. Values must be finite, numeric, non-boolean, and nonnegative. Invalid values add the cause `invalid display quantisation`; `build_product` retains the existing unavailable index and returns no lines. Zero and all valid nonnegative values keep the existing error-budget, geometry, joins, parity and tile-screen behavior. This is an offline synthetic test qualification only; it is not scientific, legal, navigation, source, live or publication acceptance.

Allowed product edit: `src/skippercast/platform/land_water.py`. New files: `tests/unit/test_sp1611_land_quantisation.py`, `scripts/accept_sp1611_land_quantisation.py`, `tests/fixtures/sp1611_land_quantisation/baseline.json`, and this note.

## Frozen expected-red pair and baseline evidence

The baseline pair was authored against unchanged product code and fixture inputs (`tests/fixtures/sp1611_land_quantisation/baseline.json`, SHA256 `f5ed338e92b7fbadee256d35a9260c17db3f75495aba0acbbd41e2020acd3a3e`). The pair is `BaselineTest.test_primary_regression` and `BaselineTest.test_healthy_control`; both use the staged original synthetic CUSP producer helpers and real `land_water` module. Their test IDs and fixture remained unchanged for the post-repair rerun. (The test module was subsequently extended with separate A1-A4 tests in the same permitted file.)

The baseline acceptance wrapper ran before the product edit. Result: `BASELINE_GAP_REPRODUCED`, wrapper exit 0; child exit 1; exactly two tests, one failure. Healthy control passed. Primary regression failed specifically because status was `available` rather than `unavailable` for HOR_ACC=20 and quantum=-20. No import/setup error or skip. Raw child stderr SHA256 `476180da75c616cecc02223d56884388b5b3b951ccd247e2bf5b3c878f0c4984`; stdout SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Evidence is under `out/author-baseline`.

## Focused and regression evidence

Focused invocation ran the unchanged baseline pair plus A1-A4: six tests, exit 0, zero skips/errors. A1 checks the reported -20 case and no lines; A2 checks -20/-1, null, string, boolean, NaN, and both infinities; A3 checks zero, the 4.31/1.96 control, and excessive HOR_ACC=20 error; A4 checks 7.63/7.64/7.65 around the exact EDGE_M sum boundary. Raw stderr SHA256 `12a6d963575925af59e9a6763f5e46266eb25b8a455cb83bd963dfdd68e90ed0`; stdout SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Evidence is under `out/author-focused`.

Unchanged original selector `tests.unit.test_land_water.BuilderTest` ran 12 tests, exit 0, zero skips/errors. Raw stderr SHA256 `21587ee1d4ade7ac37aca1c02516157360417621e85a8e9ecddc657dfa758106`; stdout SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Evidence is under `out/author-regression`.

Unchanged repository checker ran with manifest `runtime.credential_scan_python3`, exit 0. Raw stdout SHA256 `3477faedf51eb4a92734599062e202d1429c40267d56f6514f942a5b8febc720`; stderr SHA256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Evidence is under `out/author-repository`.

Every invocation uses a new unique child output directory and writes separate raw stdout/stderr plus a receipt. The child uses an on-disk bootstrap to anchor imports to this staged clone; no network, models, installation, live stores or services are used.

## Limits and handoff

Baseline source was staged at `8a805820c30895f5f037e26af9079fd3dc015b0f`. Primary baseline source SHA256 was `092536acdda562bc0a0117423152150d7a32a5c434d55ce6240ab972d66e89c9`; unchanged original regression test SHA256 was `52c2c02c75fc83aa92fdc78b7de3885ec8e76ba9a42e4c521dd16ceab840c169`. Final scoped status is REVIEW REQUIRED. Full repository test discovery, GIS/survey accounting, typecheck/build, dependency audit, browser/e2e and exact-head CI remain OWED to the operator. No PR, publication, merge, live run, source acquisition, hold change or scientific/legal/navigation acceptance is authorized by these results.
