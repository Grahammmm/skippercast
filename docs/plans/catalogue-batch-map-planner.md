# One Spanish copy batch for the map and Trip planner

**Recommendation:** Land the six copy fixes below in one catalogue change; leave the layer rail and legend registry fix out (§1).<br>
The source still supplies English on all six paths; the batch can reuse four existing Chart labels and the full route warning (§§1–2).<br>
Checked against `origin/main` at `7335068efd2627dd2a0ba9bea39f09e86a8f252d` (§4). This is a plan, not a UI change.

## 1. What is still open (C1)

| Backlog row, by title | What main does today | Shared-file risk for the future build |
| --- | --- | --- |
| The Chart’s own controls speak Spanish | **Open.** `web/map/engine.ts:155–164` writes `Sources`; `:168–190` sets the canvas name to `Chart` and supplies no locale override for the native zoom control. The separate stage buttons already have translated labels (`web/app/MapStage.tsx:169–170`); they are not this fix. Main pins MapLibre 6.18.0 (`package.json:23`). Exact native tooltip/ARIA output for that version is **UNVERIFIED** locally; the backlog’s `Zoom in` / `Zoom out` are the English targets to confirm in the locked renderer. | `web/map/engine.ts` is a map-track coordination hotspot (backlog row, 19 Nov., line 8), not a style-kit file. Do not edit `web/map/chart.ts`. |
| A Spanish page has a Spanish tab title | **Open on both pages.** The tracked landing shell is `dist/landing.html:7` (not `dist/index.html`); the map shell is `dist/app.html:9`. Both titles are English. Neither startup path replaces the title (`web/landing/main.tsx:74–93`, `web/landing/copy.ts:19–34`, `web/app/main.tsx:33–35,61–66`). Compare the existing translated-title assignment in `dist/public-page-language.js:9–12`. | No named hotspot in those title call sites. Leave both HTML shells unchanged. |
| The Trip dialog’s saved-pack lines read Spanish | **Open.** `web/app/Trip.tsx:183` calls `forecastEndLine` without a language; `web/trip-forecast-end.ts:8–11` returns three English messages and `web/map/currents.ts:79–80` supplies the English weekday/hour. The storage answer is appended as English at `web/app/Trip.tsx:30–33,152` from `web/trip.ts:221–226`. | Read the existing time formatter but do not edit `web/map/currents.ts` for this row. |
| The planning-route status line is readable and follows the page language | **Open.** `web/app/Planner.tsx:373` prints a string. `web/planner.ts:604–614,669–692` puts a raw check time, dot-decimal miles and English into it; download has a short warning, Chart preview the full one. The catch paths copy English messages, including `web/planner.ts:593` and `web/protected-route.ts:49,52`. | No named hotspot in these call sites. No route, geometry, export or timing change. |
| The trip planner’s ranked-reef cards read Spanish | **Open.** The loader makes English prose with `.toFixed(1)` (`dist/reef-trip-data.js:63–75`); the ranked card shows that prose unchanged (`web/app/Planner.tsx:73`). Missing relief is `Unknown`; missing area is `unknown` (different case). | No named hotspot in the loader or card. Do not change any published reef file or the existing prose field. |
| The surface-current source choices read Spanish | **Open.** `web/app/LayerRail.tsx:57–69` localizes the select label but uses `s.label` verbatim from `web/map/currents.ts:60–63`: `Off`, `NOAA WCOFS forecast`, `Observed HF radar · 1 km`, `Observed HF radar · 6 km`. Conditions uses the same control (`web/app/views/Conditions.tsx:127`). | `web/app/LayerRail.tsx` and `web/map/currents.ts` are map-track coordination hotspots (backlog row, 20 Nov., line 8). Only the former needs an edit: keep the English labels where the current model uses them (`web/map/currents.ts:117,131`). |

Excluded: **The layer rail and legend read Spanish again** requires the registry in the style-kit hotspot `web/map/layers.ts` (19 Nov. backlog, line 5; `REGISTRY` in that file). The six rows stay separate in the backlog. The table is a source diagnosis; a browser run, built HTML and live-site behavior are **UNVERIFIED** in this report.

## 2. Proposed catalogue blocks (C2)

