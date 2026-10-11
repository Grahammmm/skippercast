# Runbook: roll back a release

**Symptom:** a deploy went out and something is wrong: the "Deploy to Cloudflare" run is red, the site errors, or users report a regression.
**Severity:** high if the map, forecasts or feeds are broken; medium otherwise.
**Owner:** repository owner. Agents may prepare the rollback; the owner approves.

## How deploys work

- Only a `main` commit that passed **Offline checks** is deployed, and exactly that commit (`.github/workflows/deploy-cloudflare.yml`).
- `scripts/cloudflare_deploy.sh` records a D1 Time Travel bookmark, exports D1 to the private R2 bucket `skippercast-backups` (`d1/<UTC stamp>-<sha>.sql`), applies migrations, records the Worker version live before the deploy ("Live Worker version before this deploy"), then deploys.
- Each deploy makes **two** Worker deployments a few seconds apart: `wrangler deploy` (the code; its version's message is `<sha> run <run id>`) and `wrangler secret bulk` (a new version of the same code with no message). A bare `wrangler rollback` skips only the newest deployment, so it lands on the code version of the commit you are trying to leave and changes nothing (#568). Always roll back to an explicit version id.
- `scripts/smoke_test.sh` waits for the new build, then checks health, the home page, `/sw.js`, the live feed and that forged identity headers are refused.
- **A failed smoke test rolls the Worker back automatically** to the recorded previous version, then checks `/api/health` no longer serves the failed build. The step stays red either way; its error says whether the rollback took effect. If no previous version was recorded (the first deploy, or the listing failed), it says the rollback was not performed. Migrations are not reverted.

## Detect

- Actions → **Deploy to Cloudflare**: the run summary shows "failed its smoke test and was rolled back to Worker version …", "was NOT rolled back" or "did not take effect" (roll back by hand, below), or the deploy step failed.
- `bash scripts/smoke_test.sh "$CLOUDFLARE_SITE_URL" ""` from a checkout of `main`.
- `curl -s "$CLOUDFLARE_SITE_URL/api/health"` shows the build id being served.
- **Workers & Pages → skippercast → Logs** for exceptions since the deploy, and, with `ENABLE_ANALYTICS=true`, the 5xx rate by route in the latest **Operations report** run ([Observability](../../cloudflare.md#observability)).

## Fix: roll back the Worker code

1. Actions → **Deploy to Cloudflare** → **Run workflow** → action **rollback**. Leave **version** empty to roll back to the newest Worker version deployed from a different commit than the live one, or give an explicit version id. The job prints the target and its commit, runs `wrangler rollback <version-id>` and smoke-tests the result.
2. Or locally, with `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` set:
   ```bash
   mkdir -p var
   node scripts/wrangler_config.mjs 00000000-0000-0000-0000-000000000000 skippercast-feeds wrangler.rollback.jsonc
   npx --yes wrangler@4.142.0 deployments list --json --config wrangler.rollback.jsonc > var/deployments.json
   npx --yes wrangler@4.142.0 versions list --json --config wrangler.rollback.jsonc > var/versions.json
   node scripts/worker_versions.mjs rollback-target var/deployments.json var/versions.json   # or pick an id whose message names a good commit
   npx --yes wrangler@4.142.0 rollback <version-id> --config wrangler.rollback.jsonc --yes --message "why"
   ```
   Never run `wrangler rollback` without a version id (see "How deploys work").
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
- `/api/health` shows the expected build id, and not the build of the commit you rolled back from.

## Afterwards

Open an issue: what broke, why CI didn't catch it, and the test that will. Link it from the reverting PR.
