# 0010. Store spot-watch alert events separately

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Roadmap 03 defines private, owner-scoped spot watches (R1), idempotent push delivery (R5), and watch deletion and export (R9). [`nextWatchState` (`server/spot-watch-state.ts:33–49`)](../../../server/spot-watch-state.ts#L33-L49) fires only on a false-to-true transition for a newer sample. Queue redelivery still needs a durable event identity so replaying a sample does not create another push. The existing trip event table requires a trip ID ([`db/schema.ts:36–40`](../../../db/schema.ts#L36-L40)); a saved-spot watch can fire without a trip.

## Decision

Store spot-watch deliveries in a new private `spot_alert_events` table, as recommended by the plan: `id` (primary key, `spotwatch:{wid}:{sample_at}`), `owner`, `watch_id`, `message`, `status`, `created_at`, and `delivered_at`. Keep access owner-scoped and out of public routes, feeds, and previews. Leave `alert_events` and its trip semantics unchanged. Roadmap 03 has no owner decision gate, so this ADR is Accepted.

## Consequences

- (+) Delivery work (T6) can claim the event by ID before sending, reusing `subscriptions` and [`sendPush` (`server/trips.ts:102–103`)](../../../server/trips.ts#L102-L103) without changing trip storage. `sendPush` attempts delivery; it does not persist the event or deduplicate it.
- (–) T2 must add the table to [`db/schema.ts`](../../../db/schema.ts) and generate a migration. With that schema change, update the D1 restore runbook: add an [inventory row](../../operations/runbooks/d1-restore.md#L25), a [row-count query entry](../../operations/runbooks/d1-restore.md#L121), and a [`DROP TABLE` statement](../../operations/runbooks/d1-restore.md#L219).
- (–) The privacy follow-up must include watches and owner-scoped spot alert events in the [account export (`server/routes/account.ts:33`)](../../../server/routes/account.ts#L33) and remove them on [account deletion (`server/routes/account.ts:42`)](../../../server/routes/account.ts#L42). If delivery uses `delivery_receipts`, remove linked receipts before deleting their events in the same operation.
- (–) Extend [`prune` (`server/trips.ts:150–154`)](../../../server/trips.ts#L150-L154) to remove spot alert events once `created_at` is more than 90 days old, deleting any linked receipts first. This matches the existing [trip event retention rule](../../operations/runbooks/d1-restore.md#L25) without changing it.

## Alternatives

- Make `trip_id` nullable in `alert_events` and use a new value in the existing `kind` column. This changes trip-alert semantics and the [`notNull` constraint (`db/schema.ts:37`)](../../../db/schema.ts#L37). Every query that assumes an event belongs to a trip would need review, including [trip deletion](../../../server/routes/trips.ts#L58).
- Reuse only [`delivery_receipts`](../../../db/schema.ts#L41-L44). Receipts describe per-subscription attempts, not an owner-scoped event with a message and lifecycle. They cannot serve as the single event claim across subscriptions or record one when there are no subscriptions.

## Links

- Roadmap 03: [requirements R1, R5, R9](../../research/specs/03-spot-water-alerts/spec.md#requirements), [data model and recommended event storage](../../research/specs/03-spot-water-alerts/plan.md#L14-L28), and [build tasks](../../research/specs/03-spot-water-alerts/tasks.md).
- [Roadmap owner gates](../../research/specs/README.md#L15) and [ADR status rules](0001-record-architecture-decisions.md#L37-L41).