Add these pairs to `catalog/app/strings.json`, next to their existing namespaces. `Reuse` means no duplicate entry. `{...}` names are literal placeholders supplied at render time (`web/i18n-core.ts:17–29`). The English column preserves today’s words, case, spacing and punctuation; the route check timestamp is the one intentional English display-format change described below. New Spanish copy is draft: **UNVERIFIED — native review** of the marked terms and sentences before landing. Examples below are expected results, not observed browser output.

### Chart controls

| ID | English | Spanish |
| --- | --- | --- |
| `brief.sources` (reuse) | `Sources` | `Fuentes` |
| `stage.zoomIn` (reuse) | `Zoom in` | `Acercar` |
| `stage.zoomOut` (reuse) | `Zoom out` | `Alejar` |
| `stage.chart` (reuse) | `Chart` | `Carta` |

No variables or formatting. The pairs already exist (`catalog/app/strings.json:193,2719,2730–2731`). In `web/map/engine.ts:155–190`, read them at map/control creation using the ready page language, not at import. Give the three stage values to MapLibre’s `NavigationControl.ZoomIn`, `NavigationControl.ZoomOut` and `Map.Title`; use `brief.sources` in `SourcesLinkControl`. Keep `/sources#data-sources` and the English destination page as they are (`web/map/engine.ts:148,160`; backlog row). For an in-place language change, update only the owned link and the renderer’s title/ARIA labels, with cleanup on engine teardown; do not rebuild the map or touch the chart style. The update seam in the locked renderer is **UNVERIFIED**; confirm it in the focused fixture before committing to any DOM hook.

### Browser tab titles

| ID | English | Spanish |
| --- | --- | --- |
| `landing.title` | `SkipperCast · Central Coast fishing weather, tides and seafloor map` | `SkipperCast · Tiempo para la pesca, mareas y mapa del fondo marino de la Costa Central` (native review: fishing-weather wording) |
| `shell.title` | `SkipperCast · Map` | `SkipperCast · Mapa` |

No variables or formatting. Set `document.title` from `landing.title` in the ready Spanish path of `applyLandingCopy` (`web/landing/main.tsx:81–83`, `web/landing/copy.ts:15–21`). In `web/app/main.tsx:61–66`, bind the title after `await ready` to the effective language so a switch back restores the exact English title (`web/i18n-catalogue.ts:86–123`). Keep raw HTML, meta descriptions and social tags unchanged (`dist/landing.html:7`, `dist/app.html:9`). The existing Spanish-load failure should still leave an English title.

### Saved packs

| ID | English | Spanish |
| --- | --- | --- |
| `trip.pack.forecastThrough` | `Forecast saved through {time}` | `Pronóstico guardado hasta {time}` |
| `trip.pack.forecastMissing` | `Forecast end not recorded` | `No se registró hasta cuándo es válido el pronóstico` (native review) |
| `trip.pack.forecastEnded` | `The saved forecast has ended; save again with a connection` | `El pronóstico guardado ya no es válido; vuelve a guardar el paquete cuando tengas conexión` (native review) |
| `trip.pack.keep.agreed` | `This browser agreed to keep saved packs.` | `Este navegador aceptó conservar los paquetes guardados.` |
| `trip.pack.keep.already` | `This browser already keeps saved packs.` | `Este navegador ya conserva los paquetes guardados.` |
| `trip.pack.keep.refused` | `This browser may clear saved packs when space is low.` | `Este navegador puede borrar los paquetes guardados si queda poco espacio.` |

Pass `lang` from `web/app/Trip.tsx:183` into `forecastEndLine`; keep its invalid/missing and `end <= now` branches (`web/trip-forecast-end.ts:8–11`). `{time}` is a weekday and hour in the region zone already passed by the caller: retain the English `frameTime` output (e.g. `Sat 2 pm`); use the page’s Spanish locale with a short weekday and a 24-hour hour for Spanish. Do not change time rounding/granularity or parse the English label to translate it (`web/map/currents.ts:79–80`, `web/i18n-core.ts:61–69`). In `web/app/Trip.tsx:30–33,152`, carry the `Keep` key rather than a ready-made tail and translate at display, with one leading space only when there is a tail. Preserve `unavailable` as no tail and all four keys; do not change `keepSaved` or when the storage request runs (`web/trip.ts:195–226`). No other number or date fields change.

### Planning-route status

