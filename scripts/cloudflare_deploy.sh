#!/usr/bin/env bash
# Deploy SkipperCast to its own Cloudflare account (see docs/cloudflare.md).
# Creates the D1 database and R2 bucket on first run, applies D1 migrations,
# deploys the built Worker and static site, then uploads optional secrets.
# Requires CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID; run after `pnpm build`.
set -euo pipefail
WRANGLER="npx --yes wrangler@4.142.0"
DB_NAME=skippercast
BUCKET=${R2_BUCKET:-skippercast-feeds}
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

python3 - "$id" "$BUCKET" <<'PY'
import json, re, sys
text = open('wrangler.jsonc').read()
text = re.sub(r'^\s*//.*$', '', text, flags=re.M)          # strip line comments
config = json.loads(text)
config['d1_databases'][0]['database_id'] = sys.argv[1]
config['r2_buckets'][0]['bucket_name'] = sys.argv[2]
open('wrangler.deploy.jsonc', 'w').write(json.dumps(config, indent=2))
PY

$WRANGLER d1 migrations apply "$DB_NAME" --remote --config "$CONFIG"
$WRANGLER deploy --config "$CONFIG"

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
