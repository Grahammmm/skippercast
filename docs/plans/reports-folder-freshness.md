# Reports folder: readers and freshness

| Area | Tracked files | What the audit found |
| --- | ---: | --- |
| Top level | 13 | Two files cited by `docs/`; one more cited by another report; the coast inventory has a generator that also checks its bytes. Nine had no named reader or citation found. |
| `perf/` | 40 | Four Markdown reports and 36 helpers. Docs and the changelog cite the results; manual helpers read and rewrite parts of the first baseline. Raw performance captures are no longer tracked on main. |
| `promotion/` | 30 | One cited, dated preflight and 29 raw receipts. The checker can print new results; it does not refresh these files. |
| `rules/` | 3 | One report cited by a plan, another by the adjacent TSV. These are records, not a current rules decision. |
| **Total** | **86** | Five content checks below. No deletion or code change recommended. |

Read offline on **2026-11-21** from staged `origin/main`, `34761911d5c44a903873867426f316c7f1e5911c` (same as the brief's baseline). Counts and findings in this summary come from R1–R3. A dated measurement is not wrong just because it is old.

## R1. Dates and readers

Counts are **distinct tracked reader files**, not lines. The first matching file and line are shown for each nonzero count, in path/line order. The code and test columns count confirmed content readers in `scripts/`, `src/`, `.github/`, `web/`, `server/` and `tests/`, respectively. The docs column counts citations in `docs/`. Code and test mentions that do not read a report are listed separately. Folder rows count the union for all members, and use the folder's latest change. Clear report-title citations count as citations. Extra matches outside those roots are noted separately and can determine the class; a comment in code is a citation, not a read. **Cited by nothing** means no named reader or citation found by this search, not safe to delete.

| Path under `reports/` | Last change | Code | Tests | Docs | Other evidence or exceptions | Class |
| --- | --- | --- | --- | --- | --- | --- |
| `COAST-SEAFLOOR-INVENTORY.md` | ≤2026-11-10* | 0 | 0 | 0 | One code reader outside scope: `research/scripts/inventory_coast_seafloor.py:40` is the target; `:1127` reads it in check mode and `:1135` writes it in generation mode. | Read by code |
| `FE-BACKLOG-DOSSIER-2026-11.md` | ≤2026-11-10* | 0 | 0 | 0 | — | Cited by nothing |
| `FE-REVIEW-FOLLOWUPS-2026-11.md` | ≤2026-11-10* | 0 | 0 | 0 | One report cites it: `reports/ISSUE-TRIAGE-2026-11.md:41`. | Cited by docs |
| `ISSUE-TRIAGE-2026-11.md` | 2026-11-15 | 0 | 0 | 1 (`docs/plans/open-issue-status.md:9`) | — | Cited by docs |
| `LAYER-STATION-INVENTORY.md` | ≤2026-11-10* | 0 | 0 | 0 | `catalog/layer-inventory.json:4` identifies the companion inventory task, not a read of this Markdown. | Cited by nothing |
| `OLD-31-token-baseline-verification.md` | 2026-11-15 | 0 | 0 | 0 | — | Cited by nothing |
| `OLD-33-python-support.md` | 2026-11-15 | 0 | 0 | 1 (`docs/engineering/audits/python-pr-matrix-policy-gap.md:64`) | — | Cited by docs |
| `SCA-04-policy-a-verification.md` | 2026-11-15 | 0 | 0 | 0 | — | Cited by nothing |
| `SKIPPERCAST-COMPETITIVE-MATRIX.md` | ≤2026-11-10* | 0 | 0 | 0 | `catalog/competitor-matrix.json:3` records the companion task, not a read of this Markdown. | Cited by nothing |
| `branch-prune-candidates-2026-11.md` | 2026-11-15 | 0 | 0 | 0 | — | Cited by nothing |
| `branch-prune-candidates-2026-11.tsv` | 2026-11-15 | 0 | 0 | 0 | — | Cited by nothing |
| `dist-legacy-module-check.md` | 2026-11-15 | 0 | 0 | 0 | — | Cited by nothing |
| `research-workflow-use-gap.md` | 2026-11-15 | 0 | 0 | 0 | — | Cited by nothing |
| `perf/` | 2026-11-14 | 0 | 0 | 1 (`docs/operations/perf-budget.md:5`; also `:236`) | Internal manual reader `reports/perf/apply_tables.py:13` (invocation naming the report: `reports/perf/PERF-BASELINE-1.md:239`); see below for citations. | Read by code |
| `promotion/` | 2026-11-15 | 0 | 0 | 1 (`docs/plans/second-active-region.md:280`) | Receipt filenames are indexed by `reports/promotion/raw/SC1114-02-runs.json:14` and `reports/promotion/raw/SC1114-02-supplementary-gets.json:7`; see also `reports/promotion/PROMOTION-CHECK-2026-11.md:62`. | Cited by docs |
| `rules/` | 2026-11-15 | 0 | 0 | 1 (`docs/plans/route-around-protected-areas.md:18`) | That plan cites `RULES-CHECK-2026-11.md`. `reports/rules/access-vandenberg-maritime-review.tsv:2` cites `VANDENBERG-SOURCE-2026-11.md`; no named reader or citation found for the TSV itself. | Cited by docs |

\* A shallow boundary stops `git log` at `65624df97` (2026-11-10) for these rows. The files are already in that tree, but the last actual path change is not established from that result. The date shown is an upper bound in the staged history, not a confirmed last-change date.

**Do not confuse a reference with a dependency.** `CHANGELOG.md:41,44` cites `R4-SC-09.md` and `SCB-12.md`. `scripts/reef_slim_browser.mjs:3` mentions `measure.mjs` in a comment. `scripts/check_perf_budget.py:4`, `scripts/perf-budget.json:12`, `tests/test_reef_lazy.mjs:75`, and `e2e/reef-lazy.spec.ts:1` cite the first baseline as background; they do not load it. Substring hits such as `tests/test_report_rights_readiness.mjs:5` and `web/profile.ts:138` refer to different files. The retirement manifest lists `reports/` as a path prefix (`docs/engineering/subsystem-retirement.manifest.json:8`), not as a citation of each report. Separately, `scripts/check_repository.py:157–185` reads all eligible text and checks Markdown links, even for files without a named consumer. This audit cannot rule out readers using variable paths, human readers, or readers outside the repository.

Reproduce from the repo root with `B` set to the pinned SHA above. List the paths, then substitute each path (or folder) for `P`, and each basename for `F`. Deduplicate matches by path within each column and inspect the line to reject unrelated suffix hits, comments masquerading as reads, and writes.

```sh
git ls-tree -r --name-only "$B" -- reports
git log -1 --format='%cs %H' "$B" -- "$P"
git grep -nIF -e "$F" "$B" -- docs src scripts tests .github web server
git grep -nIF -e "$F" "$B" -- .
git grep -nIF -e 'reports/perf' -e 'reports/promotion' -e 'reports/rules' "$B" -- .
git grep -nIF -e 'PERF-BASELINE-1' "$B" -- .
```

## R2. What can be regenerated?

| Folder | Count and last-change range | Naming pattern | Oldest and newest visible entries |
| --- | --- | --- | --- |
| `perf/` | 40 files; visible log dates 2026-11-10 to 2026-11-14. The lower endpoint is history-limited. | Four uppercase report names (`PERF-BASELINE-1.md`, `PERF-BASELINE-2.md`, `R4-SC-09.md`, `SCB-12.md`); 25 `.py`, seven `.mjs`, and four `.sh` helpers, mostly named for the measurement or analysis they perform. | `compare_2.py` is confirmed 2026-11-10; another 35 helpers show the 2026-11-10 shallow boundary and can be older (for example `measure.mjs` is already in the 2026-11-07 commit `02c061c7b`). `R4-SC-09.md` is newest (2026-11-14). Both `PERF-BASELINE-*.md` last changed 2026-11-12; `SCB-12.md` on 2026-11-13. |
| `promotion/` | 30 files; 2026-11-15 to 2026-11-15. | One month-stamped `PROMOTION-CHECK-2026-11.md`; under `raw/`, 24 `SC1114-02-<region>-<now or through-2027-01-31>.<txt or json>` captures, three supplementary JSON responses and two JSON manifests. | All 30 tie for both oldest and newest at day resolution, including `PROMOTION-CHECK-2026-11.md`. |

The tree and per-path log commands in R1 reproduce the counts, suffixes and dates. For the performance boundary example, `git log -1 --format='%cs %h' 02c061c7b -- reports/perf/measure.mjs` returns `2026-11-07 02c061c7b` in the staged history. For promotion, the receipt breakdown is also written in `reports/promotion/PROMOTION-CHECK-2026-11.md:62`.

- **Performance: manual, partial regeneration.** `reports/perf/run-live.sh:4–7`, `run-layers.sh:8–9` and `run-ready.sh:7–17` (same directory) pass output paths to the capture scripts. `reports/perf/measure.mjs:21,215,224` writes JSON; `reports/perf/summarize.py:94–95` writes `raw/summary.json`. `reports/perf/apply_tables.py:13–17,50–63` reads a report and rewrites its generated tables; `reports/perf/PERF-BASELINE-1.md:239` names its target. These are not a generator for all four Markdown reports. The baseline notes say raw captures were removed and name the historical tree (`reports/perf/PERF-BASELINE-1.md:3`; R3 verifies the raw path is empty on main). No workflow or package script refreshing the tracked folder was found in the R1 search.
- **Promotion: manual capture, not a report generator.** `scripts/check_region_promotion.mjs:19–27,176,193–211` reads endpoints and prints a text or JSON result; it does not write the folder. `reports/promotion/PROMOTION-CHECK-2026-11.md:9–10,15,62` describes the separate invocations, captures, and extra GETs. The test at `tests/test_region_promotion.mjs:6` imports the checker, not the archived receipts. No code was found that reconstructs the folder, its manifests, or the Markdown report. Verify wiring with `git grep -nIF -e 'check_region_promotion.mjs' -e 'SC1114-02' "$B" -- scripts .github tests package.json` in addition to the R1 search. No capture, generator or checker was run for this audit.

## R3. Five spot checks against the pinned main

| Report and claim checked | What the read-only evidence says |
| --- | --- |
| `reports/dist-legacy-module-check.md:3,56,60` — 44 authored `dist/*.js` files | **Count has changed:** 44 at the report's build SHA, 45 on audited main. `dist/public-page-language.js` was added. This doesn't reclassify bundle membership; no build was run for this comparison. |
| `reports/perf/PERF-BASELINE-2.md:3,5,53,66` — 61 tracked files and replay from committed raw inputs | **Historical count matches; replay is not self-contained on main.** 61 on the report's baseline (`:44`), 40 on audited main. No files under `reports/perf/raw` on audited main, versus 28 in the historical tree cited at `:3`. The report already flags the removal; the old replay instructions and counts are not current inventory. |
| `reports/promotion/PROMOTION-CHECK-2026-11.md:30,41–43` — all-pass and “current main” | **Superseded as a current status.** The cited live SHA is not the audited main SHA. Main contains a newer dated read covering five of those regions: 2026-11-17 06:54 UTC, all five failed, with stale feed, tide, rules and brief checks (`docs/plans/second-active-region.md:268–280`). That is a checked-in later observation, not a live recheck and not evidence about the sixth region. |
| `reports/COAST-SEAFLOOR-INVENTORY.md:16` — statewide survey counts | **Matches:** 471 entries, 337 marked native, 134 catalog/metadata only, 98 marked usable, using the generator's predicates (`research/scripts/inventory_coast_seafloor.py:320–329`). Other coverage estimates not checked. |
| `reports/research-workflow-use-gap.md:16–18` — two manual-only workflow triggers | **Matches:** both still have `workflow_dispatch` as their only trigger (`.github/workflows/research-substrate.yml:3–4`; `.github/workflows/research-fish-survey.yml:3–4`). Historical usage was not rechecked. |

Read-only checks (same `B` as above; for the two workflow files, inspect the `on` block in the displayed YAML):

```sh
git ls-tree --name-only 0991fc70d dist/ | rg '^dist/[^/]+\.js$' | wc -l
git ls-tree --name-only "$B" dist/ | rg '^dist/[^/]+\.js$' | wc -l
git diff --name-status 0991fc70d "$B" -- ':(glob)dist/*.js'
git ls-tree -r --name-only 2e278b853 -- reports/perf | wc -l
git ls-tree -r --name-only "$B" -- reports/perf | wc -l
git ls-tree -r --name-only "$B" -- reports/perf/raw | wc -l
git ls-tree -r --name-only 44e6c0e5c1c9 -- reports/perf/raw | wc -l
git rev-parse "$B"
git grep -nIF -e 'Earlier all-PASS' -e 'earlier all-PASS' -e 'regional-brief-stale' "$B" -- docs/plans/second-active-region.md
git show "$B:catalog/surveys.json" | jq -c '.surveys | [length, (map(select(.inspection_level == "native")) | length), (map(select(.inspection_level == "catalog" or .inspection_level == "metadata")) | length), (map(select(.status == "usable")) | length)]'
git show "$B:.github/workflows/research-substrate.yml" "$B:.github/workflows/research-fish-survey.yml"
```

All other files and claims are **not checked for staleness**, including issue/backlog status, station observations, branch candidates, the other performance measurements and current rules. Git dates in R1–R2 do not renew that evidence.

## R4. Follow-up

No buildable unit is needed on this evidence. Use the dated reports for their original observations, not as live status or proof a file can be removed. No source, data, or policy change proposed.
