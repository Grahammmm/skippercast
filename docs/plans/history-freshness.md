# Why Recorded history goes blank

- The app hides the snapshot at 36 hours, but the normal refresh is weekly: that leaves about five and a half days with no chart (section 1).
- The history endpoint still answered HTTP 200 at about 112 hours old; feed health allows up to 192 hours (section 2).
- Recommendation for the owner: match the app's History-only limit to 192 hours, keeping the existing “historical, not current” label on old readings (sections 3–4).

Code checked against `origin/main` at `9163c89fcdb345fe4e03c42f7f22c2264f0d4e61`.

## 1. The three limits and the cadence

| Clock | What it means |
| --- | --- |
| 36 hours | The owner's limit on showing an entire history snapshot in the app. The clock starts at `generatedAt` (when the snapshot was assembled), not when a visitor downloads it. At 36 hours the app withholds it. `web/coast-data.ts:49–65,128–139,171–179`. |
| 192 hours (8 days) | The published history feed's age allowance. The status page and the server's check for using SkipperCast's own history feed both read it. It is not a limit on the age of an individual buoy reading. `catalog/feed-health.json:14`; `dist/status-page.js:150–158`; `server/coast-data.ts:192–194,215–225`. |
| 7 days | Recent refresh scheduled for Mondays at 10:41 UTC; full refresh scheduled for the 3rd of each month at 09:23 UTC. These are scheduled times, not promises of when a new file will appear. `.github/workflows/buoy-history.yml:3–9,34–37,57–68,75–92`. |

For two successful publishes exactly a week apart, `7 × 24 − 36 = 132 hours` (5½ days) without the chart. An intervening full publish can shorten that gap; a late or missed publish can lengthen it. This is schedule arithmetic, not measured weekly uptime (UNVERIFIED). The recent workflow can also skip if there is no prior file, so a run outcome alone is not proof of a publish (`.github/workflows/buoy-history.yml:57–68,75–92`).

Buoy-history runs created in the 30 days ending 2026-11-21 12:56:24 UTC. Source: `gh run list -R Grahammmm/skippercast -w buoy-history.yml --created '2026-10-22T12:56:24Z..2026-11-21T12:56:24Z' --limit 100 --json createdAt,status,conclusion,startedAt,updatedAt,databaseId` (`createdAt` dates and `conclusion` below):

| Date (UTC) | Outcome |
| --- | --- |
| 2026-10-26 | success |
| 2026-11-02 | failure |
| 2026-11-03 | success |
| 2026-11-09 | success |
| 2026-11-16 | failure |

## 2. What users see during the gap

