# Locale and number formatting audit

| Question | Finding |
| --- | --- |
| R1 · What is formatted? | 118 matching source lines; 99 date/time/number calls, plus one case-folding call and 24 comment/type-only lines. Nine calls through the shared date formatter are listed separately. |
| R2 · What does a Spanish-page visitor see? | English dates in the share-sheet title, the saved-pack forecast line and several map inspection cards. Some translated clocks deliberately retain English-locale time-zone abbreviations. The older Coast copy is a separate English fallback; the hosted Terrain rail still exposes some of it. |
| R3 · What about decimal commas? | Estimate: 53 source lines contain both template interpolation and `.toFixed(`. This is a search count, not 53 display bugs. |
| R4 · Small follow-up | One optional unit: give the saved-pack forecast line the language already used by the rest of the Trip card. No code changed here. |

## R1. Inventory by file

Source: local `origin/main` at `9e078e2bd4c2db659e0f6e175c33cd6b0fd18553`, read offline on 2026-11-21. It is the card baseline; all line numbers refer to that tree. Reproduce with `git grep -nE 'toLocale|Intl\.' -- web packages`. To focus on calls, use `git grep -nE 'new Intl\.|\.toLocale[A-Za-z]*\(' -- web packages`, excluding the quoted constructor in the comment at `packages/coast/src/date-format.ts:3`. Count individual expressions on a line, not just grep rows. `.format()` and `.formatToParts()` on an already inventoried formatter are consumers, not new locale choices. `git grep -n 'dateTimeFormat(' -- web packages` finds the wrapper callers. This is a source audit, not a deployment or browser-coverage claim.

**Spanish?** describes the consuming screen, not the language of the output: **Yes** includes English-only branches on a bilingual surface; **Island** means English copy inside a Spanish-capable app; **No** means the native English Coast surface or admin UI; **—** means no display. The page language mapping is `es` → `es`, otherwise `en-US` (`web/i18n-core.ts:62`). Each multiplet below names the separate calls on that line.

