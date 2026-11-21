<!-- Generated from 01-point-readout-and-ramps/spec.md, plan.md, tasks.md. Edit those, not this file. -->

# 01 · Full point readout and adjustable colour ranges

Status: proposed, 2026-11-19 · Priority 1 · Effort estimate: S (days) · Depends on: none
Source: SkipperCast competitor analysis, recommendation 1 (Fishare, BlueFronts, RipCharts, SatFish v2, Salty Offshore).

## Intended goal

One tap on the Chart tells the angler every number SkipperCast holds for that spot at the selected hour: water temperature, temperature contrast, front distance, chlorophyll, current, swell and wind. The water-temperature colours can be stretched so a 1 °F break stands out.

## Purpose

SkipperCast already answers a tap with **one** reading: `web/map/chart.ts` `fieldReading` returns the first non-null `reading(at)` from currents, water temp, contrast, fronts or swell. Chlorophyll and wind give no reading. The water-temp ramp always spans the whole analysis's range (`temperatureRange` in `web/map/sst.ts`), so inside a small area the colours can look flat. Offshore competitors treat a readable value at a point, and a range the user controls, as basic tools. Both close a gap at low cost and use data the client already holds.

## User journey

1. Dana opens `/map?region=morro-bay` on her phone and turns on Water temp, Chlorophyll and Currents in the layer rail.
2. She taps a spot 12 nm off Point Buchon.
3. The mark card opens with a **Here** section that lists one line per drawn layer, in the rail's order. Each line carries its value, its product and its age, for example "Water temp 58.4 °F · analysis error 0.6 °F · NOAA Geo-Polar Blended, 9 h old", "Chlorophyll 1.8 mg/m³ · sample Nov 18", "Current 0.4 kn toward 160° · WCOFS 03z +6 h".
4. A drawn layer with no value at that point says why, for example "Chlorophyll: no retrieval here (cloud)". It never shows a number taken from a neighbouring cell.
5. She opens the legend's Water temp row and sees the current range "55–61 °F (whole analysis)". She taps **Fit to view**. The ramp re-spans to the temperatures inside the visible map (57–59 °F), the contours keep their 0.5 °F spacing, and the legend says "57–59 °F (fit to view)".
6. She can also drag the two ends of a range slider. **Reset** returns to the analysis range.
7. She shares the view. The link reopens with her custom range.

## Use cases

- **Find a temperature break inside a small search box.** Fit to view makes a 1 °F edge visible.
- **Check whether a colour edge is also a chlorophyll edge.** One tap reads both layers.
- **Compare current and swell at a mark before running there.**
- **Send a crew member the exact view, ramp included.**

## Requirements

1. **R1** A Chart tap returns a list of readings, one per drawn field layer, in rail order, instead of only the first non-null one. Existing single-reading consumers keep working.
2. **R2** Chlorophyll gets a `reading(at)`: the value of the observed native cell that contains the point (no interpolation), with sample date and age. Points outside cells read "no retrieval here".
3. **R3** Wind gets a `reading(at)` from the same hourly field it draws: speed, gust where held, the direction it blows from, model and run.
4. **R4** Every reading keeps the source's own words for product, age and error, taken from the layer's existing basis or status. No new claim is made.
5. **R5** The Water temp legend row offers three range modes: `analysis` (today's behaviour, the default), `view` (fit to the samples inside the current viewport, re-fitted on `moveend`), and `custom` (two-handle slider, 0.5 °F steps, clamped to the analysis's own extremes).
6. **R6** The range drives the texture colour table (`colourTable`/`fieldTexture`) and the legend label. Contours stay at 0.5 °F inside the chosen range. Swell and chlorophyll ramps are unchanged in this increment.
7. **R7** The range mode and custom ends are part of the shareable state (`web/share-link.ts`, `web/state.ts`) under a new parameter `sstRange` (`view` or `<min>-<max>` in °F). Absent or invalid means `analysis`.
8. **R8** All new copy is in `catalog/app/strings.json` with English and Spanish.

## Acceptance

