# Why forecast skill still says “not enough data”

- The live page is still reading its November 4 scorecard: zero checks in all 18 cells (§1).
- The live job publishes the buoy and forecast archive, but does not rebuild the scorecard the page and brief read (§§2–3).
- **Measured November 22 (§5):** the published archive holds matched pairs. The existing `--check` clears the minimum in 18 of 18 rows, so the matcher and the archive are not what keeps the page empty; the stale static file is.
- **Recommendation:** with the owner's word, regenerate the one JSON from a reviewed archive copy and release it through the normal site build. A one-off fix reads for 14 days; keeping it fresh needs a workflow or schedule change that is the owner's call (§4).

Sections 1–4 were written against `origin/main` at `9163c89fcdb345fe4e03c42f7f22c2264f0d4e61`, with public files and Actions history checked November 21, 2026 (UTC); §§3–4 are updated and §5 added on `origin/main` at `245568f3be520b779a789aad6be62ac5a6c7b8a3` (November 22, 2026). The earlier dated observations are kept as written.

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

**On November 21 the match count was UNVERIFIED (now measured, §5; the cause of the original zero is still not established).** The run log gives no archive row counts or match totals, and the two public files in §1 contain no archive rows. The matcher needs a timely, valid reading for the same station and variable, among other checks (`src/skippercast/pipeline/verification.py:230–252,263–312`). A buoy reading or a forecast on its own does not prove a match. The scorecard command used to turn a missing manifest into empty input (`fd469781e`, November 21, changed that); it now refuses (`scripts/publish_forecast_skill.py:89–93`; `src/skippercast/pipeline/verification_archive.py:176–179`). The November 4 file predates that change, so a tree without the archive could have produced its zeros, but that is not proof that it did. The established cause of the **persistent** zero display is that the conditions run updates the archive, not the static scorecard (§2); there is not enough evidence to blame an empty archive or a matcher mismatch.

## 4. Smallest fix

**The build proposed on November 21 has landed (`fd469781e`, November 21).** `scripts/publish_forecast_skill.py:89–93` requires the archive for every selected port, and `--check` (`:104–112,122,126–133`) prints per-port input counts and per-row matched counts, then exits without writing. `tests/test_skill_scorecard.mjs:219–278` covers it: a constructed archive reports the expected counts with the sentinel output untouched (C2, C5), and a missing manifest exits 1 naming the port with the sentinel untouched (C1, C4). No new code is needed to diagnose or refresh. The remaining steps are not a build; the first one is already done (§5).

**Next step, under two hours once the owner approves (nothing here runs it):** (1) the no-write check on a reviewed archive copy is done (§5); repeat it on a fresh copy immediately before the refresh. (2) Run the existing publisher without `--check`, same arguments, to rewrite only `dist/data/forecast-skill.json`. (3) Release it as a normal reviewed PR through the site build. The expected reader tests need no edit: `tests/test_brief_skill.mjs:49–53` and `tests/test_skill_scorecard.mjs:95–97` judge the file by its own `generated_at` and shape. As the pre-release check, read the new file with `skillSummary` at a fixed clock (for example generation time plus one hour) and expect state `known`, then at generation plus 14 days plus one minute and expect `unknown` (`web/brief/skill.ts:13,43–44`).

**The owner's word is needed for:** any regeneration or release of the live scorecard, and above all any workflow or schedule change. The brief treats a scorecard older than 14 days as UNKNOWN, so a one-off refresh restores the page and brief for at most 14 days. Keeping them fresh means running the publisher on a schedule, for example after the intelligence cycle in `live-conditions.yml` (`scripts/live_cycle.sh:39–41`). That is a workflow or schedule edit and is held for the owner; nothing here edits, runs or dispatches a workflow. Thresholds and the matcher stay as they are.

## 5. Measured November 22, 2026 (read-only)

Clocks are kept apart. HTTP `Date` of the GETs: `Sun, 22 Nov 2026 23:04:51 GMT`. [skippercast.com/data/forecast-skill.json](https://skippercast.com/data/forecast-skill.json) returned 200, SHA-256 `7e19f2e3…9c65`, `generated_at` `2026-11-04T03:07:56Z`, 18 rows, 0 with `n>0`: the same bytes as §1, still 18 days old. Git changed-file date of the tracked file: `1db174d7b`, 2026-11-03 19:11 PST (the later `fd469781e` and `613bbe9f5` touched the script and this report, not the JSON). `/skill` returned 200.

Archive identity: `git ls-remote origin conditions` gave `69a2bed7378aa8de0dd3db5cc7fe6a565d1ad62e`. Its `regions/morro-bay/verification-state.json` (SHA-256 `321c2a98…de46`) is schema 2, `generated_at` `2026-11-22T22:51:23Z`, 284 shards (222 forecast, 62 observation), 96,572 forecasts, 7,699 observations, 30-day retention; stations 46215 and 46028; cycle days from 2026-10-17. The run that wrote this commit was not identified. The latest completed run found is [45047746484](https://github.com/Grahammmm/skippercast/actions/runs/45047746484) (success, started 17:08Z on `171eed915`); its log shows 12 cycles and `Published conditions as single commit …` each time, and no scorecard step. Since November 4: 151 live-conditions runs on `main` (81 success, 68 cancelled, 1 failure, 1 in progress at the time).

I fetched all 284 shards by that commit SHA (1.30 MB), checked each against its manifest SHA-256 (284 match, 0 bad), and ran the existing check on the disposable copy outside the repo, with explicit index, directory, fixed clock and a sentinel output:

```sh
python3 scripts/publish_forecast_skill.py --check --regions-dir <copy> --index dist/regions/index.json --out <sentinel> --now 1795387883
```

Result, exit 0, sentinel bytes unchanged: `morro-bay: 96572 forecasts, 7699 observations`, `check: 18 of 18 rows clear the minimum`. Per row, 7-day `n` is 663–1,008 over 168 valid times, 8 days and 31–32 runs; 30-day `n` is 2,903–4,320 over 699–720 valid times, 31 days and 123–124 runs. `n` counts matched pairs across runs and models, not distinct hours. **Findings:** the archive exists, holds both sides, and the same matcher produces matched pairs at every lead and window, so there is no matcher mismatch on this archive. That the November 3 archive also held pairs, and what produced the November 4 zeros, remain **UNVERIFIED**: the `conditions` branch is a single parentless commit with no history, and the zeros are consistent with a tree that lacked the archive (§3). Percentages are not given here; the check prints counts only.
