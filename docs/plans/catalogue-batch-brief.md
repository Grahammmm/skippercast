# One catalogue change for the brief and Conditions

**Recommendation:** Land all six backlog rows together once the catalogue is free and “The day verdict's reasons use the units you chose” has landed (see §3).
**What changes:** Five rows make Spanish screens read in Spanish; the sixth replaces `choppy chop` with `choppy water`, the sole approved English wording change (see §1–2).
**Source checked:** Main at `7335068efd2627dd2a0ba9bea39f09e86a8f252d` (see §4). This is a plan, not an implementation.

## 1. What still appears in English (C1)

| Backlog row | What the checked source shows |
| --- | --- |
| SC2022-01 | **Open.** The desktop heading prints the model's `Today`, `Tomorrow`, or weekday; print uses the profile table's English label. The separate print date already uses the language-aware day helper. `web/app/Desktop.tsx:45–51`, `packages/coast/src/daily.ts:73`, `web/brief/Brief.tsx:952–963`, `web/profile.ts:45–64`. |
| SC2022-02 | **Open.** The available fleet link and both local-report states print the model's English. The unavailable fleet messages already use the catalogue. `web/brief/Brief.tsx:917–926`, `web/brief/model.ts:37–41,185–198`. |
| SC2022-03 | **Open.** The disclosure heading is translated, but its list prints `brief.missing` verbatim. The nearby feed and source gaps use different renderers. `web/brief/Brief.tsx:885–899`, `packages/coast/src/daily.ts:214–253`. |
| SC2022-04 | **Open.** The lower-exposure label, first caveat, and optional custom-limits note come from English model strings. The title and no-window messages already use the catalogue. `web/brief/Brief.tsx:855–866`, `packages/coast/src/assessment.ts:42`, `packages/coast/src/daily.ts:188,203,263–270`, `packages/coast/src/limits.ts:95–101`. |
| SC2137-03 | **Open.** Conditions calls `moonLine` without a language; the line says `Moon: {phase}, {percent}% lit` with English phase names. `web/app/views/Conditions.tsx:115–116`, `web/moon.ts:11,19,57–60`. |
| SC2137-09 | **Open in English; Spanish is already correct.** The spear grader produces `choppy chop`. The verdict joins the formatted reasons into its headline, but English returns that reason before it reaches the shared `{band} chop` lookup. The Spanish test expects `oleaje corto picado`. `packages/coast/src/spear.ts:178–187`, `web/brief/verdict-copy.ts:76–82,105`, `web/brief/verdict.ts:285`, `catalog/app/strings.json:245,256`, `tests/test_verdict_i18n.mjs:217–226`. |

These are findings from code, not a live or browser replay. Deployed behaviour is **UNVERIFIED**.

## 2. Proposed catalogue blocks and where they go (C2)

Add the entries below to the `strings` map, alongside their namespace (`catalog/app/strings.json:169–179,237–263,1731`; schema consumed by `scripts/build_landing_strings.mjs:28–40`). Only text in braces is substituted. The proposed Spanish has not been reviewed by a native speaker (**UNVERIFIED**); prioritise the nearshore, bar, swell, surge and moon terminology, and retain the checks and caveats in the English. English stays byte-identical except for the explicitly approved spear wording below.

### SC2022-01 · Desktop day and printed profile

**No new ids or placeholders.** Reuse `brief.day.today` (`today` / `hoy`), `brief.day.tomorrow` (`tomorrow` / `mañana`), and the `{date}` weekday formatting used by `leadDayText`. The existing `brief.day.date` is `{date}` / `el {date}`; do not change it. For the heading use the day helper's same local today/tomorrow comparison and, for later dates, format `brief.date` as a long weekday without the sentence prefix `el`. Capitalise the first letter for the heading (`Hoy`, `Mañana`, etc.). Use the shown region's time zone and the clock already supplied to `Brief`, not the verdict lead date or device day. Keep `brief.label` in English and the existing no-brief fallback (`web/app/Desktop.tsx:45–51`, `web/brief/Brief.tsx:594–605,952–961`, `catalog/app/strings.json:169–171`; operator backlog `modes/NEXT-BACKLOG-2026-11-18-skippercast-2022-r2.tsv:5`).

