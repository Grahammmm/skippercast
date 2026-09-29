# Runbook: restore the D1 database

**Symptom:** private records (saved trips, alert events, notification devices, comfort feedback) are missing, wrong or corrupt after a migration, a bad deploy or a mistaken manual query; or private routes answer `503 "This service is temporarily unavailable. Your existing records are preserved."` because the database is unreachable.
**Severity:** SEV1 if records were exposed to the wrong person; SEV2 for loss or corruption of user records; SEV3 for a D1 outage with records intact (private features unavailable, public map unaffected). See [incident response](../incident-response.md).
**Owner:** repository owner. Restores overwrite user data and must be done by the owner, never by an agent.

**Where this applies today:**

- **ChatGPT Sites (skippercast.com):** the platform provisions the `DB` binding from `.openai/hosting.json` and applies `drizzle/` migrations. There is no Wrangler access to that database; restores there go through the Sites platform. Escalate (below).
- **Cloudflare (`skippercast` D1 database):** the commands in this runbook. Until SkipperCast has its own sign-in (guide P3-02), `IDENTITY_PROVIDER=none` makes every private route answer 401 there, so this database holds rate-limit rows only. The procedure is written now so it is proven before real records arrive.

## What is in the database

Tables from `db/schema.ts` (migrations in `drizzle/`): `trips`, `subscriptions` (push endpoints and keys), `alert_events`, `delivery_receipts`, `comfort_feedback`, `request_limits`, plus Wrangler's `d1_migrations`. Retention in code: trips, events and receipts 90 days; feedback 365 days; rate-limit rows until `expires_at`. It holds personal data: treat every export as confidential.

## Recovery points

1. **D1 Time Travel** (always on): restore to any minute inside the retention window. Wrangler's help says "within the last 30 days"; Cloudflare documents a shorter window on the Workers Free plan, so check the plan before relying on an older point.
2. **Pre-migration exports** (after PR #26, [P0-03], merges): `scripts/cloudflare_deploy.sh` logs `D1 restore bookmark before migrations: <bookmark>` and uploads `wrangler d1 export` output to the private bucket `skippercast-backups` at `d1/<UTC stamp>-<commit>.sql`. PR #26 also adds the runbook `docs/operations/runbooks/rollback-release.md` for rolling back the Worker code together with a migration.

## Detect

```bash
export SITE=https://skippercast.example.workers.dev    # the CLOUDFLARE_SITE_URL repository variable
curl -sS "$SITE/api/session"                              # public; must answer 200
curl -sS -o /dev/null -w '%{http_code}\n' "$SITE/api/trips"   # 401 today (no sign-in); 503 = storage failure once sign-in exists
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
2. **What is in it now?**
   ```bash
   $W d1 execute skippercast --remote --command "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
   $W d1 execute skippercast --remote --command "SELECT (SELECT COUNT(*) FROM trips) trips, (SELECT COUNT(*) FROM subscriptions) subscriptions, (SELECT COUNT(*) FROM alert_events) events, (SELECT COUNT(*) FROM comfort_feedback) feedback"
   $W d1 execute skippercast --remote --command "SELECT id, name, applied_at FROM d1_migrations ORDER BY id"
   ```
3. **When did it go wrong?** Match the damage to a deploy (Actions → *Deploy to Cloudflare* run times, or `$W deployments list --name skippercast`) or to a manual command. Pick the restore time: the last minute before the damage.
4. **Save the current point first,** so the restore itself can be undone:
   ```bash
   $W d1 time-travel info skippercast --json | tee "before-restore-$(date -u +%Y%m%dT%H%M%SZ).json"
   ```
   Keep the printed `bookmark`.

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

**C. Restore from an export (outside the Time Travel window; after PR #26).** Rehearse in a scratch database first:

```bash
$W r2 object get "skippercast-backups/d1/<stamp>-<commit>.sql" --remote --file restore.sql
$W d1 create skippercast-restore-check
$W d1 execute skippercast-restore-check --remote --file restore.sql --yes
$W d1 execute skippercast-restore-check --remote --command "SELECT COUNT(*) FROM trips"
```

When the counts look right, load it into the production database. The export contains `CREATE TABLE` statements, so the existing tables must go first; the bookmark from Diagnose step 4 undoes this if anything fails:

```bash
$W d1 execute skippercast --remote --yes --command "DROP TABLE IF EXISTS delivery_receipts; DROP TABLE IF EXISTS alert_events; DROP TABLE IF EXISTS subscriptions; DROP TABLE IF EXISTS trips; DROP TABLE IF EXISTS comfort_feedback; DROP TABLE IF EXISTS request_limits; DROP TABLE IF EXISTS d1_migrations"
$W d1 execute skippercast --remote --yes --file restore.sql
$W d1 delete skippercast-restore-check
rm restore.sql
```

Never attach an export to an issue, a PR or a workflow artifact, and delete local copies when done: the repository is public and the export holds users' trips and push endpoints.

**Privacy after any restore.** A restore to an earlier point brings back records that people deleted after that point (`DELETE /api/privacy`, `DELETE /api/trips`, `DELETE /api/subscription`). The Worker does not log who deleted what, so these cannot be replayed. Restore to the latest safe point, record the gap in the incident issue, and tell affected users if they can be identified.

## Verify

1. Diagnose step 2 shows the expected tables, counts and every migration in `drizzle/meta/_journal.json`.
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
