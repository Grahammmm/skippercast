# Runbook: restore the D1 database

**Symptom:** private records (accounts and passkeys, saved trips, alert events, notification devices, comfort feedback, the private catch log and saved spots, Text Advisor and charter-fleet data) are missing, wrong or corrupt after a migration, a bad deploy or a mistaken manual query; or private routes answer `503 "This service is temporarily unavailable. Your existing records are preserved."` because the database is unreachable.
**Severity:** SEV1 if records were exposed to the wrong person; SEV2 for loss or corruption of user records; SEV3 for a D1 outage with records intact (private features unavailable, public map unaffected). See [incident response](../incident-response.md).
**Owner:** repository owner. Restores overwrite user data and must be done by the owner, never by an agent.

**Where this applies today:**

- **ChatGPT Sites (skippercast.com):** the platform provisions the `DB` binding from `.openai/hosting.json` and applies `drizzle/` migrations. There is no Wrangler access to that database; restores there go through the Sites platform. Escalate (below).
- **Cloudflare (`skippercast` D1 database):** the commands in this runbook. The database holds every table in the inventory below (accounts, trips, the Text Advisor and the charter fleet registry), whether or not a feature is switched on in a given deployment, so the procedure covers all of them.

## What is in the database

Every table `db/schema.ts` defines (migrations in `drizzle/`) plus Wrangler's `d1_migrations`. The inventory lists each table once with what it holds, how current code retires its rows and where. It holds personal data: treat every export as confidential. A new table in `db/schema.ts` must be added to the inventory, the count query and the clear list below; `node scripts/check_d1_restore.mjs` (run in CI) fails until it is.

Retention here is what the code does today, not a promise. "No automatic age-based deletion found in current code" means exactly that: the rows stay until an explicit supported deletion or replacement, and no other table's age limit applies to them. The ages are measured as the code measures them (`server/trips.ts` `prune`, `server/advisor/retention.ts`). Restoring D1 does not restore media objects in R2 (`ADVISOR_MEDIA`, `skippercast-backups`) and does not reverse messages, posts or pushes already sent.

