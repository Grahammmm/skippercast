# Why forecast skill still says “not enough data”

- The live page is still reading its November 4 scorecard: zero checks in all 18 cells (§1).
- The live job publishes the buoy and forecast archive, but does not rebuild the scorecard the page and brief read (§§2–3).
- **Recommendation:** add a no-write check to the existing scorecard command, then use it to confirm matches before approving a one-off refresh. Leave scheduling out of this build (§4).

Source checked against `origin/main` at `9163c89fcdb345fe4e03c42f7f22c2264f0d4e61`. Public files and Actions history checked November 21, 2026 (UTC).

## 1. What the page shows

[The live `/skill` page](https://skippercast.com/skill) loads [the published scorecard](https://skippercast.com/data/forecast-skill.json). Both returned HTTP 200. The scorecard's `generated_at` is `2026-11-04T03:07:56.066252Z`, displayed as **2026-11-04 03:07 UTC**. Every count is zero and every cell says “not enough data yet” rather than showing a percentage (`dist/skill-page.js:40–59,67–75`). Counts below are **7-day / 30-day** for each forecast lead:

| Morro Bay & Avila buoy / forecast | 24 h | 48 h | 72 h |
| --- | --- | --- | --- |
| Diablo Canyon (46215), waves | 0 / 0 | 0 / 0 | 0 / 0 |
| Cape San Martin offshore (46028), wind | 0 / 0 | 0 / 0 | 0 / 0 |
| Cape San Martin offshore (46028), waves | 0 / 0 | 0 / 0 | 0 / 0 |

The brief reads the same URL. For an hour under 24 hours ahead it resolves to **“Forecast skill 24 h ahead: UNKNOWN. The scorecard could not be read, is out of date or lacks this lead. Not for navigation.”** The November 4 stamp was over its 14-day limit on November 21. Even at a date when the file was fresh, its zero counts could not produce a percentage. This is the result of applying the brief reader to the live file, not an inspection of every live brief; individual screens are **UNVERIFIED** (`web/brief/skill.ts:10–11,20–28,34–62,70–73`; `catalog/app/strings.json:154–162`; `tests/test_brief_skill.mjs:35–49`).

The last commit that changed the checked-in file was November 3 at 19:11 Pacific (November 4 at 03:11 UTC), not November 10. `git log -1 --format='%h %aI %cI' HEAD -- dist/data/forecast-skill.json` returns `1db174d7b 2026-11-03T19:11:46-08:00 2026-11-03T19:11:46-08:00`. The [live JSON](https://skippercast.com/data/forecast-skill.json) and the tracked file are byte-identical (`cmp` exit 0; SHA-256 `7e19f2e3bda15e4458fbe7e0a2c2baec1960c449a34ae946426bc57eea7e9c65` for both). To see each count in the downloaded JSON:

```sh
jq -r '.generated_at, (.scores[] | [.station,.variable,.lead_hours,.window_days,.n,.enough] | @tsv)' forecast-skill.live.json
```

Result: the timestamp above, then 18 score cells with `n=0` and `enough=false`.

## 2. How it was meant to refresh

1. The live workflow calls `scripts/live_loop.py`, which runs `scripts/live_cycle.sh` and asks for an intelligence refresh when due (`.github/workflows/live-conditions.yml:48–58`; `scripts/live_loop.py:35–52,60–72`). The cycle loads the last `conditions` snapshot into `var/live-published`, and runs the intelligence collector into `var/live` (`scripts/live_cycle.sh:18–24,34–41`; `scripts/refresh_regions.py:83–98`).
2. The collector merges saved and new forecasts and buoy observations, uses `verify()` to match them, and saves the two sets of records under `var/live/regions/<port>/`. The archive stores forecasts and observations separately in checked gzip files listed in `verification-state.json`; it does not store a table of pairs. The cycle copies the regional tree into `var/live-published/regions`, checks and prunes the archive, and publishes `var/live-published` to the `conditions` branch and feed bucket (`src/skippercast/pipeline/intelligence.py:148–155,170–193,210–218`; `src/skippercast/pipeline/verification_archive.py:170–191,220–240,283–294,297–325`; `scripts/live_cycle.sh:49–60,74–82`).
3. The separate scorecard command reads each active port's archive from that staged tree, reuses the same matcher and counts wind and wave-height checks in the last 7 and 30 days. It only reports a percentage with at least 30 distinct forecast times across 7 days and 3 model runs. It writes **`dist/data/forecast-skill.json`**, not a file in the `conditions` tree. The site build copies that static file rather than calculating a new one (`scripts/publish_forecast_skill.py:41–59,62–110`; `src/skippercast/pipeline/verification.py:16–18,225–252,263–312,360`; `.github/workflows/deploy-cloudflare.yml:265`; `package.json:10`; `scripts/build-worker.mjs:20`; `scripts/client-build.mjs:104–113,191–201`).

No refresh is visible since the November 4 scorecard. `git grep -n -e forecast-skill -e publish_forecast_skill HEAD -- .github/workflows scripts/live_loop.py scripts/live_cycle.sh` returns no matches (exit 1). The history and live file in §1 show no change to the figure the site actually reads. The following list establishes that the conditions workflow kept running after November 4. It does not by itself show which files those runs wrote:

```sh
gh run list -R Grahammmm/skippercast --workflow live-conditions.yml --branch main \
  --created '2026-11-04T03:07:56Z..2026-11-21T08:09:49Z' --limit 200 \
  --json databaseId,createdAt,event,headSha,conclusion > live-runs-window.json
jq '{runs:length, first:(map(.createdAt)|min), successful:(map(select(.conclusion=="success"))|length)}' live-runs-window.json
```

Observed: 137 runs, first created `2026-11-04T03:11:36Z`, 74 successful. A [successful November 21 run](https://github.com/Grahammmm/skippercast/actions/runs/44857887795) started at `02:48:46Z` on `4ebb985d938482568d7804ebefd03aa0f5850322`. `gh run view 44857887795 -R Grahammmm/skippercast --log` shows `Published conditions as single commit 6ba5e450c664.` at `03:45:39Z` in cycle 1 and no scorecard invocation or output in that run. Whether anyone rebuilt a scorecard privately or outside this workflow is **UNVERIFIED**.

## 3. Is there matched data

**The November 21 conditions run provides evidence that a Morro Bay archive was published.** The same log shows `Cycle 1 at 03:06Z (intelligence: yes)` and a Morro Bay intelligence result at `03:30:29Z` with `status: degraded`, `completed_at: 2026-11-21T03:20:20Z`, and `hfr-1` in `issues`, not a failed refresh. The collector writes the archive before it returns that result, and the cycle copies and validates the regional tree before the conditions commit in §2 (`scripts/refresh_regions.py:83–99,158–169,198–205`; `src/skippercast/pipeline/intelligence.py:210–218`; `scripts/live_cycle.sh:5,39–41,49–60,74–77`). That is evidence from the published run, not a direct inspection of its manifest bytes.

**UNVERIFIED: how many matches that archive would produce, and why the original file had zero.** The run log gives no archive row counts or match totals, and the two public files in §1 contain no archive rows. The matcher needs a timely, valid reading for the same station and variable, among other checks (`src/skippercast/pipeline/verification.py:230–252,263–312`). A buoy reading or a forecast on its own does not prove a match. The scorecard command also turns a missing manifest into empty input today (`scripts/publish_forecast_skill.py:82–91`; `src/skippercast/pipeline/verification_archive.py:170–191`). That is one way to create the observed zeros, not proof that it happened. The established cause of the **persistent** zero display is that the conditions run updates the archive, not the static scorecard (§2); there is not enough evidence to blame an empty archive or a matcher mismatch.

## 4. Smallest fix

**One follow-up build, estimated under two hours (UNVERIFIED estimate):** change only `scripts/publish_forecast_skill.py` and extend `tests/test_skill_scorecard.mjs`. Require the archive for every selected active port using the loader's existing `required=True` option. Add `--check` to run the same matching and show per-port input counts, per-row matched counts and how many rows clear the minimum, then exit without writing JSON. A missing or unreadable archive should give a clear error before any output write; a readable archive with too few matches should still report honest counts without a percentage. Reuse existing matching and score rules (`scripts/publish_forecast_skill.py:41–59,82–110`; `src/skippercast/pipeline/verification_archive.py:170–191`).

**One focused offline CLI test:** extend the constructed-archive fixture in `tests/test_skill_scorecard.mjs:133–157`. With a fixed time and known matching records, `--check` should report the expected counts and leave a sentinel `--out` file unchanged. Repeat inside that test with the manifest missing: require a nonzero exit, an error naming the port, and the same untouched sentinel. The existing tests check scoring; they do not protect against a missing archive quietly becoming a newly dated zero scorecard (`tests/test_skill_scorecard.mjs:139–178`).

**To restore the live page:** use the check on an approved copy of the published regional tree first. If the counts support a score, regenerate the one static JSON with the existing publisher and release it through the normal reviewed site build. If counts are still low, keep the minimums and investigate the input counts before changing the matcher. The follow-up build itself does not regenerate or deploy live data. Wiring the publisher into any workflow or changing its schedule **needs the owner's word** and is not part of this build (§§2–3).
