<!-- Generated from 04-heading-aware-comfort/spec.md, plan.md, tasks.md. Edit those, not this file. -->

# 04 · Heading-aware comfort ("ride by heading") and calibration from comfort reports

Status: proposed, 2026-11-19 · Priority 4 · Effort estimate: M · Depends on: none
Source: SkipperCast competitor analysis, recommendation 4 (RideScore Ride Rose and ride-learning; PredictWind vessel motion).

## Intended goal

The boat brief shows how the ride changes with the direction the boat is heading at the selected hour, especially on the outbound run and the return. Over time the boat's comfort numbers shift toward what the owner actually reports after trips.

## Purpose

`web/score.ts` is the single conditions model. It charges wind, gusts, combined seas, chop, a crossing-swell penalty and short-chop. The boat factors (`dist/boat-handling.js`) scale the thresholds. `docs/boat-profile.md` → Limits says the model ignores heading relative to the seas, and names the in-app comfort feedback (`/api/comfort`) as the calibration path. The feedback route already accepts `phase` (outbound/fishing/return), `heading`, `wind`, `sea` and `period`, but nothing reads it back into the model. RideScore's Ride Rose and ride-learning are the most visible new-entrant features, and RideScore advertises on Instagram. This spec adds both in SkipperCast's disclosed-heuristic style.

## User journey

1. Sam has saved his 25 ft centre console and picked a reef spot in the Boat brief. The brief already shows run time and turn-back time (`web/brief/run.ts`).
2. Under the day verdict there's a new **Ride by heading** card: a small compass rose with 8 sectors coloured by comfort score for the selected hour. The outbound bearing (harbor → spot) and the return bearing are marked, and each shows its score, for example "Out 290° · 6.1 Marginal (head seas, 7 s)" and "Back 110° · 7.8 Comfortable (following)".
3. Sam scrubs the dock to 2 pm and the rose updates: the return gets worse as the afternoon wind builds.
4. After the trip, the existing comfort feedback asks "How was the ride out?" (1–10). The heading is pre-filled from the trip's route, and so are the wind, sea and period of that hour.
5. After 5 or more reports, the boat card says "Calibrated from 6 of your rides: you rate head seas 0.8 points rougher than the model". The verdicts then use the adjusted numbers, labelled "calibrated". **Use model defaults** turns this off.

## Use cases

- **Choose between two spots of equal distance** when one means pounding into the swell.
- **Decide when to head home** before the afternoon wind turns the return into a head sea.
- **Get verdicts that match how a particular boat and crew feel the water.**

## Requirements

1. **R1** Add a pure `headingCosts(hour: FeedHour, course: number, boat: BoatFactors) → {score, factor, relative, sector}` in `web/score.ts`. The relative swell angle is `angleBetween(course, swell_from)`, where 0 = head seas. A disclosed multiplier on the seas cost and the chop cost applies by sector: head (0–45°), bow quarter (45–80°), beam (80–110°), stern quarter (110–150°), following (150–180°). Starting factors are written in `THRESHOLDS.heading` and documented. They are heuristics: head 1.25, bow quarter 1.1, beam 1.1 with an extra roll charge when period ≤ boat.chopPeriod × 1.5, stern quarter 0.9, following 0.85.
2. **R2** `rateComfort` and `hourScores` keep their current results when no course is given. The heading score is an extra rating and never replaces the day verdict's rules.
3. **R3** The Boat brief computes outbound and return courses from the existing water route (start → end bearing of the route polyline in `web/brief/run.ts` / `web/route.ts`). It renders a rose of 8 sector scores for the dock hour.
4. **R4** Comfort feedback pre-fills `heading`, `phase` and the hour's `wind`, `sea` and `period` from the trip plan and the forecast. The user can edit any field.
5. **R5** Calibration: `GET /api/comfort/calibration` returns, per owner and boat name, the mean residual (reported − model score) by sector group (head / beam / following) with counts. It needs at least 5 reports in a group. Residuals are shrunk toward 0 by `n / (n + 5)` and clamped to ±2 points.
6. **R6** The client applies the calibration offset to the heading scores and the day verdict only when the owner opts in (default on after 5 reports, with a visible "calibrated" tag and an off switch). Offsets are stored server-side with the account, never in links.
7. **R7** `docs/boat-profile.md` and `docs/conditions-model.md` are updated: the Limits section no longer says heading is ignored, and the new factors and calibration are listed.
8. **R8** Copy never says "safe", "unsafe" or "seaworthy". It keeps the "comfort estimate, not a safety clearance" wording.

## Acceptance

- Unit tests: head seas score ≤ beam ≤ following for the same hour, period and boat. With no course, `rateComfort` output is identical to before, checked by snapshot over the existing fixtures.
- The brief shows the rose with out and back marks for a Morro Bay spot. The scores change when the dock hour changes.
- Feedback fixtures with 6 head-sea reports averaging 1 point rougher produce a calibration of ≈ −0.55 (1 × 6/11). The verdict shows the "calibrated" tag.
- The text advisor comfort word (`server/advisor/answers/comfort.ts`) is unchanged unless it passes a course (regression test).

## Non-goals

- No phone-motion (accelerometer) ride recording in this increment. That is a follow-on spec, because it needs device permissions, battery work and privacy review.
- No physics-based sea-keeping model.
- No routing that optimises comfort.


---

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


---

# Tasks · 04 heading-aware comfort

- [ ] T1 `THRESHOLDS.heading` plus `headingRating`/`headingRose` with exhaustive unit tests, and a no-course regression snapshot over the existing score fixtures (R1, R2).
- [ ] T2 Out and back bearings from the water route, with tests (R3).
- [ ] T3 Ride by heading card in the Boat brief, accessible, en+es (R3, R8).
- [ ] T4 Feedback pre-fill (R4).
- [ ] T5 Calibration endpoint with shrinkage and clamp, with fixture tests (R5).
- [ ] T6 Client opt-in, "calibrated" tag and off switch (R6).
- [ ] T7 Docs: boat-profile Limits and conditions-model table (R7).
- [ ] T8 Advisor regression test (acceptance). Then run `pnpm typecheck && pnpm build && node --test tests/test_*.mjs && node scripts/check_copy.mjs`.

## Verification

Record a dated check of the rose on a phone for a real Morro Bay forecast, and a calibration run against the owner's real comfort reports (count only, no personal values in the PR).
