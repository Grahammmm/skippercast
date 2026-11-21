# Make unit labels follow the units choice

- **Recommendation:** Update the affected English and Spanish catalogue entries together, with their callers, and regenerate the tables once (`scripts/build_landing_strings.mjs:1–11,32–40`).
- **Keep the defaults:** Preserve the words, spacing and number formatting already shown in each language, including `kn` in model agreement and `nm` in run distances (`catalog/app/strings.json:149–150,168,562–563,675`).
- **Keep the decisions:** Change what people read and type, not what the forecast, routing or alert code compares (`web/unit-choice.ts:1–20`; `web/brief/agreement.ts:21–30`; `web/port-alert.ts:93–108`).

Source head checked: `7335068efd2627dd2a0ba9bea39f09e86a8f252d` (`git rev-parse origin/main`). Source-only review; deployed behaviour and future implementation are **UNVERIFIED**. This report does not build or replace any approved backlog row.

## 1. Catalogue inventory (C1)

The left column refers to `catalog/app/strings.json`. The other column names the code that supplies or selects the copy, not the generated dictionary. Standalone labels and fixed measurements are listed separately below: a `kt` button must still say `kt` when `mph` is chosen, and the offshore current is not wind (`web/app/UnitChoice.tsx:19–26`; `web/brief/entrance-current.ts:112–114`).

| ID and catalogue line | Caller |
| --- | --- |
| `brief.models.agree` 149; `brief.models.differ` 150; `brief.models.readings` 168 | `web/brief/Brief.tsx:805–807,822` |
| `verdict.longPeriod` 234 | `web/brief/verdict-copy.ts:131` |
| `entrance.swell` 719; `entrance.swell.period` 720 | `web/brief/entrance-current.ts:101–102` |
| `hourly.over.wind` 1802; `hourly.over.gust` 1803; `hourly.over.seas` 1804 | `web/app/views/HourlyTable.tsx:54–58` |
| `tile.basis.tide` 397; `landing.basis.tide` 851 | `web/brief/Tiles.tsx:58–68`; `web/landing/readings.ts:160–170` |
| `where.distance.water` 562; `where.distance.straight` 563; `run.distance.straightWhy` 675 | `web/brief/Run.tsx:109–113`; `web/brief/WhereToLook.tsx:102–105`; shared IDs also used by `web/mark-distance.ts:47–51` |
| `limits.unit.kt` 881; `limits.unit.ft` 882; `limits.unit.nm` 883; `limits.unit.yd` 884; `limits.unit.reach` 885 | `web/app/LimitsPanel.tsx:39–42,104,118,137,152` (literal search for `limits.unit.nm` under `web`, excluding generated tables, found no caller: runtime use **UNVERIFIED**) |
| `portAlert.wind` 1690; `portAlert.swell` 1691; `portAlert.invalid` 1694; `portAlert.hit.wind` 1703; `portAlert.hit.swell` 1704 | `web/app/PortAlert.tsx:48–55` |
| `markForecast.gusts` 535 | `web/brief/mark-forecast.ts:200–208` |

The hour headings are a separate gap: `hourly.h.wind/gust/seas/swell/second/chop` (1787–1792) are read unchanged at `web/app/views/HourlyTable.tsx:20,47`, even though the cells use the device choice at :54. `hourly.h.vis` (1794) is still truthful: the cell stays in miles (`web/hourly-table.ts:77`). The approved marker row covers the marker, not a change to visibility or printing (`modes/NEXT-BACKLOG-2026-11-18-skippercast-2022-r2.tsv:13`, operator-local backlog).

### Rest of the catalogue

See the inventory at the end of this section. It separates the dictionary entries from their display policy: source specifications, rule margins, reference boat dimensions, contour legends, other screens, and unit pickers are not automatically part of the six backlog rows. No pick-up of that work is proposed. A caller marked **UNVERIFIED** means a literal match was not sufficient to identify the production caller; it does not mean the ID can be deleted.