- With Water temp, Chlorophyll and Currents on, a tap inside all three shows three lines with values and ages. A tap on a cloud gap shows the chlorophyll "no retrieval" line.
- Fit to view on a zoomed-in map produces a narrower legend range than the analysis range, and the texture visibly re-colours. Reset restores the analysis range exactly.
- A link carrying `sstRange=57-59` reopens with that range. `sstRange=garbage` opens in analysis mode.
- `pnpm typecheck`, `node --test tests/test_*.mjs`, `node scripts/check_copy.mjs` and `pnpm build && node scripts/check_client.mjs` pass.

## Non-goals

- No interpolated or gap-filled values, no derived "fishiness" number, no species score.
- No ramp controls for swell, chlorophyll or currents in this increment. A later spec can reuse the control.
- No change to the terrain (3D) presentation's colours.


---

# Implementation plan · 01 point readout and ramps

## Evidence in the repository (observed 2026-11-19, commit fa9c358)

- `web/map/chart.ts` ~L381: `fieldReading = at => currents?.reading(at) ?? drawn.map(l => l.reading?.(at) ?? null).find(m => m !== null) ?? null`. It returns a single `ChartMark`.
- These layers have `reading(at)`: `web/map/sst.ts` (L219–L226, value and analysis error from `field.sample`), `contrast.ts` L271, `currents.ts` L350, `fronts.ts` L244, `swell.ts` L403.
- These have none: `web/map/chlorophyll.ts` (cells carry `properties.value`; observed native cells only, "never a smoothed or gap-filled field"), and `web/map/wind.ts` / `wind-layer.js`.
- Ramp: `web/map/sst.ts` builds `range` with `temperatureRange(points.map(p => p.tempF))` (L129). The legend prints `a.range` (`web/app/Legend.tsx` L206). `web/map/field.ts` `colourTable(ramp)` maps 0..1 to the ramp. The texture maps value to colour across the legend's range.
- The mark card is `web/app/MarkCard.tsx`, fed by the `chartMark` signal (`web/map/chart.ts`).
- The share and state parameters are parsed in `web/state.ts` (L158–L166) and written by `web/share-link.ts`.
- Design reference for a point readout: `docs/plans/pelagic-context/design.md` §2.1 ("reads the cell of each product that contains the point … never interpolates"). Follow it for chlorophyll.

## Contracts

```ts
// web/map/coastline.ts (ChartMark) stays. Add in web/map/chart.ts:
export interface FieldReading { layer: string; mark: ChartMark | null; reason?: string }
// chart API: readingsAt(at): FieldReading[]  (rail order, drawn layers only)
// keep fieldReading(at) = readingsAt(at).find(r => r.mark)?.mark ?? null  for existing callers
```

Range state, in `web/state.ts`:

```ts
export type SstRange = {mode: 'analysis'} | {mode: 'view'} | {mode: 'custom'; min: number; max: number};
export const sstRange = signal<SstRange>({mode: 'analysis'});
// parse: 'view' | /^-?\d+(\.5)?-\d+(\.5)?$/ with min < max; else analysis
```

## Architecture choices

- `sst.ts` keeps `range` (the analysis range) and adds a computed `shownRange` from `sstRange`, the analysis range and, for `view`, the engine's current bounds. Contours and the texture use `shownRange`. Values outside it clamp to the end colours, and the legend says "outside range" with an arrow glyph at each end.
- Fit to view samples `field.sample` on a coarse grid (for example 32 × 32) inside `map.getBounds()`. It is recomputed on `moveend`, debounced 250 ms, so there is no per-frame work.
- Chlorophyll reading: index the cells by `Math.floor` of (lat, lon) over the resolution into a `Map`, built once per observation (beside `chlorophyllCells`). The lookup is O(1) and never takes a neighbour's value.
- Wind reading: `web/map/wind.ts` draws sparse GFS samples (`WindFrame.points: WindSample{lon,lat,knots,from}`, "no inferred coastal detail"). Read the nearest sample of the shown frame within half the sample spacing; beyond that there is no reading ("no wind sample near here").
- MarkCard renders a `Here` list from `readingsAt` when more than one layer is drawn. With exactly one, it looks as it does today.

## Files to create or modify

