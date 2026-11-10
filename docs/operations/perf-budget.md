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
| Landing page scripts (entry + scripts it imports at once) | 421,933 | 304,000 (lowered by SC1407-09 from 460,000; see history in `scripts/perf-budget.json`) | 5.5% at first |
| Landing page styles | 24,339 | 26,000 | 6.8% |
| App page (brief, map) scripts, first load | 1,104,511 | 1,064,000 (lowered by SC1407-09 from 1,180,000; see history in `scripts/perf-budget.json`) | 5.0% at first |
| App page styles | 67,003 | 73,000 (raised from 71,000 to 72,000 by SC1722-06, to 73,000 by RF1935-4; see history in `scripts/perf-budget.json`) | 6.0% at first |
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

### The slim reef file (SC-PERF-REEFDIET-1)

The brief reads the slim file (`habitat-slim-<sha16>.geojson.gz`, named by its own hash; each reef's attributes and its publish-time protected-area verdict, no
outlines) instead of the 15.4 MB `habitat-export.geojson.gz`, which stays for the planner, the map and GPX export. It
is published, not in the repo, so this check cannot measure it; the publisher enforces its budget instead
(`SLIM_MAX_BYTES` in `src/skippercast/seafloor/slim.py`: 450,000 gzip bytes; tested in
`tests/gis/test_seafloor_slim.py`). Reason: the real morro-bay export (3,064 reefs) gives 363,453 bytes, so the budget
leaves 23.8% headroom for more reefs or longer credit text, and stops the file growing back toward the full export
unnoticed. Raise it in a pull request with a reason, as above.

### English first loads without the Spanish table (SC1407-09, #1762 M5)

`web/i18n.ts` and the landing's `web/landing/i18n.ts` no longer import the bilingual `catalog/app/strings.json`: they read
English tables generated from it (`scripts/build_landing_strings.mjs`, run before every client build), and the Spanish
table (`web/strings.es.generated.json`) is a separate chunk that `web/i18n-catalogue.ts` loads only for a Spanish page or
a switch to Spanish. Vite manifest static closures on main a5005eb05 against this change: landing.html 447,318 to 289,476
bytes, app.html 1,169,280 to 1,011,409. The two ceilings were lowered to the new size plus 5%, rounded up to 1,000 bytes
(304,000 and 1,064,000). The install precache and the landing's app warm-up leave the Spanish chunk out; a saved offline
trip pack keeps it, so Spanish still opens offline.

### Protected-area verdicts reused across hour steps (SC1407-02)

Not a size budget, but a runtime cost the brief no longer repeats: `web/place-verdict-cache.ts` keeps the protected-area
verdict (`screenPlace`) of each atlas pick (`web/ranking.ts`) and of the Boat run line (`web/brief/run.ts`), so moving the
time dock does not screen the same place against the same boundaries again. It holds at most 256 checked verdicts in
memory (least recently used dropped first), keyed by the region, the screen, the screen's `verdictRevision()` and every
coordinate of the place. The revision changes whenever the boundaries, their names or order, the covered envelope, the
region binding, the readiness or the check times change; a change drops that screen's verdicts, and a region change drops
them all. A screen without a revision, and any unchecked (`screened: false`) answer, is never cached. Nothing is stored on
the device or fetched. This is not the publisher's stored reef verdict (the slim file above), which has its own fingerprint.

### The hourly horizon is built once per hour (SC1407-03)

Not a byte budget, and no budget here changes. The time dock's 169-hour horizon (`horizonDays` in `web/hour.ts`) is
read by the dock, the map, the brief and the share link; issue #1762 (R2) counted it rebuilt about 64 times at one load.
It now keeps one entry, its last successful build, keyed by the whole UTC start hour and the region zone: a read in the
same hour and zone returns that same array without formatting a single hour; another hour (forward or back) or another
zone builds a new one, and an invalid date or zone still throws and leaves the entry in place. The shared result is
frozen (the array, each day and its hours) so no caller can change it; a caller's own horizon passed to `dockTime` is
neither frozen nor kept. `tests/test_frames.mjs` checks this by counting formatter calls, not by timing; no new timing
was measured.

### Protected-area distance work (SC1407-01, #1762)

Not a size budget: a note on the run-time closure screen. `distanceM` in `dist/geo-screen.js` (called by `screenPlace` for
every place shape and every nearby closure: the brief's ranking, the run line, saved spots, GPX checks) used to project
each point again for every segment it was compared with, and spread whole point and segment arrays into `Math.min` (which
also throws `RangeError` past about 10^5 positions). It now projects each position and edge end once per pair, scans with
plain loops, and skips a segment whose projected box is already farther than the best distance so far. That box gap is
shrunk by a small allowance before the comparison, so it is an exact lower bound: the minimum, every `PlaceVerdict`, the
0.1 m rounding, the 70 m margin and the 20 km far cut-off are unchanged. `withinMargin`, `geometryIntersects` and the
publish-time screen are not touched. `tests/test_distance_m.mjs` keeps the old function as an oracle and checks strict
equality on the committed Morro Bay data, run-shaped lines, seeded random cases, holes and multipart shapes.

Work for screening all 132 committed Morro Bay atlas targets (point plus reef areas) against the 8 committed closures,
counted offline in instrumented copies of the old and new module (same verdicts):

| | Projections | Point-to-segment distances |
|---|---|---|
| Before | 111,787,745 | 108,796,327 |
| After | 2,997,408 | 444,194 |

One local Node run took 1,742 ms before and 363 ms after (counters included; a sample, not a gate, and not a re-measure of
the phone load in #1762). Not profiled further: `geometryIntersects`, unchanged, still runs first on every measured pair.

### One live protected-area read per load (SC1407-06, #1762)

Not a size budget: a note on the run-time boundary check. The map's mark screen (`web/map/marks.ts`) and the planner's
screen (`dist/protected-areas.js` `refresh`) both ask the live CDFW ds582 query for the region's envelope on a `/map`
load. `dist/live-mpa.js` lets them share a read only while it is in flight: two callers of the exact same query URL get
one request and one parsed answer; any other URL (bounds, fields, output, parameter order) is its own read. A settled
read is forgotten at once (answer, HTTP or transport error, 20 s timeout, broken JSON), so a later `refresh()` always
asks again and no finished answer is kept or replayed. Each screen still runs its own checks (`validMpas` with the
region's minimum, `validMPAs` and the provider-error refusal) and its own daily-feed fallback. The checked time both
screens record is when the response arrived (before its body is parsed), never when a screen consumed it. Committed
static files keep their own share (`web/shared-fetch.ts`), unchanged. No timing was measured for this change.

## Raising a budget (in a pull request, with a reason)

Open `scripts/perf-budget.json`. For the group that is over, add an entry at the END of its `history` list with the new
`max_bytes` and a `reason` a reviewer can judge (what grew and why it is worth it), then set the group's `max_bytes` to
the same number. The check fails if `max_bytes` differs from the last history entry or a reason is empty, so a number
cannot change quietly. Prefer shrinking the file first.