At `PrintBrief`, use `where.profile.boat` (`Boat` / `Barco`), `where.profile.shore` (`Shore` / `Orilla`), `where.profile.spear` (`Spear` / `Pesca submarina`) and `where.profile.kayak` (`Kayak` / `Kayak`). Preserve the region, port, separators and date line. The existing English entries match the profile labels (`web/brief/Brief.tsx:952–963`, `web/profile.ts:45–64`, `catalog/app/strings.json:580–583`).

### SC2022-02 · Fleet and local report

Match the count pattern at `catalog/app/strings.json:2497–2498`. In `BriefLinks`, use `.one` only for `count === 1`, and use `fleet.count` as `n`, `fleet.port` as `port`, and `FLEET_WINDOW_DAYS` as `days`. Pass the published port string through unchanged, including the separator between ports; don't change the link target or unavailable-fleet branches. Pick the local-report id by `brief.localReport.available`. Retain the model's text for other readers (`web/brief/Brief.tsx:917–926`, `web/brief/model.ts:37–41,158–161,185–198`).

```json
{
  "brief.fleet.one": {"en": "{n} boat reported from {port} in the last {days} days", "es": "{n} barco envió informes desde {port} en los últimos {days} días"},
  "brief.fleet.other": {"en": "{n} boats reported from {port} in the last {days} days", "es": "{n} barcos enviaron informes desde {port} en los últimos {days} días"},
  "brief.localReport.available": {"en": "Local coast report for this area.", "es": "Informe costero local de esta zona."},
  "brief.localReport.unavailable": {"en": "Local coast report unavailable here; this brief uses SkipperCast regional feeds.", "es": "No hay un informe costero local para esta zona; este resumen usa datos regionales de SkipperCast."}
}
```

### SC2022-03 · What the brief did not check

At `BriefGaps`, look up fixed text by exact English match, as `gapText` does. For the field template, accept only the six fields below; `{field}` is the catalogue label. For clarity, accept only the three known inputs below in producer order, and fill `{inputs}` with their labels joined by the translated separator (`' and '` / `' y '`, including both spaces). Keep the list order, counts and other gaps unchanged. In Spanish, put any unrecognised line, including the separate spear clarity gaps, in `lang="en"` and leave its text intact; never drop it. Keep English output unchanged (`web/brief/Brief.tsx:225–228,885–899`, `web/brief/Run.tsx:62`, `packages/coast/src/daily.ts:214–253`, `packages/coast/src/spear.ts:148–168`; operator backlog `modes/NEXT-BACKLOG-2026-11-18-skippercast-2022-r2.tsv:7`).