| ID | English | Spanish |
| --- | --- | --- |
| `planner.route.status.checked` | `Boundary check: {checkedAt} · {nm} nm planning route. {warning}` | `Comprobación de límites: {checkedAt} · ruta de planificación de {nm} mn. {warning}` |
| `planner.route.warning` (reuse for Chart) | `NOT FOR NAVIGATION. Planning only: no depth, hazards, tides or passage clearance. Check official charts and current rules.` | `NO USAR PARA NAVEGAR. Solo planificación: sin comprobación de profundidad, peligros, mareas ni paso. Revisa las cartas oficiales y las reglas vigentes.` |
| `planner.route.warningShort` (download status only) | `NOT FOR NAVIGATION.` | `NO USAR PARA NAVEGAR.` |
| `planner.route.error.planChanged` | `Plan changed while routing. Try again.` | `El plan cambió mientras se calculaba la ruta. Inténtalo de nuevo.` |
| `planner.route.error.planOrCheckChanged` | `Plan or boundary check changed while routing. Try again.` | `El plan o la comprobación de límites cambió mientras se calculaba la ruta. Inténtalo de nuevo.` |
| `planner.route.error.noBoundaries` | `Current protected-area boundaries unavailable. Refresh before routing.` | `No están disponibles los límites vigentes de las áreas protegidas. Actualiza antes de calcular la ruta.` |
| `planner.route.error.stopCount` | `Choose 2–12 stops for the planning route, in visit order.` | `Elige de 2 a 12 paradas para la ruta, en orden de visita.` |
| `planner.route.error.stopBlocked` | `A route stop is outside the current boundary screen or within its protected-area margin.` | `Una parada está fuera de la zona de comprobación vigente o dentro del margen de un área protegida.` |
| `planner.route.error.leg` | `Planning route unavailable for leg {leg} ({reason}). No straight-line fallback is exported.` | `No se pudo calcular el tramo {leg} de la ruta ({reason}). No se exporta una alternativa en línea recta.` |
| `planner.route.error.fullCheck` | `Planning route unavailable: full-route check failed.` | `Ruta de planificación no disponible: la comprobación de la ruta completa falló.` |
| `planner.route.error.boundariesChanged` | `Protected-area boundaries changed. Try routing again.` | `Cambiaron los límites de las áreas protegidas. Intenta calcular la ruta de nuevo.` |

The six bounded `{reason}` values in `web/route.ts:30–39` are currently displayed as codes inside the leg message. Keep the English code bytes; use these pairs to say what each code means on the Spanish page:

| ID suffix under `planner.route.reason.` | English | Spanish |
| --- | --- | --- |
| `noProduct` | `no-product` | `no hay datos para calcular la ruta` |
| `linesNeeded` | `lines-needed` | `faltan datos de la costa` |
| `startNotWater` | `start-not-water` | `el inicio no está en agua confirmada` |
| `endNotWater` | `end-not-water` | `el destino no está en agua confirmada` |
| `noRoute` | `no-route` | `no se encontró una ruta` |
| `tooFar` | `too-far` | `se alcanzó el límite de búsqueda para el tramo` |

**Native review:** Spanish route wording, especially `mn`, the protected-area margin and the leg reasons. Confirm each reason against its branch in `web/route.ts`, not just its name. `{checkedAt}` is the existing check instant shown as a short local date and time (year, month, day, hour and minute; region time zone, English 12-hour / Spanish 24-hour). `{nm}` is nautical miles to exactly one decimal, no grouping (`12.0` / `12,0`); keep `toFixed(1)` for English, use a fixed-one-decimal locale formatter in Spanish rather than `num()` which can drop the zero (`web/i18n-core.ts:61–69`). `{leg}` is the existing one-based leg number, integer without grouping; `{warning}` selects the existing full warning or the short download warning. The old timestamp stays in GPX (`web/protected-route.ts:55–57`), not in the UI.