| File | Change |
| --- | --- |
| `web/map/chart.ts` | `readingsAt`, keep `fieldReading` wrapper |
| `web/map/chlorophyll.ts` | `reading(at)` + cell index |
| `web/map/wind.ts` | `reading(at)` from the shown `WindFrame` |
| `web/map/sst.ts` | `shownRange`, use in texture/contours, `viewRange()` helper |
| `web/map/field.ts` | no change expected: `fieldTexture(field, range, ramp, value)` (L84) already takes the range; pass `shownRange` |
| `web/state.ts`, `web/share-link.ts` | `sstRange` signal, parse/serialize |
| `web/app/Legend.tsx` | range mode control on the Water temp row (segmented: Analysis / Fit view / Custom + slider) |
| `web/app/MarkCard.tsx` | multi-reading list |
| `catalog/app/strings.json` | new ids (`legend.sstRange.*`, `mark.here.*`, `mark.reading.chlorophyll.*`, `mark.reading.wind.*`) en+es, then `node scripts/build_landing_strings.mjs` |
| `tests/test_point_readings.mjs` (new) | chlorophyll lookup, wind nearest-point, ordering |
| `tests/test_sst_range.mjs` (new) | parse, clamp, view fit on a synthetic field |
| `e2e/` | one Playwright spec: tap shows multiple lines; Fit view changes legend text |

## UX details

- Mark card section title "Here". Each line has the layer swatch, the value in `ui-mono`, and the product and age in the muted style. Lines follow rail order. A layer that is drawn but has no value reads in italic with its reason.
- Legend control: a 3-option segmented control under the Water temp range. Custom shows a dual slider with 0.5 °F steps, its ends labelled. The control fits 360 px wide, keyboard operable, with `aria-valuetext` "57.5 °F".
- Visual reference: the SST row of `docs/research/inspiration/skippercast_inspiration.json` per_layer "Sea surface temperature" ("Make fronts and eddies the subject; perceptual ramp"; cmocean thermal). Keep the existing `--sst-*` tokens.

## Edge cases

- The view contains no samples (all land or outside the grid). Fit to view keeps the previous range and the legend says "no water in view".
- `min == max` after fitting, for example uniform water. Widen to ±0.5 °F.
- The analysis is replaced, for example by a new day. A custom range outside the new extremes clamps. If that leaves nothing, revert to analysis mode.
- Offline or stale layers already draw nothing. Readings must return null with the layer's existing status reason.
- Terrain presentation: readings are Chart-only today (`shownPresentation === 'chart'` checks). Keep that.

## Dependencies

None. Specs 02, 05 and 07 add more layers whose `reading(at)` should plug into `readingsAt`.


---

# Tasks · 01 point readout and ramps

- [ ] T1 Add `readingsAt` to `web/map/chart.ts`, keep `fieldReading` as a wrapper. Unit-test ordering and null reasons (R1).
- [ ] T2 Chlorophyll `reading(at)` with the native-cell index. Test: inside a cell, on a gap, off the grid (R2, R4).
- [ ] T3 Wind `reading(at)` with the nearest point within half a step. Test against a synthetic field (R3, R4).
- [ ] T4 MarkCard "Here" list. With a single layer the card looks the same as today, checked by snapshot (R1).
- [ ] T5 `sstRange` signal plus parse/serialize in `state.ts`/`share-link.ts`. Tests for valid, invalid and round-trip values (R7).
- [ ] T6 `shownRange` in `sst.ts` feeding the texture and contours. Implement fit-to-view sampling with debounce. Tests on a synthetic field (R5, R6).
- [ ] T7 Legend control (segmented and slider), accessible, 360 px layout (R5).
- [ ] T8 Strings en+es, then rebuild the generated tables and run `node scripts/check_copy.mjs` (R8).
- [ ] T9 Playwright e2e: multi-line card, Fit view changes the legend, a shared link restores the range (acceptance).
- [ ] T10 Run `pnpm typecheck && pnpm build && node scripts/check_client.mjs && node --test tests/test_*.mjs`. Update `docs/web-app.md` (Chart and Legend paragraphs) in the same PR.

## Verification

Record the date, the commands and their results here after the build (rea convention: dated evidence, simulated and real-device checks kept separate).