```json
{
  "brief.missing.forecast": {"en": "Fresh local forecast unavailable", "es": "No hay un pronóstico local actualizado"},
  "brief.missing.forecastHours": {"en": "No forecast hours available for this date", "es": "No hay pronóstico por hora para esta fecha"},
  "brief.missing.alertCheck": {"en": "Current marine alert check unavailable", "es": "No se pudo comprobar si hay avisos marítimos vigentes"},
  "brief.missing.fieldHours": {"en": "{field} missing for some forecast hours", "es": "{field}: faltan datos en algunas horas del pronóstico"},
  "brief.missing.field.wind": {"en": "Wind", "es": "Viento"},
  "brief.missing.field.gusts": {"en": "Gusts", "es": "Ráfagas"},
  "brief.missing.field.seas": {"en": "Offshore seas", "es": "Oleaje mar adentro"},
  "brief.missing.field.wavePeriod": {"en": "Wave period", "es": "Período del oleaje"},
  "brief.missing.field.airTemperature": {"en": "Air temperature", "es": "Temperatura del aire"},
  "brief.missing.field.rainProbability": {"en": "Rain probability", "es": "Probabilidad de lluvia"},
  "brief.missing.tideCurve": {"en": "Tide curve unavailable for this date", "es": "No hay curva de mareas para esta fecha"},
  "brief.missing.tideCurvePartial": {"en": "Tide curve covers only part of this date", "es": "La curva de mareas solo cubre parte de esta fecha"},
  "brief.missing.tideEvents": {"en": "High and low tide events unavailable", "es": "No hay datos de pleamar y bajamar"},
  "brief.missing.seaTemperatureNow": {"en": "Fresh sea temperature observation unavailable", "es": "No hay una medición reciente de la temperatura del mar"},
  "brief.missing.seaTemperatureForecast": {"en": "Sea temperature forecast unavailable", "es": "No hay pronóstico de la temperatura del mar"},
  "brief.missing.harborRoute": {"en": "Harbor entrance and full return route need a separate check", "es": "Comprueba por separado la entrada al puerto y toda la ruta de regreso"},
  "brief.missing.beach": {"en": "Breaking surf, beach access and water quality need a local check", "es": "Comprueba en el lugar las rompientes, el acceso a la playa y la calidad del agua"},
  "brief.missing.launchAndReturn": {"en": "Launch and landing surf, drift and the paddle back need a local check", "es": "Comprueba en el lugar las rompientes al salir y desembarcar, la deriva y el regreso a remo"},
  "brief.missing.kayakWindSide": {"en": "Offshore wind cannot be told apart for this stretch of coast; wind judged on speed only", "es": "No se puede determinar si el viento sopla mar adentro en este tramo de costa; solo se evalúa su velocidad"},
  "brief.missing.kayakWindDirection": {"en": "Offshore wind unknown for some hours (no wind direction); wind judged on speed only", "es": "En algunas horas no se sabe si el viento sopla mar adentro (falta la dirección); solo se evalúa su velocidad"},
  "brief.missing.launchSurfEstimate": {"en": "Launch surf is an offshore estimate where no fresh nearshore model covers the hour", "es": "Si no hay un modelo costero actualizado para esa hora, las rompientes en la salida se estiman con datos mar adentro"},
  "brief.missing.fog": {"en": "Fog and visibility are read only from marine alerts; check the marine forecast", "es": "La niebla y la visibilidad solo se revisan en los avisos marítimos; consulta el pronóstico marítimo"},
  "brief.missing.daylight": {"en": "Sunrise or sunset unknown; daylight not checked", "es": "Falta la hora de salida o puesta del sol; no se comprobó si habrá luz de día"},
  "brief.missing.surfEstimate": {"en": "Surf is an offshore estimate where no fresh nearshore model covers the hour", "es": "Si no hay un modelo costero actualizado para esa hora, las rompientes se estiman con datos mar adentro"},
  "brief.missing.shoreWindSide": {"en": "Wind side unknown for this stretch of coast; wind judged on speed only", "es": "No se sabe si el viento sopla hacia tierra o mar adentro en este tramo de costa; solo se evalúa su velocidad"},
  "brief.missing.shoreWindDirection": {"en": "Onshore or offshore wind unknown for some hours (no wind direction); wind judged on speed only", "es": "En algunas horas no se sabe si el viento sopla hacia tierra o mar adentro (falta la dirección); solo se evalúa su velocidad"},
  "brief.missing.shoreTidePhase": {"en": "Tide phase unknown: high and low tide events unavailable", "es": "Fase de marea desconocida: faltan datos de pleamar y bajamar"},
  "brief.missing.barSwellEstimate": {"en": "Bar swell is an offshore estimate where no fresh nearshore model covers the hour", "es": "Si no hay un modelo costero actualizado para esa hora, el mar de fondo en la barra se estima con datos mar adentro"},
  "brief.missing.barEbb": {"en": "Tide phase unknown: the bar check cannot time the ebb", "es": "Fase de marea desconocida: no se puede determinar la hora de la marea vaciante al evaluar la barra"},
  "brief.missing.underwaterVisibility": {"en": "Underwater visibility is estimated, not measured; entry, exit and currents need a local check", "es": "La visibilidad bajo el agua se estima, no se mide; comprueba en el lugar la entrada, la salida y las corrientes"},
  "brief.missing.clarityInputs": {"en": "Clarity estimate needs {inputs}", "es": "Para estimar la claridad del agua, hace falta lo siguiente: {inputs}"},
  "brief.missing.input.satelliteChlorophyll": {"en": "satellite chlorophyll", "es": "datos satelitales de clorofila"},
  "brief.missing.input.recentChlorophyll": {"en": "a recent chlorophyll reading", "es": "una medición reciente de clorofila"},
  "brief.missing.input.recentSwell": {"en": "recent swell", "es": "datos recientes de mar de fondo"},
  "brief.missing.input.and": {"en": " and ", "es": " y "},
  "brief.missing.surgeEstimate": {"en": "Surge judged from offshore swell where no fresh nearshore model covers the hour", "es": "Si no hay un modelo costero actualizado para esa hora, el vaivén del agua se estima a partir del mar de fondo mar adentro"}
}
```

