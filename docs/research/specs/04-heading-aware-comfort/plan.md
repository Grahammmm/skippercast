# Implementation plan · 04 heading-aware comfort

## Evidence in the repository (observed 2026-11-19, commit fa9c358)

- `web/score.ts`: `THRESHOLDS`, `angleBetween` (L98, already used for crossing seas), `partitionCosts`, `comfortCosts`, `chargedCosts`, `hourScores`, `rateComfort(FeedHour, boat)` (L309), `REFERENCE_BOAT`. `FeedHour` holds `swell_from`, `wind_from`, `swell_period` and `chop_period` (L278–L284).
- `docs/conditions-model.md` lists every consumer of `web/score.ts`. Keep them unchanged unless they pass a course.
- `dist/boat-handling.js`: the sea and wind factors and `chopPeriod`.
- `server/routes/feedback.ts`: `POST /api/comfort` validates `rating` (1–10), `phase` ∈ outbound/fishing/return, optional `wind`, `sea`, `period` and `heading` (0–360), and `point`. It stores them in `comfort_feedback(context)` as JSON. `GET /api/comfort` returns the last 100.
- Boat brief: `web/brief/run.ts` (run time, turn-back), `web/route.ts` / `web/land-water.ts` (water route), `web/brief/verdict.ts` (day verdict).
- `docs/boat-profile.md` → Limits says the model ignores heading relative to the seas.

## Contracts

```ts
// web/score.ts
export type HeadingSector = 'head' | 'bow' | 'beam' | 'stern' | 'following';
export interface HeadingRating { course: number; relative: number | null; sector: HeadingSector | null; score: number | null; factor: number; limited: boolean }
export function headingRating(h: FeedHour, course: number, boat?: BoatFactors, offset?: Partial<Record<'head'|'beam'|'following', number>>): HeadingRating
export function headingRose(h: FeedHour, boat?: BoatFactors, offset?: …): HeadingRating[] // 8 courses, 0..315
```

The heading factor multiplies only the `seas` and `chop` costs. Wind costs are unchanged. The crossing and short-chop penalties apply as today, and beam adds `THRESHOLDS.heading.rollPenalty` (0.5) when the swell period is ≤ 1.5 × chopPeriod and the sea is ≥ 2 ft × S. A missing `swell_from` gives `sector: null`, the hour's normal score, and `limited: true`.

Calibration API (`server/routes/feedback.ts`):

```json
GET /api/comfort/calibration?boat=<name> → {"groups": {"head": {"n": 6, "residual": -0.55}, "beam": {"n": 2, "residual": 0}, "following": {"n": 0, "residual": 0}}, "min_reports": 5}
```

The model score for each report is recomputed server-side from the stored context, by importing `web/score.ts` as `server/alert-policy.ts` already does.

## Files to create or modify

| File | Change |
| --- | --- |
| `web/score.ts` | `THRESHOLDS.heading`, `headingRating`, `headingRose` |
| `web/brief/run.ts` (or new `web/brief/heading.ts`) | out and back bearings from the route |
| `web/app/` brief component that renders the day verdict (`web/brief/verdict-copy.ts` consumers) | Ride by heading card (SVG rose, 8 wedges) |
| `server/routes/feedback.ts` | calibration endpoint; store `boat` name in context if absent |
| account feedback UI (`web/account.ts` / `dist/account.js`) | pre-fill heading, phase and hour values |
| `catalog/app/strings.json` | `brief.heading.*`, `boat.calibrated.*` en+es |
| `docs/boat-profile.md`, `docs/conditions-model.md` | R7 |
| `tests/test_heading_comfort.mjs`, `tests/test_comfort_calibration.mjs` (new) | |

## UX details

- Rose: a 120 px SVG, 8 wedges coloured with the verdict tokens (go / marginal / no-go / unknown). Out and back are arrows with labels. Tapping a wedge shows its sector text. A screen-reader table lists the 8 headings.
- Visual reference: `docs/research/inspiration/skippercast_inspiration.json` per_layer "Waves / swell (sea conditions)" (direction strokes, "dense" ramp) for the swell arrow inside the rose.

## Edge cases

- Shore, Spear or Kayak profiles: no rose (Boat only).
- A route that can't be computed (land-water screen refuses it): no out/back marks, the rose only.
- Calibration across boats: group by `boat_name`. Changing the boat resets the calibration shown.
- Old feedback rows without a heading are excluded from the sector groups.

## Dependencies

None. A later "ride recording" spec builds on R4 and R5.
