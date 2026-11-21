# Client reads of the wall clock

| R1 class | Reads | What to do with them |
| --- | ---: | --- |
| Timestamp for storage/log (T) | 9 | Keep the time of the actual event, not the dock hour. |
| Expiry or staleness decision (E) | 18 | Inject elapsed-time checks; distinguish those from selected-hour inputs. |
| Which-day-is-today decision (D) | 4 | Includes reads that choose a forecast hour or day rather than just print one. |
| Display only (P) | 2 | These change text, not admission or selection. |
| Scheduler/timer (S) | 2 | Keep independent deadlines and playback cadence. |
| Injected default (I) | 62 | The direct read is a fallback, even if it serves an expiry or day decision. |
| **Total** | **97** | Excludes the shared clock itself. |

**Source:** `26aa28ab1ce4e883c0850cdb7f1243c4ed48c07e`, the locally staged `origin/main` read on 2026-11-21, also the brief's baseline. The cited files were re-read there; no remote freshness or live-site claim. All source anchors below refer to this revision. This is an offline source audit, not a tally of failures in the test suite.

## R1. Inventory and count

```sh
git grep -nE 'Date\.now\(\)|new Date\(\)' 26aa28ab1ce4e883c0850cdb7f1243c4ed48c07e -- web ':!web/clock.ts'
```

Piping the command to `wc -l` gives **97 matched lines**. `web/coast-data.ts:155` is a comment, not a read; `web/app/RulesCard.tsx:27` has two reads, listed separately below. Those adjustments cancel; `git grep -ohE 'Date\.now\(\)|new Date\(\)'` with the same revision and pathspecs counts one extra match (the comment). The census is for these literal zero-argument forms, not references such as `now = Date.now` (`web/app/App.tsx:75,88`, `web/landing/readings.ts:184`), explicit timestamps such as `new Date(at)`, or a call through an already-counted callback. `web/degraded.ts:24` defines the bound and skew using `Date.UTC`, not another read.

## R2. Which reads can disagree, and how to test them

The dock has two distinct times: the **current sample**, taken by `createHourClock` on retain, on a whole UTC hour and on return to a visible page (`web/clock.ts:24–77`), and the **selected hour**, which can be another day or an explicit URL hour (`web/hour.ts:90–103,116–143`; `web/dock-selection.ts:162` and `web/app/TimeDock.tsx:128–133`). The app's region supplies the time zone; Pacific examples below are for California. `localParts` groups actual instants by region day, including DST; `readableDate` and `readableInstant` format inputs, not the current clock (`web/hour.ts:43–59`; `web/dates.ts:19–46`).

The inventory below serves **both R1 and R2**. “Fixed” means the containing path offers a time input; “No” means supplying a fixed dock/parent date does not control the read (a test can still replace global time). A fixed *date* does not by itself drive an interval or timeout. In the scenarios, expiry earlier than the next dock tick is often **correct**: it is wrong to substitute either the selected forecast hour or a sampled hourly instant for a true-time expiry. By contrast, a panel computing the same selected hour as the dock should use the same sample and selection. All scenarios are deductions from the cited paths, not observed live incidents.

