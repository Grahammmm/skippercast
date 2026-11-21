# Load less English copy when `/map` opens

The local build sends the full English catalogue in a 206,280-byte starter script (`englishPlacement`, `chunkSizes`).\
The account dialog already opens on demand, but its 162 English strings ride along at startup (`accountSlice`; `web/account.ts:96–117`).\
**Recommendation:** move just those strings behind the dialog loader first; leave the brief, chart and language picker alone (`Slice 1`).

Measured against source head `9163c89fcdb345fe4e03c42f7f22c2264f0d4e61`. The two report files do not change the inputs to the client build (`scripts/build-worker.mjs:13–24`, `vite.config.mjs:197–225`).

## Measurement (C1)

From the repository root, with the locked dependencies installed (measured with Node 22.23.2):

```sh
pnpm build
node research/scripts/catalogue_first_paint_ids.mjs dist/client ../map-catalogue-ids.json
```

Use a fresh report filename for each run. The script prints the same JSON it writes to that path; it does not write build files. Its in-memory build recovers which source modules Vite put into each chunk, then checks the manifest and the measured JavaScript bytes against the saved build (`research/scripts/catalogue_first_paint_ids.mjs`, `build` and `chunkSizes`).

- **What counts:** `/map` serves `app.html` (`server/routes/assets.ts:29–42`). Follow its static imports, the early script, and the mandatory shell import: `appStartup` in `scripts/precache.mjs:41–43,76–79`. That includes the classic theme script recorded by `vite.config.mjs:177–191`. The raw-budget checker walks the page and mandatory shell but not the separate early entry (`scripts/check_perf_budget.py:55–78`). The Chart library can start in parallel on some links (`web/app/boot.ts:5–23`); Spanish readiness gates the first translated render on Spanish visits (`web/app/main.tsx:33–35,61–66`). The report counts both conditional graphs separately, net of files already in the main total. None of these counts is a page-load timing.

| Built JavaScript | Raw bytes | Gzip bytes (level 9, each file separately) | Output field |
| --- | ---: | ---: | --- |
| Initial `/map` scripts, 74 files including the early script | 1,158,173 | 407,162 | `startup` |
| Same raw checker scope as the existing budget | 1,155,801 | — | `rawBudgetStartup` |
| English catalogue chunk, already in the initial total | 206,280 | 55,476 | `englishPlacement` → `chunkSizes` |
| Extra Spanish chunk for Spanish visits | 224,068 | 61,723 | `conditionalSpanish` |
| Extra files for the conditional Chart warm-up | 1,124,912 | 303,649 | `conditionalChartHint` |

- **Which ids:** `modules` lists each local source script in those initial chunks (280 scripts; 113 with literal matches). It includes literal ids in code (including descriptors and lookup tables), candidate ids for constructed prefixes, and computed `t()` arguments or direct table readers that need a source check. `entries` gives each id’s UTF-8 `"key":value` size in English and Spanish, excluding the outer braces and separators. `modules` sums unique ids per module, so do not add rows to estimate a shared table. For example:

| Source in the initial scripts | Literal ids | English entry bytes | Spanish entry bytes |
| --- | ---: | ---: | ---: |
| `web/app/Masthead.tsx` | 18 | 929 | 956 |
| `web/brief/Brief.tsx` | 59 | 5,021 | 5,436 |
| `web/app/MapStage.tsx` | 22 | 1,198 | 1,252 |
| `web/app/AccountMenu.tsx` | 37 | 2,376 | 2,468 |
| `web/app/early.ts` | 0 | 0 | 0 |

The compact English table is 2,850 ids and 211,964 raw bytes. The union of literal matches is 1,430 ids and 104,096 raw bytes; adding all prefix candidates gives 2,127 ids and 156,026 raw bytes (`compactEnglish`). These are compact JSON sizes, not minified script or HTTP sizes. **UNVERIFIED:** exactly which branches execute before a particular visitor’s first paint. The source inventory can include later actions in an initial chunk and literals used with a different reader. It can also miss ids passed as values into a generic formatter, such as nested map status descriptions (`web/map/status-copy.ts:45–79`). Do not use the complement of either count as a deletion list.

## Contract (C2)

