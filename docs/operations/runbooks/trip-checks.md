# Runbook: saved-trip alerts are late or missing

**Symptom:** people report no trip alert (push or in-app) after conditions changed; the *Live regional conditions and trip alerts* `notify` job is red; the Worker logs show `trip_check_dead_letter` or `Trip check enqueue failed`.
**Severity:** SEV3 when alerts are late for everyone; SEV2 when a final (evening-before) alert was missed for everyone. See [incident response](../incident-response.md).
**Owner:** repository owner. An agent may diagnose and open fix PRs; only the owner changes variables, secrets or queues.

## Which path is running

- **`ENABLE_QUEUES` unset or not `true`** (the default): the GitHub `notify` job runs `scripts/trip_check_loop.py`, which calls `POST /api/jobs/check` once per new publication. Its step summary shows the totals.
- **`ENABLE_QUEUES=true`**: the Worker cron (`server/trip-queue.ts`) queues one message per owner to `skippercast-trip-checks` after each new publication; the consumer checks them. See [Cloudflare: trip-check queue](../../cloudflare.md#trip-check-queue).

## Detect (queue path)

1. **Workers & Pages → skippercast → Logs** (Workers Logs), filtered on:
   - `trip_check_schedule`: one line per cron run that did something. `"action":"enqueued"` with `owners` and `batches`; `"unchanged"` means that publication was already queued; `"settling"` means it is under 2 minutes old; `"no-feed"` means `conditions/latest.json` could not be read (see [feed stale](feed-stale.md)); `"enqueue-failed"` means a send failed and the next cron run retries.
   - `trip_check_batch`: one line per consumer batch with `owners`, `checked`, `changes`, `delivered`, `held`, `in_app`, `retried`.
   - `trip_check_dead_letter`: messages that failed 4 times.
2. **Workers & Pages → Queues → skippercast-trip-checks**: backlog, delivery rate and retries. A growing backlog means the consumer is failing or too slow.
3. The last publication queued: `npx wrangler d1 execute skippercast --remote --command "SELECT * FROM job_state"`.

## Respond

- **Dead letters or retries across all owners** usually mean D1 or a feed read is failing. Check D1 status and the [feed stale](feed-stale.md) runbook. Nothing needs replaying: every owner is queued again with the next publication, and events are idempotent.
- **`enqueue-failed` repeating**: check the Cloudflare status page for Queues, the free-plan operations allowance (10,000 a day; see the cost note in [Cloudflare](../../cloudflare.md#trip-check-queue)), and the deploy token. To fall back at once, set `ENABLE_QUEUES` to `false` and run **Deploy to Cloudflare**; the next live run's `notify` job takes over.
- **To check trips now**, without waiting for a publication: run **Actions → Live regional conditions and trip alerts → Run workflow** with **check_trips** ticked. It pages through all due trips via `/api/jobs/check`.
- **To re-queue the current publication**: `npx wrangler d1 execute skippercast --remote --command "DELETE FROM job_state WHERE key='trip_checks.publication'"`; the next cron run (within 15 minutes) queues every owner again. Re-checks are safe: they send nothing new unless the assessment changed.
- **Held deliveries** (`held` > 0) are ambiguous push sends. Do not resend by creating a new event id; see [production operations](../../production-operations.md).
