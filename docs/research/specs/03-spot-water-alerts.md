<!-- Generated from 03-spot-water-alerts/spec.md, plan.md, tasks.md. Edit those, not this file. -->

# 03 · Water-condition alerts on saved spots, and new-data alerts

Status: proposed, 2026-11-19 · Priority 3 · Effort estimate: M · Depends on: none (reuses existing push and cron). Spec 02 is optional, for "new pass" wording.
Source: SkipperCast competitor analysis, recommendation 3 (Salty Offshore waypoint threshold alerts and new-pass alerts; SeaStatus change alerts).

## Intended goal

A signed-in angler can ask SkipperCast to tell them, by push notification, when the water at one of their private saved spots meets a condition they set, for example "surface temp at or above 58 °F" or "chlorophyll at or above 1 mg/m³". They can also ask to hear when a new satellite analysis for their region has landed.

## Purpose

Saved spots (`saved_spots`, up to 100, private) and saved-trip alerts (`trips` + `alert_events` + web push in `server/trips.ts`) already exist. Trip alerts only judge wind, gust and sea limits for a dated window. Anglers watch water, not just weather, and competitors sell spot thresholds. Reusing the existing cron (`*/15`), the queue, the push subscriptions and the R2 feeds keeps the cost small.

## User journey

1. Maya has a saved spot "Ridge 41". She opens its card (from the "Your saved spots" layer, or from the account panel) and taps **Watch water**.
2. A short sheet asks for: a layer (Water temp / Chlorophyll / Temp contrast), a comparison (≥ / ≤ / between), a value with its units, and an optional "only on days I could go" link to her boat's day verdict. She saves.
3. If notifications aren't enabled yet, the existing push permission flow runs. The watch is stored privately with the spot.
4. Each publication cycle, the server reads the region's newest observed layer at the spot's cell. If the condition becomes true (false → true), it sends one push: "Ridge 41: water temp 58.6 °F (NOAA Geo-Polar, Nov 19). Your watch: ≥ 58 °F." Tapping it opens the Chart centred on the spot with that layer on.
5. It doesn't repeat while the condition stays true. It can fire again after it has been false for at least one new analysis.
6. A separate toggle in the account panel, "New analysis landed for my region", sends at most one push per layer per day.
7. Maya can pause or delete any watch from the spot card or the account panel. Deleting the spot deletes its watches.

## Use cases

- **"Tell me when the 58° water reaches my canyon edge."**
- **"Tell me when the chlorophyll bloom backs off my reef"** (≤ threshold).
- **"Ping me when today's SST pass is in"** so they can plan the evening before.

## Requirements