| Read | Class | Purpose, boundary scenario, and current test input |
| --- | --- | --- |
| `web/boat-entry.ts:76` | T | `saveLength` stamps a newly created boat record. |
| `web/app/TripAlerts.tsx:176` | T | `SavedTrips` stamps the calendar file's `DTSTAMP`; the actual event comes from the saved trip (`web/trip-calendar.ts:49`). |
| `web/map/currents.ts:167` | T | `regionPlace` stamps a context object, but its binding reads geography and ignores `at` (`packages/coast/src/state/report-binding.ts:13–22`); no current frame/day effect shown at this site. |
| `web/app/PrivateMapLog.tsx:46` | T | `PrivateMapLog` supplies a timestamp to its dry-run entry builder for form eligibility, not a feed-age comparison; nothing is saved by this call. |
| `web/app/PrivateMapLog.tsx:48` | T | `PrivateMapLog` stamps the new entry on save. |
| `web/brief/Brief.tsx:154` | T | `markFresh` records a live part's receipt for the held brief, rather than replacing the source time of pack parts (`:158–163`). |
| `web/brief/Brief.tsx:315` | T | `readFeeds` records daily-read completion for refresh age (`:519–530`). |
| `web/brief/Brief.tsx:428` | T | `ensureRegionalForecast` records forecast-read completion for refresh age (`:507–530`). |
| `web/trip.ts:31` | T | Page session start, forwarded to pack saving (`web/trip-runtime.ts:278–282`), not a date picked on the dock. |
| `web/app/RulesCard.tsx:27` (state) | E | `RulesLine` can mark a source overdue midway through the sampled hour while Plan still uses the older sample (`web/regs.ts:123–151`; `web/app/PlanView.tsx:22–28`). No; `regulationState` alone takes an explicit time. |
| `web/app/RulesCard.tsx:27` (label) | E | The separate read can yield an overdue label or flip “checked today” across Pacific midnight independently of the state read (`web/regs.ts:209–216`). No; `freshnessLabel` alone takes an explicit time. |
| `web/app/Trip.tsx:180` | E | `ChartPack` renders an ocean layer past its saved limit on the first render after that instant, even in the same dock hour; an untouched list may not redraw then (`web/trip-ocean-lines.ts:20–26`). No at the component; helper takes `now`. |
| `web/app/Trip.tsx:183` | E | `ChartPack` may still show “saved through” until another render if a pack's forecast ends while the list is open (`web/trip-forecast-end.ts:8–11`). No at the component; helper takes `now`. |
| `web/app/TripAlerts.tsx:156` | E | `SavedTrips` can show a saved trip's rules check as overdue on a render before a dock tick, or retain the old label if it never re-renders (`:135–141,193`). No. |
| `web/app/main.tsx:92` | E | Startup freshness pulls tiles from a newly read brief while the mounted shell can still have the last sample, so a source crossing its age or hour boundary can disagree (`web/brief/Brief.tsx:538–562`; `web/app/App.tsx:75–106`). No at this callback; the freshness helper's own clock is separate. |
| `web/brief/Brief.tsx:239` | E | `readFeed` can refuse a saved-response timestamp beyond future slack relative to receipt even with a frozen dock (`web/offline-response.ts:14–20`). No at loader; pure helper takes `now`. |
| `web/brief/WhereToLook.tsx:241` | E | `Why` can recompute its evidence reasons after an age threshold while a supplied ranking still reflects an older time. No; injecting the ranking does not inject the reasons clock. |
| `web/brief/WhereToLook.tsx:282` | E | `WhereToLook` can retain old ranked picks through a threshold if its own inputs do not redraw, or rank at real time despite a fixed Brief (`:56–69`; `web/app/Desktop.tsx:45–55`; `web/app/Mobile.tsx:136`). Indirect: give it a ranking; no clock prop on the fallback. |
| `web/coast-data.ts:156` | E | Initial independent expiry signal; a store created with a fixed dock already uses host time for its computed expiry (`:171–178`). No clock option on `createCoastData` (`:98,146`); `admitSnapshot` is separately injectable. |
| `web/coast-data.ts:157` | E | `tick` can expire a snapshot on timeout or focus before the next dock tick, as intended (`:192–202,272–290`). Events can be injected, not time. |
| `web/coast-data.ts:214` | E | A response that finishes parsing after expiry is rejected even if the hour sample predates expiry (`:128–139`). No in the store; yes in `admitSnapshot`. |
| `web/coast-data.ts:224` | E | On a response crossing held-snapshot expiry, `pull` can replace the held snapshot even with an older generated timestamp, if the incoming one is admissible. No in the store. |
| `web/coast-data.ts:228` | E | A failed read can keep a still-live held answer ready on one side of its deadline but not the other (`:224–231`). No in the store. |
| `web/conditions.ts:104` | E | `loadConditionsForecast` may refuse a saved answer just beyond the future-time slack even when Conditions itself has a fixed `now` (`web/offline-response.ts:14–20`). No in the loader; yes in the pure helper. |
| `web/degraded.ts:98` | E | `watchDegraded` captures request start for UTC budget-day eligibility; a fetch can start before UTC midnight while Pacific still shows the previous date. No clock on wrapper; yes at `noteResponse`. |
| `web/degraded.ts:99` | E | The response can arrive the next UTC day, so the notice may not clear on that cross-midnight request even while the Pacific date is unchanged (`:62–86`). No clock on wrapper; yes at `noteResponse`. |
| `web/trip-runtime.ts:273` | E | `recheckRanked` stamps a rejected hash after a manifest read; a minute recheck can change what draws while the dock is fixed or before its next tick (`:219–221,267–274`; `web/map/ranked.ts:73–98`). No time input at runtime; helpers separately take `now`. |
| `web/app/CommandBar.tsx:124` | D | `ShareControl` rebuilds the horizon from wall time and URL after awaiting ports (`:122–125`), so a click spanning Pacific midnight can share a different day than the one shown when clicked (`web/share-link.ts:58–82`). No in control; yes in `shareLink`. |
| `web/app/Planner.tsx:169` | D | `Planner` seeds Float Plan from a wall-time brief; opening or changing the date after rollover can drop/move the return suggestion when the brief's day no longer matches the draft (`web/float-plan.ts:80–94`). No for `floatSeed`; the view's `now` callback is used separately at `:217`. |
| `web/app/RulesCard.tsx:26` | D | `RulesLine` recomputes the selected hour/day with a real sample; at Pacific midnight with no explicit hour, a fixed dock can show yesterday while the mark evaluates today. No in `RulesLine`; `dockState` takes a date. |
| `web/landing/NightMap.tsx:155` | D | `NightMap` uses a fresh current-hour pivot to pick a currents source (`:39–49`); it can switch at the hour independently of the app dock, which is not on this landing view. No at this callback; `nightSource` takes a date. |
| `web/app/Legend.tsx:270` | P | `SwellRow` prints ring issue age, not ring admission (`web/map/nearshore.ts:104–109`). |
| `web/app/Legend.tsx:418` | P | `StationsRow` prints the same age independently. |
| `web/app/TimeDock.tsx:138` | S | `TimeDock` auto-play deliberately recomputes the horizon on each step; after an hour the live step can refuse an hour the fixed render still shows (`web/clock.ts:1–4`; `web/hour.ts:140–144`). No prop for step time. |
| `web/coast-data.ts:192` | S | Arms the timeout for the actual remaining milliseconds; a frozen dock does not pin this delay (`:184–202`). No clock option. |
| `web/alerts.ts:56` | I | `alertDate` defaults to tomorrow in the named zone; used after Pacific midnight, it can choose a day later than a frozen form. Fixed: `now` argument. |
| `web/alerts.ts:77` | I | `dateRange` moves the form's valid date range at region midnight (called from `web/app/TripAlerts.tsx:308`); it need not follow the selected dock day. Fixed: `now` argument. |
| `web/app/CommandBar.tsx:171` | I | Standalone time-window label can jump days on a midnight re-render. Fixed: `now` prop; App supplies it (`web/app/App.tsx:141–149`), but not to ShareControl's click path. |
| `web/app/Desktop.tsx:45` | I | Standalone `Brief` can change the verdict and tide pivot at rollover. Fixed: `now` prop; Desktop already supplies it (`:66–69`). |
| `web/app/FirstAnswerLine.tsx:23` | I | With no prop the headline's forecast can advance on a re-render across the hour. Fixed: `now` prop, supplied by App (`web/app/App.tsx:141–149`). |
| `web/app/PlanRules.tsx:42` | I | `PlanRules` can age a source or change its “checked today” label before/after dock midnight while keeping the explicit trip date (`:27–51`). Fixed: `now` prop; Planner omits it (`web/app/Planner.tsx:307`). |
| `web/app/PlanView.tsx:30` | I | Standalone `TargetRules` can use another selected hour or review date after midnight. Fixed: `now` prop, passed by Plan and Conditions (`:66`; `web/app/views/Conditions.tsx:122`). |
| `web/app/PlanView.tsx:44` | I | Standalone `PlanView` can send a new day's time to rules on midnight re-render. Fixed: `now` prop, passed from shell (`web/app/Desktop.tsx:74`; `web/app/Mobile.tsx:253`). |
| `web/app/TimeDock.tsx:128` | I | Standalone render can advance the horizon on a new render after the hour. Fixed: `now` prop, passed by Desktop (`web/app/Desktop.tsx:66–72`); not the playback override above. |
| `web/app/Trip.tsx:40` | I | `agoText` relative display can change minutes in the same dock hour; fixed `now` argument. |
| `web/app/brief-alert-prefill.ts:32` | I | `briefAlertPrefill` can reject yesterday's seed if opened after Pacific midnight (`:33`), even with a fixed dock. Fixed: `now` argument. |
| `web/app/views/Conditions.tsx:70` | I | Standalone view can jump to another forecast hour or day after midnight (`:78–95`). Fixed: `now` prop, normally passed (`web/app/Desktop.tsx:71`; `web/app/Mobile.tsx:265`). |
| `web/app/views/History.tsx:76` | I | Standalone History can move the trailing observed-day window across midnight (`:90`; `web/hour.ts:64–79`). Fixed: `now` prop, normally passed (`web/app/Desktop.tsx:71`; `web/app/Mobile.tsx:265`). |
| `web/app/views/Reports.tsx:43` | I | `openReports` can reload aged cached reports within the same dock hour or hold an open view past expiry until the effect runs again (`:33–58,180`). Fixed: fifth argument for cache age; it is not forwarded to `loadReports` at `:56`. |
| `web/app/views/Reports.tsx:177` | I | Catch-card evaluation can move to a different day on standalone render (`:187`), but the shell passes `now` (`web/app/Desktop.tsx:75`; `web/app/Mobile.tsx:253`). This prop does not control report loading (`:180`). |
| `web/brief/Brief.tsx:190` | I | `showSavedBrief` can decline an aged restored brief at startup even with a fixed first render; fixed `now` argument, omitted by startup (`web/app/main.tsx:78`). |
| `web/brief/Brief.tsx:507` | I | `refreshForecastIfStale` can reload on return to visibility halfway through a dock hour; fixed `now` argument for the age comparison, not the recorded receipt. |
| `web/brief/Brief.tsx:519` | I | `refreshDailyIfStale` likewise compares read age when visible, not the selected day; fixed `now` argument for the comparison. |
| `web/brief/Brief.tsx:773` | I | Standalone `DockVerdictGuard` can gate a different day's verdict at midnight. Fixed: `now` prop, e.g. `web/app/FirstAnswerLine.tsx:23`. |
| `web/brief/MarkForecast.tsx:29` | I | The mark's local forecast can lag the dock by an hour until the card renders, or use real time while the dock is fixed (`:33`). Fixed: `now` prop standalone; `MarkCard` omits it (`web/app/MarkCard.tsx:339`). |
| `web/brief/TideSpark.tsx:26` | I | With no explicit hour a standalone chart can pivot on a different hour/day at rollover (`:21–33`). Fixed: `now` prop, normally supplied (`web/app/Desktop.tsx:54`; `web/app/Mobile.tsx:140`). |
| `web/brief/WhereToLook.tsx:56` | I | `currentRanking` conditions evidence on age, so advancing real time while keeping fixture time fixed can drop a reason/pick (`:55–69`). Fixed: first argument; `Run` passes one (`web/brief/Run.tsx:166`). |
| `web/brief/shore.ts:178` | I | `shoreReviewLines` can change an expiry label mid-hour without changing Pacific day (`:174–183`). Fixed: `now` argument; `runMark` supplies it. |
| `web/brief/shore.ts:248` | I | `shoreReviewCopy` has the same review-label boundary (`:243–255`). Fixed: `now` argument; `runMark` supplies it. |
| `web/degraded.ts:70` | I | `noteResponse` reads UTC budget day and checks saved-time skew; UTC midnight is Pacific afternoon, not an erroneous Pacific date calculation (`:62–89`). Fixed: `now` and optionally `startedAt`. |
| `web/landing/RegionPicker.tsx:7` | I | Region coverage recheck notice can change when its age threshold crosses independently of the app dock (`:19`). Fixed: `now` prop. |
| `web/landing/live-verdict.ts:88` | I | A landing load started before midnight can still label tomorrow from the old day when its reads settle after midnight (`:101–106`); no dock on this view. Fixed: `now` argument for verdict, not every fetch path. |
| `web/landing/readings.ts:99` | I | `buoyReadings` can mark a buoy stale mid-hour (or refuse a too-far-ahead sample); fixed `now` argument (`:92–95,141–148`). |
| `web/landing/readings.ts:160` | I | `tideReading` can age an observation inside a dock hour; fixed `now` argument (`:160–169`). |
| `web/landing/readings.ts:175` | I | `feedState` changes late status at a minute-based boundary, independent of dock (`:175–178`). Fixed: `now` argument. |
| `web/map/chlorophyll.ts:63` | I | Builder evaluates sample age and reload/withhold while the dock is still on the same hour (`:69–95`). Fixed: `now` callback; Chart registration omits it (`web/app/MapStage.tsx:218`). |
| `web/map/clouds.ts:149` | I | A minute check straddling Pacific midnight can change “other day” for the same selected hour; it also ages frames (`:61–92,152–182`). Fixed: `now` callback; Chart omits it. |
| `web/map/coast-ranking.js:10` | I | `habitatGate` admits manifests at fetch check time; a manifest can expire within a dock hour (`:10–11,38–40`). Fixed: `now` argument. |
| `web/map/coast-ranking.js:56` | I | `rankedHabitat` excludes a feature as soon as a recheck is past its screen expiry, regardless of dock selection (`:56–58`). Fixed: `now` argument. |
| `web/map/contrast.ts:222` | I | Builder can withhold analysis when its issue or retrieval age crosses a mid-hour limit (`:148–153,228–265`). Fixed: `now` callback; Chart omits it. |
| `web/map/currents-layer.js:172` | I | `freshnessText` prints a relative age, which can change within the hour; fixed `now` argument, display only. |
| `web/map/currents.ts:210` | I | `createCurrents` uses its own clock for both `terrainHour` and frame freshness; a tick near rollover can choose a different hour from a fixed stage (`:223–228,317–329`). Fixed: `now` callback. |
| `web/map/depth-contours.ts:397` | I | `createDepthContours` can refuse review eligibility at UTC midnight (still Pacific afternoon) and uses real time for retry delay (`:414–432`). Fixed: `now` callback; Chart omits it. Do not change the review-day rule. |
| `web/map/fronts.ts:205` | I | Builder can withhold old fronts between dock ticks (`:127–137,208–240`). Fixed: `now` callback; Chart omits it. |
| `web/map/preview-layers.ts:139` | I | `createPreviewLayers` passes its callback to each preview; sample age can cross the cutoff during the same dock hour (`:167`; `web/map/preview/common.ts:25–35`). Fixed: `now` callback at builder; MapStage leaves the default (`web/app/MapStage.tsx:225`). |
| `web/map/ranked.ts:73` | I | `screenRanked` can stop drawing when the manifest expires between dock ticks (`:73–86`; `web/trip-runtime.ts:221`). Fixed: `now` argument, omitted by runtime. |
| `web/map/ranked.ts:93` | I | `recheckPlan` dates a rejection so a previously verified plan cannot be redrawn; loading across an expiry can disagree with a fixed dock (`:91–98`). Fixed: `now` argument, explicitly wall time in runtime. |
| `web/map/shore.ts:132` | I | `runMark` can change its review-date line after expiry between dock ticks; fixed `now` argument passed by `createShore` (`:221`). |
| `web/map/shore.ts:170` | I | `createShore` can change run visibility or advisory status before the next dock tick when reviews, checks or warnings expire (`:83–92,176–199`). Fixed: `now` callback; Chart omits it. |
| `web/map/sst.ts:309` | I | Builder selects a frame and evaluates age on its own clock, so a layer tick can advance past the dock's still-displayed hour (`:319,415–425`). Fixed: `now` callback; Chart omits it. |
| `web/map/stations.ts:36` | I | Station tide-hour selection can lag the dock until the next minute tick while observation freshness legitimately changes inside an hour (`:40–49,93–94`; `web/map/station-model.ts:32–35,141–148`). Fixed: `now` callback, not passed by MapStage (`web/app/MapStage.tsx:219`). |
| `web/map/swell.ts:304` | I | Builder can advance the swell frame at an independent tick or lose a fresh frame before the dock moves (`:312–320,393–406`). Fixed: `now` callback; Chart omits it. |
| `web/map/wind-layer.js:20` | I | `fresh` checks a grid's issue age; stale status can flip within an hour. Fixed: `now` argument. |
| `web/map/wind.ts:103` | I | Builder recomputes the selected frame and freshness on its own schedule; a `Now` forecast frame can lag or lead a tick of the dock (`:108–109,140`). Fixed: `now` callback; Chart omits it. |
| `web/planner.ts:214` | I | `createPlanner` captures region “today” once (`:219`), so an open planner can retain yesterday past Pacific midnight; its route checks still use the advancing callback (`:625–657`). Fixed/dynamic: `deps.now`, not supplied at `web/trip-runtime.ts:235–252`. |
| `web/port-alert.ts:75` | I | `evaluatePortAlert` can deem the forecast too old in the same dock hour, or advance the upcoming risk window at the hour (`:78–83`). Fixed: `now` argument. |
| `web/protected-route.ts:29` | I | `buildProtectedRoute` can reject a boundary check when its actual age crosses the cutoff within one dock hour (`:34–37`); also stamps the GPX (`:56`). Fixed: `now` input; Planner supplies it (`web/planner.ts:601`). |
| `web/regs.ts:114` | I | `regulationState` uses the trip date if supplied, else its own region day; validity or source age can flip when a fixed parent still shows yesterday (`:123–151`). Fixed: `now`, plus separate trip date/instant. |
| `web/regs.ts:209` | I | `freshnessLabel` can change from checked today to checked earlier at Pacific midnight, even for the same rule (`:212–216`). Fixed: `now` argument. |
| `web/reports.ts:68` | I | `evidenceFrom` may exclude evidence past freshness cutoff within a dock hour (`:68–74`). Fixed: `now` argument. |
| `web/reports.ts:98` | I | `watchFrom` can flag the coast status old at 36 hours while the dock's hour has not moved (`:98–99`). Fixed: `now` argument. |
| `web/reports.ts:147` | I | `loadReports` evaluates discussions, evidence and watch against its own start time, so a long load can settle after a freshness threshold (`:147–160`). Fixed: `ReportsInput.now`; `openReports` does not pass it. |
| `web/tide-selection.ts:91` | I | `packURLs` can generate a new GMT date span at UTC midnight while the page is still on the same Pacific day (`:96`; `web/tide-stations.ts:88–94`). Fixed: `now` argument. |
| `web/tide-stations.ts:88` | I | `tidePredictionsURL` chooses GMT begin/end dates, so the URL can shift in late Pacific afternoon, correctly for that upstream request. Fixed: `now` argument. |
| `web/tide-stations.ts:93` | I | `tidePackURLs` chooses the same GMT date span for bundled requests. Fixed: `now` argument. |
| `web/tide-stations.ts:131` | I | `loadTideReading` uses that span and falls back to the read's start time for the receipt; later freshness is judged against that stamp (`:135–146,164`). Fixed: `now` argument. |
| `web/trip-runtime.ts:139` | I | `oceanPhase` judges pack eligibility independently of a fixed dock, including when saving just after the drawable limit (`:131–143`). Fixed: `deps.now` callback. |