Carry the check instant, distance and status kind instead of preformatted prose in `web/planner.ts:585–614,642–645,669–692`. Give the route-specific refusals stable codes and variables at their existing throw sites (`web/planner.ts:169,593,677–679`, `web/protected-route.ts:33–54`), preserving their original `.message` for other callers. In the live status at `web/app/Planner.tsx:373`, format with the planner’s region zone (`web/planner.ts:219`) and current page language; reuse `planner.route.removed` for the already translated removal status (`catalog/app/strings.json:1474`, `web/planner.ts:644`). An unrecognized message from an underlying guard stays unchanged as escaped text inside `lang="en"`; do not guess from matching fragments of prose. Preserve catch/attempt ordering, checks, route points, nautical miles, handoff and GPX bytes (`web/planner.ts:587–614,669–692`; `web/protected-route.ts:29–57`).

### Ranked reef terrain line

| ID | English | Spanish |
| --- | --- | --- |
| `planner.reef.terrain` | `{relief} m local relief; {area} ha reef footprint.` | `{relief} m de relieve local; {area} ha de superficie del arrecife.` (native review) |
| `planner.reef.reliefUnknown` | `Unknown` | `Sin dato` |
| `planner.reef.areaUnknown` | `unknown` | `sin dato` |

`{relief}` is metres of local relief; `{area}` is hectares of reef area, each exactly one decimal without grouping (`24.0` / `24,0`; `1.7` / `1,7`). Zero is a number, not missing. There is no date or unit conversion. At `dist/reef-trip-data.js:63–75`, carry both original numbers (or null) as a distinct optional display object on the loaded target; `areas` has the area for full loads only, so do not join against it at render. Add the optional field to `Target` (`web/planner.ts:58–66`). In `web/app/Planner.tsx:73`, use the template only for ranked targets with this explicit source object. If the object is absent, keep showing the original prose, escaped; do not infer metrics from it or replace it with unknowns. Leave `terrain_interpretation` byte-identical for other readers (`web/area-reasons.ts:100–102`; `web/map/ranked.ts:173`). The existing `ranking.reason.relief` refers to rough cover, not reef area (`catalog/app/strings.json:651`), so it is not a substitute.

### Surface-current choices

| Value | ID | English | Spanish |
| --- | --- | --- | --- |
| `off` | `rail.current.off` | `Off` | `Desactivado` |
| `wcofs` | `rail.current.wcofs` | `NOAA WCOFS forecast` | `Pronóstico de NOAA WCOFS` |
| `hfr-1` | `rail.current.hfr1` | `Observed HF radar · 1 km` | `Observaciones de HF radar · 1 km` |
| `hfr-6` | `rail.current.hfr6` | `Observed HF radar · 6 km` | `Observaciones de HF radar · 6 km` |

**Native review:** radar phrasing while retaining `HF radar` and `NOAA WCOFS` as supplied. `1 km` and `6 km` are fixed resolution labels, not placeholders; no dates or number formatting. Map each value to its ID in `CurrentSource` (`web/app/LayerRail.tsx:62–69`), for both placements. Keep option order, selection, `?current=`, the unsupported choice, English `CURRENT_SOURCES` and the model’s reason sentences unchanged (`web/app/LayerRail.tsx:57–69`; `web/map/currents.ts:60–63,115–144`).

## 3. One future build, two work halves (C3)

**UNVERIFIED estimate:** reserve two named halves of up to one hour each for authoring and focused checks; keep one catalogue commit and one review after both halves, not a partial rollout. Native review, ownership waits and CI time are not measured. Before starting, check whether another branch owns the catalogue, projections, `engine.ts` or `LayerRail.tsx`; current competing ownership is **UNVERIFIED** here. Coordinate and rebase after any overlap clears, not while another change owns those files. The full batch does not require any of the excluded style-kit hotspots (§1).

