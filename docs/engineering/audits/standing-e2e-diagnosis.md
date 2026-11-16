# AUDINV-CIW-19 — Standing e2e diagnosis

## Disposition: ENVIRONMENT; exact current browser pair UNVERIFIED

This is the bounded environment receipt allowed by the CHECK FIRST spec, not a
product repair, proof of no gap, or proof of flakiness. Only this report changes.
No traced current reproduction admits a speculative production/test diff.

Checked source: `0991fc70d212c9405f7b174950cb3fa4d7c6846d` (fresh `origin/main` clone).
Branch: `rb/audinv-ciw-19`. All repository locators below are at that source unless
explicitly historical. Command cwd: `<checkout>` (this task's repository root).

**Receipt redaction:** the repository's existing privacy check rejects literal
host home paths. This public report consistently substitutes `<checkout>` for
the task checkout, `<historical-checkout>` for the hosted runner checkout, and
`$HOME` for the operator home. Output is otherwise retained in full; commands
with angle-bracket placeholders are descriptive receipts, not copy/paste shell
commands. Unredacted exact command/cwd/exit/output is retained in the task-local
`acceptance-receipt.json`, `source-receipt.json` and `historical-receipt.json`.
The first report check caught home paths; they were redacted without changing
the privacy gate. No such paths are intended for repository publication.

The source tree has no JS dependencies or built Worker. No JS install, browser
download, build, default e2e server, foreign server reuse or upstream Worker read
was attempted. The explicitly required WTENV-2 Python-only local editable setup
was performed after ENV-MISSING; it did not provision a browser harness.

## Historical full-title mapping (not line-number guessing)

The retained audit at `~/agent-work/reports/CI-WEIGHT-AUDIT-2026-11-03.md:363-378`
identifies `land-water.spec.ts:48:1` and `startup.spec.ts:13:1`, without a same-SHA
paired pass/fail. Read-only GitHub metadata independently resolves these cases:
[run 41722267205](https://github.com/Grahammmm/skippercast/actions/runs/41722267205),
branch `rb/sc1322-10`, historical SHA `eaad7aba48fdf6ea8c412b332021789c417a43b9`,
e2e job/check `126217864229`, conclusion failure. The API annotations below include
both original failures and Retry #1 failures; these are historical observations,
not a retries=0 run performed by this builder and not paired success evidence.

| Historical declaration | Stable full title | Current declaration | Historical failing assertion |
|---|---|---|---|
| `e2e/land-water.spec.ts:48` | with the committed index the places rank from clean cells and the lines file is never requested | `e2e/land-water.spec.ts:50` | line 55: `expect(lines).toEqual([])` received one `/regions/morro-bay/land-water-lines.json` request |
| `e2e/startup.spec.ts:13` | the v2 app reads each committed startup file once, within the budget | `e2e/startup.spec.ts:13` | line 20: static startup JSON 1055049 bytes, expected <= 853734 |

**VERIFY-1 correction:** the spec's example selects the adjacent delayed-index
case, not historical line 48. That adjacent title is “a delayed index that leaves
candidates in mixed cells loads the lines file and ranks the water places”:
historical declaration line 25, current line 27. Its historical annotation fails
at line 42 (`toBeVisible`, pick absent). It remains relevant supporting coverage,
but must not replace the exact clean-cell/startup phone pair. Current line 48 is
only the delayed-index test's closing line. Both land-water tests retain laptop
coverage; only startup intentionally limits measurement to phone (line 14).

The historical assertions identify symptoms, not a traced current root cause.
The startup annotation reached the budget assertion after the repeated-read
assertion; its later page-error assertion is not thereby proved. A different
SHA's successful workflow (41741510708 at 804030145d4dd62780082a94fc48a0f7fd175455)
is not same-SHA flake evidence and was not used to claim either case repaired.

## Current observations and safe-harness boundary

- `web/brief/WhereToLook.tsx:291-319` already computes `wantLines` from pending,
  ready state and missing lines, and includes `lw.model` in the lines-loading
  effect dependencies. This resembles a repair; it is not browser evidence.
- `e2e/land-water.spec.ts:16-19` already sets Save-Data and blocks coast-report
  in its setup. This differs from the historical source; no causal claim follows
  without an isolated browser reproduction.
- `playwright.config.ts:29-74` sets retries=0 but launches `node e2e/serve.mjs`.
  That server's lines 28-34 write Wrangler config, remove local state and migrate
  and seed D1; lines 43-60 seed R2 and start the Worker. Its comments explicitly
  say browser origin blocking does not block all Worker-side upstream reads.
  The default normal route is not authorized by this spec and was not launched.
- The fresh checkout has neither `node_modules/@playwright/test/package.json`
  nor `dist/server/index.js`. No alternative provisioned isolated, source-free
  browser harness was supplied or found in this task checkout. The tracked
  Playwright-config filename search found only `playwright.config.ts` and
  `tests/test_playwright_config.mjs`. This is a bounded checkout finding, not an
  assertion that no safe harness could exist elsewhere on the host.
- Chromium availability is UNKNOWN (not probed after prerequisites failed).
  No browser assertion ran. JS dependency import failure is an ENVIRONMENT
  observation, not historical product-failure reproduction.
- All four requested Node modules fail loading `@preact/signals` before their
  assertions. Their full output is retained below. No foreign node_modules,
  installed-source fallback or automatic JS package installation was used.
- The required local Python checker initially returned ENV-MISSING (exit 2).
  The task-authorized WTENV-2 helper created a checkout-resolving venv, installed
  only this checkout editable with `--no-deps`, reused existing shared Python
  dependencies and reported the shared venv unchanged. Re-running the checker
  passed layout and repository gates. This does not fix the JS environment.
- `package.json` has no `check` script. `npm run check` is not applicable.
- Open-PR file metadata was checked before writing: no open PR in that returned
  snapshot owned this report. No source, pin, test, workflow or budget changed.

## Acceptance coverage / precise remaining gaps

These rows distinguish retained assertion locations from executed proof. No
synthetic or source-inspection observation populates a live browser result.

| Spec edge | Relevant existing coverage | Observation in this run |
|---|---|---|
| 1. Held index, no early lines, release mixed cells, ranked water | `e2e/land-water.spec.ts:27-47`; `tests/test_land_water_pending.mjs:24-57` | Browser NOT RUN; Node import failed; no behavior proved |
| 2. Clean cells / omitted published lines | `e2e/land-water.spec.ts:50-85`; `tests/test_land_water.mjs:351-385` | Exact historical title mapped; current browser NOT RUN; Node import failed |
| 3. Old-region/reset response cannot revive | `tests/test_land_water.mjs:210`; `tests/test_land_water_pending.mjs:79-116,134-189`; `tests/test_sp1503_land_water_retry.mjs:126` | Node import failed; stale/reset/cancel-style disposal unverified |
| 4. Coalescing / bounded explicit transient retry | `tests/test_land_water.mjs:136-208`; `tests/test_sp1503_land_water_retry.mjs:85-197` | Node import failed; duplicate and failure-path outcomes unverified |
| 5. Static once-per-path / exact byte boundary | `e2e/startup.spec.ts:18-20`; `tests/test_map_startup.mjs:58-73` | Browser NOT RUN; Node import failed; equal-budget/one-byte-over boundary execution UNKNOWN |
| 6. Live/static separation / independent page errors | `scripts/measure_startup.mjs`; `e2e/startup.spec.ts:18-21` | No budget, repeated-read or page-error assertion weakened; current behavior unverified |
| 7. Missing prerequisites are environment, not flake proof | Actual missing paths and ERR_MODULE_NOT_FOUND below | Observed ENVIRONMENT; no inferred product cause |
| 8. Phone startup / laptop land-water | `e2e/startup.spec.ts:14`; `playwright.config.ts:52-54`; land-water has no project skip | Preserved by zero test/config edits; browser execution unverified |

No new cancellation/expiry/duplicate/stale behavior is introduced in this
report-only branch. No failure-path tests were added to mask the unavailable
harness. Existing shared-suite regressions remain untouched. No retries, timeout,
skip/quarantine, startup-budget raise or workflow edit is part of this handoff.
Current startup budget remains the committed value in
`scripts/startup-budget.json:morro-bay`; its source-recorded baseline is not a
measurement made in this run.

**HOLD / custodian gap:** the existing e2e/CI harness custodian would need to
supply an already provisioned, isolated, source-free checkout harness for a later
admitted retries=0 reproduction of the mapped exact phone pair (and preserved
laptop land-water coverage). Its actual owner identity and safe-harness path are
UNKNOWN here. That missing execution evidence remains unresolved; this bounded
report completes without demanding an owner response. No new card, live action,
source acquisition, deployment, semantic acceptance or retry authority is granted.

## Source identity receipts

SHA256 values are computed from the checked checkout, not copied as proof from
an older receipt. Historical source files were separately read with `git show`
at the failing run SHA; their declaration titles were compared to the annotations.

| Current source | SHA256 |
|---|---|
| `e2e/land-water.spec.ts` | `ab23e698162efb0d906bd1f45f4af6e4046a2f8467122f4612e5d1d68d89d365` |
| `e2e/startup.spec.ts` | `7f5771f2f343f99e8c991b47d3f0af205ebdfddc7cc2470815f91f144e1274e0` |
| `web/brief/WhereToLook.tsx` | `c5e885c4d6816d09d98a099fd0255588621acb3712977d571aac6892341e39ed` |
| `web/land-water.ts` | `4cace2073c285b1e24e63cd0c26bafe5e5990690f0d500c4eadfade4e6dfc151` |
| `scripts/measure_startup.mjs` | `cb916bdcdf4a32b80aeee685b65efca1efe077d53301389793267b7d5af34c14` |
| `playwright.config.ts` | `052549def17d95761457bcb9bbe743ee89b360a72bc5224dfedf111c9d947f58` |
| `e2e/serve.mjs` | `9c819d2221e50fcaffc5a07f79299df521ba5ca34e25ba2908a768cef9ddc462` |
| `tests/test_map_startup.mjs` | `af7ad6fa6ead82f74b79d85a10a504f02d10fe9c2f630e69e94bb7d4ef6cba45` |
| `tests/test_land_water_pending.mjs` | `fd8e6602a0064eb69021bae73f4fbb96308ae42a1c3cfe62f7a6e427b2f78ca9` |
| `tests/test_land_water.mjs` | `83adb4c6013f6b06f6dbf5b800b5adb5dcf391c37327fee5139a256e621e09b2` |
| `tests/test_sp1503_land_water_retry.mjs` | `6afee76e32f0b366c9dde2ba52527e89bd11f7b967a30f1bc426571006d20e3b` |

| Historical source at failing SHA | SHA256 |
|---|---|
| `e2e/land-water.spec.ts` | `1369fe77cf9220c538e0d9f9fb09f307ef9a72e1fbf58eaf12367394d7275529` |
| `e2e/startup.spec.ts` | `7f5771f2f343f99e8c991b47d3f0af205ebdfddc7cc2470815f91f144e1274e0` |

## Retained historical annotations

Read-only API command (cwd above, exit 0, stderr empty):

```text
gh api repos/Grahammmm/skippercast/check-runs/126217864229/annotations --paginate
```

The following is a labeled projection, not the entire endpoint response: only
annotations whose `path` is `e2e/land-water.spec.ts` or `e2e/startup.spec.ts`.
All six matching entries (original and retry for each of three cases) are retained
in endpoint order. JSON escaping preserves complete message strings, including
trailing whitespace, without introducing Markdown whitespace errors.

```json
[
  {
    "path": "e2e/land-water.spec.ts",
    "blob_href": "https://github.com/Grahammmm/skippercast/blob/eaad7aba48fdf6ea8c412b332021789c417a43b9/e2e/land-water.spec.ts",
    "start_line": 42,
    "start_column": 52,
    "end_line": 42,
    "end_column": 52,
    "annotation_level": "failure",
    "title": "[phone] › e2e/land-water.spec.ts:25:1 › a delayed index that leaves candidates in mixed cells loads the lines file and ranks the water places",
    "message": "  3) [phone] › e2e/land-water.spec.ts:25:1 › a delayed index that leaves candidates in mixed cells loads the lines file and ranks the water places \n\n    Retry #1 ───────────────────────────────────────────────────────────────────────────────────────\n    Error: expect(locator).toBeVisible() failed\n\n    Locator: locator('.app-sheet-brief .app-where').locator('.app-pick').first()\n    Expected: visible\n    Timeout: 15000ms\n    Error: element(s) not found\n\n    Call log:\n      - Expect \"toBeVisible\" locator('.app-sheet-brief .app-where').locator('.app-pick').first() with timeout 15000ms\n      - waiting for locator('.app-sheet-brief .app-where').locator('.app-pick').first()\n\n\n      40 |   expect(lines, 'no lines file while the index is held').toEqual([]);\n      41 |   release();\n    > 42 |   await expect(where.locator('.app-pick').first()).toBeVisible();\n         |                                                    ^\n      43 |   expect(lines).toHaveLength(1);\n      44 |   await expect(where.locator('.app-empty')).toHaveCount(0);\n      45 |   expect(pageErrors).toEqual([]);\n        at <historical-checkout>/e2e/land-water.spec.ts:42:52",
    "raw_details": ""
  },
  {
    "path": "e2e/land-water.spec.ts",
    "blob_href": "https://github.com/Grahammmm/skippercast/blob/eaad7aba48fdf6ea8c412b332021789c417a43b9/e2e/land-water.spec.ts",
    "start_line": 42,
    "start_column": 52,
    "end_line": 42,
    "end_column": 52,
    "annotation_level": "failure",
    "title": "[phone] › e2e/land-water.spec.ts:25:1 › a delayed index that leaves candidates in mixed cells loads the lines file and ranks the water places",
    "message": "  3) [phone] › e2e/land-water.spec.ts:25:1 › a delayed index that leaves candidates in mixed cells loads the lines file and ranks the water places \n    Error: expect(locator).toBeVisible() failed\n\n    Locator: locator('.app-sheet-brief .app-where').locator('.app-pick').first()\n    Expected: visible\n    Timeout: 15000ms\n    Error: element(s) not found\n\n    Call log:\n      - Expect \"toBeVisible\" locator('.app-sheet-brief .app-where').locator('.app-pick').first() with timeout 15000ms\n      - waiting for locator('.app-sheet-brief .app-where').locator('.app-pick').first()\n\n\n      40 |   expect(lines, 'no lines file while the index is held').toEqual([]);\n      41 |   release();\n    > 42 |   await expect(where.locator('.app-pick').first()).toBeVisible();\n         |                                                    ^\n      43 |   expect(lines).toHaveLength(1);\n      44 |   await expect(where.locator('.app-empty')).toHaveCount(0);\n      45 |   expect(pageErrors).toEqual([]);\n        at <historical-checkout>/e2e/land-water.spec.ts:42:52",
    "raw_details": ""
  },
  {
    "path": "e2e/startup.spec.ts",
    "blob_href": "https://github.com/Grahammmm/skippercast/blob/eaad7aba48fdf6ea8c412b332021789c417a43b9/e2e/startup.spec.ts",
    "start_line": 20,
    "start_column": 129,
    "end_line": 20,
    "end_column": 129,
    "annotation_level": "failure",
    "title": "[phone] › e2e/startup.spec.ts:13:1 › the v2 app reads each committed startup file once",
    "message": "  2) [phone] › e2e/startup.spec.ts:13:1 › the v2 app reads each committed startup file once, within the budget \n\n    Retry #1 ───────────────────────────────────────────────────────────────────────────────────────\n    Error: static startup JSON 1055049 bytes; budget 853734 (scripts/startup-budget.json)\n\n    expect(received).toBeLessThanOrEqual(expected)\n\n    Expected: <= 853734\n    Received:    1055049\n\n      18 |   const repeated = result.rows.filter(r => !r.live && r.requests > 1).map(r => `${r.path} × ${r.requests}`);\n      19 |   expect(repeated, 'each committed static file is requested once').toEqual([]);\n    > 20 |   expect(result.static, `static startup JSON ${result.static} bytes; budget ${budget.max_bytes} (scripts/startup-budget.json)`).toBeLessThanOrEqual(budget.max_bytes);\n         |                                                                                                                                 ^\n      21 |   expect(pageErrors).toEqual([]);\n      22 | });\n      23 |\n        at <historical-checkout>/e2e/startup.spec.ts:20:129",
    "raw_details": ""
  },
  {
    "path": "e2e/startup.spec.ts",
    "blob_href": "https://github.com/Grahammmm/skippercast/blob/eaad7aba48fdf6ea8c412b332021789c417a43b9/e2e/startup.spec.ts",
    "start_line": 20,
    "start_column": 129,
    "end_line": 20,
    "end_column": 129,
    "annotation_level": "failure",
    "title": "[phone] › e2e/startup.spec.ts:13:1 › the v2 app reads each committed startup file once",
    "message": "  2) [phone] › e2e/startup.spec.ts:13:1 › the v2 app reads each committed startup file once, within the budget \n    Error: static startup JSON 1055049 bytes; budget 853734 (scripts/startup-budget.json)\n\n    expect(received).toBeLessThanOrEqual(expected)\n\n    Expected: <= 853734\n    Received:    1055049\n\n      18 |   const repeated = result.rows.filter(r => !r.live && r.requests > 1).map(r => `${r.path} × ${r.requests}`);\n      19 |   expect(repeated, 'each committed static file is requested once').toEqual([]);\n    > 20 |   expect(result.static, `static startup JSON ${result.static} bytes; budget ${budget.max_bytes} (scripts/startup-budget.json)`).toBeLessThanOrEqual(budget.max_bytes);\n         |                                                                                                                                 ^\n      21 |   expect(pageErrors).toEqual([]);\n      22 | });\n      23 |\n        at <historical-checkout>/e2e/startup.spec.ts:20:129",
    "raw_details": ""
  },
  {
    "path": "e2e/land-water.spec.ts",
    "blob_href": "https://github.com/Grahammmm/skippercast/blob/eaad7aba48fdf6ea8c412b332021789c417a43b9/e2e/land-water.spec.ts",
    "start_line": 55,
    "start_column": 17,
    "end_line": 55,
    "end_column": 17,
    "annotation_level": "failure",
    "title": "[phone] › e2e/land-water.spec.ts:48:1 › with the committed index the places rank from clean cells and the lines file is never requested",
    "message": "  1) [phone] › e2e/land-water.spec.ts:48:1 › with the committed index the places rank from clean cells and the lines file is never requested \n\n    Retry #1 ───────────────────────────────────────────────────────────────────────────────────────\n    Error: expect(received).toEqual(expected) // deep equality\n\n    - Expected  - 1\n    + Received  + 3\n\n    - Array []\n    + Array [\n    +   \"http://localhost:8787/regions/morro-bay/land-water-lines.json\",\n    + ]\n\n      53 |   await expect(where.locator('.app-pick').first()).toBeVisible();\n      54 |   await page.waitForLoadState('networkidle');\n    > 55 |   expect(lines).toEqual([]);\n         |                 ^\n      56 |   expect(pageErrors).toEqual([]);\n      57 | });\n      58 |\n        at <historical-checkout>/e2e/land-water.spec.ts:55:17",
    "raw_details": ""
  },
  {
    "path": "e2e/land-water.spec.ts",
    "blob_href": "https://github.com/Grahammmm/skippercast/blob/eaad7aba48fdf6ea8c412b332021789c417a43b9/e2e/land-water.spec.ts",
    "start_line": 55,
    "start_column": 17,
    "end_line": 55,
    "end_column": 17,
    "annotation_level": "failure",
    "title": "[phone] › e2e/land-water.spec.ts:48:1 › with the committed index the places rank from clean cells and the lines file is never requested",
    "message": "  1) [phone] › e2e/land-water.spec.ts:48:1 › with the committed index the places rank from clean cells and the lines file is never requested \n    Error: expect(received).toEqual(expected) // deep equality\n\n    - Expected  - 1\n    + Received  + 3\n\n    - Array []\n    + Array [\n    +   \"http://localhost:8787/regions/morro-bay/land-water-lines.json\",\n    + ]\n\n      53 |   await expect(where.locator('.app-pick').first()).toBeVisible();\n      54 |   await page.waitForLoadState('networkidle');\n    > 55 |   expect(lines).toEqual([]);\n         |                 ^\n      56 |   expect(pageErrors).toEqual([]);\n      57 | });\n      58 |\n        at <historical-checkout>/e2e/land-water.spec.ts:55:17",
    "raw_details": ""
  }
]
```

## Executed offline acceptance: exact command / cwd / exit / full output

### `$HOME/agent-work/bin/memcap -- node --test tests/test_map_startup.mjs tests/test_land_water_pending.mjs tests/test_land_water.mjs tests/test_sp1503_land_water_retry.mjs`

Cwd: `<checkout>`; exit: **1**.

stdout:
```text
TAP version 13
# node:internal/modules/package_json_reader:314
#   throw new ERR_MODULE_NOT_FOUND(packageName, fileURLToPath(base), null);
#         ^
# Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@preact/signals' imported from <checkout>/web/land-water.ts
#     at Object.getPackageJSONURL (node:internal/modules/package_json_reader:314:9)
#     at packageResolve (node:internal/modules/esm/resolve:768:81)
#     at moduleResolve (node:internal/modules/esm/resolve:855:18)
#     at defaultResolve (node:internal/modules/esm/resolve:985:11)
#     at \#cachedDefaultResolve (node:internal/modules/esm/loader:747:20)
#     at ModuleLoader.resolve (node:internal/modules/esm/loader:724:38)
#     at ModuleLoader.getModuleJobForImport (node:internal/modules/esm/loader:320:38)
#     at ModuleJob._link (node:internal/modules/esm/module_job:182:49) {
#   code: 'ERR_MODULE_NOT_FOUND'
# }
# Node.js v22.23.2
# Subtest: tests/test_land_water.mjs
not ok 1 - tests/test_land_water.mjs
  ---
  duration_ms: 86.572058
  type: 'test'
  location: '<checkout>/tests/test_land_water.mjs:1:1'
  failureType: 'testCodeFailure'
  exitCode: 1
  signal: ~
  error: 'test failed'
  code: 'ERR_TEST_FAILURE'
  ...
# node:internal/modules/package_json_reader:314
#   throw new ERR_MODULE_NOT_FOUND(packageName, fileURLToPath(base), null);
#         ^
# Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@preact/signals' imported from <checkout>/web/land-water.ts
#     at Object.getPackageJSONURL (node:internal/modules/package_json_reader:314:9)
#     at packageResolve (node:internal/modules/esm/resolve:768:81)
#     at moduleResolve (node:internal/modules/esm/resolve:855:18)
#     at defaultResolve (node:internal/modules/esm/resolve:985:11)
#     at \#cachedDefaultResolve (node:internal/modules/esm/loader:747:20)
#     at ModuleLoader.resolve (node:internal/modules/esm/loader:724:38)
#     at ModuleLoader.getModuleJobForImport (node:internal/modules/esm/loader:320:38)
#     at ModuleJob._link (node:internal/modules/esm/module_job:182:49) {
#   code: 'ERR_MODULE_NOT_FOUND'
# }
# Node.js v22.23.2
# Subtest: tests/test_land_water_pending.mjs
not ok 2 - tests/test_land_water_pending.mjs
  ---
  duration_ms: 57.563333
  type: 'test'
  location: '<checkout>/tests/test_land_water_pending.mjs:1:1'
  failureType: 'testCodeFailure'
  exitCode: 1
  signal: ~
  error: 'test failed'
  code: 'ERR_TEST_FAILURE'
  ...
# node:internal/modules/package_json_reader:314
#   throw new ERR_MODULE_NOT_FOUND(packageName, fileURLToPath(base), null);
#         ^
# Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@preact/signals' imported from <checkout>/web/state.ts
#     at Object.getPackageJSONURL (node:internal/modules/package_json_reader:314:9)
#     at packageResolve (node:internal/modules/esm/resolve:768:81)
#     at moduleResolve (node:internal/modules/esm/resolve:855:18)
#     at defaultResolve (node:internal/modules/esm/resolve:985:11)
#     at \#cachedDefaultResolve (node:internal/modules/esm/loader:747:20)
#     at ModuleLoader.resolve (node:internal/modules/esm/loader:724:38)
#     at ModuleLoader.getModuleJobForImport (node:internal/modules/esm/loader:320:38)
#     at ModuleJob._link (node:internal/modules/esm/module_job:182:49) {
#   code: 'ERR_MODULE_NOT_FOUND'
# }
# Node.js v22.23.2
# Subtest: tests/test_map_startup.mjs
not ok 3 - tests/test_map_startup.mjs
  ---
  duration_ms: 56.347143
  type: 'test'
  location: '<checkout>/tests/test_map_startup.mjs:1:1'
  failureType: 'testCodeFailure'
  exitCode: 1
  signal: ~
  error: 'test failed'
  code: 'ERR_TEST_FAILURE'
  ...
# node:internal/modules/package_json_reader:314
#   throw new ERR_MODULE_NOT_FOUND(packageName, fileURLToPath(base), null);
#         ^
# Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@preact/signals' imported from <checkout>/web/land-water.ts
#     at Object.getPackageJSONURL (node:internal/modules/package_json_reader:314:9)
#     at packageResolve (node:internal/modules/esm/resolve:768:81)
#     at moduleResolve (node:internal/modules/esm/resolve:855:18)
#     at defaultResolve (node:internal/modules/esm/resolve:985:11)
#     at \#cachedDefaultResolve (node:internal/modules/esm/loader:747:20)
#     at ModuleLoader.resolve (node:internal/modules/esm/loader:724:38)
#     at ModuleLoader.getModuleJobForImport (node:internal/modules/esm/loader:320:38)
#     at ModuleJob._link (node:internal/modules/esm/module_job:182:49) {
#   code: 'ERR_MODULE_NOT_FOUND'
# }
# Node.js v22.23.2
# Subtest: tests/test_sp1503_land_water_retry.mjs
not ok 4 - tests/test_sp1503_land_water_retry.mjs
  ---
  duration_ms: 70.919929
  type: 'test'
  location: '<checkout>/tests/test_sp1503_land_water_retry.mjs:1:1'
  failureType: 'testCodeFailure'
  exitCode: 1
  signal: ~
  error: 'test failed'
  code: 'ERR_TEST_FAILURE'
  ...
1..4
# tests 4
# suites 0
# pass 0
# fail 4
# cancelled 0
# skipped 0
# todo 0
# duration_ms 92.18822
```

stderr:
```text
```

### `$HOME/agent-work/bin/memcap -- python3 scripts/check_e2e_pins.py`

Cwd: `<checkout>`; exit: **0**.

stdout:
```text
e2e pin guard: 28 pinned files match
```

stderr:
```text
```

### `git diff --check`

Cwd: `<checkout>`; exit: **0**.

stdout:
```text
```

stderr:
```text
```

## Required local Python gate

Cwd: `<checkout>`. Commands below were run through the memory cap.
The first checker invocation exited 2 with ENV-MISSING, naming the absent
`<checkout>/.venv/bin/python` and the WTENV-2 build command.

```text
$HOME/agent-work/bin/memcap -- python3 $HOME/agent-work/bin/worktree-env.py build <checkout>
```
Exit 0; output:
```text
REPAIR <checkout>: none (no .venv)
  venv created/completed from /usr/bin/python3.12
  pip install -e . --no-deps done (worktree's own skippercast only)
OK <checkout>: import skippercast -> <checkout>/src/skippercast/__init__.py; metadata <checkout>/.venv/lib/python3.12/site-packages; deps via $HOME/repos/skippercast/.venv/lib/python3.12/site-packages; shared venv unchanged
```

```text
$HOME/agent-work/bin/memcap -- python3 $HOME/agent-work/bin/sc-ci-local-check.py <checkout>
```
Exit 0; output:
```text
PASS layout contract
PASS repository checks
ALL PASS
```

This Python gate is not the browser pair, the full CI tier, or independent review.
Builder release ends at the authorized report push/PR; downstream ship-queue owns
CI and review (named review route: opus-coder), not a claimed repair or deployment.

## Subsequent CI evidence — retirement-history RETURN (2026-11-15)

This addendum addresses the separate required-check RETURN at
`91565f8e5ca657471dffe6bc999a04746ddd2d9d`; it does not replace the original
source receipts or resolve the local browser-environment gap above.

In [run 43776387890](https://github.com/Grahammmm/skippercast/actions/runs/43776387890),
the two frozen-inventory tests failed because the shallow checkout lacked
`351e321dd8c7b3ef82b149d2bb9476fbe337e180`. The `survey-science` gate then
correctly rejected `CHECK: failure`, despite `TESTS: success`.
Main's fixes `af8d688e204a8e9501b57a68d2ced193feb2672c` and
`4a84e938b42e0014363438d5b531dddf323eaa25` provision that immutable source
before core/full-tier tests; the tests remain offline and missing CI history
fails rather than skips. Neither the manifest nor the gate is relaxed here.

[Run 43785858179](https://github.com/Grahammmm/skippercast/actions/runs/43785858179)
at `03e02a63e682955083cd5826505e7efb78f1ac86` reports successful
`check (3.13)` (job `133033274603`) and `survey-science` (job `133035032342`).
Those are prior-head results, not proof of a later head or a local browser run.
A separate depth-2 clone at that same source reproduced the missing-history
CI fixture errors (12 passed, 2 errors); fetching exactly the workflow's frozen
source made the unchanged retirement-manifest module pass all 14 tests.
Current main `877615d718619fd9ca15e068e9b2dd1a9da992ac` was merged before
this revalidation; final-head checks still belong to the downstream merge gate.
