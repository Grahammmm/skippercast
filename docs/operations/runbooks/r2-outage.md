# Runbook: R2 outage or stale R2 feeds

**Symptom:** on the Cloudflare deployment, `/feeds/*` answers 5xx, or it answers with data older than the GitHub branch; publishing jobs log `R2 publish failed`; seafloor layers answer `503 Seafloor screening unavailable or expired`.
**Severity:** SEV2 if the site that users open serves broken or stale feeds; SEV3 if only the Cloudflare staging site is affected. See [incident response](../incident-response.md).
**Owner:** repository owner (Cloudflare account access).

**Where this applies today:** skippercast.com is still served by ChatGPT Sites, which has no R2 binding and reads feeds from GitHub branches. R2 serves users only once the domain points at the Cloudflare Worker ([Cloudflare](../../cloudflare.md)). Until then an R2 incident affects the Cloudflare staging site (the `CLOUDFLARE_SITE_URL` repository variable) and seafloor archives, which exist only in R2.

## How R2 is used

- Bucket `skippercast-feeds` (override with `R2_BUCKET`), bound to the Worker as `FEEDS` in `wrangler.jsonc`. Keys mirror the GitHub branches: `conditions/...`, `data/...`, `forecasts/...`, plus `tiles/seafloor/...` from the seafloor workflow.
- Writers: `scripts/publish_branch_r2.sh <worktree> <prefix>` (live loop, daily job, forecast tiles) calls `scripts/publish_r2.py`, which uploads only files whose SHA-256 differs from the index at `<prefix>/.r2-sync.json`, data files before pointer files (`latest`, `index`, `manifest`, `*-health`), deletions last. `src/skippercast/seafloor/publish.py` writes seafloor archives and their `manifest-<region>.json` after a read-back check.
- Credentials: `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. The S3 access key is the token's id and the secret is the SHA-256 of the token, so rotating the token rotates both.
- Reader: `server/feeds.ts`. `serveFeed` (the `/feeds/` route) and `createFeedReader` (used by `/api/om`, `/api/forecast`, `/api/intelligence`, `/api/habitat`, `/api/daily` and trip checks) read published feeds **from R2 only**; the Worker never fetches a feed from GitHub (SC2184-13). What users then get:
  - a key absent from the bound bucket: `404` on `/feeds/` (map tiles under `tiles/` may still come from the shipped assets), and an error answer on the `/api/` route;
  - no bucket bound: `503` with `Cache-Control: no-store`;
  - past the R2 cost ceiling ([cost ceiling](../cost-ceiling.md)): the last-known copy if one is held, otherwise `503` with `{degraded: true}`;
  - R2 itself erroring: the request fails (5xx).
  Seafloor archives fail closed with 503/404 by design. The cron watchdog alone still compares the GitHub branch copy of `conditions/latest.json` when R2 has none (`server/watchdog.ts` `liveFeed`); it serves nothing to users.
- On `main`, an R2 upload failure is a warning and the job stays green. After PR #30 ([P0-04]) merges, it fails the job, every `latest.json` carries `published_at` and `run_id`, and `scripts/verify_published_feed.py` checks the public route after each publish.

## Detect

With `ENABLE_ANALYTICS=true`, the latest **Operations report** run shows `/feeds/*` requests by status class and p95 latency ([Observability](../../cloudflare.md#observability)). Then check what the site serves:

```bash
export SITE=https://skippercast.example.workers.dev   # the CLOUDFLARE_SITE_URL repository variable
export RAW=https://raw.githubusercontent.com/Grahammmm/skippercast
for p in conditions/latest.json data/latest.json forecasts/gfs_global/manifest.json; do
  printf '%s  ' "$p"; curl -sS -o /dev/null -D - -w '%{http_code}\n' "$SITE/feeds/$p" | grep -iE '^x-feed-source|^[0-9]{3}$' | tr '\n' ' '; echo
done
```

Healthy: `200` and `x-feed-source: r2` for each. `404` means R2 has no copy of that key (there is no GitHub fallback); `503` with no `x-sc-degraded` header means the Worker has no bucket bound; `503` with `x-sc-degraded: cost-ceiling` means the R2 cost ceiling tripped ([cost ceiling](../cost-ceiling.md)); another 5xx means R2 errored.

## Diagnose (in order)

Work from an empty directory so Wrangler does not pick up the placeholder database id in the repository's `wrangler.jsonc`, with the owner's credentials exported:

```bash
cd "$(mktemp -d)"
export CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=...
W="npx --yes wrangler@4.142.0"
```

1. **Is Cloudflare R2 degraded?** Check cloudflarestatus.com for R2 incidents.
2. **Is the token valid?** (This is the call `publish_r2.py` makes first.)
   ```bash
   curl -fsS -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" https://api.cloudflare.com/client/v4/user/tokens/verify
   ```
   `"status":"active"` is required. Anything else: [secrets rotation](secrets-rotation.md).
3. **Can the bucket be read?**
   ```bash
   $W r2 bucket info skippercast-feeds
   $W r2 object get skippercast-feeds/conditions/latest.json --remote --pipe | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("published_at") or d.get("completed_at"), d.get("run_id"))'
   ```
   Always pass `--remote`: Wrangler 4 otherwise reads its local simulator.
4. **Is R2 behind GitHub?** Compare step 3 with `curl -fsS "$RAW/conditions/latest.json"` (same fields). R2 older than GitHub means uploads are failing; read the publish step of the latest run:
   ```bash
   gh run view "$(gh run list --workflow live-conditions.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --log | grep -iE 'R2|r2 publish' | tail -20
   ```
5. **Seafloor only?** `curl -fsS "$SITE/feeds/tiles/seafloor/manifest-morro-bay.json"` and check `status` (`ready`), `expires_at` (in the future) and `archive_sha256`. An expired manifest is correct fail-closed behaviour until the daily seafloor workflow (`seafloor.yml`, 10:23 UTC) republishes; to republish now, run `gh workflow run seafloor.yml --ref main -f region=<region>` (see Fix C below).

## Fix

**A. R2 is erroring (platform outage): there is no fallback store.** Since SC2184-13 the Worker never reads a published feed from GitHub, so deploying without the R2 binding no longer helps: every feed would answer `503`. Leave the binding in place, track the incident on cloudflarestatus.com, and escalate (below) if it lasts more than an hour. Edge-cached copies keep answering until their TTL runs out. When R2 recovers, check Detect again; if uploads failed during the outage, do B.

**B. Uploads are failing (R2 stale).** Fix the cause (usually the token: [secrets rotation](secrets-rotation.md)), then republish. The next live cycle republishes `conditions` and `forecasts`; to catch up immediately, dispatch the jobs:

```bash
gh workflow run live-conditions.yml --ref main
gh workflow run daily-data.yml --ref main
gh workflow run forecast-tiles.yml --ref main -f force=true
```

Or mirror a branch from a checkout (needs `pip install -r requirements-publish.txt` and the credentials above):

```bash
git fetch origin conditions --depth=1
git worktree add --detach var/r2-resync-conditions FETCH_HEAD
bash scripts/publish_branch_r2.sh var/r2-resync-conditions conditions
git worktree remove var/r2-resync-conditions
```

Repeat with `data` or `forecasts` as needed. This uploads exactly what the GitHub branch holds.

**C. R2 objects were lost or corrupted but the sync index says they are current.** `publish_r2.py` trusts `<prefix>/.r2-sync.json`, so delete it to force a full upload, then do B:

```bash
$W r2 object delete skippercast-feeds/conditions/.r2-sync.json --remote
```

For seafloor archives, rerun the publication: `gh workflow run seafloor.yml --ref main -f region=morro-bay`.

## Verify

- Every line of Detect shows `200` and `x-feed-source: r2`.
- `latest.json` on `$SITE/feeds/conditions/` matches the GitHub copy (Detect and Diagnose step 4).
- After PR #30: `python3 scripts/verify_published_feed.py "$SITE/feeds/conditions/latest.json" <run_id>` passes for the latest run.

## Rollback

Fix A changes nothing. If a deploy without the `FEEDS` binding was made anyway, a normal deploy restores it: **Actions → Deploy to Cloudflare → Run workflow**. Fixes B and C only write what the GitHub branches already hold; there is nothing to undo.

## Escalate

Cloudflare support (dashboard → Support) for an R2 incident longer than an hour or data loss in the bucket. The owner for any token change.

## Postmortem

Required if users saw stale or failed feeds for more than an hour. Use the [postmortem template](../incident-response.md#postmortem-template).
