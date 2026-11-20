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
