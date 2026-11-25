# Which Node tests take the most CI time?

- **Timing:** The [latest three main runs](#1-what-the-ci-logs-can-tell-us-c1) do not give us a top 20. An older main run logs thousands of case times but almost no file times.
- **Overlap:** The [source comparison](#2-duplicate-coverage-c2) found one whole case and several individual inputs whose checks are already covered elsewhere.
- **Recommendation:** Remove the duplicate checks for easier maintenance; measure file times before choosing a speed fix. Do not change which suites CI runs.

Source checked at main commit [`7335068efd2627dd2a0ba9bea39f09e86a8f252d`](https://github.com/Grahammmm/skippercast/commit/7335068efd2627dd2a0ba9bea39f09e86a8f252d). GitHub Actions runs below are pinned by run and attempt; the source line references are at that commit.

## 1. What the CI logs can tell us (C1)

**UNVERIFIED: per-file times and the top 20 for the latest three main runs.** At the 2026-11-21 13:30 UTC check, the three newest runs of `Offline checks` on `main`, without filtering out cancellations, were all first attempts:

| Run | Created (UTC) | What `gh run view --log` returned |
| --- | --- | --- |
| [44908555492](https://github.com/Grahammmm/skippercast/actions/runs/44908555492/attempts/1) | 13:22:41 | Queued in the listing; the CLI said `run 44908555492 is still in progress; logs will be available when it is complete`. |
| [44908525424](https://github.com/Grahammmm/skippercast/actions/runs/44908525424/attempts/1) | 13:22:19 | Cancelled; exit 0, zero bytes of log output. |
| [44908491056](https://github.com/Grahammmm/skippercast/actions/runs/44908491056/attempts/1) | 13:21:56 | Cancelled; exit 0, zero bytes of log output. |

An absent timing is not a zero. The workflow runs the Node suite in both `check` jobs (the job labels are Python 3.11 and 3.13). The main Node step runs `tests/test_*.mjs` except the contrast file, which has a separate step. The local `npm test` script includes that file in its glob instead (`.github/workflows/ci.yml:312–323,432–443`; `package.json:9–15`).

As a cross-check, the [latest successful main run visible at collection](https://github.com/Grahammmm/skippercast/actions/runs/44900870525/attempts/1) and one [successful pull-request run](https://github.com/Grahammmm/skippercast/actions/runs/44902015553/attempts/1) both printed 8,428 duration rows per `Forecast handling and GPX checks` job. Only **one** result row per job names a test file; most rows name individual cases without a source path. `# duration_ms` at the end is the whole Node step's reporter total, not a file total. The two jobs run separately; adding their times would not give the time someone waits for CI. These runs are format checks, not replacements for the requested three.

| Observable result | Main `check (3.11)` / `check (3.13)` | Pull request `check (3.11)` / `check (3.13)` | What it covers |
| --- | ---: | ---: | --- |
| Main Node suite, reporter total | 207,111.666 / 280,045.496 ms | 232,088.793 / 308,816.216 ms | The whole glob, less contrast; no attribution to files (`.github/workflows/ci.yml:432–440`). |
| `tests/test_f13_02_audit.mjs`, file row | 29.593 / 38.427 ms | 37.612 / 42.407 ms | Loading the opt-in phone print/privacy diagnostic. The Chromium/PDF assertions require a mode argument, so these are **not** timings of those assertions (`tests/test_f13_02_audit.mjs:1–16,53–57`). |
| `tests/test_contrast_ci_adoption.mjs`, separate one-file suite total | 306.556 / 410.207 ms | 336.897 / 426.075 ms | Light/dark design-token contrast and the pinned source proof; this number includes the one-file runner overhead (`.github/workflows/ci.yml:441–443`; `tests/test_contrast_ci_adoption.mjs:25–62`). |

**Replay the evidence.** The listings are live, so use the pinned run IDs above to reproduce the sample, not whatever three runs are now newest. Save log output outside the checkout. The older main log contains the sole filename row at lines 23888–23890 and 79861–79863, and the summary durations at 58119, 58151, 114092 and 114124. The pull-request log has those rows at 25302–25304 and 86119–86121, and 59533, 59565, 120350 and 120382, respectively.

```sh
gh run list -R Grahammmm/skippercast -w ci.yml -b main -L 3 --json databaseId,attempt,headSha,status,conclusion,createdAt,event,url
gh run list -R Grahammmm/skippercast -w ci.yml -b main -s success -L 3 --json databaseId,attempt,headSha,status,conclusion,createdAt,event,url
gh run list -R Grahammmm/skippercast -w ci.yml -e pull_request -s success -L 3 --json databaseId,attempt,headSha,createdAt,url
gh run view -R Grahammmm/skippercast 44908555492 -a 1 --log
gh run view -R Grahammmm/skippercast 44908525424 -a 1 --log
gh run view -R Grahammmm/skippercast 44908491056 -a 1 --log
gh run view -R Grahammmm/skippercast 44900870525 -a 1 --log > main-node.log
gh run view -R Grahammmm/skippercast 44902015553 -a 1 --log > pr-node.log
rg -n -A 2 'Forecast handling and GPX checks.* (not )?ok [0-9]+ - tests/test_[^ ]+\.mjs$' main-node.log pr-node.log
rg -c 'Forecast handling and GPX checks.* +duration_ms: ' main-node.log pr-node.log
rg -n '(Forecast handling and GPX checks|Design token contrast).*# (tests|duration_ms) ' main-node.log pr-node.log
```

The count command yields 16,856 rows in each file (8,428 in each job). The filename command yields two results per log, both for `test_f13_02_audit.mjs`. Do not rank files by guessing from case names, summing unassigned case durations, or treating the elapsed span of log output as a file's runtime.

## 2. Duplicate coverage (C2)

Only the checks explicitly identified below are candidates. For a mixed case, remove only the named assertions and keep the case. This is proof from the source, not a measurement of time saved. A complete inventory outside the groups below is **UNVERIFIED**.

| Same behavior and module | Candidate to remove | Evidence that the retained check covers it |
| --- | --- | --- |
| `oceanLines` in `web/trip-ocean-lines.ts`: a pack without ocean data, or with an empty regional layer map | Whole case at `tests/test_trip.mjs:438–442` | Both files import the same helper and pin the same clock (`tests/test_trip.mjs:404–408`; `tests/test_trip_ocean_layer_shape.mjs:6–9`). The retained `tests/test_trip_ocean_layer_shape.mjs:23–25,48–51` checks the identical three inputs and outputs: `{}` and `{ocean: undefined}` give `null`; `{ocean: {path: 'regional', layers: {}}}` gives `not saved` for both water and currents. All three assertions are covered. The separate coastal-report and real saved-pack checks stay (`tests/test_trip.mjs:444–456`). |
| `hourText` and `dayOptions` in `web/app/TimeDock.tsx`: English clock and day labels | Only `tests/test_app_shell.mjs:624,627` in the case at line 621 | Both bundle the same exports (`tests/test_app_shell.mjs:66`; `tests/test_time_season_i18n.mjs:25–28`). The retained `tests/test_time_season_i18n.mjs:46–51` checks midnight, noon and 2 pm with the same outputs, and the same eight English day labels (the `WEEK` array at `tests/test_app_shell.mjs:26`) from the same date/time, Los Angeles time zone and null selection (`tests/test_time_season_i18n.mjs:16,48`; `tests/test_app_shell.mjs:626–629`). Keep the store and selected-day checks in the shell case. |
| `cadenceLine` in `web/map/freshness.ts`: exact English water temperature and cloud update wording | Only `tests/test_layer_cadence_names.mjs:49–50` | `tests/test_layer_cadence_names.mjs:13–19` and `tests/test_layer_freshness.mjs:13–25` load the same module. The retained `tests/test_layer_freshness.mjs:42–43` checks the same two IDs and language against the same exact wording, including both age limits. Keep the inventory count and unknown-ID checks (`tests/test_layer_cadence_names.mjs:22–47`). |
| `monthDay` in `server/advisor/answers/fishid.ts`: the Spanish rendering of the last day of December 2026 | Only `tests/test_advisor_fishid.mjs:158` | Both import the same module (`tests/test_advisor_fishid.mjs:22`; `tests/test_advisor_fishid_dates.mjs:15`). The retained `tests/test_advisor_fishid_dates.mjs:19–27` directly checks the identical input and output, `2026-12-31` in `es` → `31 dic`, without requiring the database fixture. Keep the rule-selection and fallback checks (`tests/test_advisor_fishid.mjs:138–157`). |

## 3. Small next units (C3)

These are work estimates, not measured savings. **UNVERIFIED:** impact on the Node step or on the time a pull request waits for CI.

1. **Trip ocean coverage cleanup (45 minutes).** Drop just the three-assertion case at `tests/test_trip.mjs:438–442`; keep the shape and saved-pack checks in Section 2. Compare both files' focused offline results before and after with `node --test tests/test_trip.mjs tests/test_trip_ocean_layer_shape.mjs`. Expect one fewer case and no lost inputs in the table above.
2. **Display wording cleanup (75 minutes).** Remove the named repeated English clock/day and water/cloud lines, not their surrounding cases (`tests/test_app_shell.mjs:624,627`; `tests/test_layer_cadence_names.mjs:49–50`). Replay `node --test tests/test_app_shell.mjs tests/test_time_season_i18n.mjs tests/test_layer_cadence_names.mjs tests/test_layer_freshness.mjs`. Expect the same cases and skips; verify that the exact strings still have an owner.
3. **Spanish date cleanup (30 minutes).** Remove only `tests/test_advisor_fishid.mjs:158`. Replay `node --test tests/test_advisor_fishid.mjs tests/test_advisor_fishid_dates.mjs`; confirm the direct date case runs and the rules case is otherwise unchanged.
4. **Get usable file timings before tuning (90 minutes; needs the operator's word for any workflow or CI-tier change).** Prototype a file-level timer in a small offline trial, keeping the exact Node file selection and the separate contrast gate (`.github/workflows/ci.yml:432–443`). Check that it records one duration per file including setup, keeps test results and skips visible, and cannot turn a failed file green. Compare the same fixtures with and without timing. If adopted in CI, use future normal runs, compare the two jobs separately, and choose a speed fix only after a file is consistently near the top. The current logs do not support naming a slow file.