| ID and catalogue line | Caller or source reference |
| --- | --- |
| `brief.boat.reference` 145 | web/brief/Brief.tsx:724 |
| `brief.boat.yours` 146 | web/brief/Brief.tsx:724, web/landing/live-verdict.ts:59 |
| `brief.boat.note` 148 | web/brief/Brief.tsx:810, web/landing/live-verdict.ts:111 |
| `units.celsius` 194 | web/app/UnitChoice.tsx:16 |
| `units.fahrenheit` 195 | web/app/UnitChoice.tsx:15 |
| `units.height.ft` 196 | web/app/UnitChoice.tsx:26 |
| `units.height.m` 198 | web/app/UnitChoice.tsx:26 |
| `units.wind.kmh` 200 | web/app/UnitChoice.tsx:21 |
| `units.wind.kt` 201 | web/app/UnitChoice.tsx:21 |
| `units.wind.mph` 202 | web/app/UnitChoice.tsx:21 |
| `verdict.wind` 214 | web/brief/verdict-copy.ts:68 |
| `verdict.seas` 216 | web/brief/verdict-copy.ts:70 |
| `verdict.chop` 218 | web/brief/verdict-copy.ts:71–72 |
| `verdict.steepChop` 219 | web/brief/verdict-copy.ts:71–72 |
| `verdict.cross` 220 | web/brief/verdict-copy.ts:73 |
| `verdict.calm` 222 | web/brief/verdict-copy.ts:119 |
| `verdict.reason.detail` 258 | web/brief/verdict-copy.ts:62–115 |
| `verdict.reason.windDetail` 260 | web/brief/verdict-copy.ts:62–115 |
| `skill.tolerance.wave_height` 310 | UNVERIFIED (no exact literal caller found) |
| `skill.tolerance.wind_speed_10m` 311 | UNVERIFIED (no exact literal caller found) |
| `markForecast.gap.noCell` 505 | web/brief/mark-forecast.ts:279 |
| `markForecast.src.cell` 507 | web/brief/mark-forecast.ts:306 |
| `markForecast.gridAbout` 532 | web/brief/mark-forecast.ts:151 |
| `markForecast.towardTrue` 536 | web/brief/mark-forecast.ts:281 |
| `where.screen.near` 560 | web/brief/WhereToLook.tsx:142, web/waypoint-placement.ts:24, web/waypoint-placement.ts:31 |
| `where.dive.depth` 585 | web/brief/WhereToLook.tsx:189 |
| `where.dive.swim` 588 | web/brief/WhereToLook.tsx:188 |
| `ranking.basis.ranged` 617 | web/ranking.ts:437 |
| `ranking.basis.swum` 618 | web/ranking.ts:438 |
| `ranking.basis.water` 620 | web/ranking.ts:438 |
| `ranking.within` 625 | web/ranking.ts:439 |
| `ranking.within.reach` 626 | web/ranking.ts:439 |
| `ranking.within.shore` 627 | web/ranking.ts:439 |
| `ranking.swim` 647 | web/ranking.ts:140 |
| `ranking.reason.relief` 651 | web/ranking.ts:147 |
| `ranking.reason.clearance` 653 | web/brief/ranking-copy.ts:38 |
| `run.lead.noTime` 664 | web/brief/Run.tsx:136 |
| `run.detail.eachSpeed` 674 | web/brief/Run.tsx:140 |
| `entrance.wcofs.out` 725 | web/brief/entrance-current.ts:112–114 |
| `entrance.wcofs.in` 726 | web/brief/entrance-current.ts:112–114 |
| `entrance.wcofs.across` 727 | web/brief/entrance-current.ts:112–114 |
| `entrance.wcofs.weak` 728 | web/brief/entrance-current.ts:112–114 |
| `entrance.wcofs.unjudged` 729 | web/brief/entrance-current.ts:112–114 |
| `entrance.basis` 737 | web/brief/entrance-current.ts:80 |
| `run.route.near` 740 | web/brief/Run.tsx:57 |
| `run.basis.text` 753 | web/brief/Run.tsx:119 |
| `landing.profile.note.boat` 794 | web/landing/ProfileStep.tsx:49; web/app/FirstRun.tsx:136 |
| `landing.profile.note.spear` 796 | web/landing/ProfileStep.tsx:49; web/app/FirstRun.tsx:136 |
| `landing.profile.note.kayak` 797 | web/landing/ProfileStep.tsx:49; web/app/FirstRun.tsx:136 |
| `landing.place.from` 836 | web/landing/readings.ts:67 |
| `landing.boat.reference` 852 | web/landing/live-verdict.ts:36, web/landing/live-verdict.ts:111 |
| `boatEntry.length` 866 | web/boat-entry.ts:23 |
| `boatEntry.lengthHint` 867 | web/boat-entry.ts:24 |
| `boatEntry.wind` 868 | web/boat-entry.ts:25 |
| `boatEntry.seas` 869 | web/boat-entry.ts:26 |
| `boatEntry.windSaved` 875 | web/boat-entry.ts:107 |
| `boatEntry.seasSaved` 876 | web/boat-entry.ts:107 |
| `accountMenu.ratingsReference` 1027 | web/app/AccountMenu.tsx:137 |
| `layer.water-temp-contours.basis` 1062 | web/map/layers.ts:238 (dynamic selector; individual route UNVERIFIED) |
| `layer.sst-contrast.basis` 1064 | web/map/layers.ts:238 (dynamic selector; individual route UNVERIFIED) |
| `layer.sst-contrast.legend0` 1065 | web/map/layers.ts:238 (dynamic selector; individual route UNVERIFIED) |
| `layer.wind.basis` 1075 | web/map/layers.ts:238 (dynamic selector; individual route UNVERIFIED) |
| `layer.wind.legend0` 1076 | web/map/layers.ts:238 (dynamic selector; individual route UNVERIFIED) |
| `layer.depth-contours.basis` 1078 | web/map/depth-contours.ts:341, web/map/legend-model.ts:177 |
| `layer.depth-contours.legend0` 1079 | web/map/legend-model.ts:178 |
| `layer.depth-contours.v2.basis` 1081 | web/map/legend-model.ts:182 |
| `layer.depth-contours.v2.legend0` 1082 | web/map/legend-model.ts:183 |
| `layer.depth-contours.v3.basis` 1084 | web/map/legend-model.ts:187 |
| `layer.depth-contours.v3.legend0` 1085 | web/map/legend-model.ts:188 |
| `layer.seafloor.basis` 1100 | web/map/layers.ts:238 (dynamic selector; individual route UNVERIFIED) |
| `layer.commercial-ais.basis` 1108 | web/map/commercial-ais.ts:108 |
| `layer.currents.basis` 1120 | web/map/layers.ts:238 (dynamic selector; individual route UNVERIFIED) |
| `rail.terrain.waterHint` 1168 | web/app/LayerRail.tsx:167 |
| `legend.perNm` 1205 | web/app/Legend.tsx:223 |
| `legend.windRow` 1207 | web/app/Legend.tsx:247 |
| `legend.relief.depth` 1221 | web/app/Legend.tsx:441 |
| `legend.relief.band` 1222 | web/app/Legend.tsx:446 |
| `legend.relief.hardEdge` 1227 | web/map/legend-model.ts:109 |
| `legend.relief.resolution` 1228 | web/map/legend-model.ts:112 |
| `legend.surveyDetail.estimateGrid` 1231 | web/map/bottom-relief.ts:217 |
| `legend.surveyDetail.chip.1m-measured` 1232 | web/map/legend-model.ts:158; web/map/bottom-relief.ts:218 |
| `legend.surveyDetail.chip.2m` 1233 | web/map/legend-model.ts:158; web/map/bottom-relief.ts:218 |
| `legend.surveyDetail.chip.5m` 1234 | web/map/legend-model.ts:158; web/map/bottom-relief.ts:218 |
| `legend.surveyDetail.chip.4-16m-compiled` 1235 | web/map/legend-model.ts:158; web/map/bottom-relief.ts:218 |
| `legend.planningRoute.detail` 1264 | web/app/Legend.tsx:352 |
| `planner.leg.total` 1321 | web/app/Planner.tsx:255 |
| `planner.forecast.wind` 1361 | web/trip-forecast.ts:62 |
| `planner.forecast.gusts` 1362 | web/trip-forecast.ts:62 |
| `planner.forecast.seas` 1363 | web/trip-forecast.ts:63 |
| `planner.forecast.overWind` 1366 | web/trip-forecast.ts:48 |
| `planner.forecast.overGust` 1367 | web/trip-forecast.ts:49 |
| `planner.forecast.overSeas` 1368 | web/trip-forecast.ts:50 |
| `planner.maxDepth` 1383 | web/app/Planner.tsx:275 |
| `planner.maxDistance` 1389 | web/app/Planner.tsx:280 |
| `planner.how.fit` 1394 | web/app/Planner.tsx:287 |
| `planner.hit.near` 1422 | web/planner-copy.ts:72 |
| `planner.hit.reefNear` 1423 | web/planner-copy.ts:72 |
| `planner.alert.limits` 1434 | web/app/Planner.tsx:117 |
| `planner.route.note` 1470 | web/app/Planner.tsx:368 |
| `pm.verdict.near` 1508 | web/planner-copy.ts:66 |
| `pm.verdict.nearFallback` 1509 | web/planner-copy.ts:66 |
| `pm.depthDistance` 1541 | UNVERIFIED (no exact literal caller found) |
| `pm.contourWhy.multiple` 1569 | UNVERIFIED (no exact literal caller found) |
| `pm.outlineNamed` 1577 | UNVERIFIED (no exact literal caller found) |
| `pm.alignmentNamed` 1578 | UNVERIFIED (no exact literal caller found) |
| `pm.al.limitsRef` 1608 | UNVERIFIED (no exact literal caller found) |
| `disagree.wind.today` 1778 | web/model-disagreement.ts:68 |
| `disagree.wind.tomorrow` 1779 | web/model-disagreement.ts:68 |
| `disagree.wind.weekday` 1780 | web/model-disagreement.ts:68 |
| `disagree.seas.today` 1781 | web/model-disagreement.ts:68 |
| `disagree.seas.tomorrow` 1782 | web/model-disagreement.ts:68 |
| `disagree.seas.weekday` 1783 | web/model-disagreement.ts:68 |
| `history.age.min` 1894 | web/view-copy.ts:49 |
| `mark.save.margin` 1933 | web/saved-spots.ts:23 |
| `mark.copy.reason.margin` 1948 | web/app/MarkCard.tsx:177 |
| `mark.layer.seafloor.cell.name` 1962 | web/map/seafloor.ts:285 |
| `mark.layer.seafloor.depth.band` 1965 | web/map/seafloor.ts:266 |
| `mark.layer.seafloor.depth.range` 1966 | web/map/seafloor.ts:266 |
| `mark.layer.seafloor.basis.interpreted` 1975 | web/map/seafloor.ts:122 |
| `mark.layer.seafloor.basis.cell` 1976 | web/map/seafloor.ts:98 |
| `mark.layer.habitat.rules.screened` 2014 | web/map/habitat.ts:278 |
| `mark.layer.habitat.rules.mpaSubtracted` 2015 | web/map/habitat.ts:320 |
| `mark.layer.habitat.within` 2024 | web/map/habitat.ts:200 |
| `mark.layer.contour.name` 2036 | web/map/depth-contours.ts:378 |
| `mark.layer.contour.index` 2037 | web/map/depth-contours.ts:378 |
| `mark.layer.contour.minor` 2038 | web/map/depth-contours.ts:378 |
| `mark.layer.contour.reading.conflict` 2042 | web/map/depth-contours.ts:350 |
| `mark.layer.contour.reading.base` 2046 | web/map/depth-contours.ts:372 |
| `mark.layer.grounds.reading` 2056 | web/map/charter-grounds.ts:199 |
| `mark.layer.ais.basis` 2075 | web/map/commercial-ais.ts:108 |
| `mark.layer.fronts.reading` 2082 | web/map/fronts.ts:187 |
| `map.station.tide.reading` 2258 | web/map/station-model.ts:139 |
| `map.nearshore.basis` 2273 | web/map/nearshore.ts:97, web/map/nearshore.ts:131 |
| `map.nearshore.depth` 2275 | web/map/nearshore.ts:132 |
| `map.nearshore.summary` 2283 | web/map/nearshore.ts:106 |
| `alerts.wind` 2329 | web/app/TripAlerts.tsx:461 |
| `alerts.gust` 2330 | web/app/TripAlerts.tsx:462 |
| `alerts.sea` 2331 | web/app/TripAlerts.tsx:463 |
| `alerts.noteReference` 2339 | web/app/TripAlerts.tsx:474 |
| `alerts.plan.totals` 2424 | web/app/TripAlerts.tsx:123 |
| `reportCatch.age.min` 2551 | web/reports-copy.ts:62 |
| `account.position.filled` 2653 | dist/account.js:447 |
| `account.spots.margin` 2680 | dist/account.js:659 |
| `savedSpots.card.near` 2760 | web/app/TripAlerts.tsx:115, web/map/saved-spots.ts:185 |
| `mark.layer.coastline.accuracy` 2812 | web/map/coastline.ts:125 |
| `trip.pos.onBoundary` 2845 | web/app/PositionView.tsx:62 |

