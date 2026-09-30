# Runbook: roll back a release

**Symptom:** a deploy went out and something is wrong: the "Deploy to Cloudflare" run is red, the site errors, or users report a regression.
**Severity:** high if the map, forecasts or feeds are broken; medium otherwise.
**Owner:** repository owner. Agents may prepare the rollback; the owner approves.

## How deploys work

- Only a `main` commit that passed **Offline checks** is deployed, and exactly that commit (`.github/workflows/deploy-cloudflare.yml`).
- `scripts/cloudflare_deploy.sh` records a D1 Time Travel bookmark, exports D1 to the private R2 bucket `skippercast-backups` (`d1/<UTC stamp>-<sha>.sql`), applies migrations, then deploys.
- `scripts/smoke_test.sh` waits for the new build, then checks health, the home page, `/sw.js`, the live feed and that forged identity headers are refused.
- **A failed smoke test rolls the Worker back automatically.** Migrations are not reverted.

## Detect

- Actions → **Deploy to Cloudflare**: the run summary shows "failed its smoke test and was rolled back", or the deploy step failed.
- `bash scripts/smoke_test.sh "$CLOUDFLARE_SITE_URL" ""` from a checkout of `main`.
- `curl -s "$CLOUDFLARE_SITE_URL/api/health"` shows the build id being served.
- **Workers & Pages → skippercast → Logs** for exceptions since the deploy, and, with `ENABLE_ANALYTICS=true`, the 5xx rate by route in the latest **Operations report** run ([Observability](../../cloudflare.md#observability)).

## Fix: roll back the Worker code

1. Actions → **Deploy to Cloudflare** → **Run workflow** → action **rollback**. This runs `wrangler rollback` to the previous version and smoke-tests the result.
2. Or locally, with `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` set:
   ```bash
   node scripts/wrangler_config.mjs 00000000-0000-0000-0000-000000000000 skippercast-feeds wrangler.rollback.jsonc
   npx --yes wrangler@4.142.0 versions list --config wrangler.rollback.jsonc          # find a good version id
   npx --yes wrangler@4.142.0 rollback <version-id> --config wrangler.rollback.jsonc --yes --message "why"
   ```
3. Revert the bad commit on `main` through a PR so the next deploy doesn't reintroduce it.

## Fix: the database (only if a migration caused the problem)

Migrations are forward-only. Prefer a new corrective migration in a PR. If data was damaged:

1. Find the bookmark in the deploy log ("D1 restore bookmark before migrations").
2. Restore: `npx --yes wrangler@4.142.0 d1 time-travel restore skippercast --bookmark <bookmark> --config wrangler.deploy.jsonc` (create the config with the real database id from `wrangler d1 list`).
3. If Time Travel is out of its retention window, download the export from `skippercast-backups/d1/` and import it into a fresh database with `wrangler d1 execute <db> --remote --file <export.sql>`, then point the binding at it.
4. Roll the Worker back to the version matching that schema (above).

Never download exports to a shared machine or attach them to issues: they contain users' trips and push endpoints.

## Verify

- `bash scripts/smoke_test.sh "$CLOUDFLARE_SITE_URL" ""` passes.
- `/api/health` shows the expected build id.

## Afterwards

Open an issue: what broke, why CI didn't catch it, and the test that will. Link it from the reverting PR.
