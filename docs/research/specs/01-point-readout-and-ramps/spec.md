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