## 2. Proposed template changes and number rules (C2)

These are exact edits to the two texts in the Section 1 catalogue rows: replace only the token or phrase shown in the table, in place. All other bytes (including leading spaces, periods, accents and separator glyphs) stay as in `catalog/app/strings.json`. Keep each ID. `web/i18n-core.ts:28–29` interpolates named arguments and leaves unspecified placeholders visible, so update every caller in the same batch, even callers that deliberately keep passing a fixed unit.

| ID(s) | English and Spanish template edits; arguments at default |
| --- | --- |
| `brief.models.agree`, `brief.models.differ`, `brief.models.readings` | Both: every `kn` → `{windUnit}`, every `ft` → `{heightUnit}`. Defaults `kn`, `ft` in both languages. |
| `verdict.longPeriod`, `entrance.swell`, `entrance.swell.period` | Both: `ft` → `{unit}`, default `ft`. Leave `s`, the period, and time alone. |
| `hourly.over.wind`, `hourly.over.gust` | Both: `kt` → `{unit}`, default `kt`. |
| `hourly.over.seas` | Both: `ft` → `{unit}`, default `ft`. |
| `tile.basis.tide`, `landing.basis.tide` | EN `feet` → `{unit}`, ES `pies` → `{unit}`; default `feet`/`pies`, alternate `metres`/`metros`. Retain the actual reference level and source note. |
| `where.distance.water`, `where.distance.straight`, `run.distance.straightWhy` | Both: `{nm} nm` → `{distance} {unit}`, with the old formatted number and `nm` by default. `nmi` can name the stored chooser option; do not silently respell the displayed default. Keep the straight-line explanation. |
| `limits.unit.reach` | Both: `nm` → `{unit}`; default `nm`, retain `, one way` / `, solo ida`. `limits.unit.kt`, `.ft`, `.nm`, `.yd` are literal label entries, not sentences: the equivalent placeholder is the existing `unit` field from the selected label (`web/app/LimitsPanel.tsx:39–42`). Reuse the existing wind/height labels (196–202), keep depth and swim fixed. |
| `portAlert.wind`, `portAlert.hit.wind` | Both: each `kt` → `{unit}`, default `kt`. |
| `portAlert.swell`, `portAlert.hit.swell` | EN each `ft` → `{unit}`; ES each `pies` → `{unit}`. Defaults `ft`/`pies`; alternate `m`/`metros`. |
| `portAlert.invalid` | EN `1 to 60 kt` → `{windMin} to {windMax} {windUnit}` and `0.5 to 30 ft` → `{swellMin} to {swellMax} {swellUnit}`. ES `1 a 60 kt` → `{windMin} a {windMax} {windUnit}` and `0,5 a 30 pies` → `{swellMin} a {swellMax} {swellUnit}`. Defaults are the replaced substrings after filling; the bounds come from `web/port-alert.ts:17–18`. |
| `markForecast.gusts` | Both: `kt` → `{unit}`, default `kt`. Keep the initial ` · `; also make the sustained speed on the same line use the same unit (it is built in code, not catalogue copy: `web/brief/mark-forecast.ts:207`). |

