# SCB-12 — start the map in parallel

**MEASURED: final cold canvas median is 4.811 s, versus the original main baseline's 7.610 s.** After merging current main 9037fd2be, all five final runs meet the unchanged 5.0 s target: [4803, 4820, 4811, 4846, 4806] ms. Earlier outliers remain disclosed below; this is not a worst-case guarantee. Not merged, deployed or verified live.

**MEASURED trade-off:** the first verdict is 713 ms later. This improves map start, not the whole first visit. SCB-11 owns the brief diet. The map's first-idle mark is not proof every later asynchronous overlay has arrived.

| Cold median | original main 114079ae (n=3) | merged runtime 317406aab8 (n=5) |
|---|---:|---:|
| canvasMs | 7610 | 4811 |
| verdictMs | 7466 | 8179 |
| chartIdleMs | 19943 | 19779 |
| bytesToVerdict | 960698 | 1234945 |

MEASURED warm medians: canvas 895 ms, saved verdict 488 ms, chart idle 3952 ms. Raw final file: `round3-phone-merged.json`, preserved with the card evidence.

## Change and preserved boundaries (READ)

A dependency-free Vite entry starts the existing MapLibre wrapper and mandatory app graph concurrently. Explicit terrain choices, unchosen homes and non-map pages stay lazy. The store still resolves saved homes, aliases and terrain fallbacks. Library failure cannot block the app; createChart owns its existing failure panel. No handwritten preloads, new providers, service changes or credentials.

Heavy aerial/seafloor work gets the brief's first settlement or a **maximum five-second head start**, whichever comes first. The latch never re-holds imagery during refresh. It does not seal the weather verdict or weaken the independent seafloor publication, expiry, rights and held-source checks. Initial idle/flyover does not claim completion while imagery is deliberately held. Both startup budgets and landing warm assets include the mandatory dynamic shell.

The asynchronous entry also needed the existing ordered-page stylesheet plugin to handle ../web/ paths: otherwise UI sheet defaults reversed the phone cascade. Reload-language and text-size tests now await actual app state before their original language/geometry assertions. The swell pixel test waits for honest map idle before sampling water, rather than sampling before delayed Aerial appears. No semantic assertions were dropped and no global timeout was raised.

## Final-round diagnosis and verification

- **MEASURED:** twelve selected original failures reproduced on the preserved old build. The old imagery latch could wait for a held coast/report's twenty-second verdict deadline, blocking map idle and seafloor feedback beyond existing browser expectations.
- **MEASURED:** pre-merge five-second-cap build passes all four affected specs together: 186 passed, 24 existing viewport-conditional skips, zero failures (7.0 min). This includes the original failed language, text-size, map loading, credits, publication/expiry, protected-area and aerial cases, plus held-main and failed-library bootstrap coverage. Receipt: `round3-repo-e2e-1794620885692746870.log`.
- **MEASURED:** after merging main, the five affected specs (including phone-sheet reach) pass together: 203 passed, 41 existing viewport-conditional skips, zero failures (5.7 min). Receipt: `round3-repo-e2e-1794622057143700415.log`.
- **MEASURED:** 64 focused startup/aerial/chart/seafloor unit tests pass, including exact head-start boundary, unchanged unsealed weather epoch, disposal, publication hold and expiry behavior. Typecheck, build, both size gates, all 27 source pins, copy/token lint, check_web and local CI checks pass. Exact-head installed prepush and remote outcomes belong in the final Kanban handoff; earlier-head receipts do not establish them.
- **MEASURED:** an intermediate broad run hit the desktop Chart rail centre-click assertion. Untouched main 114079ae reproduced that same assertion in two of three repetitions; its receipt and the candidate trace are retained. This does not excuse another failure or clear the separate main-red release hold. No rail assertion or product layout was changed in this round.

## Timing method, rejected trials and limits

**READ/MEASURED:** actual built Vite assets, Brotli local HTTP, public live GET fallthrough and real external aerial imagery; no stubbed feeds, aerial pixels or route-fulfilled app downloads. CDP CPU 4x, 150 ms latency, down 204800 B/s, up 96000 B/s, 390x844, DPR3, mobile/touch. Fresh browser context for each cold run, same-context warm tab three seconds later. Flyover remains enabled. Canvas, verdict and chart-idle markers follow SCB-02's method; its proposed relaxation to six seconds was not adopted.

**MEASURED:** an initial three-second-cap probe had canvas median 4.817 s but included 5.782 s in its first run, while another task-owned browser overlapped. That first library response began at 1.581 s versus about 0.55 s subsequently. **READ:** the harness synchronously compresses assets on their first request. **INFERRED:** that one-time work and overlap contributed; neither is proven to explain the whole delay. All raw runs remain preserved, not relabelled as passes.

**MEASURED:** after explicitly preparing the server's compressed representations (not browser caches), the three-second-cap sample had all five canvas runs <=5 s but verdict median 9.152 s. Rejected because imagery competed with ordinary brief completion. The five-second cap restored the pre-merge verdict to 8.183 s, while its canvas sample included a 5.014 s outlier. That whole sample remains in `round3-phone-final5s.json`.

**READ/MEASURED:** main then advanced to 9037fd2be, including CI-1's reviewed phone-sheet CSS fix. Merged it with both changelog entries retained and all 27 source pins matching, rebuilt as 317406aab8, prepared that build's compressed representations, and repeated all five cold/warm runs. No other task-owned browser overlapped this final sample. It yielded the primary table above, with 32–51 shared-host load at cold-run completion. The merged build's repeated browser and exact-head gate outcomes are recorded in the final handoff, not inferred from the pre-merge pass.

**Limits:** one emulated region (Morro Bay), software WebGL, loaded shared host, changing public upstream responses, local HTTP/Brotli rather than edge HTTP2. Baseline n=3 and final n=5 were not simultaneous. No real-phone or production speed guarantee. Re-measure live after a reviewed deployment before claiming the live target.

## Budget and rollback (READ)

The original candidate proposed a 2,000-byte app_js increase to 1,061,000, retained in its written history. Main subsequently merged SC-CI-2's independently approved drift budgets, including app_js 1,111,000. Reconciliation retains that main ceiling and both histories, with no further ceiling increase relative to current main. Both corrected checkers still count the mandatory shell; main's warning/drift behavior is preserved. No separate held BODY09 acceptance run was executed; its source-pin applicability note remains intact.

Rollback: revert this one PR through the usual reviewed path. No migration, live flag swap or service restart.