### SC2022-04 · Lower exposure and limits

Keep the window, times, selection and order of reasons as they are. Match the known English labels and reasons at the web renderer, not in the grader. Reuse `brief.missing.harborRoute` above for the identical boat reason. Render the bar reason if selected, not as a new line: the producer appends it and the current renderer displays only the first reason other than the limits note. `{entrance}` is the published name, not translated. Unknown text gets the same Spanish-page `lang="en"` fallback as the gaps list (`packages/coast/src/assessment.ts:42`, `packages/coast/src/daily.ts:188,203,263–270`, `web/brief/Brief.tsx:855–866`; operator backlog `modes/NEXT-BACKLOG-2026-11-18-skippercast-2022-r2.tsv:8`).

```json
{
  "brief.window.surfWind": {"en": "Lower surf & wind", "es": "Menores rompientes y viento más flojo"},
  "brief.window.surgeWind": {"en": "Lower surge & wind", "es": "Menor vaivén del agua y viento más flojo"},
  "brief.window.windSeas": {"en": "Lower wind & seas", "es": "Viento más flojo y menor oleaje"},
  "brief.window.windOffshoreSeas": {"en": "Lower wind & offshore seas", "es": "Viento más flojo y menor oleaje mar adentro"},
  "brief.window.offshoreExposure": {"en": "Lower offshore exposure", "es": "Menor exposición mar adentro"},
  "brief.window.reason.entry": {"en": "Breaking surf and exact entry conditions are not measured", "es": "No se miden las rompientes ni las condiciones exactas en el punto de entrada"},
  "brief.window.reason.visibility": {"en": "Underwater visibility is not measured", "es": "No se mide la visibilidad bajo el agua"},
  "brief.window.reason.bar": {"en": "{entrance}: bar caution or unknown at departure or return (estimate); check the bar status", "es": "{entrance}: precaución en la barra o estado desconocido a la salida o al regreso (estimación); consulta el estado de la barra"},
  "brief.window.reason.limits": {"en": "Using your limits ({limits}); the default limits would not suggest all of it", "es": "Según tus límites ({limits}); los límites predeterminados no sugerirían todo este intervalo"},
  "brief.window.limit.wind": {"en": "wind {value} {unit}", "es": "viento {value} {unit}"},
  "brief.window.limit.gust": {"en": "gusts {value} {unit}", "es": "ráfagas {value} {unit}"},
  "brief.window.limit.seas": {"en": "seas {value} {unit}", "es": "oleaje {value} {unit}"},
  "brief.window.limit.surf": {"en": "surf {value} {unit}", "es": "rompientes {value} {unit}"},
  "brief.window.limit.surge": {"en": "surge {band}", "es": "vaivén del agua {band}"}
}
```

Only when the existing limits reason is present, use the assessed `brief.limits.values` from the same brief, not a new reading of the saved limits or the window's weather measurements. This avoids parsing numbers and needs no changes to the coast package or model. Match the known limits form, otherwise preserve the original. For Spanish, join the translated fields in producer order with `, ` to fill `{limits}`. Use chosen wind units for wind and gusts, chosen height units for seas or shore surf, and reuse `tile.detail.band.low`, `.moderate`, `.strong` for the optional spear `{band}`. Each `{value}` uses the page number format and each `{unit}` uses the existing unit label. Convert with `WIND_SPEED` and `M_PER_FT`, then round **up** to a tenth for converted values so a displayed limit is never below the stored one. Do not change stored values or comparisons. Keep English rendering of this note byte-identical (including `kt` and `ft`); converting its English display would change bytes and is not part of the approved English exception (`packages/coast/src/limits.ts:22–26,43–47,95–101`, `packages/coast/src/daily.ts:266–270,305`, `web/brief/model.ts:158–161`, `web/brief/types.ts:106`, `web/units.ts:1–9`, `web/unit-choice.ts:4–15`, `web/i18n-core.ts:62–65`, `catalog/app/strings.json:424–428`).

