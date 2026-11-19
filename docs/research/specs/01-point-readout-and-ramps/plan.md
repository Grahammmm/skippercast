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
