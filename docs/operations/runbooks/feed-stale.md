# Runbook: live conditions feed is stale

**Symptom:** the app's Live and forecast cards show old times or "stale" labels; a GitHub issue labelled `feed-stale` titled "Live conditions feed is stale" is open; the *Live feed freshness* workflow is red.
**Severity:** SEV2 when the feed is more than 3 hours old (the issue threshold); SEV3 between 75 minutes and 3 hours (the automatic-restart threshold). See [incident response](../incident-response.md) for levels.
**Owner:** repository owner. An agent may diagnose and open fix PRs; only the owner merges or changes secrets.

## How the feed is produced

- `.github/workflows/live-conditions.yml` runs `scripts/live_loop.py`, which runs `scripts/live_cycle.sh` every 30 minutes (at :07 and :37) for about 5.5 hours, then dispatches its own successor. A push to `main` that touches the live pipeline runs one cycle.
- Each cycle rebuilds forecast tiles (`scripts/publish_forecasts.sh`; a failure keeps the previous tiles), refreshes every region (`scripts/refresh_regions.py live|intelligence|habitat`), commits to the `conditions` branch, mirrors that commit to R2 (`scripts/publish_branch_r2.sh` → `scripts/publish_r2.py`), then checks saved trips (`scripts/check_saved_trips.py`).
- Two things restart a broken chain: the hourly *Live feed freshness* workflow (`.github/workflows/feed-freshness.yml`, at :52) dispatches `live-conditions.yml` when the feed is more than 75 minutes old and no run is queued or running; and, on the Cloudflare deployment only, the Worker cron (`server/watchdog.js`, every 15 minutes) does the same at 45 minutes if the `GITHUB_TOKEN` Worker secret is set.
- The Worker serves `/feeds/conditions/...` from R2 when the `FEEDS` bucket is bound (Cloudflare), otherwise from the GitHub branch (ChatGPT Sites, which serves skippercast.com today). See `server/feeds.js`.

What "fresh" means: `scripts/check_feed_freshness.py` reads `completed_at` (or `generated_at`) from `latest.json`. On `main` it checks the GitHub branch copy only. After PR #30 ([P0-04]) merges, it checks the public route first (`$FEEDS_PUBLIC_BASE/feeds/conditions/latest.json`, reading `published_at`) and reports the GitHub copy as a secondary signal.

## Detect

Set these once per shell:

```bash
export SITE=https://skippercast.com     # or the Cloudflare site, the CLOUDFLARE_SITE_URL repository variable
export RAW=https://raw.githubusercontent.com/Grahammmm/skippercast
```

1. The same check the workflow runs, from a checkout of `main`:
   ```bash
   python3 scripts/check_feed_freshness.py --max-age-hours 3
   ```
   Exit status 1 and a "stale" or "could not be fetched" line means the feed is not confirmed fresh.
2. Compare what users get with what GitHub holds (the timestamp, the run id if present, and which store answered):
   ```bash
   for url in "$SITE/feeds/conditions/latest.json" "$RAW/conditions/latest.json"; do
     curl -fsS "$url" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("published_at") or d.get("completed_at") or d.get("generated_at"), d.get("run_id"), sys.argv[1])' "$url"
   done
   curl -sS -o /dev/null -D - "$SITE/feeds/conditions/latest.json" | grep -i '^x-feed-source'
   ```
   Use GET as shown: the Worker's `/feeds/` route answers GET only, so `curl -I` does not reach it.

## Diagnose (in order)

1. **Is a live run going at all?**
   ```bash
   gh run list --workflow live-conditions.yml --limit 5
   gh run list --workflow feed-freshness.yml --limit 3
   ```
   - No run in the last hour, and none queued: the self-dispatch chain broke (a cycle ended in under an hour, so it deliberately did not chain; or GitHub cancelled the run). Go to Fix 1.
   - Workflows show as disabled (`gh workflow list --all`): GitHub disables scheduled workflows after 60 days without repository activity. Go to Fix 1.