### SC2137-03 · Moon line in Conditions

Pass the current `lang` from `Conditions` into `moonLine`, defaulting the formatter to English for other calls. Use a typed phase-to-id map and interpolate the translated `{phase}` and the locale-formatted integer `{percent}` from the existing rounding. Preserve local noon, selected day, time zone, phase windows and fraction calculation. Load Spanish in the fixture via the existing catalogue test path, not a network call (`web/app/views/Conditions.tsx:73,115–116`, `web/moon.ts:11–19,32–60`, `web/i18n-core.ts:62–65`, `tests/test_moon.mjs:44–63,95–101`, `tests/test_verdict_i18n.mjs:217–226`).

```json
{
  "conditions.moon.line": {"en": "Moon: {phase}, {percent}% lit", "es": "Luna: {phase}, {percent} % iluminada"},
  "conditions.moon.phase.new": {"en": "new", "es": "nueva"},
  "conditions.moon.phase.waxingCrescent": {"en": "waxing crescent", "es": "creciente"},
  "conditions.moon.phase.firstQuarter": {"en": "first quarter", "es": "cuarto creciente"},
  "conditions.moon.phase.waxingGibbous": {"en": "waxing gibbous", "es": "gibosa creciente"},
  "conditions.moon.phase.full": {"en": "full", "es": "llena"},
  "conditions.moon.phase.waningGibbous": {"en": "waning gibbous", "es": "gibosa menguante"},
  "conditions.moon.phase.lastQuarter": {"en": "last quarter", "es": "cuarto menguante"},
  "conditions.moon.phase.waningCrescent": {"en": "waning crescent", "es": "menguante"}
}
```

### SC2137-09 · Spear verdict

**Sole approved English exception:** `choppy chop` → `choppy water`. Add one placeholder-free id and match exactly `choppy chop` in the spear verdict's profile-reason path, before the English early return (recheck the equivalent branch after “The day verdict's reasons use the units you chose”). Preserve `oleaje corto picado`, Light, Rough, the shared `{band} chop` template, and every other reason. Do not change the producer or the verdict logic (operator backlog `modes/NEXT-BACKLOG-2026-11-20-skippercast-2137-r2.tsv:13`; `packages/coast/src/spear.ts:185`, `web/brief/verdict-copy.ts:76–82,105`, `catalog/app/strings.json:245,256`, `tests/test_verdict_i18n.mjs:217–226`).

```json
{
  "verdict.reason.choppyWater": {"en": "choppy water", "es": "oleaje corto picado"}
}
```

## 3. One build, one catalogue owner (C3)

Wait for the catalogue and its generated tables to be free. **SC2137-09 depends on SC1222-05, “The day verdict's reasons use the units you chose,”** which edits the same verdict renderer. Before reserving the batch, confirm that dependency has landed and re-read the changed entry point. Current reservations and dependency landing are **UNVERIFIED** here (operator backlog `modes/NEXT-BACKLOG-2026-11-20-skippercast-2137-r2.tsv:13`, `modes/NEXT-BACKLOG-2026-11-18-skippercast-1222.tsv:9`; overlapping renderer at `web/brief/verdict-copy.ts:65–105`). Keep each row's backlog id. Use two named work sessions in **one** build unit and land neither half on its own. The time estimates and future test results are **UNVERIFIED**.