**Number rules by caller.** Use the shared exact factors (`web/units.ts:3–10`): knots × 1, `1852 / 1000` or `1852 / 1609.344` for `kt`, `km/h` or `mph`; feet × `0.3048` for metres; nautical miles × `1852 / 1000` or `1852 / 1609.344` for km or statute miles. Convert before rounding; do not introduce a temperature conversion in this batch. Keep the default formatter of each caller, not a single new formatter for all rows (`web/i18n-core.ts:65`; `web/brief/Tiles.tsx:53–60`; `web/hourly-table.ts:65–78`).

- **Agreement and long-period reason:** On alternate units, use whole wind numbers and one decimal for height, as on the tiles. For `agree`, convert the *gap*, not the readings, and round the bound up to the displayed precision. For a `differ` line, use that hour's unrounded per-quantity gap: where it exceeds its own stored threshold and rounding would hide the difference, increase precision for that quantity and its paired readings until they show the gap. Equal stays equal; a sub-threshold gap uses normal rounding. Do not recompute agreement from rounded values (`web/brief/agreement.ts:21–30`; `web/score.ts:21`; `web/brief/Brief.tsx:805–807,822`; `modes/NEXT-BACKLOG-2026-11-18-skippercast-2022-r2.tsv:11`). For long-period height convert the raw feet then round *up* to a tenth of a metre (`up1`, `web/brief/verdict-copy.ts:17`). The checked head uses `r1` in the default long-period branch (:131), so the follow-on must take its feet-byte baseline after **the verdict's honest rounding** prerequisite, not quietly change the default along with the unit label. Whether that prerequisite is ready is **UNVERIFIED**.
- **Entrance and tide:** Swell uses the old `num(feet, lang, 1)` in feet and the metric tile rule (one decimal, comma in ES) in metres, with no change to swell availability, period rounding or offshore `kn` (`web/brief/entrance-current.ts:88–114`; `web/brief/Tiles.tsx:53–60`). Both tide bases reuse the unit of the reading; where no reading has a unit, preserve the existing source wording. Landing already converts the reading but does not change the basis; do not convert it again (`web/landing/readings.ts:57,160–170`; `web/brief/Tiles.tsx:58–80`). Do not change the source request or tide-trend threshold (`web/landing/readings.ts:155–166`).
- **Hourly:** For changed units, round wind/gust to zero decimals and seas to one as the cells do; localize that number like the cells. Keep `String(limits[f])` for each default dimension to meet the byte requirement. This intentionally leaves the Spanish default fractional limit with the old decimal point: the row's general request for Spanish formatting and byte-identical defaults cannot both apply to that same output. Recommend keeping the byte constraint and treating a future default punctuation change as separate. Equality still does not mark a cell; do not compare rounded limits (`web/app/views/HourlyTable.tsx:21–25,54–58`; `web/hourly-table.ts:65–84`; operator-local backlog `modes/NEXT-BACKLOG-2026-11-18-skippercast-2022-r2.tsv:13`).
- **Run and Where to look:** Apply the distance factor only to the display of a distance, then `toFixed(1)` with the existing surface's Spanish treatment. Keep route basis, minutes, rank, GPX, and stored nautical miles unchanged. `markDistanceLine` also fills the two `where.distance` IDs: pass `unit: 'nm'` and its current formatted number until/unless that card's display is separately approved. Keep path margins and distinct swim distances as they are (`web/brief/Run.tsx:109–116,137–140`; `web/brief/WhereToLook.tsx:102–105,172–177,334`; `web/mark-distance.ts:47–51`; `web/ranking.ts:435–441`).
- **Comfort limits and home-port inputs:** For an edited wind/height/reach field divide by the same selected factor once, then compare with existing bounds in stored units. For an untouched field keep its original number, rather than parsing rounded input text back. Convert displayed bounds/hints with their fields; use sufficiently precise numeric controls, not whole-number/tenth-rounded comparisons. Recommend showing up to three fractional digits for non-default form hints and keeping exact converted endpoints internally (snap a displayed bound explicitly to the original bound, never broaden the comparison). When switching units during an edit, preserve/reproject the draft or finish the edit in the old units; do not relabel an old numeric draft in place. Keep default formatting/steps and validators unchanged. For port hits use the current `num` precision in defaults and one decimal after conversion in alternate units; pair each hit with its limit in the same unit and leave the original alert time and inclusive comparisons untouched (`web/app/LimitsPanel.tsx:46–77,84–121`; `web/app/PortAlert.tsx:32–55`; `web/port-alert.ts:17–18,43–62,93–108`). Precise form-control behaviour is **UNVERIFIED** until tested.
- **Mark gust:** Use `Math.round(raw × factor)` for both sustained wind and displayed gust; leave missing and below-sustained omission rules and the numeric readings unchanged. Pass the screen's choice into the display path with a default for other callers; do not change the planner or private log by making the pure sampler read a global choice. Currents and seas are not part of this gust change (`web/brief/MarkForecast.tsx:33`; `web/brief/mark-forecast.ts:200–214,281`; `web/trip-forecast.ts:80`; `web/private-map-log.ts:25`).

