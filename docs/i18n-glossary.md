# Spanish caveat glossary

This is contributor guidance for the people and agents who write the app's
Spanish. It is not legal text, not a safety clearance, not a claim that the app
is fully covered in Spanish, and not a translation engine: the Spanish is
written by hand, never generated at run time. It gives one neutral Latin
American rendering to the caveats that recur across the app, so builders who
add Spanish in separate pull requests do not pick different words for the same
caveat.

Checked against `main` at `eb75c403b115df635450b8f51b0195dce3cf4d34`, with
the catalogue as last changed by `db2b0ca302055e59d0d72c200bcafd036ed5c664`
(the verdict reasons and holds from SC0452-09 are included). The catalogue is
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
| Marginal (verdict label) | `Marginal` | `brief.verdict.marginal`, `brief.basis.comfort`, `verdict.held`, `fa.marginal` (resolved by SC1352-10, see section 2) |
| Rough (verdict label; "too rough" in the first answer) | `Agitado` | `brief.verdict.rough`, `brief.basis.comfort`, `brief.basis.profile`, `fa.no` (resolved by SC1352-10, see section 2) |
| Unknown (verdict label; never Comfortable) | `Desconocido` | `brief.verdict.unknown` |
| not checked | `no revisado` | `brief.gaps.unchecked` |
| inside (protected area) | `dentro de un área protegida` | Not in the catalogue at the checked revision. `rules.depth.inside` is a different phrase, the depth line: `Dentro de la línea de 50 brazas` |
| within 70 m (of a protected area) | `a 70 m o menos de un área protegida` | Not in the catalogue at the checked revision |
| not a legal boundary | `no es una delimitación legal` | Not in the catalogue at the checked revision |
| not a catch prediction | `no es una predicción de capturas` | Not in the catalogue at the checked revision. The bite-forecast caveat is a different one, see below |
| planning outline | `contorno de planificación` | Not in the catalogue at the checked revision. `brief.planning` ("Planning aid · not a navigation chart") is a planning aid, not an outline: `Ayuda de planificación · no es una carta náutica` |
| out at sea: not a harbor or launch reading | `mar adentro: no es una lectura del puerto ni del punto de salida al agua` | Not in the catalogue at the checked revision |
| straight line | `en línea recta` | Not in the catalogue at the checked revision |
| by water | `por agua` | Not in the catalogue at the checked revision |

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
| the marine alert check is unavailable | `la revisión de avisos marinos no está disponible` | `verdict.alertMissing` |
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
| feet | `ft` | `pies` | `brief.boat.reference`, `brief.boat.yours`, `brief.boat.note`, `brief.models.agree`, `brief.models.differ`, `brief.models.readings`, `verdict.seas`, `verdict.chop`, `verdict.steepChop`, `verdict.cross`, `verdict.calm`, `verdict.longPeriod`, `verdict.reason.detail` (all keep `ft`) |
| fathoms | `fm` | `brazas` | `rules.depth.inside`, `rules.depth.outside` (spell out `brazas`) |
| knots | `kn` or `kt`, as supplied | `nudos` | `kn`: `brief.models.agree`, `brief.models.differ`, `brief.models.readings`. `kt`: `verdict.wind`, `verdict.calm`, `verdict.reason.windDetail` |
| nautical miles | `nm` | `millas náuticas` | Not in the catalogue at the checked revision |
| metres | `m` | `metros` | Not in the catalogue at the checked revision |
| kilometres | `km` | `kilómetros` | Not in the catalogue at the checked revision |
| seconds | `s` | `segundos` | `verdict.period`, `verdict.longPeriod`, `verdict.reason.period` (all keep `s`) |
| minutes | `min` | `minutos` | Not in the catalogue at the checked revision |
| hours | `h` | `horas` | `h`: `verdict.stale`. Prose `horas`: `brief.models.hours`, `brief.models.partial`, `verdict.missingForecast`, `verdict.missingProfile` |
| temperature | `°F` or `°C`, as supplied | not spelled out | Not in the catalogue at the checked revision |

`kn` and `kt` are both source-unit spellings; keep the one supplied and do not
normalize one to the other. Do not convert between units.

### Tile detail lines (SC1137-02)

The line under each brief tile reading is said from structured parts by
`web/brief/tile-copy.ts`; the model's English line stays for other readers.
Station, buoy, site and datum names are never translated. Catalogue IDs:
`tile.detail.*`, `tile.clock.*`, `tile.gap.*`, `tide.unavailable`, `tide.noCurve`; the map's station and ring cards use `map.station.*` and `map.nearshore.*` (`high event` / `low event` are `evento de pleamar` / `evento de bajamar`).

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

## 2. Observed divergences

Every catalogue Spanish value that renders a listed term differently from
section 1 at the checked revision. The values are kept verbatim, awkward or not.
They are existing divergences and documented debt: this page changes neither
the catalogue nor any code, and it is not a mandate to replace the whole
sentence mechanically.

| ID | Catalogue line | English | Current Spanish (verbatim) | Preferred term |
| --- | --- | --- | --- | --- |
| `fa.marginal` | 8 | `Marginal - {day} is a borderline day to fish.` | Historical: `Dudoso - {day} es un día límite para pescar.` | `Marginal` |
| `fa.no` | 9 | `No - {day} looks too rough to fish.` | Historical: `No - {day} el mar está demasiado picado para pescar.` | `agitado` (the catalogue word for the English "Choppy" is `picado`, `verdict.band.choppy`) |

Resolved by `[SC1352-10]` (PR title: "Align Spanish first-answer verdict terms"):

- `fa.marginal` now reads `Marginal - {day} es un día límite para pescar.`
- `fa.no` now reads `No - {day} el mar está demasiado agitado para pescar.`

The English values are unchanged. `verdict.band.choppy` stays `picado`.

The verdict labels are at lines 48 to 50 (`brief.verdict.comfortable`,
`brief.verdict.marginal`, `brief.verdict.rough`).

Matches that are **not** divergences, so nobody "repairs" them:

- `brief.gaps.unchecked`, `No revisado en este resumen ({n})`, is the preferred
  `no revisado` in context.
- `rules.depth.inside`, `Dentro de la línea de 50 brazas`, is the depth-line
  phrase, a different caveat from protected-area `inside`.
- `brief.basis.profile` `La hora más dura` is the roughest hour, not a verdict
  label.
- `kn` against `kt` is a permitted source-unit variant, not a divergence.
- `brief.gap.daily.alerts` and `brief.gap.daily.both` use `faltan las
  revisiones de avisos marinos`, a different complete sentence from
  `verdict.alertMissing` and `verdict.noAlertCheck`.

Not in the catalogue yet, so nothing to list: within 70 m, not a legal
boundary, not a catch prediction, planning outline, out at sea (not a harbor or
launch reading), straight line and by water. Their source English exists in app
code, but a translation surface is not an ID; add the ID, then list it here.

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