| Call site | Locale argument | Purpose / consumer | Spanish? |
| --- | --- | --- | --- |
| `packages/coast/src/assessment.ts:34` | `en-CA` | Machine: local day used in the assessment | — |
| `packages/coast/src/coast3d/shading.ts:86` (first, last stop) | `en-US` ×2 | Display: fixed ramp depth range; native readout / host rail | Island |
| `packages/coast/src/coast3d/shading.ts:87` (min, max) | `en-US` ×2 | Display: visible ramp depth range; same consumer | Island |
| `packages/coast/src/coast3d/viewer.ts:259` | None | Display: screened footprint count; native status / host rail | Island |
| `packages/coast/src/coast3d/viewer.ts:281` | None | Display: reef screening expiry evidence | Island |
| `packages/coast/src/date-format.ts:14` | `locale` from caller | Shared constructor/cache; see wrapper table below | Mixed |
| `packages/coast/src/presentation.ts:9` | `en-US` | Display: native report clocks and sample label; web nearshore card builds a separate Spanish label (`web/map/nearshore.ts:119–138`) | No in native; Yes, English branch in web |
| `packages/coast/src/shore-review.ts:45` | None | Display: shore access inventory checked date | Island |
| `packages/coast/src/shore-review.ts:46` | None | Display: prior legal review expiry date | Island |
| `packages/coast/src/ui/catches.ts:26` | `en-US` | Display: catch trip day without copy adapter; web Reports supplies one for Spanish (`web/app/views/Reports.tsx:70`) | No in native; Yes, English branch in web |
| `packages/coast/src/ui/format.ts:3` | `en-US` | Display: Coast clocks; no-copy History/chart path (`ui/history.ts:24,52`, `charts/series.ts:19` in same package); web History supplies copy (`web/app/views/History.tsx:90`) | No in native; Yes, fallback helper not the Spanish formatter |
| `packages/coast/src/ui/history.ts:24` | None | Display: no-copy contributing-hour grouping (`:39`) | No on native path |
| `packages/coast/src/ui/history.ts:45` (valid, expected) | None ×2 | Display: no-copy observed/expected hourly bins | No on native path |
| `packages/coast/src/ui/history.ts:48` (count, expected, samples) | None ×3 | Display: no-copy reference coverage hours and samples | No on native path |
| `web/admin/api.ts:221` | `en-US` | Admin only: timestamp, device zone | No |
| `web/admin/posts.tsx:21` | `en-US` | Admin only: post calendar time, 24-hour | No |
| `web/admin/posts.tsx:22` | `en-US` | Admin only: post calendar day heading/range | No |
| `web/alerts.ts:78` | `en-CA` | Machine: minimum selectable local day | — |
| `web/alerts.ts:170` | `locale` (default `en-US`; caller passes `es` / `en-US`, `web/app/TripAlerts.tsx:524`) | Display: feedback date | Yes |
| `web/alerts.ts:171` | Same `locale` | Display: same date with fallback time zone, not fallback language | Yes |
| `web/alerts.ts:236` | `en-CA` | Machine: recap local-day grouping (`:241`) | — |
| `web/alerts.ts:346` | `es` / `en-GB` by `lang` | Display: alert timestamp, English format differs from `localeOf('en')` | Yes |
| `web/app/Legend.tsx:302` | `localeOf(lang)` | Display: legend date | Yes |
| `web/app/TimeDock.tsx:28` | `localeOf(lang)` | Display: hour on non-English branch | Yes |
| `web/app/TimeDock.tsx:31` | `en-US` | Display: zone-name part only; dock and repeated-hour labels (`:59,158`) | Yes |
| `web/app/TimeDock.tsx:40` | `localeOf(lang)` | Display: short weekday on non-English branch | Yes |
| `web/app/Trip.tsx:37` | `localeOf(lang)` | Display: saved-pack timestamp | Yes |
| `web/app/brief-alert-prefill.ts:12` | `en-CA` | Machine: input date and time parts for alert prefill | — |
| `web/app/views/Conditions.tsx:56` | `localeOf(lang)` | Display: non-English weekday | Yes |
| `web/app/views/Conditions.tsx:125` | `en-US` | Machine: numeric year passed to SeasonStrip | — |
| `web/app/views/HourlyTable.tsx:39` | `localeOf(lang)` | Display: non-English weekday | Yes |
| `web/brief/Brief.tsx:853` | `localeOf(lang)` | Display: Brief clocks including print and window | Yes |
| `web/brief/Brief.tsx:936` | `localeOf(lang)` | Display: Brief weekday/clock with zone | Yes |
| `web/brief/Run.tsx:186` | `en-CA` | Machine: local day for active-window alert prefill | — |
| `web/brief/clock.ts:5` | `localeOf(lang)` (default `lang='en'`) | Display: Run/daylight clock; callers pass `lang` (`web/brief/Run.tsx:69–71,130,145,207`; `web/conditions-daylight.ts:23–24`) | Yes |
| `web/brief/entrance-current.ts:43` | `localeOf(lang)` | Display: entrance-current and tide turn times | Yes |
| `web/brief/mark-forecast.ts:124` | `en-US` | Display: English-only clock branch (`:136–143`) | Yes, English branch |
| `web/brief/mark-forecast.ts:132` | `localeOf(lang)` | Display: corresponding non-English clock | Yes |
| `web/brief/saved-brief.ts:92` | `localeOf(lang)` | Display: saved brief clock | Yes |
| `web/brief/shore.ts:64` | `en-US` | Display: raw English review dates (`:182`); Spanish copy has `dayCopy` | Yes, English branch |
| `web/brief/shore.ts:242` | `es` | Display: Spanish review date (`:253`) | Yes |
| `web/brief/tide-copy.ts:25` | `localeOf(lang)` | Display: tide event clock | Yes |
| `web/brief/verdict-copy.ts:24` | `en-CA` | Machine: hour part used in timing logic | — |
| `web/brief/verdict-copy.ts:36` | `localeOf(lang)` | Display: verdict clock | Yes |
| `web/conditions-daylight.ts:14` | `en-US` | Display: zone abbreviations used with translated sunrise/sunset (`:22–24`) | Yes |
| `web/dates.ts:11` | `locale` from `localeOf(lang)` (`:44`) | Display: date label parts | Yes |
| `web/dates.ts:24` | `en-US` | Machine: local date parts | — |
| `web/dates.ts:39` | `en-US` | Machine: zoned parts to align local noon | — |
| `web/dates.ts:42` | `en-US` | Machine: read back the aligned day as numbers | — |
| `web/degraded.ts:120` | `localeOf(lang)` or `undefined` | Display: saved-copy notice; current component passes `language.value` (`web/degraded-notice.tsx:9`); omitted language is the legacy English-copy path (`:112–120`) | Yes, no default-locale path with Spanish copy |
| `web/float-plan.ts:24` | `en-US` | Machine: zone offset arithmetic | — |
| `web/float-plan.ts:88` | `en-CA` | Machine: validate day and set `HH:mm` field value | — |
| `web/hour.ts:56` | `en-US` | Mixed: machine day/hour parts and English weekday; Spanish renderers replace weekday (`web/app/TimeDock.tsx:40`; `web/app/views/Conditions.tsx:56`; `web/app/views/HourlyTable.tsx:39`) | Yes, English weekday branch |
| `web/i18n-core.ts:65` | `localeOf(lang)` | Display: numeric copy without grouping | Yes |
| `web/i18n-core.ts:69` | `localeOf(lang)` | Display: short date | Yes |
| `web/map/charter-grounds.ts:177` | `en-US` | Display: raw report and audit dates (`:192–193`); invalid Spanish input also falls through here, not a valid English date (`:181`) | Yes, English branch for valid dates |
| `web/map/charter-grounds.ts:181` | `es` | Display: Spanish charter-ground dates | Yes |
| `web/map/clouds.ts:54` | `en-US` | Display: raw cloud label/last frame (`:59–64,92`); paired copy for translated legend (`:67,224`; `web/app/Legend.tsx:278`) | Yes, raw English branch |
| `web/map/coastline.ts:87` | `es` | Display: Spanish survey accuracy (`:125`) | Yes |
| `web/map/commercial-ais.ts:91` | `en-US` | Display: raw AIS apparent fishing hours (`:99`) | Yes, English branch |
| `web/map/commercial-ais.ts:92` | `es` | Display: Spanish counterpart (`:106`) | Yes |
| `web/map/contrast.ts:96` | `en-US` | Display: raw analysis date; translated legend stamp, raw inspection-card kind/source/basis (`:129,165,199–201`) | Yes / Island |
| `web/map/currents.ts:80` | `en-US` | Display: raw current/frame hour; translated status note, raw inspection kind and saved-pack forecast endpoint (`:133–155`; `web/trip-forecast-end.ts:11`); Trip ocean lines use a separate Spanish formatter | Yes / Island |
| `web/map/fleet.ts:129` | `en-US` | Admin only: map fleet event/trip timestamps (`:142–152`); not a public reading | Yes, admin overlay on bilingual map |
| `web/map/past-day-gate.ts:27` | `en-US` | Machine: zoned day parts for past-day gating | — |
| `web/map/past-sample.ts:16` | `en-US` | Machine: zoned parts for past-hour samples | — |
| `web/map/sst.ts:106` | `en-US` | Display: raw SST analysis date; paired legend stamp, raw inspection card (`:127,191,237–239`) | Yes / Island |
| `web/map/status-copy.ts:29` | `locale` from `localeOf(lang)` (`:48`) | Display: day or clock in map status copy | Yes |
| `web/map/status-copy.ts:39` | `locale` from `localeOf(lang)` (`:48`) | Display: weekday/hour parts for map status | Yes |
| `web/map/status-copy.ts:56` | `locale` from `localeOf(lang)` (`:48`) | Display: fixed decimals in map status | Yes |
| `web/map/swell.ts:124` | `en-US` | Display: raw run/valid timestamp; paired legend stamp, raw inspection card (`:128–147,202–204,275–277`) | Yes / Island |
| `web/mark-copy.ts:54` | `es` | Display: Spanish one-decimal mark reading | Yes |
| `web/mark-copy.ts:57` | `es` | Display: Spanish fixed decimals | Yes |
| `web/mark-copy.ts:63` | `es` | Display: Spanish mark timestamp, optional zone | Yes |
| `web/model-disagreement.ts:24` | `en-US` | Machine: extract numeric local hour | — |
| `web/model-disagreement.ts:55` | `localeOf(lang)` | Display: weekday | Yes |
| `web/moon.ts:48` | `en-US` | Machine: local date/time parts for calculation | — |
| `web/planner-copy.ts:91` (Spanish call) | `localeOf(lang)` | Display: Planner GPX preview counts (`web/app/Planner.tsx:354`) | Yes |
| `web/planner-copy.ts:91` (English call) | None | Display: same counts on English branch, device grouping | Yes, English branch |
| `web/planner.ts:219` | `en-CA` | Machine: today key for date selection | — |
| `web/ports.ts:60` | None | Search case folding, not date/number formatting | — |
| `web/reach.ts:101` | `es` | Display: Spanish distance; English branch interpolates a number | Yes |
| `web/regs.ts:47` | `en-CA` | Machine: local day key | — |
| `web/regs.ts:97` | `es-US` / `en-US` by `lang` | Display: rules clock | Yes |
| `web/reports-copy.ts:20` | `localeOf(lang)` | Display: report date | Yes |
| `web/reports-copy.ts:72` | `localeOf(lang)` | Display: catch trip day adapter | Yes |
| `web/share-link.ts:49` | `en-US` | Display: native share-sheet title (`:92–103`), not the URL's date key (`:78`) | Yes, from bilingual toolbar |
| `web/size-text.ts:9` | `localeOf(lang)` | Display: GB label | Yes |
| `web/trip-calendar.ts:28` | `en-CA` | Machine: date/time parts for calendar serialization | — |
| `web/trip-ocean-lines.ts:17` | `localeOf(lang)` | Display: Spanish Trip ocean timestamp, English calls `frameTime` | Yes |
| `web/trip-times.ts:35` | `locale`; default `en-US` for offset (`:38`), `en-CA` for day key (`:43`), `es-US` / `en-US` for clock (`:105`) | Mixed: machine timing and display of plan clock | Yes for display |
| `web/view-copy.ts:24` | `localeOf(lang)` | Display: decimal formatting, after rounding | Yes |
| `web/view-copy.ts:32` | `locale` from `en-US` (`:34`, zone part only) or `localeOf(lang)` (`:35`, rest) | Display: alert, Conditions and History clocks; see R2 | Yes |
| `web/view-copy.ts:33` | `localeOf(lang)` | Display: English clock branch | Yes, English branch |
| `web/zone.ts:9` | `en-US` | Machine: validate IANA time-zone name | — |

