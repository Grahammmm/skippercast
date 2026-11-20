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