**Important non-matches.** `expireWhenStale` is a one-minute interval invoking the caller's check (`web/map/preview/common.ts:33–35`), not a second clock read. Shore and Stations likewise invalidate their computed state from timers (`web/map/shore.ts:176–199`; `web/map/stations.ts:93–98`); `startTrip` invokes the already-inventoried ranked recheck every minute (`web/trip.ts:249`; `web/trip-runtime.ts:267–274`). The route preview already uses one injectable `deps.now` for its boundary age, deadline and last admission check; it has a precise expiry timeout, plus minute and visibility rechecks (`web/planner.ts:214,621,625–657,679–685`). A fixed-time test needs to advance that clock **and** the timer or invoke a resume event; the future dock selection should never extend an expired review. UTC contour review-date admission (`web/planner.ts:356`; `web/map/depth-contours.ts:416`) is also not a Pacific “today” bug.

## R3. Ten highest-priority visitor-facing sites

Rank is an estimate from visible impact and the ease of reaching the boundary, not traffic data. These are proposed changes, not decisions about data or rules. Keep thresholds and meaning intact.

| Rank | Site and smallest change |
| ---: | --- |
| 1 | `web/app/RulesCard.tsx:26`, `RulesLine`: receive the shell hour sample for selected time, as `targetRules` does (`web/app/PlanView.tsx:22–28`); then midnight/rollover cannot make the mark use a second horizon. |
| 2 | `web/brief/MarkForecast.tsx:29`, `MarkForecast`: pass the same sample from `MarkCard` (`web/app/MarkCard.tsx:339`) to recalculate local forecasts on dock changes, not just incidental renders. Supply freshness separately if a test needs sub-hour expiry. |
| 3 | `web/map/stations.ts:36`, `createStations`: split the shared sample used for `terrainHour` from the real-time freshness callback at `:46–49`; keep the minute recheck. |
| 4 | `web/app/CommandBar.tsx:124`, `ShareControl`: pass the same `now` and effective dock day the shell is presenting to `shareLink` (`web/share-link.ts:58–70`), rather than rebuild selection from a click's wall time and URL alone. |
| 5 | `web/planner.ts:214`, `createPlanner`: derive the planner's current-day bounds from a reactive region-day input instead of the captured string at `:219`; do not change an explicitly saved date or the precise route clock. |
| 6 | `web/app/RulesCard.tsx:27` (state), `RulesLine`: give rule evaluation a named, injectable real-time sample independent of the selected instant. Reuse it for the freshness label instead of taking another timestamp. |
| 7 | `web/brief/WhereToLook.tsx:282`, `WhereToLook`: pass a named clock input down from Brief and recompute with the existing publication recheck (`:293`); don't treat the forecast selection as evidence time. |
| 8 | `web/map/clouds.ts:149`, `createClouds`: use the shell sample for region-day comparison and leave the frame age on its existing callback (`:78–92,152–182`). |
| 9 | `web/app/Planner.tsx:169`, `Planner` / `floatSeed`: pass an explicit sample and look up the brief for the requested day; preserve manual values and existing reseed guards (`:169–171`; `web/float-plan.ts:80–94`). |
| 10 | `web/app/views/Reports.tsx:43`, `openReports`: forward the one injected load timestamp when calling `loadReports` at `:56`; separately decide if an already-open view needs the existing reload check on visibility, without increasing read frequency by default. |