Additional calls through `packages/coast/src/date-format.ts:14`:

| Wrapper call | Locale | Purpose | Spanish? |
| --- | --- | --- | --- |
| `packages/coast/src/daily.ts:41` | `en-US` | Machine: assemble zoned date key | — |
| `packages/coast/src/daily.ts:54` | `en-US` | Machine: calculate zone offset | — |
| `packages/coast/src/daily.ts:72` | `en-US` | Display: native day label | No on native path |
| `packages/coast/src/daily.ts:309` | `en-US` | Display: hour in native and web Brief headline/deck | Island in web |
| `packages/coast/src/daily.ts:310` | `en-US` | Display: tide clock in native and web Brief deck | Island in web |
| `packages/coast/src/daily.ts:377` | `en-US` | Display: calmest-hour sentence in native and web Brief deck | Island in web |
| `web/app/PlanView.tsx:26` | `en-CA` | Machine: local plan day | — |
| `web/app/RulesCard.tsx:26` | `en-CA` | Machine: rules date lookup | — |
| `web/brief/verdict.ts:81` | `en-CA` | Machine: zoned parts for timing | — |

The other hits in the broad search are not calls: `packages/coast/src/date-format.ts:1,3,7,9`, `packages/coast/src/ui/copy.ts:26`, `packages/coast/src/ui/history.ts:52`, `web/alert-time.ts:9`, `web/alerts.ts:169`, `web/brief/mark-forecast.ts:121,128`, `web/dates.ts:5–6`, `web/hour.ts:51`, `web/i18n-core.ts:68`, `web/map/clouds.ts:50`, `web/map/contrast.ts:92`, `web/map/past-day-gate.ts:39`, `web/map/past-sample.ts:33`, `web/map/sst.ts:102`, `web/map/status-copy.ts:25–26,34`, `web/map/swell.ts:121`, `web/view-copy.ts:31`.