| Session | Files and work | Focused offline checks to extend and run |
| --- | --- | --- |
| **Brief headings, links and gaps** (up to 90 minutes) | Draft the heading, link and gap entries from §2 in `catalog/app/strings.json` and wire `web/app/Desktop.tsx:45–51` and `web/brief/Brief.tsx:885–926,952–963`. Keep models and print layout as they are. | Extend `tests/test_shell_i18n.mjs` and `tests/test_brief_print.mjs` with today, tomorrow and a later weekday from `brief.date`, the printed profile, no-brief fallback and byte-identical English. Extend the `BriefGaps` harness at `tests/test_brief_view.mjs:383–388` and add `BriefLinks` cases: one boat, several boats, two published ports and both local-report states; assert English bytes. Cover every fixed gap, both templates (including multiple clarity inputs), and an unknown line tagged `lang="en"`. Check the fixed literals from `daily.ts:215–253` against the lookup so new fixed gaps cannot bypass coverage. |
| **Window, moon and spear; generate and verify** (up to 105 minutes) | Add the remaining blocks to the **same** catalogue and wire `web/brief/Brief.tsx:855–866`, `web/app/views/Conditions.tsx:116`, `web/moon.ts:57–60` and the updated `web/brief/verdict-copy.ts`. No coast-package changes. | Extend `tests/test_brief_view.mjs` with the window labels, known reasons, bar name, unknown text, shore surf vs seas, spear surge, no-window branch, and kt/ft and km/h/m limits; check rounding never shows less than the converted limit and English stays identical. Extend `tests/test_moon.mjs` with all eight Spanish phase labels, a percentage and the existing English/local-noon controls. Extend `tests/test_verdict_i18n.mjs:217–226` with both languages for Choppy and unchanged Light, Rough and a non-chop control. |

After both halves, run `node scripts/build_landing_strings.mjs` and then `node scripts/build_landing_strings.mjs --check`. The four configured projections are `web/strings.en.generated.json`, `web/strings.es.generated.json`, `web/landing/strings.generated.json` and `dist/status-strings.generated.json`. Only the first two should change for these ids; the existing print profile ids need no edit. Include only changed projections, and if the branch moves, reconcile **only the source catalogue** and regenerate again; never hand-merge a generated table (`scripts/build_landing_strings.mjs:9–17,28–59`).

Run `node --test tests/test_shell_i18n.mjs tests/test_brief_print.mjs tests/test_brief_view.mjs tests/test_moon.mjs tests/test_verdict_i18n.mjs tests/test_i18n_catalogue_loading.mjs`, then `node scripts/check_copy.mjs` and `pnpm typecheck` as future build checks (`AGENTS.md`, “Before opening a PR”; `scripts/check_copy.mjs:260–275,288`). `Brief.tsx`, `Desktop.tsx`, `Conditions.tsx` and `verdict-copy.ts` are covered by copy lint: use catalogue lookups for visible copy, keep English match keys out of visible JSX, and don't expand the lint exception list. No future build changes or focused test edits are part of this report.

## 4. Replay the source evidence (C4)

Run these from the checkout root. The report changes only this document, so the cited source lines are unchanged at its signed head. Backlog line references are to the operator's backlog, not files in this checkout.

```sh
$ git rev-parse origin/main
7335068efd2627dd2a0ba9bea39f09e86a8f252d
$ git grep -n -F -e 'brief ? brief.label' -e 'moonLine(state.day, tz)' -e "if (lang === 'en') return raw;" -- web/app/Desktop.tsx web/app/views/Conditions.tsx web/brief/verdict-copy.ts
web/app/Desktop.tsx:51:      <span class="ui-eyebrow">{brief ? brief.label : t('shell.todayBrief', language.value)}</span>
web/app/views/Conditions.tsx:116:      <p class="app-conditions-moon">{moonLine(state.day, tz)}</p>
web/brief/verdict-copy.ts:78:    if (lang === 'en') return raw;
$ git grep -n -F "'choppy chop': 'oleaje corto picado'" -- tests/test_verdict_i18n.mjs
tests/test_verdict_i18n.mjs:219:    'Low surge': 'vaivén del agua leve', 'rough chop': 'oleaje corto agitado', 'choppy chop': 'oleaje corto picado', 'clarity estimate likely poor': 'estimación de claridad probablemente mala',
```
