# Size budget (quick pull request check)

`scripts/check_perf_budget.py` runs in the `check` job of the Offline checks workflow (after `pnpm build`). It stops a
pull request that makes the app's first-load files or the brief's data files much bigger. It adds up file sizes in
bytes: no network, no timing, so it gives the same answer every run. Origin: PERF-BASELINE-1 found a 15.4 MB file that
no test flagged (proposal P34).

Run it yourself: `pnpm build && python3 scripts/check_perf_budget.py`. It prints a table of each group, its size now,
its budget and the share used, then PASS or FAIL. A failing group also lists its largest files.

## What is measured, and the budgets (bytes, main at 771d317133)

| Group | Size when set | Budget | Headroom |
|---|---|---|---|
| Landing page scripts (entry + scripts it imports at once) | 421,933 | 445,000 | 5.5% |
| Landing page styles | 24,339 | 26,000 | 6.8% |
| App page (brief, map) scripts, first load | 1,104,511 | 1,160,000 | 5.0% |
| App page styles | 67,003 | 71,000 | 6.0% |
| Largest single built script, style or font (any page, loaded now or later) | 1,094,203 | 1,150,000 | 5.1% |
| Brief data files in the repo (`protected-areas.geojson`, `land-water-lines.json`, `seafloor-ledger.json`) | 951,224 | 1,050,000 | 10.4% |
| Per-region startup data, biggest single file (`atlas-marks.json`, `search-plan-index.json`, `regulations-startup.json` in every region) | 222,047 | 240,000 | 8.1% |
| Biggest file of any kind in the served site outside `assets/` (data, tiles, pages; catches a file no list names) | 6,444,161 | 6,800,000 | 5.5% |

The last row is a safety net: the largest file today is `survey-habitat.geojson` for Southern California, loaded on
demand. A 15 MB file anywhere in the site fails it. If a glob in the budget file matches nothing, the check fails
rather than passing silently.

Scripts loaded on demand are not first-load; the largest-file budget still covers every built file. Sizes are
uncompressed bytes of the built output, so they differ from the compressed network sizes in PERF-BASELINE-1.
Not measured: live data answers (`/api/...`) and the reef export, which are published outside this repository.

## Raising a budget (in a pull request, with a reason)

Open `scripts/perf-budget.json`. For the group that is over, add an entry at the END of its `history` list with the new
`max_bytes` and a `reason` a reviewer can judge (what grew and why it is worth it), then set the group's `max_bytes` to
the same number. The check fails if `max_bytes` differs from the last history entry or a reason is empty, so a number
cannot change quietly. Prefer shrinking the file first.