1. Keep `t(id, lang, vars)` synchronous. Every screen has its English entries before it renders. Keep `lookup`’s fallback and placeholder rules; a bare id is a failure to catch before shipping, not loading UI (`web/i18n.ts:4–11`, `web/i18n-core.ts:14–29`). Keep the existing Spanish load and the initial render wait. A failed startup Spanish load keeps English and exposes the existing retry; do not let a late Spanish load overwrite a newer English choice (`web/i18n-catalogue.ts:53–67,76–124`, `web/app/main.tsx:33–35,61–66`).
2. Give later views their own English projection as a static dependency of the **view’s** lazy module, not of the app entry. Wait for the view and its English entries before opening it; do not fetch on a call to `t()`. Reuse the shared Spanish table and read the selected language once the view loads, not at the click. Validate that the selected view’s Spanish ids are present before using them. If its Spanish entries are incomplete, fall back as a whole to English for that dialog until retry, never to a mix of strings and ids. This follows the existing per-dialog copy model (`web/account.ts:96–117`, `web/account-copy.ts:9–17`, `dist/account.js:15–34`). Keep shared/loading/error strings in the shell; the alerts opener shows how an early reader can use its own messages while the view is not ready (`web/app/AccountMenu.tsx:42–53`). Account deep links may request their slice as soon as the shell opens; don’t count those as ordinary no-dialog visits (`web/account.ts:107–117`).
3. Keep `catalog/app/strings.json` the only source of copy, and keep the full English reference, full Spanish, landing and status projections intact. Have the existing generator write and check any new projections in catalogue order; every app English id belongs to exactly one of the shell or dialog projections for this slice. The build already runs the generator; `--check` must still refuse missing or stale output without writing (`scripts/build_landing_strings.mjs:9–55`, `scripts/client-build.mjs:195–200`). `check_copy.mjs` continues checking ids and wording against the full source, including `dist/account.js`; it should neither consume the audit report nor gain an exemption. Its literal-call scan cannot validate all computed ids, so test those through the reader’s existing fixtures (`scripts/check_copy.mjs:258–272,288–303`). Generated JSON conversions are tested separately (`tests/test_i18n_catalogue_loading.mjs:255–288`).

## Slice 1 (C3)

**Move only `account.*`, not `accountMenu.*`.** All 162 account ids are literal matches in `dist/account.js`, and none match a literal or constructed prefix in the initial scripts (`accountSlice`). The one startup module that enumerates the namespace is `web/account-copy.ts:11–17`, and both callers do so only when opening the dialog (`web/account.ts:96–117`). The menu trigger’s distinct `accountMenu.*` ids stay put (`web/account.ts:80–84`, `web/app/AccountMenu.tsx:27–39`). The isolated compact account table is 11,429 raw bytes; the shell projection is 11,428 raw and 2,587 gzip bytes smaller than the full compact table (`compactEnglish`). Actual savings for a changed build are **UNVERIFIED**; these are sizing inputs, not a claimed browser result.

| Future files | Change |
| --- | --- |
| `scripts/build_landing_strings.mjs`, new `web/strings.app.generated.json` and `web/strings.account.generated.json` | Project all ids except `account.*` into the first file and exactly `account.*` into the second. Leave the original generated tables unchanged. |
| `web/i18n.ts`, `web/account-copy.ts`, `web/account.ts`, `dist/account.js` | Switch the shared reader and its `StringId` to the app projection. Make account copy read the account projection and use `spanish(id)` from `web/i18n-catalogue.ts:47–51`; choose English for the whole dialog if the account ids are incomplete. Load both account modules together behind one helper called by the direct and hash opens, preserving return-hash behavior and reading language after the imports. Point the dialog’s existing English defaults at that same account projection, so it cannot pull the full table back in. |
| `tests/test_i18n_catalogue_loading.mjs`, `e2e/v2-account-i18n.spec.ts` | Extend the existing graph and generator controls: check disjoint coverage without changing full-table fixtures; require the account projection outside `/map` and landing’s ordinary first-load graphs, but reachable from the dialog and the saved app pack. In the existing stubbed account journey, include the menu click as well as the hash path and hold the account load briefly: no dialog text until ready, then actual English or Spanish, including a switch while loading. These cover static reintroduction and wrong-language first render, which isolated copy tests do not. |
| `scripts/perf-budget.json`, `scripts/startup-budget.json` | Lower only the raw and gzip app JavaScript limits after the real build passes. Keep CSS, landing and offline-pack limits as-is. |

**Byte gate.** Target at least 8,000 fewer raw bytes and 1,500 fewer gzip bytes on the existing app JavaScript scopes, versus the same base built with the same tools. On this base that means at most 1,147,801 raw and 405,662 gzip bytes. Use the measured candidate plus 10,000 raw and 4,000 gzip bytes, capped at one byte below the respective current limits (1,172,000 raw and 414,000 gzip at this head). If the measured result cannot meet the target and both lowered caps, stop rather than raise a budget or omit a required script (`rawBudgetStartup`, `startup.gzipBytes`; `scripts/perf-budget.json:72–76,118–122`, `scripts/startup-budget.json:19–22`). Check landing isolation and the saved pack as well: warm-up uses the initial graph, while the pack follows later imports (`scripts/precache.mjs:47–62,81–88,107–116`).

**Under two hours:** budget 35 minutes for the projections and two callers, 40 for the existing focused tests, 15 for the build and byte checks, and 20 for diff review. Run `pnpm typecheck`, `node scripts/check_copy.mjs`, `node scripts/build_landing_strings.mjs --check`, `node --test tests/test_i18n_catalogue_loading.mjs tests/test_account_i18n.mjs tests/test_strings_merge_layout.mjs`, and the focused account browser journey with stubbed local responses only. Then build and run `node scripts/check_client.mjs` and `python3 scripts/check_perf_budget.py`; compare the saved manifest and byte totals on both builds. The existing account test compares every account id with the canonical text in both languages (`tests/test_account_i18n.mjs:17–38`); keep it unchanged. Leave alerts and other candidates for later.

## Scope (C4)

This is a local build measurement and design, not an implementation or live-site check. Only this plan and the research script change. Product code does not call the script (`AGENTS.md:39–44`; `tests/contract/test_research_boundary.py:34–75`).
