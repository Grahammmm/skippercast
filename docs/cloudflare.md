# Running SkipperCast on its own Cloudflare account

SkipperCast runs only on a Cloudflare account the owner controls: the Worker, the static site, the private-trip database (D1), published feeds (R2) and a cron watchdog. The workers.dev address (`https://skippercast.g4651.workers.dev`) is the staging URL and always stays on. skippercast.com and www.skippercast.com attach to the same Worker as custom domains once the zone is on Cloudflare; see [Custom domain](#custom-domain). Until the Cloudflare secrets exist, deploys do nothing and feeds keep publishing to GitHub branches.

## What is in place

- **`wrangler.jsonc`**: the Worker (`dist/server/index.js`), the fingerprinted site (`dist/client`), D1 as `DB`, the R2 bucket `skippercast-feeds` as `FEEDS`, and a cron trigger every 15 minutes.
- **`/feeds/<branch>/<path>`**: the site's single route for published feeds (`conditions`, `data`, `forecasts`). It serves from R2 when the bucket is bound, and otherwise from the GitHub branch through Cloudflare's cache. It supports Range and ETag. The browser uses this route for every feed, so moving storage needs no front-end change. Each response names its source in the `X-Feed-Source` header (`r2`, `github` or `assets`). `/api/health` reports only the service, version and build.
- **Publishing:**
  - After each GitHub push, `scripts/publish_branch_r2.sh` mirrors that branch's committed files to R2 under the same path.
  - `scripts/publish_r2.py` hashes files and uploads only changes. The conditions feed has about 1,500 files, and most don't change each cycle. Data files go before `latest`/`index`/`manifest` pointers, and deletions go last.
  - It runs in the live loop (conditions and forecasts) and the daily job (data), and does nothing without credentials.
  - With credentials, an upload error fails the job: the site serves R2 first, so a failed upload would otherwise leave users on stale data. Every `latest.json` carries `published_at` and `run_id` (the GitHub run, or `local`).
  - When the repository variable `FEEDS_PUBLIC_BASE` is set (for example `https://skippercast.g4651.workers.dev`), the live cycle and daily job then fetch `/feeds/<branch>/latest.json` from that site with `scripts/verify_published_feed.py` and fail unless it serves this run.
  - `scripts/check_feed_freshness.py` (hourly, `feed-freshness.yml`) checks the public route first — `FEEDS_PUBLIC_BASE`, defaulting to the workers.dev host (set it to `https://skippercast.com` once the custom domain is attached) — and reports the GitHub branch age second. A stale public route opens the `feed-stale` issue.
- **Watchdog (`server/watchdog.js`)**: every 15 minutes, if the live feed is more than 45 minutes old and no refresh is running, it dispatches the live-conditions workflow. This replaces reliance on GitHub's throttled schedules. It needs `WATCHDOG_GITHUB_TOKEN`. The same cron prunes expired trips, alert events, feedback and rate-limit rows in D1 (see [production operations](production-operations.md)).
- **Edge cache and rate limits (`server/edge-cache.js`)**:
  - `/api/om/*`, `/api/forecast`, `/api/intelligence`, `/api/habitat` and R2-served `/feeds/*` use the Workers Cache API (`caches.default`). Responses carry `X-SC-Cache: hit|miss`.
  - API keys are the path plus sorted query parameters (region only, for the region endpoints) plus the build id.
  - An R2 feed of up to 32 MB is cached as one whole object, and the Cache API answers Range and `If-None-Match` requests from it (206/304). A PMTiles client therefore never mixes byte ranges from two object versions. Seafloor archives are never cached.
  - Per-IP limits use the Workers Rate Limiting bindings in `wrangler.jsonc`: `PUBLIC_LIMITER`, 60 a minute for `/api/om`, and `FEED_LIMITER`, 300 a minute for `/feeds/`. Over the limit returns 429 with `Retry-After: 60`.
  - Without the shared cache or the bindings (unit tests), both are skipped.
- **Security headers (`server/security-headers.js`)**: the Worker adds HSTS, a Content-Security-Policy with an enumerated host list, `frame-ancestors 'none'`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` and `Cross-Origin-Opener-Policy` to every response it returns, including page shells and the www→apex redirect. The build writes the same headers to `dist/client/_headers` for assets that Cloudflare serves without running the Worker. Pages have no meta CSP. To call a new external host from the browser, add it to `CONNECT_ORIGINS` or `IMAGE_ORIGINS` (a test fails otherwise). Vendored scripts and stylesheets carry SRI `integrity` hashes, which `check_web.py` verifies against the files and `scripts/web-vendor-sha256.json`.
- **Deploy (`.github/workflows/deploy-cloudflare.yml`)**: after **Offline checks** pass on a `main` commit, it builds exactly that commit, creates the D1 database and R2 buckets if missing, records a D1 Time Travel bookmark, exports D1 to the private `skippercast-backups` bucket, applies `drizzle/` migrations, deploys and uploads optional secrets. `scripts/smoke_test.sh` then checks the site; a failure rolls the Worker back automatically. Manual rollback: run the workflow with action **rollback**. See [roll back a release](operations/runbooks/rollback-release.md).

Verified locally with `wrangler dev` (Cloudflare's runtime, local D1 and R2):
- pages, the forecast API, `/feeds/` from R2 and from GitHub, and path-traversal refusal;
- the cron handler;
- the full app in Chromium, with every feed through `/feeds/`, no direct GitHub requests and no errors.

## One-time setup (owner)

1. **Create a Cloudflare account** at [dash.cloudflare.com](https://dash.cloudflare.com/sign-up).
   - Open **Workers & Pages** once and choose your `workers.dev` subdomain.
   - Open **R2** and enable it. R2 has a free tier, but Cloudflare asks for a payment method to activate it.
2. **Create an API token.** Go to **My Profile → API Tokens → Create Token** and use the **Edit Cloudflare Workers** template. Add **Account · D1 · Edit** and **Account · Workers R2 Storage · Edit**, and limit it to your account. For the custom domain it also needs **Zone · Workers Routes · Edit** and **Zone · Zone · Read** on skippercast.com (see [Custom domain](#custom-domain)); you can add those once the zone exists. Copy the token. Your **Account ID** is on the Workers & Pages overview page.
3. **Add GitHub secrets** under repository **Settings → Secrets and variables → Actions**:
   - `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`: required.
   - `ANTHROPIC_API_KEY`: optional, for the AI boat lookup.
   - `WATCHDOG_GITHUB_TOKEN`: optional, for the watchdog. Create a fine-grained GitHub token for this repository only, with **Actions: Read and write**.
4. **Add repository variables** on the same page, under the Variables tab:
   - `CLOUDFLARE_SITE_URL`, e.g. `https://skippercast.<subdomain>.workers.dev`, for the post-deploy check;
   - `EXTRA_ORIGINS` set to the same URL, so the staging copy accepts its own form posts.
5. **Run it.** Go to **Actions → Deploy to Cloudflare → Run workflow**, or merge to `main` (deploys once Offline checks pass). The staging site appears at the workers.dev URL. Feeds start mirroring to R2 on the next live cycle (within 30 minutes) and the next daily run (4:17 a.m. Pacific). After that, `curl -sI <staging>/feeds/conditions/latest.json` shows `X-Feed-Source: r2`.

## Cost

These are the free-tier allowances as published by Cloudflare; check current pricing.
- **Workers free plan:** 100,000 requests a day.
- **R2:** 10 GB storage and 1 million writes a month free, with no egress charge. SkipperCast's feeds total about 185 MB. Incremental uploads keep writes to changed files only.
- **Workers paid plan:** $5 a month, once traffic or cron needs exceed the free plan.

## Custom domain

The deploy attaches every host in the `CUSTOM_DOMAINS` repository variable as a [Worker custom domain](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/): `scripts/wrangler_config.mjs` turns `skippercast.com,www.skippercast.com` into `"routes": [{"pattern": "skippercast.com", "custom_domain": true}, {"pattern": "www.skippercast.com", "custom_domain": true}]` and keeps `workers_dev` on. Without the variable nothing changes (workers.dev only). Cloudflare then creates the DNS records and certificates itself. The Worker answers any `www.` host with a 301 to the apex, keeping path and query, so there is one canonical origin for cookies, passkeys and caches (hashed static files under www may still be served directly; they are identical and harmless). `deployments/production.json` allows `https://skippercast.com` and `https://www.skippercast.com` as Origins; the `EXTRA_ORIGINS` secret keeps the workers.dev origin allowed.

Cloudflare's rules that shape the checklist: a custom domain needs an **active** zone on the same account, and cannot be created on a hostname that already has a CNAME record (Wrangler also sends `override_existing_dns_record: false`, so an existing A record for the apex blocks it too). Cloudflare's API schema lists **Workers Scripts · Edit** for the Workers domains endpoints (already in the Edit Cloudflare Workers template). In Wrangler 4.142.0's source, a deploy with `workers_dev` on and only custom domains calls just the Worker's domains changeset endpoint; older and newer versions have also listed the zone's Worker routes, which needs **Zone · Workers Routes** ([workers-sdk#15903](https://github.com/cloudflare/workers-sdk/pull/15903)). Grant **Zone · Workers Routes · Edit** and **Zone · Zone · Read** on skippercast.com so either path works. Cloudflare's docs do not list **DNS · Edit** for custom domains (Cloudflare writes the DNS records itself); add it only if a deploy fails with an authorization error on the domains step.

Verified offline: `npx --yes wrangler@4.142.0 deploy --dry-run --config <generated>` with a dummy database id and no Cloudflare credentials accepts the generated config (and rejects a path or wildcard in a custom-domain pattern). A dry run does not contact Cloudflare, so it cannot check the zone or the token.

### Owner checklist: move skippercast.com to Cloudflare

Today the domain is registered at Namecheap with Namecheap nameservers (`*.registrar-servers.com`); the apex A records point at the old ChatGPT Sites IPs and `www` is a CNAME to `custom-domains.chatgpt.site`. SkipperCast no longer uses Sites; these steps retire it.

1. **Add the site to Cloudflare.** In the dashboard, **Add a domain** → `skippercast.com` → **Free** plan. Let Cloudflare scan the existing DNS records. Before continuing, note any records you must keep (for example **MX** and **TXT** records for email or domain verification) and make sure they were imported.
2. **Change the nameservers at Namecheap.** In Namecheap, **Domain List → skippercast.com → Manage → Nameservers → Custom DNS**, and enter the two nameservers Cloudflare shows (`<name>.ns.cloudflare.com`). Remove any DNSSEC DS record at Namecheap first if DNSSEC is on (re-enable it from Cloudflare later). Wait until Cloudflare shows the zone as **Active** (minutes to a day); Cloudflare emails you.
3. **Delete the Sites records in Cloudflare DNS.** Under **DNS → Records**, delete the apex (`skippercast.com`) **A** records that point at the Sites IPs and the **`www` CNAME** to `custom-domains.chatgpt.site`. Keep MX/TXT records. (The site is briefly unreachable from here until step 6 finishes; do steps 3–6 together.)
4. **Extend the API token.** Edit the `CLOUDFLARE_API_TOKEN` token: add **Zone · Workers Routes · Edit** and **Zone · Zone · Read**, with **Zone Resources → Include → Specific zone → skippercast.com**. Keep the account permissions from [one-time setup](#one-time-setup-owner). No new token value is needed unless you create a new token (then update the GitHub secret).
5. **Set the repository variables** (GitHub → Settings → Secrets and variables → Actions → Variables):
   - `CUSTOM_DOMAINS` = `skippercast.com,www.skippercast.com`
   - `CLOUDFLARE_SITE_URL` = `https://skippercast.com` (the post-deploy smoke test and rollback check this host)
   - `FEEDS_PUBLIC_BASE` = `https://skippercast.com` (the feed freshness check and publish verification read this host)
   - `EXTRA_ORIGINS` stays `https://skippercast.g4651.workers.dev`, so the staging copy keeps accepting its own posts.
6. **Re-run the deploy.** **Actions → Deploy to Cloudflare → Run workflow** (action **deploy**). The log shows the two custom domains attached. Then check:
   - `curl -sI https://skippercast.com/` → `200`, with `strict-transport-security`;
   - `curl -sI "https://www.skippercast.com/sources.html?x=1"` → `301`, `location: https://skippercast.com/sources.html?x=1`;
   - `curl -s https://skippercast.com/api/health` names the build the workflow deployed;
   - **Workers & Pages → skippercast → Settings → Domains & Routes** lists both custom domains and the workers.dev route.
7. **Retire Sites.** Delete the SkipperCast project in ChatGPT Sites. Its D1 database is abandoned: nothing is migrated from it.

If step 6 fails with "hostname already has a DNS record", a record from step 3 remains. If it fails with an authorization error, recheck step 4. The workers.dev deploy and the previous Worker version are unaffected either way; re-run after fixing.