For the other inventory entries below the batch boundary: retain the catalogue's existing text and caller formatting (identity conversion, no new rounding) unless a later owner admits that surface. If later parameterized without changing policy, use a fixed `{unit}` per existing spelling and language, with separate placeholders for distinct units/words (e.g. `°F` and `nautical mile`, `ft` and `m`, or `foot` and `ft`). This is not a global search/replace; native grid sizes, map margins, source and reference units, and the dual-unit legend would otherwise describe a different quantity (`catalog/app/strings.json:1062–1085,1222,2273`; `web/map/fronts.ts:187`; `web/map/habitat.ts:200`). Likewise, a future heading fix would replace only `kt`/`ft` with `{unit}` while retaining the direction and seconds wording, and would check print headings separately (`web/app/views/HourlyTable.tsx:20,47–58`). Default **rendered** byte equality is a future acceptance check, **UNVERIFIED** here; the table defines how to get the same strings without retranslation.

## 3. Build in short units, ship the catalogue together (C3)

The times below are **UNVERIFIED** planning estimates, not measurements. File ownership is proposed for a future build, not approval to edit a reserved file. The six entries remain separate approved rows (operator-local `modes/NEXT-BACKLOG-2026-11-18-skippercast-2022-r2.tsv:11–14`; `modes/NEXT-BACKLOG-2026-11-17-skippercast-1152-r2.tsv:10,15`). Prepare the surface changes as short patches on one integration branch. One shared owner updates each namespace once and pairs it with all its callers before review; don't deliver a catalogue with unresolved placeholders (`web/i18n-core.ts:28–29`).

