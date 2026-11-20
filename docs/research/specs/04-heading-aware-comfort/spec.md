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