- **History, where the app has local coverage:** “Recorded history is unavailable right now: the history snapshot could not be read or is out of date.” The app checks age even on a successful HTTP response. An expired snapshot yields no chart and no “Try again” button for expiry; the button is for a read error (`web/coast-data.ts:128–139,208–230`; `web/app/views/History.tsx:50–63,76–94`; `catalog/app/strings.json:1809`).
- **Live [history endpoint](https://skippercast.com/api/coast/history):** one GET at 2026-11-21 12:56:43 UTC returned HTTP 200, `X-Coast-Upstream: history=skippercast` and `generatedAt: 2026-11-16T20:51:09.528Z`. The snapshot was about 112.1 hours old: over 36 and under 192. Both stations had `recent.stale: true`; their last observations were 19:56 and 20:00 UTC on Nov 16. A reachable snapshot is not a current observation (`server/coast-data.ts:231–233,336–345`). The Nov 16 run log (`gh run view 43952280235 -R Grahammmm/skippercast --log`) shows that exact `generatedAt`, then a successful data-branch push and an upload error. The matching live snapshot was served despite the failed run; the exact release path after the upload error is UNVERIFIED.
- **[/status](https://skippercast.com/status):** one GET at the same time returned HTTP 200 and the Data status page with “Loading the published feeds…” in the HTML. The browser loads the published history feed separately. If it gets the same snapshot, the English row for “NDBC standard-met annual archives and 45-day realtime files (recorded history)” shows the Nov 16 timestamp, about `112 h` old, a `192 h` interval and “Inside its interval.” The row goes “Overdue” above 192 hours if the file is readable; it measures the publication clock, not whether today's water was measured. The live rendered row and whether it read the same snapshot are UNVERIFIED by the single HTML GET (`dist/status-page.js:32–50,150–158,206–215,225–239`; `dist/status-names.js:62`; `catalog/app/strings.json:373–374`).

## 3. Options

Incremental costs below are relative to the present weekly recent schedule, leaving the monthly full refresh alone.

| Option | Extra NDBC requests and workflow minutes | Risk of mistaking old records for current ones | Owner decision |
| --- | --- | --- | --- |
| **Match the client to the 192-hour feed allowance (recommended).** | **0** extra scheduled NDBC requests and **0** extra recurring workflow minutes: change only history admission in `web/coast-data.ts:49–65,128–139`, not the schedule in `.github/workflows/buoy-history.yml:6–9`. | The chart could show a snapshot nearly eight days old. The latest hourly mean already shows its observation time and says “historical, not current” when old, but there is no prominent snapshot-age warning in this option. How often users would miss the cue is UNVERIFIED (`packages/coast/src/ui/history.ts:27–45,48`; `catalog/app/strings.json:1835–1836`). | **Yes.** It changes the owner's 36-hour rule. Publication health and app display are separate decisions (`web/coast-data.ts:49–57`; `catalog/feed-health.json:14`). |
| **Show a dated snapshot with its age from 36 hours until 192 hours.** Keep 36 hours as the switch to a clear “older snapshot, not live” notice above the chart, with the snapshot date and age, separately from the last observation time. | **0** extra scheduled NDBC requests and **0** extra recurring workflow minutes if this stays on the existing client request (`web/coast-data.ts:203–215`; `.github/workflows/buoy-history.yml:6–9`). More app work than a limit change: today the client drops the data and the view has no dated state (`web/coast-data.ts:128–139,187–200`; `web/app/views/History.tsx:46–63,86–94`). | An explicit notice would make the two clocks easier to tell apart; its effect on users is UNVERIFIED. Keep the existing observation-time warning too (`packages/coast/src/ui/history.ts:27–45,48`). | **Yes.** Even with a warning, showing data after 36 hours changes the owner's rule (`web/coast-data.ts:49–57`). |
| **Run recent mode daily.** Keep the 36-hour app rule and the monthly full refresh. | Six extra runs per week. Two routine NDBC GETs per collecting run (one 45-day file per station): **12 extra GETs/week** without retries or redirects; actual HTTP counts are UNVERIFIED (`.github/workflows/buoy-history.yml:6–9,57–68`; `src/skippercast/pipeline/ndbc_history.py:34–35,57–59,220–225,297–326,368–371`; `src/skippercast/http.py:76,485,823–826`). **UNVERIFIED estimate: about 5 extra workflow minutes/week** at the Nov 9 recent run's pace, or **65** at the Nov 16 recent run's pace. `gh run list` with `startedAt,updatedAt` gives 49 s and 650 s from start to last update respectively; `gh run view 42699150973 -R Grahammmm/skippercast --log` and the Nov 16 log confirm `MODE: recent`. These are elapsed-time examples, not billed minutes or a forecast. | A daily successful publish normally fits inside 36 hours, but a late or failed publish can still leave a blank. A new snapshot can retain old observations if one station fetch fails; keep the existing observation-time warning (`web/coast-data.ts:49–57,128–139`; `src/skippercast/pipeline/ndbc_history.py:325–353`; `packages/coast/src/ui/history.ts:33–45`). User confusion is UNVERIFIED. | **Yes.** It increases calls to NOAA and adds six publish attempts each week, including writes to the shared data branch and upload step (`.github/workflows/buoy-history.yml:6–9,24–26,75–92`). |

## 4. Recommendation

If the owner agrees that the archive may remain visible for eight days, match only the History client limit to the existing 192-hour feed-health value. This covers a normal weekly gap without more NOAA requests or scheduled work. Keep the observation dates and “historical, not current” cue; do not loosen the report or ocean rules (`catalog/feed-health.json:14`; `.github/workflows/buoy-history.yml:6–9`; `web/coast-data.ts:49–65`; `packages/coast/src/ui/history.ts:33–45`). This does not fix missed publications or make old measurements live (sections 1–2).

**Proposed files and effort:** `web/coast-data.ts` for the history-only limit and `tests/test_coast_data_client.mjs` for one offline test. Extend the existing admission test: with the same valid history fixture, assert the snapshot is admitted one millisecond before 192 hours and rejected as expired at exactly 192 hours. Use 192 hours in the test rather than reading the production constant, so it catches both the current early cutoff and a lost cutoff (`web/coast-data.ts:128–139`; `tests/test_coast_data_client.mjs:269–277`). **UNVERIFIED estimate: 60–90 minutes** for the change and focused test, excluding review. No change is approved or implemented by this report.
