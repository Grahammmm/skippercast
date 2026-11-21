# Tasks · 02 observed look-back

- [ ] T1 Pipeline history append/trim for `sst-analysis` and `chlorophyll-observation`, tile retention, manifest `history`. Offline pytest with fixture tiles covering 0, 1 and 8 days (R1, R2).
- [ ] T2 Dated `sst-fronts` output plus index, with a test (R2).
- [ ] T3 Add `fetch_for_date` (exact dated file from the same catalogs; depth verified 2026-11-19) and a `--backfill-days 7` flag (R9).
- [ ] T4 R2 lifecycle rule and feed-health/layer-inventory entries. Run `python scripts/check_repository.py` (R1).
- [ ] T5 `habitat-feed.ts` history parse and verify, plus `loadHistoryDay`. Test a tampered tile, a wrong region and a path escape (R3).
- [ ] T6 Dock past segment (`hour.ts`, `TimeDock.tsx`, `dock-selection.ts`, `state.ts`, `share-link.ts`). Tests for DST, missing days and the link round-trip (R4, R7, R8).
- [ ] T7 Layer gates: observed layers draw the past frame, forecast layers hide with a reason (R5, R6).
- [ ] T8 Strings en+es, then run `node scripts/check_copy.mjs`.
- [ ] T9 e2e: select −2d, the legend date changes and swell hides. Play skips a missing day.
- [ ] T10 Update `docs/web-app.md` (time dock) and `docs/data-feed-readme.md` (history fields) in the same PR series.

## Verification

Record dated results here (pipeline run on a real region, R2 object count and bytes, phone check).