2. **Did the latest run fail, and where?**
   ```bash
   gh run view <run-id> --log-failed | tail -80
   ```
   - *Test the live conditions pipeline* failed: a change on `main` broke a live test (`python scripts/run_core_tests.py --scope live`). Go to Fix 2.
   - `Cycle N did not publish cleanly` with a Python traceback from `refresh_regions.py`: one region or source raised. On `main`, `live_cycle.sh` runs under `set -e`, so one failing region stops publication for every region (PR #34, [P2-04], isolates regions). Go to Fix 2.
   - `git push` to `conditions` rejected: someone else pushed to the branch, or the workflow lost `contents: write`. Re-dispatch (Fix 1); if it repeats, inspect `git ls-remote origin conditions` and the workflow `permissions:` block.
   - `R2 publish failed` or `could not verify CLOUDFLARE_API_TOKEN`: on `main` this is only a warning and the GitHub copy is current, but the Cloudflare site keeps serving the older R2 copy. After PR #30 merges it fails the cycle. Go to the [R2 outage runbook](r2-outage.md) and, for a bad token, [secrets rotation](secrets-rotation.md).
   - `Delivery was held or ambiguous` from `check_saved_trips.py`: the conditions feed *was* published (the trip check runs after it); this is a push-delivery problem, not staleness. Check the feed age again before treating it as SEV2.
3. **Is GitHub fresh but the public route stale?** Then publication to GitHub works and the store the site reads is behind: R2 (Cloudflare) or an edge cache. Follow the [R2 outage runbook](r2-outage.md). Edge-cache TTLs are 60 seconds for `latest.json`, so a gap longer than a few minutes is not caching.
4. **Is everything stale, including GitHub, with green runs?** Check the step summary of the latest run (`gh run view <run-id>`) for `0/N cycles published`, and the source warnings written by `scripts/report_conditions.py`. A provider outage shows as `stale`/`failed` sources with a published feed; that is expected fail-closed behaviour, not a stale feed.

## Fix

1. **Restart the chain.**
   ```bash
   gh workflow enable live-conditions.yml          # only if it was disabled
   gh workflow run live-conditions.yml --ref main
   ```
   The first cycle starts immediately; a normal cycle takes a few minutes, and up to about 15 when the intelligence stage runs.
2. **Fix forward on `main`.** Open a PR that fixes the failing test or source adapter (or, for a single broken provider, makes the adapter record the source as `failed` instead of raising, the existing fail-closed pattern of `source()` in `src/skippercast/pipeline/collect.py`). Never skip or weaken a live test to get the feed out. After merge, a push that touches the pipeline runs one cycle; then restart the chain (Fix 1).
3. **Credentials or R2:** follow [R2 outage](r2-outage.md) or [secrets rotation](secrets-rotation.md), then Fix 1.
4. **Other feeds.** The same pattern applies to the daily `data` feed (`.github/workflows/daily-data.yml`, 4:17 a.m. Pacific; restart with `gh workflow run daily-data.yml --ref main`) and forecast tiles (`gh workflow run forecast-tiles.yml --ref main -f force=true`). Check their age with:
   ```bash
   curl -fsS "$SITE/feeds/data/latest.json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("completed_at"))'
   curl -fsS "$SITE/feeds/forecasts/gfs_global/manifest.json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("cycle_iso"))'
   ```

## Verify

- `python3 scripts/check_feed_freshness.py --max-age-hours 3` exits 0.
- Both `latest.json` copies from Detect step 2 show the same, recent time.
- The `feed-stale` issue closes on the next hourly freshness run; to close it sooner, run `gh workflow run feed-freshness.yml --ref main`.
- The app's Live card shows a reading from the last hour.

## Rollback

Nothing to roll back for a restart. If a fix PR made things worse, revert it through a PR; the next push-triggered cycle republishes. The `conditions` branch keeps its history, so a bad generation is replaced by the next good cycle; do not force-push the branch by hand.

## Escalate

- The owner, if a fix needs a secret, a workflow permission or a merge.
- GitHub Status (githubstatus.com) if Actions runs are not starting at all.
- The provider's status page when one source is down; the app already labels it, so this does not block closing the incident.

## Postmortem

Required for SEV2 (more than 3 hours stale). Use the template in [incident response](../incident-response.md#postmortem-template) and link it from the `feed-stale` issue before closing it.
