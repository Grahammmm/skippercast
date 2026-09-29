# Running SkipperCast on its own Cloudflare account

SkipperCast's Worker, static site, private-trip database (D1), published feeds (R2) and a cron watchdog can all run on a Cloudflare account you own. Until the pieces below are configured, nothing changes: ChatGPT Sites keeps serving skippercast.com, and feeds keep publishing to GitHub branches.

## What is in place

- **`wrangler.jsonc`**: the Worker (`dist/server/index.js`), the fingerprinted site (`dist/client`), D1 as `DB`, the R2 bucket `skippercast-feeds` as `FEEDS`, and a cron trigger every 15 minutes.
- **`/feeds/<branch>/<path>`**: the site's single route for published feeds (`conditions`, `data`, `forecasts`). It serves from R2 when the bucket is bound, and otherwise from the GitHub branch through Cloudflare's cache. It supports Range and ETag. The browser uses this route for every feed, so moving storage needs no front-end change. `/api/health` reports `"feeds": "r2"` or `"github"`.
- **Publishing:**
  - After each GitHub push, `scripts/publish_branch_r2.sh` mirrors that branch's committed files to R2 under the same path.
  - `scripts/publish_r2.py` hashes files and uploads only changes. The conditions feed has about 1,500 files, and most don't change each cycle. Data files go before `latest`/`index`/`manifest` pointers, and deletions go last.
  - It runs in the live loop (conditions and forecasts) and the daily job (data), and does nothing without credentials.
- **Watchdog (`server/watchdog.js`)**: every 15 minutes, if the live feed is more than 45 minutes old and no refresh is running, it dispatches the live-conditions workflow. This replaces reliance on GitHub's throttled schedules. It needs `WATCHDOG_GITHUB_TOKEN`.
- **Security headers (`server/security-headers.js`)**: the Worker adds HSTS, a Content-Security-Policy with an enumerated host list, `frame-ancestors 'none'`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` and `Cross-Origin-Opener-Policy` to every response it returns, including page shells on both hosts. The build writes the same headers to `dist/client/_headers` for assets that Cloudflare serves without running the Worker. Pages have no meta CSP. To call a new external host from the browser, add it to `CONNECT_ORIGINS` or `IMAGE_ORIGINS` (a test fails otherwise). Vendored scripts and stylesheets carry SRI `integrity` hashes, which `check_web.py` verifies against the files and `scripts/web-vendor-sha256.json`.
- **Deploy (`.github/workflows/deploy-cloudflare.yml`)**: after **Offline checks** pass on a `main` commit, it builds exactly that commit, creates the D1 database and R2 buckets if missing, records a D1 Time Travel bookmark, exports D1 to the private `skippercast-backups` bucket, applies `drizzle/` migrations, deploys and uploads optional secrets. `scripts/smoke_test.sh` then checks the site; a failure rolls the Worker back automatically. Manual rollback: run the workflow with action **rollback**. See [roll back a release](operations/runbooks/rollback-release.md).

Verified locally with `wrangler dev` (Cloudflare's runtime, local D1 and R2):
- pages, the forecast API, `/feeds/` from R2 and from GitHub, and path-traversal refusal;
- the cron handler;
- the full app in Chromium, with every feed through `/feeds/`, no direct GitHub requests and no errors.

## One-time setup (owner)

1. **Create a Cloudflare account** at [dash.cloudflare.com](https://dash.cloudflare.com/sign-up).
   - Open **Workers & Pages** once and choose your `workers.dev` subdomain.
   - Open **R2** and enable it. R2 has a free tier, but Cloudflare asks for a payment method to activate it.
2. **Create an API token.** Go to **My Profile → API Tokens → Create Token** and use the **Edit Cloudflare Workers** template. Add **Account · D1 · Edit** and **Account · Workers R2 Storage · Edit**, and limit it to your account. Copy the token. Your **Account ID** is on the Workers & Pages overview page.
3. **Add GitHub secrets** under repository **Settings → Secrets and variables → Actions**:
   - `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`: required.
   - `ANTHROPIC_API_KEY`: optional, for the AI boat lookup.
   - `WATCHDOG_GITHUB_TOKEN`: optional, for the watchdog. Create a fine-grained GitHub token for this repository only, with **Actions: Read and write**.
4. **Add repository variables** on the same page, under the Variables tab:
   - `CLOUDFLARE_SITE_URL`, e.g. `https://skippercast.<subdomain>.workers.dev`, for the post-deploy check;
   - `EXTRA_ORIGINS` set to the same URL, so the staging copy accepts its own form posts.
5. **Run it.** Go to **Actions → Deploy to Cloudflare → Run workflow**, or merge to `main` (deploys once Offline checks pass). The staging site appears at the workers.dev URL. Feeds start mirroring to R2 on the next live cycle (within 30 minutes) and the next daily run (4:17 a.m. Pacific). After that, `/api/health` on staging shows `"feeds": "r2"`.

## Cost

These are the free-tier allowances as published by Cloudflare; check current pricing.
- **Workers free plan:** 100,000 requests a day.
- **R2:** 10 GB storage and 1 million writes a month free, with no egress charge. SkipperCast's feeds total about 185 MB. Incremental uploads keep writes to changed files only.
- **Workers paid plan:** $5 a month, once traffic or cron needs exceed the free plan.

## Before skippercast.com moves here

Sign-in is still ChatGPT's (`signin-with-chatgpt` and OpenAI identity headers). Only ChatGPT Sites injects those headers and strips visitor-supplied copies, so the Worker trusts them only there. `wrangler.jsonc` sets `IDENTITY_PROVIDER` to `none`, and on Cloudflare every private route (trips, alerts, comfort feedback, AI lookup) returns 401 even when a request carries the headers; `/api/session` reports `signIn: null` and the app says accounts are coming soon. Do not remove that variable: without it, anyone could send the headers and act as any owner. Keep skippercast.com on Sites until SkipperCast has its own sign-in (the next step, together with Stripe). Then point the domain at this Worker and update `deployments/production.json`.
