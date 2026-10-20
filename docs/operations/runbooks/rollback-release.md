# Runbook: roll back a release

**Symptom:** a deploy went out and something is wrong: the "Deploy to Cloudflare" run is red, the site errors, or users report a regression.
**Severity:** high if the map, forecasts or feeds are broken; medium otherwise.
**Owner:** repository owner. Agents may prepare the rollback; the owner approves.

## How deploys work

- The newest `main` commit whose **Offline checks** passed is deployed (`.github/workflows/deploy-cloudflare.yml`). Each run, automatic or a manual **deploy** of `main`, walks main's first parents from the head (at most 20 commits) and selects the first one whose latest push/main Offline checks run succeeded. A newer commit whose checks are pending or failed is skipped, never deployed, and an older checked one ships in its place; the newer commit deploys once its own checks pass. The selection reads public GitHub metadata before checkout or deployment credentials, and missing or unreadable metadata fails closed.
- The deploy job checks out exactly the selected commit (the candidate). Its guards run from the workflow's own revision (the controller: `scripts/check_deploy_source.py` and `scripts/worker_versions.mjs`, sparse-checked-out at `github.workflow_sha` into the runner's temp directory), never from the candidate, so a candidate older than the current guard is still checked by the current guard. Before dependencies, and again immediately before production writes, the controller checks that the checkout is exactly the selected commit, that the commit is current main or an ancestor of it, and that its latest exact-SHA push/main CI succeeded. The candidate's own build, deploy script and smoke test run as before. The deploy script runs with `GITHUB_SHA` set to the selected commit, so older scripts that label with `GITHUB_SHA` still name the right commit.
- Before any write the job also reads the commit production serves, through read-only `wrangler deployments list` and `versions list`. It traces the live version's provenance. A code upload (`workers/triggered_by` `upload` or `version_upload`) names its commit in the exact `<sha> run <run id>` message. A secrets change (`secret`) is traced to the version created just before it, but only when the newest deployment older than the change served that version at 100%. Cloudflare refuses a secrets change unless the latest version is deployed, so that version holds the secrets change's code. The deploy holds when production already serves that commit or a newer one, so a deploy never moves production backwards. It also holds, on every event, when the commit production serves cannot be traced: split traffic, an untagged or hand-labelled upload, another trigger, a version or deployment missing from the listings, or a listing that fails. Only missing Cloudflare credentials skip the comparison (the deploy script then writes nothing). To recover from an untraceable production, roll back to a version a deploy made (action **rollback** with a code version id whose message is `<sha> run <run id>`), then deploy again. A manual dispatch may redeploy the live commit to apply changed variables or secrets. When production serves a commit that is not on main, an automatic run holds and a manual dispatch may replace it.
- A run that ships nothing says so: the source or deploy step prints a "Deploy held" warning with the reason, and the `report` job writes the outcome to the job summary and adds a **Cloudflare deploy** check run to the commit. That check run is neutral when the deploy was held or Cloudflare is unconfigured, and success when the commit deployed and passed its smoke test. The workflow run itself still ends green, because GitHub Actions has no neutral run result. Look at the check run or the summary, not only the run's colour. The `report` job is the only one whose token can write, and it can write only check runs (`checks: write`). Explicit rollback remains a separate path without these forward-deployment guards.
- `scripts/cloudflare_deploy.sh` records a D1 Time Travel bookmark, exports D1 to the private R2 bucket `skippercast-backups` (`d1/<UTC stamp>-<sha>.sql`), applies migrations, records the Worker version live before the deploy ("Live Worker version before this deploy"), then deploys.
- Each deploy makes **two** Worker deployments a few seconds apart: `wrangler deploy` (the code; its version's message is `<sha> run <run id>`) and `wrangler secret bulk` (a new version of the same code with no message). A bare `wrangler rollback` skips only the newest deployment, so it lands on the code version of the commit you are trying to leave and stays on the same commit (only its secrets upload is undone) (#568). Always roll back to an explicit version id.
- `scripts/smoke_test.sh` waits for the new build, then checks health, the home page, `/sw.js`, the live feed and that forged identity headers are refused.
- **A failed smoke test rolls the Worker back automatically** to the recorded previous version, then confirms the live version from `wrangler deployments list` and, when `CLOUDFLARE_SITE_URL` is set, only reports the build id `/api/health` serves. The step stays red either way; its error says whether the rollback took effect. If no previous version was recorded (the first deploy, or the listing failed), it says the rollback was not performed. Migrations are not reverted.

## Detect

- Actions → **Deploy to Cloudflare**: the run summary shows "failed its smoke test and was rolled back to Worker version …", "was NOT rolled back" or "did not take effect" (roll back by hand, below), or the deploy step failed.
- `bash scripts/smoke_test.sh "$CLOUDFLARE_SITE_URL" ""` from a checkout of `main`.
- `curl -s "$CLOUDFLARE_SITE_URL/api/health"` shows the build id being served.
- **Workers & Pages → skippercast → Logs** for exceptions since the deploy, and, with `ENABLE_ANALYTICS=true`, the 5xx rate by route in the latest **Operations report** run ([Observability](../../cloudflare.md#observability)).

## Fix: roll back the Worker code

1. Actions → **Deploy to Cloudflare** → **Run workflow** → action **rollback**. Leave **version** empty to roll back to the version live before the current commit's deploy, or give an explicit version id. The job prints the target and its commit, runs `wrangler rollback <version-id>` and smoke-tests the result.
2. Or locally, with `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` set:
   ```bash
   mkdir -p var
   node scripts/wrangler_config.mjs 00000000-0000-0000-0000-000000000000 skippercast-feeds wrangler.rollback.jsonc
   npx --yes wrangler@4.142.0 deployments list --json --config wrangler.rollback.jsonc > var/deployments.json
   npx --yes wrangler@4.142.0 versions list --json --config wrangler.rollback.jsonc > var/versions.json
   node scripts/worker_versions.mjs rollback-target var/deployments.json var/versions.json   # the version live before the current commit's deploy; or pick an id whose message names a good commit
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
- The rollback run confirms the live Worker version from Cloudflare (`wrangler deployments list`) and fails if it is not the one you asked for.
- `/api/health` shows the expected build id. The build id can stay the same after a rollback when the commit you rolled back from changed no client files, so it identifies the pages served, not the Worker version.

## Afterwards

Open an issue: what broke, why CI didn't catch it, and the test that will. Link it from the reverting PR.
