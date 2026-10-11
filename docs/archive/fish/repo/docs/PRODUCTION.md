> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/PRODUCTION.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Production publishing

## October 3 launch state

The `fish-report` Worker is deployed at https://fish-report.g4651.workers.dev with a dedicated `fish` D1 database and private `fish-habitat` R2 bucket. Both migrations are applied. Report, ocean and history snapshots were seeded and read back exactly. The reviewed government habitat release was uploaded with full SHA read-back and atomic control promotion. R2 public development access is disabled.

Actual HTTP checks cover report/ocean/history/health, unchanged annual baselines, habitat manifest/details/species, both regions' HEAD/206 ranges, native bathymetry bytes, and private-prefix denial. Actual cloud map rendering shows the selected government release. Evidence: `research/production-launch-2026-10-03/`.

Custom domains are configured in Wrangler. Activation remains pending the Namecheap nameserver switch and replacement of imported parking A/CNAME records. Mail MX/SPF records are retained. Assigned nameservers: `collins.ns.cloudflare.com` and `gerardo.ns.cloudflare.com`.

The new Cloudflare GitHub installation was restricted to `Grahammmm/fish`, but its callback failed. Recovery and the automatic build connection remain pending; automatic publishing is not yet established.

## Automatic publishing contract

Connect the existing `fish-report` Worker to `Grahammmm/fish`, production branch `main`, root `/`. Build command: `npm run check && npm test && npm run build`. Deploy command: `npx wrangler deploy`. Set Node 22. Do not deploy other branches to production. The Worker name must match `wrangler.jsonc`.

Updates are checked and merged to `main`; the production build repeats the checks before deployment. Failed checks leave the previous deployment live. `/assets/release.json` records the actual Git commit, dirty tracked-source state and build time. Verify the served commit matches the merged commit. Deployment credentials never belong in the repository; Cloudflare manages its build authorization.

## Storage and ongoing data

```sh
npm run db:remote
node scripts/seed-production.mjs --remote
node scripts/verify-production.mjs https://fish-report.g4651.workers.dev
```

Run the read-only verifier against `https://slofishreport.com` after activation. The seed command is initial installation only: existing durable rows always win. The scientific release command in `SKIPPERCAST-UPDATES.md` explicitly stages remote R2; website deployment does not upload local map objects.

The collector is scheduled hourly at UTC minute 17. Report, ocean and recent buoy jobs retain original clocks and all annual baselines. A configured schedule is not evidence of successful execution: witness two distinct cloud runs and their durable audit records before claiming unattended operation. No such runs have yet been witnessed at the initial check. This is separate from the removed Codex chat automation.

Compatible SkipperCast currents/catches use this collector. Reviewed complete government habitat releases use private conditional promotion. New species meanings, rights or schema require review. The producer's automatic release hook still needs activation; cloud storage alone does not establish that upstream job.

## Rollback

Use a prior verified Worker deployment for code rollback. Durable data remain in D1 and take precedence over old bundled assets. Habitat is independently gated; never roll back to expired or withdrawn science. Keep email disabled until its separate delivery verification is complete.