## R2. English or device-default output in Spanish context

The examples use one synthetic instant, `2026-07-15T23:05:00Z`, in `America/Los_Angeles` unless noted. Offline scratch probe `node locale-examples.mjs`, 2026-11-21 (Node v22.23.2, ICU 78.2, default `en-US` / `America/Los_Angeles`), returned `PDT`, `GMT+2` (Madrid), `4:05 PM`, `Jul 15`, `Wed 4 PM`, `Wed Jul 15`, `Jul 15, 4:05 PM PDT`, `7/15/2026`, and `4,560`. The examples below combine those fragments with the source text; they are not screenshots. The no-locale results can vary with the device, and the no-options dates also use its time zone.

| Where Spanish copy meets fixed/default formatting | Example fragment a visitor can see | Why it survives the language switch |
| --- | --- | --- |
| Trip saved-pack forecast end | `Forecast saved through Wed 4 pm` | `web/app/Trip.tsx:183` supplies `lang` to adjacent saved status and size but not this line. `web/trip-forecast-end.ts:8–11` uses the raw English `frameTime` (`web/map/currents.ts:79–80`). The whole line is English, not just the timestamp. |
| Share sheet title | `Wed Jul 15` among the title parts | `web/app/CommandBar.tsx:124` calls `shareLink` from the bilingual toolbar. `web/share-link.ts:49,92–103` sends that English date to native share; clipboard fallback copies the URL, not this title. |
| Time Dock zone and repeated-hour suffix | `PDT` (or an English-locale offset label such as `GMT+2`) | `web/app/TimeDock.tsx:28–31,54–59,158` localizes the hour separately from its zone. The zone token alone is pinned; not an English weekday/clock leak. |
| Conditions daylight | `PDT` appended to the translated sunrise/sunset line | `web/conditions-daylight.ts:13–14,22–24` uses English-locale zones while passing `lang` to both clocks and the sentence. |
| Alert span, port alert, Conditions clocks and web History (when the options include a zone) | `PDT` inside an otherwise Spanish date/time | `web/view-copy.ts:31–35,43` explicitly substitutes only the English-locale zone token. Consumers: `web/alert-time.ts:24–29`, `web/app/PortAlert.tsx:16`, `web/app/views/Conditions.tsx:53`, `packages/coast/src/ui/history.ts:40,45`. Keep this distinct from a full English timestamp. |
| Current inspection card | `Forecast · valid Wed 4 pm` | `web/map/currents.ts:155` sets raw kind without a Spanish override; the chart card chooses translated fields only when supplied (`web/mark-copy.ts:42–45`, `web/app/MarkCard.tsx:316–324`). The status note itself has translated copy (`web/map/currents.ts:133–139`). |
| SST and temperature contrast inspection cards | `Daily analysis · Jul 15` and `analysis Jul 15 · … old` | Raw kind/source/basis survive in the card (`web/map/sst.ts:127,188–191,237–239`; `web/map/contrast.ts:129,161–165,199–201`); legend stamps have separate localized parts. |
| Swell inspection card | `run Jul 15, 4 pm` in the source stamp | Raw kind/source/basis at `web/map/swell.ts:128–147,167,275–277`; translated status/stamp at `:202–204`. |
| Brief Details, model headline and deck | `Calmest daylight hour: 4 PM`; `Very low tide near 4:05 PM` | The model forwards `daily.headline` and `daily.summary` (`web/brief/model.ts:157`) into a translated disclosure without translating those fields (`web/brief/Brief.tsx:834–843,610`). Clock sources: `packages/coast/src/daily.ts:282–290,309–310,342–347,363,377`. |
| Terrain ramp (explicit English detail) | `Fixed ramp 0–5,900 ft` or `Ramp 0–5,900 ft in view` | Both ends use `en-US` (`packages/coast/src/coast3d/shading.ts:86–88`); the host uses `EnglishDetail` next to translated layer controls and notes (`web/app/LayerRail.tsx:169–174`). |
| Terrain habitat count (explicit English detail) | `4,560 screened reef footprints` | `packages/coast/src/coast3d/viewer.ts:259`; host retains the status inside `EnglishDetail` (`web/app/LayerRail.tsx:137`). |
| Terrain reef / shore evidence (raw English detail) | `Screening valid until 7/15/2026.`; `Access inventory checked 7/15/2026.`; `the prior legal review expired 7/15/2026.` | `packages/coast/src/coast3d/viewer.ts:265,281–283` and `packages/coast/src/shore-review.ts:44–46` use the browser default in the native target panel (`packages/coast/src/embed-template.ts:9`; `packages/coast/src/embed.ts:66`). These are not dates inserted into translated review sentences. |