1. **Map, landing and Conditions:** `web/map/engine.ts`, `web/landing/copy.ts`, `web/app/main.tsx` and `web/app/LayerRail.tsx`. Extend `tests/test_map_layers.mjs` (existing options and link cases at `:287–326`) to check Spanish Sources, canvas and both native zoom labels, and exact English labels and href. Confirm both `title` and `aria-label` with the locked renderer on an offline fixture; the locale options alone cannot prove DOM behavior. Keep the still-map/no-controls case. Extend `tests/test_landing_i18n.mjs:123–148` (with `tests/test_landing.mjs:171` as the static-shell control) and `tests/test_shell_i18n.mjs:196` for ready Spanish title, failed load and exact English title, including switching back on the app. Extend `tests/test_layer_rail.mjs` at its render fixture (`:38`) for the same four choices in the rail and shared Conditions control; compare exact English labels, values and selection, and verify the English model text is unmodified.
2. **Trip and planning route:** `web/trip-forecast-end.ts`, `web/app/Trip.tsx`, `web/trip.ts` if replacing the `KEEP_WORDS` lookup, `web/planner.ts`, `web/protected-route.ts`, `web/app/Planner.tsx` and `dist/reef-trip-data.js` (the reader adapter only). Extend `tests/test_pack_forecast_end.mjs:43–54` for Spanish future, ended, missing/invalid, exact cutoff and region-local hour; preserve the English cases. Extend `tests/test_trip_storage_persist.mjs:35,54,63–64` for three Spanish tails, English bytes and no tail when unavailable; keep the browser-storage behavior checks. Extend `tests/test_planning_route_preview.mjs:80–89,242–247` and the route status render fixture in `tests/test_planner_i18n.mjs:193–197`: Chart and download success in both languages, no raw ISO timestamp in the UI, comma vs dot with a trailing zero, named failure with a leg reason, and verbatim unknown error marked English. Retain refusal, invalidation, no-export and byte-identical GPX checks (`tests/test_protected_route.mjs:176–192`). For ranked reefs extend `tests/test_planner_i18n.mjs:83–109` with two numbers, one missing, zero, and the old escaped-prose case; extend the loader fixture’s existing target parity check (`tests/test_reef_slim.mjs:36–37,62–72`) to catch either raw number being dropped before rendering. These are proposed tests, **UNVERIFIED** until run on the implementation.

Add all new pairs to `catalog/app/strings.json` and run `node scripts/build_landing_strings.mjs` once after both halves. It checks four projections: `web/strings.en.generated.json`, `web/strings.es.generated.json`, `web/landing/strings.generated.json`, `dist/status-strings.generated.json`. Expect the first three to change (the landing title enters the landing slice); the status projection should stay byte-identical. Do not hand-merge tables. Verify with `node scripts/build_landing_strings.mjs --check` (`scripts/build_landing_strings.mjs:10–17,27–55`). Then run the focused files above with `node --test`, `node --test tests/test_i18n_catalogue_loading.mjs`, and `pnpm typecheck`; keep local tests on synthetic data and verify the title change adds no new catalogue request on English startup (`web/i18n-catalogue.ts:90–102`). Build, fixture results and any bundle-size effect are **UNVERIFIED** here.

## 4. How to re-check the evidence (C4)

Run from the repository root. The line references above are bound to the checked main commit; they also apply unchanged to the report branch because none of the cited files is edited. The row titles come from the approved 19 Nov. map/Trip backlog (lines 5, 8–12) and 20 Nov. surface-current backlog (line 8).

| Read-only command | Deciding output (excerpt) |
| --- | --- |
| `git log -1 --format=%H origin/main` | `7335068efd2627dd2a0ba9bea39f09e86a8f252d` at checkout; use this pinned SHA if main has advanced. |
| `git grep -n -E '<title>\|doc\.title' -- dist/index.html dist/app.html dist/landing.html dist/public-page-language.js` | `dist/app.html:9` and `dist/landing.html:7` have the English titles above; `dist/public-page-language.js:12` assigns `doc.title`. No `dist/index.html` hit. |
| `git grep -n -E 'SOURCES_HREF\|Map.Title\|NavigationControl' -- web/map/engine.ts` | `:148` has the unchanged anchor, `:160` sets `Sources`, `:177` sets `Chart`, `:188` adds the native control. |
| `git grep -n -E 'forecastEndLine\|KEEP_WORDS\|Boundary check:\|terrain_interpretation\|s\.label' -- web/app/Trip.tsx web/trip-forecast-end.ts web/trip.ts web/app/Planner.tsx web/planner.ts dist/reef-trip-data.js web/app/LayerRail.tsx` | Deciding hits: `Trip.tsx:152,183`, `trip-forecast-end.ts:8`, `trip.ts:221`, `planner.ts:606,686`, `Planner.tsx:73`, `reef-trip-data.js:68`, `LayerRail.tsx:67`. |
| `git grep -n -E 'brief.sources\|stage.zoomIn\|stage.zoomOut\|stage.chart\|planner.route.warning' -- catalog/app/strings.json` | Reuse anchors `:193,1471,2719,2730–2731`. |
