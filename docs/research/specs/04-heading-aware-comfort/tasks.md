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