| Unit and estimate | Proposed owned files | Focused offline acceptance (future; not run) |
| --- | --- | --- |
| SC2022-07 Agreement and long-period reason, 105 min; after the verdict's honest rounding | `web/brief/Brief.tsx`, `web/brief/verdict-copy.ts`, `tests/test_brief_agreement.mjs`, `tests/test_brief_long_period.mjs` | Both mixed cases (equal wind/different seas and reverse), upward agree bound, threshold equality, unchanged held state, alternate units, both default languages. |
| SC2022-08 Entrance swell, 55 min | `web/brief/entrance-current.ts`, `web/brief/EntranceCurrent.tsx`, `tests/test_entrance_current.mjs` | Metres with/without period, stale/missing, unchanged band and offshore text, both defaults. |
| SC2022-09 Hourly marker, 50 min | `web/app/views/HourlyTable.tsx`, `web/hourly-table.ts` if sharing the formatter, `tests/test_hourly_table.mjs` | Assert the rendered accessible name for mph, km/h, m and Spanish fractional values; prove the same rows are marked, equality not marked, both default bytes. |
| SC2022-10 Tide bases, 45 min; use landing's existing converted reading | `web/brief/Tiles.tsx`, `web/landing/readings.ts`, `tests/test_brief_tiles.mjs`, `tests/test_landing.mjs` | Feet and metres, English and Spanish, station and datum preserved, missing and stale inputs. |
| SC1152-06 Distance choice, 55 min | `web/unit-choice.ts`, `web/units.ts`, `web/app/UnitChoice.tsx`, `tests/test_unit_choice.mjs` | Old and missing storage default to nautical miles, invalid preferences rejected, exact factors and switching back; no profile/account write. |
| SC1152-06 Distance displays, 60 min; after distance choice | `web/brief/Run.tsx`, `web/brief/WhereToLook.tsx`, `web/mark-distance.ts`, `tests/test_run.mjs` | By-water vs straight/pending vs straight/failed, both languages, exact 1-decimal output, unchanged run minutes and original mark copy. |
| SC1152-11 Comfort form, 110 min; after distance choice | `web/app/LimitsPanel.tsx`, `tests/test_limits.mjs` | Save untouched fractional values exactly, edit in km/h/metres/miles, exact bounds and just outside, switch during edit, depth/swim and old payload unchanged. |
| Home-port alert fields and lines, 100 min | `web/app/PortAlert.tsx`, `tests/test_port_alert.mjs` | No-edit storage equality; edited metric thresholds including both bound edges; wind/swell hit name and time; both default languages; alert equal-to-threshold and stale behaviour unchanged. |
| Mark forecast wind and gust, 55 min | `web/brief/MarkForecast.tsx`, `web/brief/mark-forecast.ts`, `tests/test_mark_forecast.mjs` | Paired units, default bilingual bytes, below-sustained and missing gust, same sampled numbers for planner/log. |
| Catalogue integration, 75 min; shared across the listed rows | `catalog/app/strings.json` and changed outputs from `scripts/build_landing_strings.mjs:11,32–40`; `tests/test_i18n_catalogue_loading.mjs` for any focused projection check | Run `node scripts/build_landing_strings.mjs`, then `node scripts/build_landing_strings.mjs --check`; don't hand-edit generated JSON. Review all changed IDs in EN and ES, load ES before the localized fixtures, check missing placeholders and unchanged defaults, including the landing projection. Run the listed focused tests and `pnpm typecheck`. |

