# Tasks · 03 spot water alerts

- [ ] T1 ADR: event storage choice (new table vs nullable `trip_id`) (R5).
- [ ] T2 Schema plus the generated migration. Run `pnpm db:generate` and `node scripts/check_d1_restore.mjs` if relevant (R1).
- [ ] T3 Watch routes with validation and owner scoping, plus cascade. Route tests (R2, R9).
- [ ] T4 Shared native-cell sampler, with tests for inside, gap and outside (R3).
- [ ] T5 `nextWatchState` pure transition. Exhaustive tests (R4).
- [ ] T6 Evaluation in the queue consumer, idempotent delivery via `sendPush`, cost-ceiling guard. Fixture tests with sequential publications (R3–R5, R8).
- [ ] T7 New-analysis alerts (R7).
- [ ] T8 UI: Watch water sheet on the spot card, list in the account panel, strings en+es (R6).
- [ ] T9 Privacy export plus docs (R9).
- [ ] T10 Full checks: `pnpm typecheck && pnpm build && node --test tests/test_*.mjs && node scripts/check_copy.mjs`.

## Verification

Record a dated staging push test (real device), a queue re-delivery test, and the D1 migration apply.