Do not count `en-CA` lookups as Spanish prose; for example the probe returned `2026-07-15` for the machine day. Do not count the no-copy Coast History counts, catch dates or clock/month labels as leaks from web History or Reports: those web views pass language-aware adapters (`web/app/views/History.tsx:90`, `web/app/views/Reports.tsx:70`), while native Coast uses no-copy views (`packages/coast/src/coast3d/report.ts:83,96–98`). Alert feedback/zone fallback, Brief/mark clocks and reviewed shore dates also already have Spanish branches (R1). The admin Fleet overlay is a restricted English detail, not evidence of a public locale regression (`web/map/fleet.ts:142–152`).

## R3. Decimal points in template strings (estimate)

`git grep -nF '.toFixed(' -- web packages` returned **103 matching lines**. `git grep -nE '(\$\{.*\.toFixed\(|\.toFixed\(.*\$\{)' -- web packages` is a candidate search; the estimate counts any matching `.toFixed(` line containing `${` (53 lines in the local scratch scan, 2026-11-21). It counts source lines, not individual calls or rendered fields. Some hits are CSS/SVG, IDs, English-only branches, or numbers rounded before locale formatting; some display helpers format and interpolate on different lines and are missed. The same probe showed `4.5` from `.toFixed(1)` and `4,5` from Spanish `Intl.NumberFormat`. The ten examples include controls for what not to change.