## R4. Two small follow-up units (estimates, not implemented)

1. **Match mark-card hour to the dock (estimated 105 minutes).** Files: `web/app/Desktop.tsx`, `web/app/Mobile.tsx`, `web/app/MarkCard.tsx`, `web/app/RulesCard.tsx`, `web/brief/MarkForecast.tsx`, prospective `tests/test_mark_card_clock.mjs`. Thread the rendered hour sample into mark forecasts and `RulesLine` selection; give the rules reads one separate overridable freshness sample. Offline: `node --test tests/test_mark_card_clock.mjs tests/test_hour_clock.mjs` with synthetic forecast and rules, a frozen Pacific midnight rollover, one explicit future hour and a distinct receipt-time cutoff. Assert both mark outputs follow dock selection and never treat a future forecast hour as the age of a rules source. Source seams: `web/app/MarkCard.tsx:338–339`, `web/app/RulesCard.tsx:26–27`, `web/brief/MarkForecast.tsx:29–33`.
2. **Use the stage's hour sample for station tide selection (estimated 75 minutes).** Files: `web/app/MapStage.tsx`, `web/map/stations.ts`, prospective `tests/test_stations_hour_clock.mjs`. Pass an observable selected-hour input based on the same stage clock; keep the `now` freshness callback and minute recheck. Offline: `node --test tests/test_stations_hour_clock.mjs tests/test_hour_clock.mjs` with a fake feed/engine, a step across a whole hour without a timer tick, then an observation-age step inside that hour. Assert the tide frame advances with the dock at rollover, and the stale pin changes on its own recheck without moving the chosen tide hour. Source seams: `web/app/MapStage.tsx:215–219`, `web/map/stage.ts:448`, `web/map/stations.ts:40–49,93–94`.
