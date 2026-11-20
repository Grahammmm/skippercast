# Spanish caveat glossary

This is contributor guidance for the people and agents who write the app's
Spanish. It is not legal text, not a safety clearance, not a claim that the app
is fully covered in Spanish, and not a translation engine: the Spanish is
written by hand, never generated at run time. It gives one neutral Latin
American rendering to the caveats that recur across the app, so builders who
add Spanish in separate pull requests do not pick different words for the same
caveat.

Checked against builder base `main` at `def43f14d0335f37df6a5787ef7ac0560bd67f1b`, with
the catalogue as last changed by `af453d0c2b2b7f0ea128f0f429d1ef1050c5ad12`
(2,651 entries; SC1352-08 landed in #1739). The catalogue is
[`catalog/app/strings.json`](../catalog/app/strings.json) and
[`web/i18n.ts`](../web/i18n.ts) reads it and formats numbers (decimal comma, no
digit grouping). The evidence the caveats protect is described in
[Evidence limits](web-app.md#evidence-limits).

This page has three sections:

1. **Canonical terms and the catalogue IDs that use them**: the one preferred
   Spanish rendering of each recurring term, with every catalogue ID that
   renders it today.
2. **Observed divergences**: every catalogue Spanish value that renders a
   listed term differently, with its ID and its current value verbatim. They
   are documented, not changed here.
3. **Review rules** for new Spanish copy.

The catalogue holds no entry for several terms yet. Where a table says
`Not in the catalogue at the checked revision`, no ID uses the term; a future
builder adds the ID and lists it here. Never put a source filename or a guessed
ID in the ID column.

## 1. Canonical terms and catalogue IDs

Capitalized labels keep their case; a sentence fragment may take ordinary
grammatical case. Spanish on the right is the preferred rendering for new
app-written copy.

### Verdict words and caveats

| English term / context | Canonical Spanish | Catalogue IDs at the checked revision |
| --- | --- | --- |
| Comfortable (verdict label) | `Cómodo` | `brief.verdict.comfortable`, `brief.basis.comfort`, `brief.basis.profile` |
| Marginal (verdict label) | `Marginal` | `fa.marginal`, `brief.verdict.marginal`, `brief.basis.comfort`, `verdict.held` (first-answer debt resolved in #1617; see section 2) |
| Rough (verdict label; "too rough" in the first answer) | `Agitado` | `fa.no`, `brief.verdict.rough`, `brief.basis.comfort`, `brief.basis.profile`, `verdict.band.rough`, `alerts.comfort.rating` (also severity/comfort-scale uses, not new verdicts) |
| Unknown (verdict label; never Comfortable) | `Desconocido` | `rules.fresh.unknown`, `brief.verdict.unknown`, `brief.skill.unknown`, `brief.skill.unreadable`, `verdict.noProfileWindow`, `verdict.missingProfile`, `verdict.band.unknown`, `verdict.band.unknownFeminine`, `verdict.reason.clarityUnknown`, `verdict.reason.surfUnknown`, `verdict.reason.windUnknown`, `verdict.reason.seasUnknown`, `verdict.reason.swellUnknown`, `tile.detail.unknownGust`, `tile.detail.bar.unknown`, `run.bar`, `entrance.caution.noSwell`, `entrance.caution.staleSwell`, `entrance.basis`, `dev.unknownLayer`, `planner.how.index`, `planner.fit.0`, `pm.noTarget`, `history.unknown`, `mark.layer.unknown`, `mark.layer.unknownF`, `mark.layer.unknownSize`, `mark.layer.seafloor.kind.fitUnknown`, `mark.layer.seafloor.depth.unknown`, `mark.layer.seafloor.basis.interpreted`, `mark.layer.grounds.basis`, `mark.layer.ais.basis`, `mark.layer.ais.status.summary`, `reports.charters.caveat`, `mark.layer.shore.review.unknown`, `mark.layer.shore.review.dateUnknown`, `trip.legal.stale`, `trip.legal.unknown`, `trip.pos.unknownDate` (includes unknown dates, evidence and measurements; grammatical variants below) |
| Source (the disclosure on each brief tile; was "basis") | `Fuente` | `tile.basis.source`, `a11y.basis.verdict`, `a11y.basis.wind`, `a11y.basis.swell`, `a11y.basis.water`, `a11y.basis.tide`, `shared.popover.basis`; run disclosure `run.basis`, `a11y.basis.run` is `Cómo se calcula` |
| MLLW (tide reference level) | `MLLW`, glossed `bajamar media inferior, el cero de la carta` | `tile.basis.referenceMllw`, `layer.depth-contours.basis`; `tile.basis.reference` preserves other supplied datums |
| Halibut (the layer preset; California halibut) | `Lenguado` | `preset.halibut` |
| not checked | `no revisado` | `brief.gaps.unchecked`, `where.screen.unchecked`, `run.route.unchecked`, `planner.alert.notChecked`, `pm.verdict.unchecked`, `pm.al.screen`, `mark.save.notChecked`, `mark.copy.reason.notChecked`, `account.spots.unchecked`, `trip.pos.noBoundaries`, `trip.pos.notCovered`, `trip.pos.denied`, `trip.pos.unavailable`, `trip.pos.unsupported` |
| inside (protected area) | `dentro de un área protegida` | `where.screen.inside`, `planner.hit.inside`, `planner.hit.near`, `planner.hit.reefNear`, `planner.notExported`, `pm.verdict.inside`, `pm.verdict.insideFallback`, `pm.outlineNamed`, `pm.alignmentNamed`, `pm.al.screen`, `mark.save.inside`, `mark.copy.reason.inside`, `mark.layer.habitat.withheld.basis`, `mark.layer.habitat.inside`, `mark.layer.habitat.within`, `account.spots.fine`, `account.spots.inside`, `account.spots.margin`, `account.exp.allHeld`, `mark.layer.shore.reason.inside`, `trip.pos.inside`, `trip.pos.insideUnnamed` (named areas, boundaries and closed areas use contextual `dentro de`) |
| within 70 m (of a protected area) | `a 70 m o menos de un área protegida` | `run.route.near`, `planner.hit.near`, `planner.hit.reefNear`, `pm.outlineNamed`, `pm.alignmentNamed`, `mark.save.margin`, `mark.copy.reason.margin`, `mark.layer.habitat.within`, `account.spots.margin`, `savedSpots.card.near`, `trip.pos.margin`; literal 70 m: `mark.save.margin`, `mark.copy.reason.margin`, `account.spots.margin`, `savedSpots.card.near`; the other entries are parameterized contexts described below |
| not a legal boundary | `no es una delimitación legal` | Not in the catalogue at the checked revision |
| not a catch prediction | `no es una predicción de capturas` | Not in the catalogue at the checked revision. The bite-forecast caveat is a different one, see below |
| planning outline | `contorno de planificación` | Not in the catalogue at the checked revision. `brief.planning` ("Planning aid · not a navigation chart") is a planning aid, not an outline: `Ayuda de planificación · no es una carta náutica` |
| out at sea: not a harbor or launch reading | `mar adentro: no es una lectura del puerto ni del punto de salida al agua` | `landing.basis.wind` |
| straight line | `en línea recta` | `where.distance.straight`, `where.range.routed`, `where.range.straight`, `ranking.basis.publication`, `ranking.basis.terrain`, `ranking.basis.atlas`, `ranking.basis.swum`, `run.distance.straightWhy`, `run.basis.text`, `limits.reach.hint`, `layer.reach.basis`, `layer.reach.legend0`, `planner.leg.straight`, `planner.leg.straightCaveat`, `planner.distanceNote`, `planner.dist.straight`, `planner.route.note` |
| by water | `por agua` | `where.distance.water`, `where.range.routed`, `run.basis.text`, `planner.distanceNote`, `planner.dist.water` |
| Blank (no catch), private device log | `Sin captura (no se registró ninguna captura)`; never `desconocido` or zero fish | `privateMapLog.kind.blank`, `privateMapLog.logBlank`, `privateMapLog.explain` |
| Private device log (device-only, not the account catch log) | `Registro privado del dispositivo` | `privateMapLog.title`, `privateMapLog.count`, `privateMapLog.countUnavailable`, `privateMapLog.readFailed` |
| NOT FOR NAVIGATION (device-log caveat) | `NO USAR PARA NAVEGACIÓN.` | `privateMapLog.privacy` |
| model snapshot, not an on-water observation | `instantáneas del modelo … no observaciones en el agua` | `privateMapLog.evidence`; stored snapshots stay English (`privateMapLog.snapshotEnglish`), and `privateMapLog.snapshot.*` are rendered only in English inside `lang="en"` |

Related caveats that are distinct and already present, not divergences:

- `brief.basis.comfort` and `brief.basis.profile` carry the bite-forecast and
  safety caveat as `no es un pronóstico de picadas ni una autorización de
  seguridad`. It is not the catch-prediction caveat above; keep both.
- `rules.depth.inside` ("Inside 50-fm line") is a depth-line phrase, not the
  protected-area `inside`.
- `verdict.band.rough` ("Rough", `agitado`) is the severity word for seas and
  chop, not a verdict label. It uses the same adjective as the verdict.
- The "roughest hour" in `brief.basis.profile` (`La hora más dura`) names an
  hour, not a verdict label.

### Thin evidence and alert-check holds

"Thin evidence" has no catalogue ID of its own and no invented verdict: the
umbrella rendering is `evidencia insuficiente`, and each hold below is its own
complete sentence. A missing check and an unavailable check are different
sentences; do not rewrite either into reassurance.

| English term / context | Canonical Spanish | Catalogue IDs at the checked revision |
| --- | --- | --- |
| thin evidence (umbrella) | `evidencia insuficiente` | No literal umbrella ID; the holds below are the actual sentences |
| Held at Marginal | `Se mantiene en Marginal: {reasons}.` | `verdict.held` |
| forecast detail is partial | `el detalle del pronóstico es parcial` | `verdict.partial` |
| {missing} of {total} hours have no forecast | `{missing} de {total} horas no tienen pronóstico` | `verdict.missingForecast` |
| {missing} of {total} hours are unknown | `se desconocen {missing} de {total} horas` | `verdict.missingProfile` |
| the forecast run is {hours} h old | `la corrida del pronóstico tiene {hours} h de antigüedad` | `verdict.stale` |
| the marine alert check is unavailable | `la revisión de avisos marinos no está disponible` | `verdict.alertMissing`, `run.window.alertCheck`, `layer.shore-runs.basis` (embedded hold; divergence below) |
| No current marine alert check. | `No hay una revisión actual de avisos marinos.` | `verdict.noAlertCheck` |

Contextual evidence holds that read the same way and stay as written:

- `brief.gap.daily.alerts` and `brief.gap.daily.both`: `faltan las revisiones
  de avisos marinos` (checks are missing because the daily feed could not be
  read). `brief.gap.both` says no marine alert readings are available.
- `brief.basis.comfort`: an estimate missing wave detail or the second model is
  capped at 6.9 (`6,9` in Spanish). This is an evidence hold inside a longer
  sentence, not a literal translation of the umbrella term.
- `brief.details.gaps` (`Faltantes o desactualizadas: {n}`) and
  `brief.gaps.label` (`Lecturas faltantes`) count missing or stale readings;
  they are not the run-age sentence `verdict.stale`. Missing and stale are
  different holds.
- `verdict.bar` and `verdict.longPeriod` are hazard reasons that can appear in
  a hold; they are not listed terms and are untouched here.

### Units

Units are explicit exceptions to "one prose rendering": the unit token is kept
as supplied. Nothing here is a conversion instruction; numbers, placeholders,
source units and rounding are preserved.

| Unit | Token | Prose | Catalogue IDs at the checked revision |
| --- | --- | --- | --- |
| feet | `ft` | `pies` | `brief.boat.reference`, `brief.boat.yours`, `brief.boat.note`, `brief.models.agree`, `brief.models.differ`, `brief.models.readings`, `verdict.seas`, `verdict.chop`, `verdict.steepChop`, `verdict.cross`, `verdict.calm`, `verdict.longPeriod`, `verdict.reason.detail`, `tile.basis.tide`, `where.dive.depth`, `ranking.within`, `entrance.swell`, `entrance.swell.period`, `landing.profile.note.boat`, `landing.profile.note.spear`, `landing.profile.note.kayak`, `landing.basis.tide`, `landing.boat.reference`, `boatEntry.length`, `boatEntry.lengthHint`, `boatEntry.seas`, `boatEntry.seasSaved`, `limits.unit.ft`, `accountMenu.ratingsReference`, `layer.depth-contours.basis`, `layer.depth-contours.legend0`, `layer.seafloor.basis`, `planner.forecast.seas`, `planner.forecast.overSeas`, `planner.maxDepth`, `planner.alert.limits`, `planner.layer.contours.text`, `pm.depthDistance`, `pm.contourWhy.multiple`, `pm.al.limitsRef`, `portAlert.swell`, `portAlert.invalid`, `portAlert.hit.swell`, `disagree.seas.today`, `disagree.seas.tomorrow`, `disagree.seas.weekday`, `hourly.h.seas`, `hourly.h.swell`, `hourly.h.second`, `hourly.h.chop`, `hourly.over.seas`, `history.chartTitle`, `history.ref.detail`, `history.recentAria`, `history.seasonAria`, `chart.series`, `mark.layer.seafloor.depth.band`, `mark.layer.seafloor.depth.range`, `mark.layer.seafloor.basis.interpreted`, `mark.layer.contour.name`, `mark.layer.contour.index`, `mark.layer.contour.minor`, `mark.layer.contour.reading.conflict`, `mark.layer.contour.reading.base`, `mark.layer.grounds.reading`, `mark.layer.ais.basis`, `map.station.obs.reading`, `map.station.tide.reading`, `map.nearshore.basis`, `map.nearshore.summary`, `alerts.sea`, `alerts.noteReference`, `trip.pos.distance`, `trip.pos.margin`, `trip.pos.accuracy`, `trip.pos.distanceScoped` |
| fathoms | `fm` | `brazas` | `rules.depth.inside`, `rules.depth.outside` |
| knots | `kn` or `kt`, as supplied | `nudos` | `brief.models.agree`, `brief.models.differ`, `brief.models.readings`, `verdict.wind`, `verdict.calm`, `verdict.reason.windDetail`, `tile.basis.wind`, `tile.empty.basis.wind`, `tile.detail.gust`, `markForecast.gusts`, `markForecast.towardTrue`, `run.lead.noTime`, `run.detail.eachSpeed`, `entrance.wcofs.out`, `entrance.wcofs.in`, `entrance.wcofs.across`, `entrance.wcofs.weak`, `entrance.wcofs.unjudged`, `boatEntry.wind`, `boatEntry.windSaved`, `limits.unit.kt`, `layer.wind.basis`, `layer.wind.legend0`, `legend.windRow`, `planner.forecast.wind`, `planner.forecast.gusts`, `planner.forecast.overWind`, `planner.forecast.overGust`, `planner.alert.limits`, `portAlert.wind`, `portAlert.invalid`, `portAlert.hit.wind`, `disagree.wind.today`, `disagree.wind.tomorrow`, `disagree.wind.weekday`, `hourly.h.wind`, `hourly.h.gust`, `hourly.over.wind`, `hourly.over.gust`, `history.chartTitle`, `history.ref.detail`, `history.recentAria`, `history.seasonAria`, `chart.series`, `map.station.obs.reading`, `alerts.wind`, `alerts.gust` |
| nautical miles | `nm` | `millas náuticas` | `where.distance.water`, `where.distance.straight`, `ranking.basis.ranged`, `ranking.within.reach`, `run.distance.straightWhy`, `landing.place.from`, `limits.unit.nm`, `limits.unit.reach`, `layer.sst-contrast.basis`, `layer.sst-contrast.legend0`, `legend.perNm`, `legend.planningRoute.detail`, `planner.leg.total`, `planner.maxDistance`, `planner.how.fit`, `alerts.plan.totals`, `trip.pos.distance`, `trip.pos.distanceFar`, `trip.pos.accuracy`, `trip.pos.distanceScoped` |
| metres | `m` | `metros` | `where.screen.near`, `ranking.basis.water`, `ranking.reason.relief`, `ranking.reason.clearance`, `run.route.near`, `run.basis.text`, `layer.wind.basis`, `layer.wind.legend0`, `layer.depth-contours.basis`, `layer.seafloor.basis`, `rail.terrain.waterHint`, `planner.hit.near`, `planner.hit.reefNear`, `planner.route.note`, `pm.verdict.near`, `pm.verdict.nearFallback`, `pm.outlineNamed`, `pm.alignmentNamed`, `mark.save.margin`, `mark.copy.reason.margin`, `mark.layer.seafloor.cell.name`, `mark.layer.seafloor.basis.cellNamed`, `mark.layer.seafloor.basis.cellUnnamed`, `mark.layer.habitat.rules.screened`, `mark.layer.habitat.rules.mpaSubtracted`, `mark.layer.habitat.within`, `mark.layer.contour.reading.base`, `map.nearshore.depth`, `account.position.filled`, `account.spots.margin`, `savedSpots.card.near`, `mark.layer.coastline.accuracy`, `trip.pos.distance`, `trip.pos.onBoundary`, `trip.pos.margin`, `trip.pos.accuracy`, `trip.pos.distanceScoped` |
| kilometres | `km` | `kilómetros` | `markForecast.gap.noCell`, `markForecast.src.cell`, `markForecast.gridAbout`, `entrance.basis`, `layer.wind.basis`, `layer.commercial-ais.basis`, `layer.currents.basis`, `mark.layer.fronts.reading`, `trip.pos.distance`, `trip.pos.distanceFar`, `trip.pos.accuracy`, `trip.pos.distanceScoped` |
| seconds | `s` | `segundos` | `verdict.period`, `verdict.longPeriod`, `verdict.reason.period`, `entrance.swell.period`, `accountMenu.coordinates.dms`, `planner.forecast.seas`, `planner.snapshot`, `hourly.h.swell`, `hourly.h.chop`, `history.chartTitle`, `history.ref.detail`, `history.recentAria`, `history.seasonAria`, `chart.series`, `map.station.obs.reading` |
| minutes | `min` | `minutos` | `tile.age.minutes`, `tile.basis.tide`, `markForecast.gate.noHour`, `entrance.basis`, `run.basis.text`, `landing.basis.wind`, `landing.basis.tide`, `accountMenu.coordinates.ddm`, `accountMenu.coordinates.dms`, `layer.clouds.basis`, `layer.stations.basis`, `legend.fresh.min5`, `planner.leg.min`, `planner.times.fishMin`, `planner.times.invalid`, `planner.float.err.time`, `planner.times.note`, `pm.al.done`, `trip.ago.min`, `history.age.min`, `mark.layer.fronts.age.lessMinute`, `mark.layer.fronts.age.minute`, `mark.layer.fronts.age.minutes`, `map.status.clouds.underMinute`, `map.status.clouds.minutes`, `map.status.swell.runAhead`, `map.status.swell.retrievalAhead`, `map.status.swell.noNear`, `map.status.wind.noHour`, `map.station.basis`, `map.nearshore.basis`, `alerts.status.saved`, `alerts.plan.totals`, `reportCatch.age.min`, `account.err.rate` |
| hours | `h` | `horas` | `rules.reason.checkOld`, `brief.worst`, `brief.basis.comfort`, `brief.basis.profile`, `brief.models.hours`, `brief.models.partial`, `brief.skill.known`, `brief.skill.unknown`, `brief.skill.unreadable`, `brief.skill.unavailable.range`, `brief.skill.unavailable.invalid`, `verdict.missingForecast`, `verdict.missingProfile`, `verdict.stale`, `tile.age.hours`, `tile.basis.wind`, `tile.basis.staleAfter`, `tile.empty.basis.wind`, `markForecast.basis`, `markForecast.gate.oldRun`, `markForecast.gate.oldRetrieval`, `markForecast.gate.outside`, `markForecast.gate.noHour`, `run.set.hours`, `run.window.incomplete`, `run.entrance.caution`, `entrance.noTide`, `entrance.caution.noSwell`, `entrance.why.wcofsEbb`, `entrance.why.wcofsMissing`, `entrance.why.slackEbb`, `entrance.wcofs.missing`, `entrance.gap.old`, `entrance.basis`, `landing.readout.more`, `landing.basis.rule.limit`, `landing.basis.tide`, `limits.wanted.label`, `limits.wanted.hint`, `limits.note`, `dock.nextHour`, `shell.hour`, `layer.water-temp.basis`, `layer.sst-contrast.basis`, `layer.sst-fronts.basis`, `layer.swell.basis`, `layer.wind.basis`, `layer.commercial-ais.legend0`, `layer.currents.basis`, `layer.stations.basis`, `legend.fresh.limit.currents`, `legend.fresh.gate`, `legend.fresh.stale`, `legend.fresh.cycles`, `planner.times.invalid`, `planner.float.err.time`, `planner.times.firstOccurrence`, `planner.forecast.noHour`, `pm.unchecked`, `trip.ago.hour`, `tripOcean.onlyWater`, `tripOcean.onlyCurrents`, `portAlert.state.alert`, `portAlert.state.clear`, `portAlert.state.partial`, `conditions.now.aria`, `conditions.caption.local`, `conditions.caption.nolocal`, `hourly.caption`, `hourly.aria`, `hourly.limits`, `history.hourStart`, `history.hour.one`, `history.hour.other`, `history.season.caveat`, `history.ref.detail`, `history.caveat.gust`, `history.age.hour`, `mark.layer.habitat.withheld.basis`, `mark.layer.ais.reading`, `mark.layer.fronts.basis`, `mark.layer.fronts.age.hour`, `mark.layer.fronts.age.hours`, `mark.layer.fronts.status.stale`, `map.status.common.underHour`, `map.status.common.hours`, `map.status.common.afterHourNote`, `map.status.sst.stale`, `map.status.sst.afterHour`, `map.status.contrast.stale`, `map.status.contrast.afterHour`, `map.status.chlorophyll.sample`, `map.status.currents.noFresh`, `map.status.currents.noFreshLast`, `map.status.swell.runStale`, `map.status.swell.retrievalStale`, `map.status.swell.noHourNote`, `map.status.swell.outside`, `map.status.swell.outsideEnds`, `map.status.swell.noNearNote`, `map.status.swell.noNear`, `map.status.wind.runStale`, `map.status.wind.retrievalStale`, `map.status.wind.noHour`, `map.status.wind.noSamples`, `map.status.wind.stamp`, `map.station.basis`, `map.nearshore.basis`, `tour.s1.text`, `alerts.from`, `alerts.until`, `alerts.status.comfort`, `alerts.reuse.hours`, `reportCatch.age.hour`, `account.exp.unavailable`, `trip.pos.stale` |
| temperature | `°F` or `°C`, as supplied | not spelled out | `layer.sst-contrast.legend0`, `legend.perNm`, `history.chartTitle`, `history.ref.detail`, `history.recentAria`, `history.seasonAria`, `chart.series`, `mark.layer.fronts.reading`, `map.station.obs.reading` |

`kn` and `kt` are both source-unit spellings; keep the one supplied and do not
normalize one to the other. Do not convert between units.

Snapshot context for the exhaustive rows above:

- Unknown includes `desconocido`, feminine/plural forms, and the verb `se desconocen`; uppercase `DESCONOCIDO` is allowed in the skill disclosure. `account.counts.body` has a count placeholder `{unknown}`, not the English term; `fa.unknown` says “Not known yet”, a different sentence.
- Rough terrain is not Rough seas: `ranking.reason.relief`, `ranking.reason.nearby`, `mark.layer.seafloor.title.search`, `mark.layer.seafloor.kind.search`, `mark.layer.seafloor.basis.search` and `mark.layer.contour.reading.ringRange` describe rugosity; `stage.seafloorRough` means coarse detail. `disagree.wind.today`, `disagree.wind.tomorrow`, `disagree.wind.weekday`, `disagree.seas.today`, `disagree.seas.tomorrow`, `disagree.seas.weekday` say “rougher”, the more adverse model, not a verdict. `alerts.comfort.rating` is a scale endpoint; `verdict.band.rough` is severity. The roughest-hour distinction above still applies.
- `pm.shared` means inside the plotter app, `map.status.wind.noHour` inside the forecast run, and `rules.depth.inside` inside the 50-fm line; none means inside a protected area. `trip.pos.insideUnnamed` refers specifically to a closed area.
- Parameterized near-area contexts: `planner.hit.near`, `planner.hit.reefNear`, `pm.outlineNamed`, `pm.alignmentNamed`, `mark.layer.habitat.within` and `run.route.near` render the planning margin; `trip.pos.margin` renders `70 m (230 ft)` plus position accuracy. They are not literal “within 70 m” catalogue English. `where.screen.near`, `pm.verdict.near` and `pm.verdict.nearFallback` render a measured distance, not a threshold. `run.basis.text` and `planner.route.note` instead say “70 m planning margin”, not inside/within 70 m.
- No English catalogue ID uses “not a legal boundary”, “not a catch prediction” or “planning outline” at this snapshot. `layer.mpas.basis` adds a Spanish legal-delimitation caveat but its English says boundaries are context; `planner.boundary.context` likewise describes context. `ranking.basis.water` says not a navigation boundary. `alerts.purpose` says “do not … predict catches”; the bite forecast in `brief.basis.comfort` and `brief.basis.profile`, the catch-probability rubric in `planner.how.index`, and search windows in `layer.charter-grounds.basis` remain distinct, not missing IDs for those exact terms.
- `markForecast.gate.noIssue`, `markForecast.gate.noRetrieval`, `map.status.swell.runAhead`, `map.status.swell.retrievalAhead` concern age that cannot be checked, not an unperformed area check. `pm.outlineFails` says an outline cannot be checked, not that a check returned clear. Conjugated `no se revisó` and plural `no revisadas` are grammatical forms of `no revisado`; different vocabulary is recorded below.
- The seven hold sentences above retain their IDs and full distinctions. `mark.layer.shore.reason.alertNotCurrent` says the marine alert check is not current (`La revisión de avisos marinos no está actualizada`), not unavailable. `layer.shore-runs.basis` embeds an unavailable-check hold; `run.window.alertCheck` conjugates `no esté disponible`. There is still no literal “thin evidence” umbrella ID.
- Units include duration and clock-hour prose (`hora`/`horas`), singular `pie`, `minuto`, `segundo`, and compound templates. `history.chartTitle`, `history.ref.detail`, `history.recentAria`, `history.seasonAria` carry `{unit}` from the history metric (`ft`, `kt`, `sec`, `°F`); `chart.series` preserves the supplied series unit; `map.station.obs.reading` carries `ft`, `s`, `°F` or `kt`. These are parameterized renderers, not literal unit entries. `mark.layer.habitat.geologyKind` uses a geological map-unit identifier, not a measurement unit.
- `trip.pos.distance`, `trip.pos.distanceScoped` and `trip.pos.accuracy` carry `{distance}`: `m (ft)` below 1 km, `nmi (km)` otherwise. `trip.pos.distanceFar` always supplies 20 km, rendered as `nmi (km)`. `trip.pos.margin` fixes the planning-margin distance to `70 m (230 ft)`. These supplied strings stay unchanged; the nautical-mile spelling `nmi` is context, not an instruction to normalize `nm`.
- `where.range.value` and `where.range.title` contain `{nm}` without a literal unit; `planner.leg.total` carries `{minutes}` composed from `planner.leg.min`. `markForecast.valid`, `markForecast.gap.noWind`, `markForecast.gap.noSeas` and `markForecast.gap.noCell` contain `{hour}` without an hour unit. `mark.layer.ais.reading` changes `hr` to `h` (recorded below). `history.age.min` and `reportCatch.age.min` use `m` for minutes, never metres. `{min}` in limits or zoom bounds means minimum; possessive `’s`, ordinal “second” and plural endings are not seconds. No literal `°C`/`°F` is inferred from generic temperature prose, a credit, a provider name or an arbitrary placeholder.

### Tile detail lines (SC1137-02)

The line under each brief tile reading is said from structured parts by
`web/brief/tile-copy.ts`; the model's English line stays for other readers.
Station, buoy, site and datum names are never translated. Catalogue IDs:
`tile.detail.*`, `tile.clock.*`, `tile.gap.*`, `tide.unavailable`, `tide.noCurve`; the map's station and ring cards use `map.station.*` and `map.nearshore.*`; the map stage's toggle, terrain buttons and terrain reasons use `stage.*` (`Chart` is `Carta`; `Los gráficos costeros no están disponibles. La carta, los pronósticos y las herramientas de viaje siguen funcionando.` and `Aún no hay terreno costero revisado que cubra esta región.` keep every clause), and the private saved-spots row and cards use `savedSpots.*` (`A saved position, not a recommendation. Check current rules before you fish.` is `Una posición guardada, no una recomendación. Revisa el reglamento vigente antes de pescar.`; `No protected-area overlap found in this check.` is `No se encontró superposición con áreas protegidas en esta comprobación.`, a result of this check and never legal clearance), with the protected-area verdict lines still `where.screen.*` (`high event` / `low event` are `evento de pleamar` / `evento de bajamar`).

| English | Spanish | Catalogue ID | Meaning kept |
| --- | --- | --- | --- |
| `no bar flag (estimate)` | `sin señal de alerta en la barra (estimación)` | `tile.detail.bar.clear` | an estimate, not a clearance |
| `bar caution (estimate)` | `precaución en la barra (estimación)` | `tile.detail.bar.caution` | estimate |
| `bar hazardous (estimate)` | `condiciones peligrosas en la barra (estimación)` | `tile.detail.bar.hazardous` | estimate |
| `bar unknown (estimate)` | `estado desconocido de la barra (estimación)` | `tile.detail.bar.unknown` | unknown stays unknown |
| `very low` | `muy baja` | `tile.detail.veryLow` | tide height |
| `ebb` / `flood` / `mid-ebb` | `vaciante` / `creciente` / `mitad de la vaciante` | `tile.detail.ebb`, `.flood`, `.midEbb` | tide stage |
| `Rising` / `Falling` / `Turning` | `Subiendo` / `Bajando` / `Cambiando` | `tile.detail.rising`, `.falling`, `.turning` | trend |
| `next high` / `next low` | `próxima pleamar` / `próxima bajamar` | `tile.detail.nextHigh`, `.nextLow` | |
| rule-of-thumb model, not a sea-keeping calculation | `modelo empírico` ... `no un cálculo de navegabilidad` | `brief.boat.note` | `empírico` is this heuristic, not a validated sea-keeping calculation; `navegabilidad` does not certify seaworthiness |
| Saved regions are unchanged | `Las regiones guardadas no han cambiado` | `tidePack.unavailable`, `tidePack.notLive` | only the two refusals before anything is stored; not a claim about a storage failure |
| Life stage / What to search for / How to fish it / Timing / When conditions change / Caution / Confirm on the day | `Etapa de vida` / `Qué buscar` / `Cómo pescarlo` / `Cuándo pescar` / `Cuando cambian las condiciones` / `Precaución` / `Confirmar ese día` | `where.searchPlan.*` | labels only; the reviewed plan text is not translated |
| surf, seas small / moderate / large / heavy | `pequeño` / `moderado` / `grande` / `muy intenso` | `tile.detail.band.small`, `.moderate`, `.large`, `.heavy` | in `oleaje en la costa {band}` and `oleaje {band}` |
| surge low / moderate / strong / heavy | `leve` / `moderado` / `fuerte` / `muy intenso` | `tile.detail.band.low`, `.moderate`, `.strong`, `.heavy` | in `vaivén del agua {band}` |
| kayak wind light / moderate / fresh / strong | `leve` / `moderado` / `fresco` / `fuerte` | `tile.detail.band.light`, `.moderate`, `.fresh`, `.strong` | |
| onshore / offshore / cross-shore | `hacia la costa` / `hacia mar adentro` / `paralelo a la costa` | `tile.detail.side.*` | |
| `(offshore estimate)` | `(estimación mar adentro)` | `tile.detail.offshoreEstimate` | not an exact launch reading |

### Mark forecast block (SC1137-04)

The mark card's forecast rows, gap reasons, source lines and basis are said from the catalogue by
`web/brief/MarkForecast.tsx` and `web/brief/mark-forecast.ts` (explicit `lang`, English default).
Model, family and forecast-point names, grid degrees and `kt` / `ft` / `s` / `km` tokens stay as published.
Catalogue IDs: `markForecast.*`.

| English | Spanish | Catalogue ID | Meaning kept |
| --- | --- | --- | --- |
| run (model run) | `corrida` | `markForecast.gate.*`, `markForecast.src.run` | the model run, not the forecast |
| not values at this mark or at a model cell | `no valores en esta marca ni en una celda del modelo` | `markForecast.basis` | point values, not the mark's or a cell's |
| never averaged | `nunca se promedian` | `markForecast.basis` | two families, two rows |
| leaves a gap | `deja un hueco` | `markForecast.basis` | a gap is not filled |
| Gap: {reason}. | `Faltante: {reason}.` | `markForecast.gapLine` | |
| about {km} km / unstated | `aproximadamente {km} km` / `no indicada` | `markForecast.gridAbout`, `markForecast.unstated` | grid spacing as stated |
| from / gusts / toward {n}° true | `desde` / `ráfagas de` / `hacia {n}° verdadero` | `markForecast.from`, `.gusts`, `.towardTrue` | direction wind comes from vs. current goes toward |
| within 1.5 grid lengths | `a menos de {km} km (1.5 longitudes de malla)` | `markForecast.gap.noCell` | both failure clauses stay |

### Where to look ranking words (SC1137-05)

The list's source labels, basis, empty lines, fit and generated reasons are said from the catalogue by
`web/brief/ranking-copy.ts` from parts `web/ranking.ts` and `web/area-reasons.ts` attach (display only; English and every
export read the plain fields). Published names, `terrain_interpretation` and source titles stay as published.
Catalogue IDs: `ranking.*`; the fit line reuses `mark.layer.habitat.fit`, `.fitUnrated` and the screen notes `mark.layer.habitat.screen.*`.

| English | Spanish | Catalogue ID | Meaning kept |
| --- | --- | --- | --- |
| distances are straight-line from | `las distancias son en línea recta desde` | `ranking.basis.publication`, `.terrain`, `.atlas` | a straight line, not a route |
| not applied / not a swim route | `no es una ruta para nadar` / `No se aplica tu límite de nado` | `ranking.basis.swum`, `ranking.basis.swimOff` | the distance is approximate; the limit may be off |
| the shoreline is not a navigation boundary | `la línea costera no es un límite de navegación` | `ranking.basis.water` | land/water check; 25 m and tiles stay |
| fish presence is unverified | `la presencia de peces no está verificada` | `ranking.basis.fish` | a place to look, not a catch probability |
| spots withheld: land/water not confirmed | `lugares omitidos: no se ha confirmado si son tierra o agua` | `ranking.withheld.one`, `.many` | withheld is never "clear" |
| Protected-area check not current | `La revisión de áreas protegidas no está actualizada · se omiten los lugares de pesca` | `ranking.empty.screenNotCurrent` | every place withheld |
| Passed the protected-area check with {m} m clearance | `Pasó la revisión de áreas protegidas con {m} m de separación` | `ranking.reason.clearance` | dated evidence, not a current safety authorization |
| within {ft} ft ... yd of shore | `dentro de {ft} ft ... y {yd} yd de la costa` | `ranking.within`, `.within.reach`, `.within.shore` | the thresholds in the empty line |

The Where to look sentences say "omitido" for a withheld place (the spec's wording); the map's screen notes say "retenido". Both mean withheld.

### Plan-date rules card and landing layer dots (SC1407-13)

The planner's rules card (`web/app/PlanRules.tsx`) says its own words from the catalogue and reuses the rules
card's `rules.status.*`, `rules.fresh.*`, `rules.verified`, `rules.notconfirmed`, `rules.notverified`, `rules.link.*`,
`rules.depth.*`, `rules.english` and `rules.english.inline`. The registry's reason (closures, restrictions, the
opening-time note), its bag and size clauses, species names and the official link targets stay as published, in English,
marked `lang="en"` (the link `hreflang="en"`), and the card says so; the app-written depth line is translated and not marked
English. Stale, overdue, unknown, not-reviewed or location-dependent rules read `Revisa las reglas` with the check line,
never open or verified. Catalogue IDs: `planRules.*`. The landing's layer dots (`web/landing/LayerDots.tsx`) read
`landing.dots.*` from the first-paint slice; each label equals the map rail's label in both languages (by test).

| English | Spanish | Catalogue ID | Meaning kept |
| --- | --- | --- | --- |
| Rules on the plan's date | `Reglas para la fecha del plan` | `planRules.aria` | the card's accessible name |
| Rules on {date} | `Reglas para el {date}` | `planRules.heading` | the plan's date, as written |
| Closed on {date}. | `Cerrado el {date}.` | `planRules.closedOn` | closed said plainly, never softened |
| Check the official rules before this trip. | `Consulta las reglas oficiales antes de este viaje.` | `planRules.check` | unconfirmed is never open |
| Not legal advice; check the official page. | `No es asesoría legal; consulta la página oficial.` | `planRules.notLegalAdvice` | not legal advice |
| Map layers | `Capas del mapa` | `landing.dots.aria` | the dots' navigation name |
| Seafloor / Currents / Water temp / Temp contrast / Temp fronts / Chlorophyll / Swell + wind / Stations / Charter fleet / Clouds | `Fondo marino` / `Corrientes` / `Temperatura del agua` / `Contraste de temperatura` / `Frentes de temperatura` / `Clorofila` / `Oleaje y viento` / `Estaciones` / `Flota chárter` / `Nubes` | `landing.dots.seafloor`, `.currents`, `.water-temp`, `.sst-contrast`, `.sst-fronts`, `.chlorophyll`, `.swell`, `.stations`, `.fleet`, `.clouds` | the rail's labels (`layer.*.label`, `rail.swell.label`, `rail.fleet.label`) |
### Language loading (SC1407-09)

English pages ship English only; the Spanish table (`web/strings.es.generated.json`, generated from this catalogue) loads only for a Spanish page. When it cannot load, the page stays English and says so once beside the language choice (the landing adds a link that reloads the page in Spanish).

| English | Spanish | IDs | Note |
|---|---|---|---|
| Spanish could not load, so the page stays in English. | `No se pudo cargar el español, así que la página sigue en inglés.` | `language.loadFailed` | never claims Spanish is active |
| Try Español again | `Volver a intentar en español` | `language.retrySpanish` | the landing's retry link; the app retries from its Español button |

### Fishing profile and Coast view (SC1722-13)

Two different controls must never share a visible Spanish name. The fishing profile (and the origin choice in the limits form) is `Orilla`; the Coast view of the app is `Costa`. Geographic prose about the coast as a place (`costa`, `la costa`, `línea costera`, `Costa de California central`) is not a profile label and keeps its ordinary wording.

| English | Spanish | IDs | Note |
|---|---|---|---|
| Shore (fishing profile; also the profile name inside composed sentences such as the default-limits notice and the target group headings) | `Orilla` | `where.profile.shore` | the machine value stays `shore` |
| Shore (launch-origin choice in the limits form) | `Orilla` | `limits.from.shore` | follows the profile name |
| Coast (the map view, masthead and phone tab) | `Costa` | `shell.view.coast` | never the profile; the machine value stays `coast` |
| Find a target (target search field, placeholder and accessible name) | `Busca especie` | `command.findTarget` | short, so the 128 px field shows it whole |

## 2. Observed divergences

Every active divergence from the listed term/context rules at the checked revision is below. Full current values are verbatim; line numbers are physical catalogue key lines, not glossary lines. These are documented debt, not changes to the catalogue, a safety clearance, or instructions to replace whole sentences mechanically. Different wording and source-token changes are included even where the sense is understandable.

| ID | Catalogue line | English | Current Spanish (verbatim) | Preferred term |
| --- | --- | --- | --- | --- |
| `where.screen.unchecked` | 439 | `Protected areas not checked` | `Áreas protegidas sin revisar` | `no revisado (with grammatical agreement)` |
| `run.route.unchecked` | 619 | `Route: protected areas not checked.` | `Ruta: áreas protegidas sin revisar.` | `no revisado (with grammatical agreement)` |
| `run.route.near` | 621 | `Route passes within {m} m of {name}.` | `La ruta pasa a menos de {m} m de {name}.` | `a {m} m o menos de {name} (inclusive parameterized margin)` |
| `layer.shore-runs.basis` | 963 | `NOAA ESI 2006 sandy-shore runs and public access points from the California Coastal Commission inventory, each with its source, access and rules review dates; held while the protected-area or marine alert check is unavailable, a marine alert covers the area or the county posts a beach-health advisory, closure or warning there; hidden when source review expires. Review dates remain historical context. Ranking does not establish legal permission.` | `Tramos de costa arenosa NOAA ESI 2006 y puntos de acceso público del inventario de la California Coastal Commission, cada uno con las fechas de revisión de fuente, acceso y reglas. Se retienen mientras no esté disponible la comprobación de áreas protegidas o alertas marinas, una alerta marina cubra el área o el condado publique allí un aviso, cierre o advertencia de salud de playa; se ocultan cuando vence la revisión de la fuente. Las fechas de revisión siguen siendo contexto histórico. El orden no establece permiso legal.` | `la revisión de avisos marinos no está disponible (grammatical agreement allowed)` |
| `dev.unknownLayer` | 1146 | `Unknown map layer {id}` | `Unknown map layer {id}` | `Desconocido (with grammatical agreement)` |
| `planner.alert.notChecked` | 1290 | ` · Protected areas not checked` | ` · Áreas protegidas sin revisar` | `no revisado (with grammatical agreement)` |
| `pm.verdict.unchecked` | 1355 | `Protected areas not checked` | `Áreas protegidas sin revisar` | `no revisado (with grammatical agreement)` |
| `pm.al.screen` | 1439 | `A selected stop is inside, near, or not checked against protected areas. Review the plan before saving alerts.` | `Una parada seleccionada está dentro de un área protegida, cerca de una o sin revisar. Revisa el plan antes de guardar alertas.` | `no revisado (with grammatical agreement)` |
| `portAlert.swell` | 1541 | `Swell limit (ft)` | `Límite de oleaje de fondo (pies)` | `ft (keep supplied token)` |
| `portAlert.invalid` | 1544 | `Enter wind from 1 to 60 kt and swell from 0.5 to 30 ft.` | `Escribe viento de 1 a 60 kt y oleaje de fondo de 0,5 a 30 pies.` | `ft (keep supplied token)` |
| `portAlert.hit.swell` | 1554 | `Swell {value} ft from {time} (limit {limit} ft)` | `Oleaje de fondo {value} pies desde {time} (límite {limit} pies)` | `ft (keep supplied token)` |
| `mark.save.notChecked` | 1750 | `Protected areas not checked for this spot: outside coverage or check unavailable; not saved.` | `No se han comprobado las áreas protegidas para este lugar. No se guardó.` | `no revisado; retain outside-coverage/unavailable clauses` |
| `mark.save.margin` | 1752 | `Within 70 m of a protected area. Not saved.` | `A menos de 70 m de un área protegida. No se guardó.` | `a 70 m o menos de un área protegida (inclusive, not menos de)` |
| `mark.copy.reason.notChecked` | 1765 | `Protected areas not checked for this position: outside coverage or check unavailable.` | `No se han comprobado las áreas protegidas para esta posición: fuera de cobertura o comprobación no disponible.` | `no revisado (with grammatical agreement)` |
| `mark.layer.habitat.within` | 1848 | `Inside or within {margin} m of {names}` | `Dentro o a menos de {margin} m de {names}` | `dentro de / a {margin} m o menos de {names} (inclusive parameterized margin)` |
| `mark.layer.ais.reading` | 1896 | `{days} · {hours} hr apparent fishing time. Apparent fishing activity, not a verified catch spot.` | `{days} · {hours} h de tiempo de pesca aparente. Actividad pesquera aparente, no un lugar de captura verificado.` | `hr (preserve supplied English token; preferred new-copy hour token remains h)` |
| `map.nearshore.summary` | 2109 | `{count} · {product}{run} · ring {base} px + {perFt} px per ft` | `{count} · {product}{run} · anillo {base} px + {perFt} px por pie` | `ft (keep supplied token)` |
| `trip.pos.margin` | 2646 | `"Near" means within {distance} of a boundary plus your position accuracy, the same margin the planner uses.` | `«Cerca» significa a menos de {distance} de un límite más la precisión de tu posición, el mismo margen que usa el planificador.` | `a {distance} o menos (inclusive margin, still plus position accuracy)` |

The former `fa.marginal` and `fa.no` divergences are resolved, not active debt: #1617 (SC1352-10), merge `c25ccf3322f613cd6847b195ac264d19844aaff8`, landed `Marginal - {day} es un día límite para pescar.` and `No - {day} el mar está demasiado agitado para pescar.` Current key lines are 46 and 47. The English values are unchanged; `verdict.band.choppy` stays `picado`. Verdict label key lines are 122–125 (`brief.verdict.comfortable`, `brief.verdict.marginal`, `brief.verdict.rough`, `brief.verdict.unknown`).

Matches that are **not** divergences: case/number/gender and `se desconocen` for unknown; `no se revisó` / `no revisadas` for not checked; `Dentro de {name}` for a named protected area; `línea recta` as a noun in `run.basis.text`, `limits.reach.hint` and `layer.reach.legend0` rather than the adverbial `en línea recta`; singular `pie` when English spells out “foot”; the permitted `kn`/`kt` source variants; the seven hold sentences and the distinct missing/daily-check and not-current sentences in section 1. An `ft` token replaced by prose is separately listed above, not silently treated as a grammatical variant. Depth-line inside, rough terrain/roughest hour, geological map units and arbitrary published provider text remain different contexts, not debt.

At this snapshot only the exact English “not a legal boundary”, “not a catch prediction” and “planning outline” remain absent among the formerly missing caveats; section 1 explains their related but distinct contexts. Within-70-m, out-at-sea, straight-line and by-water IDs now exist. Parameterized margin templates and the two “70 m planning margin” paragraphs are identified separately rather than inventing literal English thresholds.

## 3. Review rules for builders

- Use the preferred term for new app-written copy. Published names, the
  registry's own rule wording, model source text and event names stay as
  published (see `rules.english`).
- Keep negation, uncertainty, thresholds and unit placeholders. "Not checked"
  stays "not checked"; an unknown check is never a clear place; screening is
  not clearance; `Desconocido` is never `Cómodo`.
- Review every hold sentence and refusal text explicitly, including inflected
  and embedded occurrences, not only whole-string matches. Do not conflate
  missing with stale, protected-area `inside` with the depth line, bite forecast
  with catch prediction, or a planning aid with an outline.
- Preserve numbers, placeholders, source units, rounding and the decimal-comma,
  no-grouping format. Do not convert `kn`, `kt`, `ft` or `m`.
- Do not translate arbitrary provider text and do not relax evidence to make a
  sentence read better.
- When a new ID uses a listed term, add it to section 1; when an existing
  value differs, add it to section 2. The divergences above are documented
  debt for a later unit, not changes delivered by this page.