Generator outputs named at `scripts/build_landing_strings.mjs:11`: `web/strings.en.generated.json`, `web/strings.es.generated.json`, `web/landing/strings.generated.json`, `dist/status-strings.generated.json`. Keep only actual generator changes under the future shared reservation; a status projection with no changed IDs should stay byte-identical. Reservation availability and integration results are **UNVERIFIED**.

## 4. Recheck the source evidence (C4)

Run from the checkout, on the source head named above or its report-only child:

```sh
git rev-parse origin/main
git grep -nE 'entrance\.swell|hourly\.over|portAlert\.(wind|swell|invalid|hit)|markForecast\.gusts|where\.distance\.water|run\.distance\.|brief\.models\.|landing\.basis\.tide' -- web ':!*.generated.*'
git grep -n 'tile.basis' -- web/brief/Tiles.tsx
git grep -nE 'WIND_SPEED|M_PER_FT|M_PER_NMI' -- web/units.ts
git grep -n 'export const OUTPUTS' -- scripts/build_landing_strings.mjs
git grep -niEc '"en".*\b(kt|kn|feet|ft|nmi|nm|km|nudos?|pies)\b|°[FC]' -- catalog/app/strings.json
```

The last command prints `catalog/app/strings.json:134`. It is a spot check, not the size of the full inventory: that inventory also considers metres, yards, miles, word forms in both languages, and other spellings while excluding placeholder names and time abbreviations.

Expected anchors: main `7335068efd2627dd2a0ba9bea39f09e86a8f252d`; entrance swell 101–102, hourly marker 58, port alert 48–55, mark gust 207, run distance 111/113, agreement 806–807/822 and landing basis 170 (paths in Section 1); brief tile basis 68; conversion inputs in `web/units.ts:3–9`; four output paths at generator line 11. These are source checks, not browser measurements. The historical [catalogue](https://raw.githubusercontent.com/Grahammmm/skippercast/9163c89f/catalog/app/strings.json), [unit choice](https://raw.githubusercontent.com/Grahammmm/skippercast/9163c89f/web/unit-choice.ts) and [landing reading](https://raw.githubusercontent.com/Grahammmm/skippercast/9163c89f/web/landing/readings.ts) compared equal with `diff -u` (exit 0, no output) against the checked source files.
