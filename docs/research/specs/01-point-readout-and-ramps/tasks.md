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