1. **R1** A new private table `spot_watches` (owner, spot_id, layer, op, a, b, enabled, last_state, last_fired_at, last_sample_at, created_at). At most 5 watches per spot and 50 per owner. It is never read by a public route, feed or preview, matching the `saved_spots` privacy rule.
2. **R2** API: `GET/POST /api/spots/:id/watches`, `PATCH/DELETE /api/spots/:id/watches/:wid`, all owner-scoped and validated (layer ∈ {water-temp, chlorophyll, sst-contrast}; ops; finite values in the layer's valid range; `between` needs a < b).
3. **R3** Evaluation runs inside the existing trip-check path, once per new live publication (`server/trip-queue.ts`), reading the region's `habitat-dynamics.json` tiles from `FEEDS`. It samples the native cell containing the spot (no interpolation; outside the grid or a gap gives `unknown`).
4. **R4** It fires only on a false → true transition with a newer `sample_at` than the last evaluation. An `unknown` result never fires and never resets state.
5. **R5** Delivery reuses `subscriptions` and `sendPush`, with an idempotent event id `spotwatch:{wid}:{sample_at}`. Events go to a new `spot_alert_events` table, or to `alert_events` with `trip_id` made nullable plus a `kind` value. Choose one, and record the choice in an ADR (`docs/engineering/adr/`).
6. **R6** The message names the spot, the value with units, the product and the sample date, and the user's condition. It never says "fish", "bite" or "hot spot".
7. **R7** New-analysis alerts are per owner per region per layer, at most one a day.
8. **R8** The cost ceiling (`server/cost-ceiling.ts`) is respected: in degraded mode, no evaluation runs and nothing fires.
9. **R9** Deleting a spot cascades to its watches. **Export my records** includes the watches.

## Acceptance

- A fixture with two publications (57.8 °F, then 58.4 °F at the spot cell) and a watch ≥ 58 sends exactly one push on the second. A third publication at 58.9 sends nothing. A fourth at 57.5 then a fifth at 58.2 fires again.
- A spot inside a cloud gap evaluates as `unknown` and nothing fires.
- Re-delivering the queue message creates no second push.
- `node --test tests/test_*.mjs` and `pnpm typecheck` pass. The Drizzle migration is generated with `pnpm db:generate`.

## Non-goals

- No SMS or email. No public or shared watches. No watches on forecast layers in this increment. Swell and wind thresholds already exist through trips.
- No "fishing is good here" inference.


---

# Implementation plan · 03 spot water alerts

## Evidence in the repository (observed 2026-11-19, commit fa9c358)

- `db/schema.ts`: `savedSpots` (id, owner, name, lat, lon, note, created_at; private by design, no visibility column). `subscriptions` (web push endpoints). `events` = `alert_events` with `tripId` **notNull**. `receipts`.
- `server/routes/spots.ts`: owner CRUD, `MAX_SPOTS = 100`.
- `server/trips.ts`: `sendPush`, `pushConfigured`, `retryable`, `FeedCache`, `checkOwnerTrips`, `ownersWithDueTrips`, idempotent event claims.
- `server/trip-queue.ts`: cron → new live publication → one message per owner with due trips → consumer. `SETTLE_MS` waits for the R2 upload.
- `server/index.ts` `scheduled()` runs every 15 minutes (`wrangler.jsonc` `triggers.crons`).
- `server/env.ts`: `FEEDS` R2 bucket. `server/cost-ceiling.ts` sets degraded mode.
- Tile format: `web/map/habitat-feed.ts` (browser) documents tile checks. The server must apply the same checks (region, SHA-256, fields). Port the parsing to a shared module that is pure and DOM-free.
- UI: `web/map/saved-spots.ts` (owner-only layer), `web/saved-spots.ts`, `web/app/MarkCard.tsx`, `dist/account.js` (account panel), `web/app/TripAlerts.tsx`.

## Data model (Drizzle, `db/schema.ts`, new migration `drizzle/0020_spot_watches.sql`)

```ts
export const spotWatches = sqliteTable('spot_watches', {
  id: text('id').primaryKey(), owner: text('owner').notNull(), spotId: text('spot_id').notNull(),
  layer: text('layer').notNull(), op: text('op').notNull(), a: real('a').notNull(), b: real('b'),
  enabled: integer('enabled').notNull().default(1), lastState: text('last_state'), // 'true'|'false'|'unknown'
  lastSampleAt: text('last_sample_at'), lastFiredAt: text('last_fired_at'), createdAt: text('created_at').notNull(),
}, t => [index('spot_watch_owner').on(t.owner), index('spot_watch_spot').on(t.spotId)]);
export const regionDataAlerts = sqliteTable('region_data_alerts', {
  owner: text('owner').notNull(), region: text('region').notNull(), layer: text('layer').notNull(), lastSentDay: text('last_sent_day'),
}, t => [primaryKey({columns: [t.owner, t.region, t.layer]})]);
```

Recommended event storage: a new `spot_alert_events` table (id = `spotwatch:{wid}:{sample_at}`, owner, watch_id, message, status, created_at, delivered_at). This leaves trip alert semantics untouched. Record the decision in an ADR.

## API

| Method | Path | Body / result |
| --- | --- | --- |
| GET | `/api/spots/:id/watches` | `{watches: Watch[]}` |
| POST | `/api/spots/:id/watches` | `{layer, op, a, b?}` → 201 `Watch` |
| PATCH | `/api/spots/:id/watches/:wid` | `{enabled?, a?, b?, op?}` |
| DELETE | `/api/spots/:id/watches/:wid` | 200 / 404 |
| PUT | `/api/regions/:region/data-alerts` | `{layers: string[]}` |

Valid ranges: water-temp 28–95 °F, chlorophyll 0.01–100 mg/m³, sst-contrast 0–10 °F/nm.

## Architecture choices

- Evaluation lives in `server/spot-watches.ts` (new). `evaluateOwnerWatches(env, owner, feeds)` is called from the trip-queue consumer for owners with enabled watches. Extend `ownersWithDueTrips` with a union query, or add `ownersWithWatches`.
- Sampling: a shared pure module `packages/coast/src/habitat-sample.ts` (or `web/map/habitat-sample.ts` imported by the server, following the existing `server` → `web/score.ts` import precedent) that finds the native cell for (lat, lon) given the tile grid and resolution.
- The transition logic is a pure function (`nextWatchState(prev, value, sampleAt) → {state, fire}`), unit-tested exhaustively.

## Files to create or modify

| File | Change |
| --- | --- |
| `db/schema.ts`, `drizzle/0020_spot_watches.sql` (generated) | tables |
| `server/routes/spots.ts` | watch routes, cascade on spot delete |
| `server/spot-watches.ts` (new) | evaluation + delivery |
| `server/trip-queue.ts`, `server/trips.ts` | include watch owners; reuse `sendPush` |
| `server/routes/account.ts` | privacy export includes watches |
| `web/app/MarkCard.tsx`, `web/saved-spots.ts`, `dist/account.js` | Watch water sheet and list |
| `catalog/app/strings.json` | `spot.watch.*`, push message templates en+es |
| `tests/test_spot_watches.mjs` (new), `tests/test_spot_watch_routes.mjs` (new) | |
| `docs/web-app.md` (Account), `docs/operations/runbooks/trip-checks.md` | document |

## UX details

- The sheet uses existing form primitives. The value field shows units from the user's unit choice (°F/°C via `web/app/UnitChoice.tsx`). Storage is always °F and mg/m³.
- The push body is at most 120 characters. The URL is `/map?region=…&spot=<spotId>&layers=water-temp`.
- The spot card shows "Watching: ≥ 58 °F · last read 57.6 °F (Nov 19)".

## Edge cases

- A spot outside the region bounds: the watch can't be created ("outside this region's data").
- The layer is withheld (stale): `unknown`, no fire.
- An owner without a push subscription: the watch is stored, and the card says "Turn on notifications to receive this".
- Spanish users: the message uses the owner's last language (store it with the subscription if it isn't already).

## Dependencies

- None hard. If spec 02 lands, new-analysis alerts can say "new pass" using history metadata.


---

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