| Example | Output pattern and exposure |
| --- | --- |
| `web/app/Legend.tsx:352` | `4.5` passed into the translated route detail; decimal-point exposure. |
| `web/app/PositionView.tsx:17` | `4.5 nmi (8.3 km)` from fixed decimals, not a locale formatter. |
| `web/brief/WhereToLook.tsx:104` | `4.5` passed to distance copy; separate number creation and template rendering. |
| `web/brief/Tiles.tsx:59` | `4.5` in the optional metric conversion; separate helper expression, not in the same-line interpolation estimate. |
| `web/map/contrast.ts:200` | `0.25 °F per nautical mile (0.075 °C per km)` in raw inspection copy. |
| `web/map/currents.ts:156` | `1.50 kt toward 90° true` in raw inspection copy. |
| `web/map/swell.ts:276` | `4.5 ft · 10.0 s` in raw inspection copy. |
| `web/map/nearshore.ts:123–138` | `4.5 ft · 9.0 s` in the raw branch; Spanish has its own reading parts. |
| `web/brief/Run.tsx:110` | Spanish explicitly replaces `.` with `,`; a workaround, not an unchanged decimal point. |
| `web/map/stage.ts:112` | Fixed decimals in comma-delimited map camera coordinates; machine string, not display. |

## R4. One optional follow-up (estimate: 60–90 minutes)

Scope just the saved-pack forecast line (`web/trip-forecast-end.ts:8–11`, `web/app/Trip.tsx:183`). If the owner wants it localized, pass the existing page language through, use the localized clock pattern already used in `web/trip-ocean-lines.ts:17`, and add the owner-approved keys in `catalog/app/strings.json` and its app projections `web/strings.en.generated.json` and `web/strings.es.generated.json` (`scripts/build_landing_strings.mjs:34–55`). Keep the existing English output, saved-pack times, comparisons and data unchanged. Extend `tests/test_pack_forecast_end.mjs:40–54` with synthetic future, ended and missing-time cases in both languages; run `node --test tests/test_pack_forecast_end.mjs` offline. This is a proposal, not a copy decision or implementation.
