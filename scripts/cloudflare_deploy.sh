#!/usr/bin/env bash
# Deploy SkipperCast to its own Cloudflare account (see docs/cloudflare.md).
# Creates the D1 database and R2 buckets on first run, backs up D1, applies
# migrations, deploys the built Worker and static site, then uploads optional
# secrets. The workflow smoke-tests the result and rolls back on failure.
# Requires CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID; run after `pnpm build`.
set -euo pipefail
WRANGLER="npx --yes wrangler@4.142.0"
DB_NAME=skippercast
BUCKET=${R2_BUCKET:-skippercast-feeds}
BACKUP_BUCKET=${R2_BACKUP_BUCKET:-skippercast-backups}   # private; never bound to the Worker
CONFIG=wrangler.deploy.jsonc   # generated; gitignored

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  echo "Cloudflare is not configured (CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID); nothing to deploy."
  exit 0
fi

db_id() { $WRANGLER d1 list --json 2>/dev/null | python3 -c "
import json,sys
rows=json.load(sys.stdin)
print(next((r.get('uuid') or r.get('database_id') for r in rows if r.get('name')=='$DB_NAME'),''))"; }

id=$(db_id)
if [ -z "$id" ]; then
  echo "Creating D1 database $DB_NAME"
  $WRANGLER d1 create "$DB_NAME" >/dev/null
  id=$(db_id)
fi
[ -n "$id" ] || { echo "::error::Could not find or create D1 database $DB_NAME"; exit 1; }

# Creating an existing bucket fails with "already exists", which is fine.
if ! out=$($WRANGLER r2 bucket create "$BUCKET" 2>&1); then
  echo "$out" | grep -qi "already exist" || { echo "$out"; echo "::error::Could not create R2 bucket $BUCKET"; exit 1; }
else
  echo "Created R2 bucket $BUCKET"
fi
# Retention backstops (run manifests 7 days, history and verification archive after
# the pipeline's own pruning). Idempotent: `lifecycle set` replaces the whole rule set.
if ! python3 scripts/r2_lifecycle.py --bucket "$BUCKET"; then
  echo "::warning title=R2 lifecycle::rules not applied to $BUCKET; feeds are unaffected (see docs/cloudflare.md)"
fi

# Trip-check queues (ENABLE_QUEUES=true repository variable; docs/cloudflare.md).
# Created before the deploy that binds them; `queues info` makes this idempotent.
if [ "${ENABLE_QUEUES:-}" = "true" ]; then
  for queue in skippercast-trip-checks-dlq skippercast-trip-checks; do
    if $WRANGLER queues info "$queue" >/dev/null 2>&1; then continue; fi
    if ! out=$($WRANGLER queues create "$queue" 2>&1); then
      echo "$out" | grep -qiE "already (exist|taken)" || { echo "$out"; echo "::error::Could not create queue $queue (Queues needs the Workers plan to allow it; see docs/cloudflare.md)"; exit 1; }
    else
      echo "Created queue $queue"
    fi
  done
fi

# CUSTOM_DOMAINS (repository variable, e.g. "skippercast.com,www.skippercast.com")
# attaches those hosts as Worker custom domains; unset means workers.dev only.
# The zone must already be active on this Cloudflare account (docs/cloudflare.md).
# ENABLE_QUEUES / ENABLE_ANALYTICS ("true") add the optional bindings; the script reads them from the environment.
node scripts/wrangler_config.mjs "$id" "$BUCKET" "$CONFIG" "${CUSTOM_DOMAINS:-}"

# Before touching the schema, keep a way back. D1 Time Travel can restore to any
# minute in its retention window; the bookmark below marks this exact point. A
# full export also goes to the private backup bucket. Never to a workflow
# artifact: the repository is public and the export holds users' trips and push
# endpoints.
bookmark=$($WRANGLER d1 time-travel info "$DB_NAME" --json --config "$CONFIG" 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin).get('bookmark',''))" || true)
echo "D1 restore bookmark before migrations: ${bookmark:-unavailable}"
if ! out=$($WRANGLER r2 bucket create "$BACKUP_BUCKET" 2>&1); then
  echo "$out" | grep -qi "already exist" || { echo "$out"; echo "::error::Could not create R2 bucket $BACKUP_BUCKET"; exit 1; }
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="var/d1-$stamp.sql"
$WRANGLER d1 export "$DB_NAME" --remote --output "$backup" --config "$CONFIG"
$WRANGLER r2 object put "$BACKUP_BUCKET/d1/$stamp-${GITHUB_SHA:-local}.sql" --file "$backup" --remote --config "$CONFIG" >/dev/null
rm -f "$backup"
echo "D1 export saved to r2://$BACKUP_BUCKET/d1/$stamp-${GITHUB_SHA:-local}.sql"

$WRANGLER d1 migrations apply "$DB_NAME" --remote --config "$CONFIG"
$WRANGLER deploy --config "$CONFIG" --message "${GITHUB_SHA:-local} run ${GITHUB_RUN_ID:-local}"
if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "deployed=true" >> "$GITHUB_OUTPUT"; fi

# Optional secrets, uploaded only when provided to this job.
python3 - <<'PY' > var/cloudflare-secrets.json
import json, os
secrets = {name: os.environ[source] for name, source in [
    ('ANTHROPIC_API_KEY', 'ANTHROPIC_API_KEY'),       # AI boat lookup
    ('GITHUB_TOKEN', 'WATCHDOG_GITHUB_TOKEN'),        # cron watchdog restarts the live refresh
    ('EXTRA_ORIGINS', 'EXTRA_ORIGINS'),               # e.g. https://skippercast.<you>.workers.dev
] if os.environ.get(source)}
print(json.dumps(secrets))
PY
if [ "$(cat var/cloudflare-secrets.json)" != "{}" ]; then
  $WRANGLER secret bulk var/cloudflare-secrets.json --config "$CONFIG"
fi
rm -f var/cloudflare-secrets.json
echo "Deployed SkipperCast to Cloudflare."