<!-- d1-restore:inventory:start -->
| Table | Contents / sensitivity | Retention / deletion in current code | Source |
| --- | --- | --- | --- |
| `trips` | Saved trip plans: owner id, point, limits, boat, plan JSON. Private. | Deleted 90 days after the trip date by `prune`; the owner deletes one trip; account deletion removes all of the owner's. | `server/trips.ts` `prune`; `server/routes/trips.ts` `DELETE /api/trips`; `server/routes/account.ts` `DELETE /api/privacy` |
| `catch_log` | The account's private effort log, with coordinates. Private. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement: the owner deletes one entry, or account deletion removes all. | `server/routes/catch-log.ts` `DELETE /api/catch-log/:id`; `server/routes/account.ts` `DELETE /api/privacy` |
| `saved_spots` | The account's private saved places, with coordinates. Private. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement: the owner deletes one spot, or account deletion removes all. | `server/routes/spots.ts` `DELETE /api/spots/:id`; `server/routes/account.ts` `DELETE /api/privacy` |
| `subscriptions` | Web push endpoints and keys. Private. | No age limit. Deleted when the owner turns alerts off, when a push endpoint answers 404 or 410 (expired), and by account deletion. | `server/routes/subscriptions.ts` `DELETE /api/subscription`; `server/trips.ts` `deliver`; `server/routes/account.ts` |
| `alert_events` | Trip alert messages. Private. | Deleted 90 days after `created_at` by `prune`; deleted with their trip or the account. | `server/trips.ts` `prune`; `server/routes/trips.ts`; `server/routes/account.ts` |
| `delivery_receipts` | Push delivery attempts per event and subscription. | Deleted with their events: `prune` selects receipts through events older than 90 days and has no age test of its own; also deleted with a trip or the account. | `server/trips.ts` `prune`; `server/routes/trips.ts`; `server/routes/account.ts` |
| `comfort_feedback` | Comfort ratings with owner and region. Private. | Deleted 365 days after `observed_at` by `prune`; account deletion removes the owner's. | `server/trips.ts` `prune`; `server/routes/account.ts` |
| `request_limits` | Rate-limit counters. No user data. | Deleted once `expires_at` has passed, by `prune`. | `server/trips.ts` `prune` |
| `users` | Accounts: id, display name, admin role. No password or email. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement: account deletion. | `server/auth.ts` `deleteAccountStatements`; `server/routes/account.ts` `DELETE /api/privacy` |
| `passkeys` | Passkey public keys per user. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement: the owner removes one passkey while another remains, or account deletion removes all. | `server/auth.ts` passkey removal and `deleteAccountStatements` |
| `sessions` | Sign-in sessions (sha256 of the cookie token, user agent). | Deleted once `expires_at` has passed, by `prune` and when read; deleted at sign-out or sign-in; account deletion removes the user's. | `server/trips.ts` `prune`; `server/auth.ts` `sessionUser`, `authRoute` |
| `auth_challenges` | Single-use sign-in challenges. | Deleted when used and once `expires_at` has passed, by `prune`; account deletion removes the user's. | `server/auth.ts` `consumeChallenge`; `server/trips.ts` `prune` |
| `job_state` | Shared key/value state for background jobs: advisor flow, link, share and once-markers, caption and graphic keys, fleet heartbeat and processed markers. | No whole-table age limit. Only the advisor keys named in `AGED_KEY_PREFIXES` (and the listed once-marker and graphic cases) are deleted 30 days after `updated_at`; `forgetContact` deletes a contact's keys; every other key stays until its job deletes or overwrites it. | `server/advisor/retention.ts` `pruneJobState`; `server/advisor/contacts.ts` `forgetContact` |
| `advisor_contacts` | Text Advisor people: phone hash, encrypted phone, web session, Instagram id. Private. | Web-only contacts inactive 90 days are erased weekly through `forgetContact` (bounded per run); contacts reached by phone or Instagram have no age rule; "forget me" erases on request. | `server/advisor/retention.ts` `pruneContacts`; `server/advisor/contacts.ts` `forgetContact` |
| `advisor_boats` | Skipper boats and consent records. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. Erasing the owner keeps the boat and clears `owner_contact_id`. | `server/advisor/contacts.ts` `forgetContact` |
| `advisor_crew` | Crew who may post for a boat; removal sets `removed_at`. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement: `forgetContact` deletes a contact's crew rows. | `server/advisor/contacts.ts` `forgetContact` |
| `advisor_messages` | Every inbound and outbound message. Private. | The `body` is set to NULL 180 days after `created_at` and the row stays; the row is deleted only by `forgetContact` (including the 90-day web-only contact rule). | `server/advisor/retention.ts` `pruneBodies`, `pruneContacts`; `server/advisor/contacts.ts` `forgetContact` |
| `advisor_media` | Photo, video and audio metadata and R2 keys. Private. | Unreferenced originals older than 90 days: the R2 object goes and the row stays with a cleared key; the row is deleted only by `forgetContact`. Restoring D1 does not bring the R2 object back. | `server/advisor/retention.ts` `pruneMedia`; `server/advisor/contacts.ts` `forgetContact` |
| `advisor_reports` | Skipper fish reports, the boat's record. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. `forgetContact` keeps the report and clears `contact_id`. | `server/advisor/contacts.ts` `forgetContact` |
| `advisor_report_edits` | Corrections to reports. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement: `forgetContact` deletes a contact's edits. | `server/advisor/contacts.ts` `forgetContact` |
| `advisor_reviews` | The admin review queue. | Decided reviews are deleted 90 days after `decided_at`; open reviews stay; `forgetContact` deletes reviews about the contact's messages and media. | `server/advisor/retention.ts` `pruneReviews`; `server/advisor/contacts.ts` `forgetContact` |
| `advisor_rules` | Regulation rows the advisor may quote. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. Retired rows stay in the table. | `server/advisor/retention.ts` (no rule for this table) |
| `advisor_daily_answers` | Cached daily answer per port and day. | Deleted 30 days after `generated_at`; also deleted for a port when a new report invalidates its answer. | `server/advisor/retention.ts` `pruneDaily`; `server/advisor/intake/reports.ts` `invalidateDailyAnswer` |
| `advisor_posts` | Social posts in any state, with captions and Meta ids. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement: `forgetContact` deletes posts of a contact's photos that never went out; a posted one stays. | `server/advisor/contacts.ts` `forgetContact` |
| `advisor_post_stats` | Insights per post, platform and day. | Deleted 730 days after `day`. | `server/advisor/retention.ts` `pruneStats` |
| `fleet_operators` | Charter operators: business contact, consent, outreach status. Private registry data. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_operators` (no `DELETE` under `server/`) |
| `fleet_vessels` | One row per charter vessel with resolved fields and consent. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_vessels` (no `DELETE` under `server/`) |
| `fleet_vessel_facts` | Observed values with provenance. | Not an age limit: the `fact.purge` operation deletes the facts of one source in one region last seen before a given time, except kept fields. | `server/fleet/registry.ts` `applyRegistry` |
| `fleet_aliases` | Other names a vessel goes by. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_aliases` (no `DELETE` under `server/`) |
| `fleet_offerings` | Trips a vessel sells, with prices. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_offerings` (no `DELETE` under `server/`) |
| `fleet_departures` | Dated departures where a schedule is published. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_departures` (no `DELETE` under `server/`) |
| `fleet_reviews` | The fleet review queue. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_reviews` (no `DELETE` under `server/`) |
| `fleet_changes` | Detected changes to vessels. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_changes` (no `DELETE` under `server/`) |
| `fleet_outreach` | Private outreach notes and drafts. Never sent by code. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. The schema comment says an operator's removal request deletes these rows, but no `DELETE` for the table exists under `server/`. | `db/schema.ts` `fleet_outreach`; `server/fleet/admin/operators.ts` |
| `fleet_link_clicks` | Outbound link click counts per vessel, target, placement and day. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_link_clicks` (no `DELETE` under `server/`) |
| `fleet_runs` | One row per pipeline step run or job call. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_runs` (no `DELETE` under `server/`) |
| `fleet_ais_watch` | MMSIs the listener watches and candidates. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement. | `db/schema.ts` `fleet_ais_watch` (no `DELETE` under `server/`) |
| `fleet_trips` | Derived port-to-port trips of watched vessels. | Not an age limit: replaced per MMSI, source and departure window each time the activity push reprocesses it. | `server/fleet/activity.ts` `activity` |
| `fleet_segments` | Derived classified stretches of a trip. | Not an age limit: replaced with their trips by the activity push. | `server/fleet/activity.ts` `activity` |
| `fleet_events` | Derived fishing events per segment. | Not an age limit: replaced with their trips by the activity push. | `server/fleet/activity.ts` `activity` |
| `fleet_aggregates` | Binned events from an aggregate module. | Not an age limit: deleted by id, or replaced per region, season and module when the push names a prune marker. | `server/fleet/activity.ts` `activity` |
| `fleet_segment_labels` | Validation labels on a trip's time range; they survive reprocessing. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement: an admin deletes one label, or an agent import replaces that labeller's labels on a trip. | `server/fleet/admin/labels.ts` `deleteLabel`, `importAgentLabels` |
| `fleet_ais_hours` | Listener counters per region and UTC hour. | No automatic age-based deletion found in current code; retained until an explicit supported deletion/replacement; rows are upserted per region and hour. | `server/fleet/activity.ts` `heartbeat` |
| `fleet_trip_reports` | Catch-log pairing of trips with reports. | Not an age limit: removed when a pairing no longer holds, or when its trip is replaced. | `server/fleet/pairing.ts` `advisorPrune`, `landingPrune`; `server/fleet/activity.ts` `activity` |
| `d1_migrations` | Wrangler's migration history. | Not an application retention job: kept until a whole-database restore or a migration-history change. | Wrangler (`$W d1 migrations`) |
<!-- d1-restore:inventory:end -->

## Recovery points

1. **D1 Time Travel** (always on): restore to any minute inside the retention window. Wrangler's help says "within the last 30 days"; Cloudflare documents a shorter window on the Workers Free plan, so check the plan before relying on an older point.
2. **Pre-migration exports** (after PR #26, [P0-03], merges): `scripts/cloudflare_deploy.sh` logs `D1 restore bookmark before migrations: <bookmark>` and uploads `wrangler d1 export` output to the private bucket `skippercast-backups` at `d1/<UTC stamp>-<commit>.sql`. PR #26 also adds the runbook `docs/operations/runbooks/rollback-release.md` for rolling back the Worker code together with a migration.

## Detect

```bash
export SITE=https://skippercast.example.workers.dev    # the CLOUDFLARE_SITE_URL repository variable
curl -sS "$SITE/api/session"                              # public; must answer 200
curl -sS -o /dev/null -w '%{http_code}\n' "$SITE/api/trips"   # 401 without a session; 503 = storage failure
```

Worker logs show `SkipperCast request failed` with `type: "dependency"` for storage errors:

```bash
npx --yes wrangler@4.142.0 tail skippercast --format pretty --status error
```

## Diagnose (in order)

Work from an empty directory (so Wrangler ignores the placeholder id in the repository's `wrangler.jsonc`) with the owner's credentials:

```bash
cd "$(mktemp -d)"
export CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=...
W="npx --yes wrangler@4.142.0"
```

1. **Is D1 up?** Check cloudflarestatus.com, then `$W d1 info skippercast`. A platform outage with intact data needs no restore: wait, keep the incident open, verify afterwards.
2. **What is in it now?** Copy the SQL between the `d1-restore:counts` markers below, exactly, into a local `restore-counts.sql`, then:
   ```bash
   $W d1 execute skippercast --remote --command "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
   $W d1 execute skippercast --remote --file restore-counts.sql
   $W d1 execute skippercast --remote --command "SELECT id, name, applied_at FROM d1_migrations ORDER BY id"
   ```
   The table list must be the inventory plus SQLite's and Cloudflare's internal tables (`sqlite_*`, `_cf_*`); the counts query returns one row per inventory table. Save all three outputs with the incident notes.
3. **When did it go wrong?** Match the damage to a deploy (Actions → *Deploy to Cloudflare* run times, or `$W deployments list --name skippercast`) or to a manual command. Pick the restore time: the last minute before the damage.
4. **Save the current point first,** so the restore itself can be undone:
   ```bash
   $W d1 time-travel info skippercast --json | tee "before-restore-$(date -u +%Y%m%dT%H%M%SZ).json"
   ```
   Keep the printed `bookmark`.

The counts query is the one complete count check. Run it for Diagnose, for the scratch rehearsal and for Verify, and compare each result only with a saved result from the same recovery point. A trips count alone proves nothing about the other tables, and counts from different recovery points are not expected to be equal.

<!-- d1-restore:counts:start -->
```sql
SELECT 'trips' AS table_name, COUNT(*) AS row_count FROM trips
UNION ALL SELECT 'catch_log' AS table_name, COUNT(*) AS row_count FROM catch_log
UNION ALL SELECT 'saved_spots' AS table_name, COUNT(*) AS row_count FROM saved_spots
UNION ALL SELECT 'subscriptions' AS table_name, COUNT(*) AS row_count FROM subscriptions
UNION ALL SELECT 'alert_events' AS table_name, COUNT(*) AS row_count FROM alert_events
UNION ALL SELECT 'delivery_receipts' AS table_name, COUNT(*) AS row_count FROM delivery_receipts
UNION ALL SELECT 'comfort_feedback' AS table_name, COUNT(*) AS row_count FROM comfort_feedback
UNION ALL SELECT 'request_limits' AS table_name, COUNT(*) AS row_count FROM request_limits
UNION ALL SELECT 'users' AS table_name, COUNT(*) AS row_count FROM users
UNION ALL SELECT 'passkeys' AS table_name, COUNT(*) AS row_count FROM passkeys
UNION ALL SELECT 'sessions' AS table_name, COUNT(*) AS row_count FROM sessions
UNION ALL SELECT 'auth_challenges' AS table_name, COUNT(*) AS row_count FROM auth_challenges
UNION ALL SELECT 'job_state' AS table_name, COUNT(*) AS row_count FROM job_state
UNION ALL SELECT 'advisor_contacts' AS table_name, COUNT(*) AS row_count FROM advisor_contacts
UNION ALL SELECT 'advisor_boats' AS table_name, COUNT(*) AS row_count FROM advisor_boats
UNION ALL SELECT 'advisor_crew' AS table_name, COUNT(*) AS row_count FROM advisor_crew
UNION ALL SELECT 'advisor_messages' AS table_name, COUNT(*) AS row_count FROM advisor_messages
UNION ALL SELECT 'advisor_media' AS table_name, COUNT(*) AS row_count FROM advisor_media
UNION ALL SELECT 'advisor_reports' AS table_name, COUNT(*) AS row_count FROM advisor_reports
UNION ALL SELECT 'advisor_report_edits' AS table_name, COUNT(*) AS row_count FROM advisor_report_edits
UNION ALL SELECT 'advisor_reviews' AS table_name, COUNT(*) AS row_count FROM advisor_reviews
UNION ALL SELECT 'advisor_rules' AS table_name, COUNT(*) AS row_count FROM advisor_rules
UNION ALL SELECT 'advisor_daily_answers' AS table_name, COUNT(*) AS row_count FROM advisor_daily_answers
UNION ALL SELECT 'advisor_posts' AS table_name, COUNT(*) AS row_count FROM advisor_posts
UNION ALL SELECT 'advisor_post_stats' AS table_name, COUNT(*) AS row_count FROM advisor_post_stats
UNION ALL SELECT 'fleet_operators' AS table_name, COUNT(*) AS row_count FROM fleet_operators
UNION ALL SELECT 'fleet_vessels' AS table_name, COUNT(*) AS row_count FROM fleet_vessels
UNION ALL SELECT 'fleet_vessel_facts' AS table_name, COUNT(*) AS row_count FROM fleet_vessel_facts
UNION ALL SELECT 'fleet_aliases' AS table_name, COUNT(*) AS row_count FROM fleet_aliases
UNION ALL SELECT 'fleet_offerings' AS table_name, COUNT(*) AS row_count FROM fleet_offerings
UNION ALL SELECT 'fleet_departures' AS table_name, COUNT(*) AS row_count FROM fleet_departures
UNION ALL SELECT 'fleet_reviews' AS table_name, COUNT(*) AS row_count FROM fleet_reviews
UNION ALL SELECT 'fleet_changes' AS table_name, COUNT(*) AS row_count FROM fleet_changes
UNION ALL SELECT 'fleet_outreach' AS table_name, COUNT(*) AS row_count FROM fleet_outreach
UNION ALL SELECT 'fleet_link_clicks' AS table_name, COUNT(*) AS row_count FROM fleet_link_clicks
UNION ALL SELECT 'fleet_runs' AS table_name, COUNT(*) AS row_count FROM fleet_runs
UNION ALL SELECT 'fleet_ais_watch' AS table_name, COUNT(*) AS row_count FROM fleet_ais_watch
UNION ALL SELECT 'fleet_trips' AS table_name, COUNT(*) AS row_count FROM fleet_trips
UNION ALL SELECT 'fleet_segments' AS table_name, COUNT(*) AS row_count FROM fleet_segments
UNION ALL SELECT 'fleet_events' AS table_name, COUNT(*) AS row_count FROM fleet_events
UNION ALL SELECT 'fleet_aggregates' AS table_name, COUNT(*) AS row_count FROM fleet_aggregates
UNION ALL SELECT 'fleet_segment_labels' AS table_name, COUNT(*) AS row_count FROM fleet_segment_labels
UNION ALL SELECT 'fleet_ais_hours' AS table_name, COUNT(*) AS row_count FROM fleet_ais_hours
UNION ALL SELECT 'fleet_trip_reports' AS table_name, COUNT(*) AS row_count FROM fleet_trip_reports
UNION ALL SELECT 'd1_migrations' AS table_name, COUNT(*) AS row_count FROM d1_migrations;
```
<!-- d1-restore:counts:end -->

## Fix

Prefer the least destructive option that works.

**A. Forward fix (bad data from a migration, schema otherwise fine).** Write a corrective migration in a PR (`pnpm run db:generate` after editing `db/schema.ts`, or a hand-written SQL file in `drizzle/` with its journal entry). Never edit a migration that has already been applied.

**B. Time Travel restore in place.** Restores the whole database, including `d1_migrations`, to the chosen point:

```bash
$W d1 time-travel restore skippercast --timestamp 2026-09-28T17:05:00Z    # RFC 3339 or Unix seconds
# or, with the bookmark logged by a deploy (after PR #26):
$W d1 time-travel restore skippercast --bookmark <bookmark>
```

If the restore point is before a migration that the deployed Worker needs, roll the Worker back to the matching version as well (`$W versions list --name skippercast`, then `$W rollback <version-id> --name skippercast --message "match D1 restore"`), or redeploy after re-applying migrations.

**C. Restore from an export (outside the Time Travel window; after PR #26).** The owner alone runs this. The export contains `CREATE TABLE` statements for every table, so every existing table must be dropped first; a table left behind makes its `CREATE` fail part way through the load. The drop list below is the clear list for the whole database, in an order that removes dependent rows before their parents, and it is the only list to use: never build `DROP` statements from `sqlite_master`, never skip a table and never turn off foreign-key enforcement. If a future real foreign key stops this order working, the scratch rehearsal fails: revise the documented order, do not work around it.

<!-- d1-restore:clear:start -->
```sql
DROP TABLE IF EXISTS advisor_post_stats;
DROP TABLE IF EXISTS advisor_posts;
DROP TABLE IF EXISTS advisor_report_edits;
DROP TABLE IF EXISTS advisor_reviews;
DROP TABLE IF EXISTS advisor_reports;
DROP TABLE IF EXISTS advisor_crew;
DROP TABLE IF EXISTS advisor_media;
DROP TABLE IF EXISTS advisor_messages;
DROP TABLE IF EXISTS advisor_rules;
DROP TABLE IF EXISTS advisor_daily_answers;
DROP TABLE IF EXISTS advisor_boats;
DROP TABLE IF EXISTS advisor_contacts;
DROP TABLE IF EXISTS fleet_trip_reports;
DROP TABLE IF EXISTS fleet_segment_labels;
DROP TABLE IF EXISTS fleet_events;
DROP TABLE IF EXISTS fleet_segments;
DROP TABLE IF EXISTS fleet_trips;
DROP TABLE IF EXISTS fleet_departures;
DROP TABLE IF EXISTS fleet_offerings;
DROP TABLE IF EXISTS fleet_vessel_facts;
DROP TABLE IF EXISTS fleet_aliases;
DROP TABLE IF EXISTS fleet_ais_watch;
DROP TABLE IF EXISTS fleet_link_clicks;
DROP TABLE IF EXISTS fleet_changes;
DROP TABLE IF EXISTS fleet_vessels;
DROP TABLE IF EXISTS fleet_outreach;
DROP TABLE IF EXISTS fleet_operators;
DROP TABLE IF EXISTS fleet_aggregates;
DROP TABLE IF EXISTS fleet_ais_hours;
DROP TABLE IF EXISTS fleet_runs;
DROP TABLE IF EXISTS fleet_reviews;
DROP TABLE IF EXISTS delivery_receipts;
DROP TABLE IF EXISTS alert_events;
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS trips;
DROP TABLE IF EXISTS catch_log;
DROP TABLE IF EXISTS saved_spots;
DROP TABLE IF EXISTS passkeys;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS auth_challenges;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS comfort_feedback;
DROP TABLE IF EXISTS request_limits;
DROP TABLE IF EXISTS job_state;
DROP TABLE IF EXISTS d1_migrations;
```
<!-- d1-restore:clear:end -->

**Before production is cleared, all of these must hold.** If any does not, or if the production table list shows a table the inventory does not name, or the inventory names a table the export does not create, print and obey:

> **STOP: schema or counts do not match the reviewed restore; do not clear production.**

There is no automatic remediation and no "ignore the extra table" step: escalate to the owner's review, fix the runbook or choose another recovery point.

1. A recovery bookmark from Diagnose step 4 and a current confidential export of production (`$W d1 export skippercast --remote --output current-before-restore.sql`) exist.
2. The export's source revision is known (`<stamp>-<commit>` in its name), its `d1_migrations` rows match the migration journal (`drizzle/meta/_journal.json`) at that commit, and the deployed Worker version matches that journal (see B).
3. The table inventory is known: the production table list from Diagnose step 2 is the inventory plus internal tables, and every table the export creates is in the inventory.
4. Writers and cron are quiet for the whole clear-and-load: the Worker's scheduled handler, the fleet activity and heartbeat pushes, the Text Advisor webhooks and any Actions job that calls the job endpoints are paused, and `wrangler tail` shows no writing requests.
5. The scratch rehearsal below ran with the same files and its counts were reviewed and saved.

**Rehearse in a scratch database first,** the same clear, import and count sequence you will run on production, on a scratch database the owner creates for this and that already holds the tables, not an empty one:

```bash
$W r2 object get "skippercast-backups/d1/<stamp>-<commit>.sql" --remote --file restore.sql
$W d1 create skippercast-restore-check
$W d1 execute skippercast-restore-check --remote --file restore.sql --yes              # first load: the scratch now holds every table
$W d1 execute skippercast-restore-check --remote --file restore-counts.sql            # save as expected-counts.txt and review it
$W d1 execute skippercast-restore-check --remote --yes --file restore-clear.sql       # the clear block above, copied exactly
$W d1 execute skippercast-restore-check --remote --yes --file restore.sql             # must load with no "already exists" error
$W d1 execute skippercast-restore-check --remote --file restore-counts.sql            # must equal expected-counts.txt row for row
```

`restore-counts.sql` and `restore-clear.sql` are the text between the markers above, copied as is. If the second load reports that a table already exists, a table is missing from the clear list: STOP as above. Delete the scratch database only after the owner has read the counts.

When the rehearsal passes and every condition above holds, load the export into production. The bookmark from Diagnose step 4 undoes this if anything fails:

```bash
$W d1 execute skippercast --remote --yes --file restore-clear.sql
$W d1 execute skippercast --remote --yes --file restore.sql
$W d1 execute skippercast --remote --file restore-counts.sql
$W d1 delete skippercast-restore-check
rm restore.sql restore-clear.sql restore-counts.sql current-before-restore.sql
```

The production counts must equal `expected-counts.txt` row for row; any difference is a failed restore (use the Rollback bookmark).

Never attach an export to an issue, a PR or a workflow artifact, and delete local copies when done: the repository is public and the export holds users' accounts, trips, catch logs, saved spots, advisor messages and push endpoints.

**Privacy after any restore.** A restore to an earlier point brings back records that people deleted after that point (`DELETE /api/privacy`, `DELETE /api/trips`, `DELETE /api/catch-log/:id`, `DELETE /api/spots/:id`, `DELETE /api/subscription`, and Text Advisor "forget me" erasures). The Worker does not log who deleted what, so these cannot be replayed. Restore to the latest safe point, record the gap in the incident issue, and tell affected users if they can be identified. Media objects in R2 are not part of a D1 restore, and pushes or messages already sent stay sent.

## Verify

1. Run `restore-counts.sql` (Diagnose step 2): every inventory table is present, the counts equal the saved `expected-counts.txt` for the chosen recovery point, and `d1_migrations` lists every migration in `drizzle/meta/_journal.json`.
2. Migrations are in step with the repository (run at the repository root with a generated config; `wrangler.deploy.jsonc` is gitignored):
   ```bash
   DB_ID=$($W d1 list --json | python3 -c "import json,sys; print(next(r.get('uuid') or r.get('database_id') for r in json.load(sys.stdin) if r.get('name')=='skippercast'))")
   sed "s/00000000-0000-0000-0000-000000000000/$DB_ID/" wrangler.jsonc > wrangler.deploy.jsonc
   npx --yes wrangler@4.142.0 d1 migrations list skippercast --remote --config wrangler.deploy.jsonc   # expect no pending migrations
   ```
3. `curl -sS "$SITE/api/session"` answers 200 and `wrangler tail` shows no new `dependency` errors.

## Rollback

Undo a restore with the bookmark saved in Diagnose step 4: `$W d1 time-travel restore skippercast --bookmark <that bookmark>`.

## Escalate

- ChatGPT Sites database: the Sites platform support channel; the owner holds that account.
- Cloudflare D1 platform issues: Cloudflare support.
- Any exposure of one person's records to another, or loss of personal data: SEV1; the owner decides on user notification with counsel (California breach-notification rules may apply).

## Postmortem

Always required. Use the [postmortem template](../incident-response.md#postmortem-template).
