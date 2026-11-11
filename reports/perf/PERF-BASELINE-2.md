# PERF-BASELINE-2: second, smaller page-load measurement of the live build (SC1922-12)

Date: 2026-11-10 PST (measured 2026-11-11 04:16-04:28 UTC). Lab numbers from one shared host, one browser, one load at a time. **They are observations, not a pass or fail, and not real-device speed.** The 2026-11 baseline (`PERF-BASELINE-1.md`, `raw/live-desktop.json`, `raw/live-phone.json`, `raw/summary.json`) is untouched (SHA-256 of all 61 tracked files under `reports/perf` identical before and after).

## 1. Which build was measured (status: **deployed build verified**)

A workflow run's head SHA is only its trigger. The shipped SHA below comes from the deployment check run and the smoke step of the same run; the live build id is a different thing again (a client build stamp, not a commit).

| link | evidence (read-only `gh` / one GET) | result |
|---|---|---|
| newest deploying run | `deploy-cloudflare.yml` run **42957769171** (created 2026-11-11T04:13:04Z); jobs source/rollback/deploy/report = success/skipped/success/success; step `Back up D1, migrate and deploy` = success, smoke-test step = success, `Roll back after a failed smoke test` = skipped | ok |
| trigger vs selected | trigger SHA `2e278b853ff36dd5285403774236992beecd32e9`, run head `2e278b853ff36dd5285403774236992beecd32e9`, selected SHA `2e278b853ff36dd5285403774236992beecd32e9` (report job env). Here they coincide; see the example below where they did not | ok |
| deploy check run | **130317361593** `Cloudflare deploy`, conclusion `success`, title `Deployed 2e278b853`, attached to `2e278b853ff36dd5285403774236992beecd32e9`, completed 2026-11-11T04:14:31Z; summary: "Why: deployed 2e278b853ff36dd5285403774236992beecd32e9 (newest main commit with successful Offline checks) and its smoke test passed; production served 6bd39044a4afdcfaae64bd7b661c30aa8dcc75cb before" | ok |
| smoke step in the same run | deploy job log of run 42957769171: `health ok (build c0fafae87d)` | build `c0fafae87d` |
| later runs, read before | none newer than run 42957769171 in the 100 most recent `deploy-cloudflare.yml` runs (read 2026-11-11T04:15:41+00:00) | none |
| `/api/health` before | read 2026-11-11T04:15:47+00:00: HTTP 200, `{"service":"SkipperCast","version":"0.8.0","build":"c0fafae87d"}` | build `c0fafae87d` = smoke build |
| `/api/health` after | read 2026-11-11T04:28:44+00:00: HTTP 200, `{"service":"SkipperCast","version":"0.8.0","build":"c0fafae87d"}` | build `c0fafae87d` = before |
| later runs, read after | none newer than run 42957769171 (read 2026-11-11T04:28:40+00:00); run, check run, SHA and build identical to the first read | none |

Shipped SHA: `2e278b853ff36dd5285403774236992beecd32e9`. Live build id before and after: `c0fafae87d` / `c0fafae87d`. No deploy or rollback ran between the two reads, so **all 36 loads are attributed** to this build and none is marked unattributed.

The deploy run 42957769171 was still in progress when this task started (04:13 UTC, step `Back up D1, migrate and deploy` running). Nothing was measured until it had completed (04:14:35Z) and the first read above had passed.

Trigger, selected SHA and build id are distinct. Example from the retained evidence: run 42956996172 (head `2e278b853`, 04:05:59Z) deployed **`6bd39044a4afdcfaae64bd7b661c30aa8dcc75cb`**: its report job logged `SELECTED_SHA: 6bd39044a4afdcfaae64bd7b661c30aa8dcc75cb`, `SOURCE_REASON: newest main commit with successful Offline checks (newer: 2e278b853 pending)` and created check run 130314896389 on `6bd39044a`; there is no deploy check run on `2e278b853` from that run. A reader taking that run's head would have been wrong.

Ancestry (`git -C <clone> merge-base --is-ancestor <merge commit> 2e278b853`, clone at that SHA):

| unit | PR | merge commit | exit |
|---|---|---|---|
| SC1407-03 | #1835 | `c80d656efb2470e08414f7300de4db3db99dd9d1` | 0 |
| SC1407-04 | #1837 | `e8b2aed97f4d3d192f8e927bf0430e62aede2029` | 0 |
| SC1407-06 | #1839 | `07621807a9b463a7720372fbac6eb7bcef8fdc28` | 0 |
| SC1407-07 | #1841 | `020dd86e1da286c1dd5b6dde0d54a7003e81a041` | 0 |
| SC1407-08 | #1840 | `f7623167ad1d016bdd9209451dc5bb842565896d` | 0 |
| SC1407-09 | #1843 | `1deba4ec361e3f27ff0d6f1dfacdacccfb59bfef` | 0 |
| SC1407-10 | #1842 | `358944d62be681f11e50e1e4bdfaeee7bd0d90df` | 0 |

Build id note: building this checkout locally (`node scripts/build-worker.mjs` under memcap) gave build `63b6ecacbb`, not the live `c0fafae87d`, so the local dist cannot be assumed byte-identical to the shipped one. The catalogue asset names therefore were not taken from it alone: the English asset the live site served in the measured loads is `strings.en.generated.5db58dd7c4.js`, the same name as the local dist manifest, and the Spanish table named by that manifest, `strings.es.generated.c14f910685.js`, answered HTTP 200 on a single read-only GET after measuring (199,829 bytes decoded). Same content-hashed names; byte equality of the Spanish file with what the deploy shipped was not proven.

## 2. Method and exact commands

Harness: this checkout is `main` at `2e278b853ff36dd5285403774236992beecd32e9` (equal to the shipped SHA); `measure.mjs` and `summarize.py` are unchanged since PERF-BASELINE-1 (last commit `02c061c7b`). Chromium 156.0.8078.4 (the baseline's version), locale en-US, America/Los_Angeles, service workers blocked, fresh context per run, cold then warm in that context; desktop 1350x940 DPR 1 unthrottled, phone 412x915 DPR 2.625, CPU 4x, 150 ms RTT, 1.6 Mbit/s down, 750 kbit/s up. Pages: landing `/`, brief `/map?region=morro-bay&ui=v2`, map-home `/map` with a saved home port. Read-only public GETs, no sign-in.

Isolation: both raw files and the summarizer output were written under a scratch directory outside the checkout (`SCR=<workspace>/scratch`). `run-live.sh` and `run-ready.sh` were not run. Both measure commands ran one after the other under one 60-minute wall-clock supervisor (ended after 12 min 36 s; the budget was not reached).

```text
node reports/perf/measure.mjs --base https://skippercast.com --pages live --only landing,brief,map-home --runs 3 --profiles desktop --cap-ms 90000 --out $SCR/live-desktop-2.json   # 04:16:02Z-04:21:27Z
node reports/perf/measure.mjs --base https://skippercast.com --pages live --only landing,brief,map-home --runs 3 --profiles phone --cap-ms 150000 --out $SCR/live-phone-2.json       # 04:21:27Z-04:28:37Z
cd $SCR && python3 -B <checkout>/reports/perf/summarize.py $SCR/live-desktop-2.json $SCR/live-phone-2.json > summarize-2.md   # wrote $SCR/reports/perf/raw/summary.json (copied as summary-2.json)
git status --porcelain reports/perf   # empty before the new files were copied in
python3 -B reports/perf/compare_2.py --baseline-summary reports/perf/raw/summary.json --baseline-raw reports/perf/raw/live-desktop.json --baseline-raw reports/perf/raw/live-phone.json \
  --catalogue-asset english=strings.en.generated.5db58dd7c4.js --catalogue-asset spanish=strings.es.generated.c14f910685.js --baseline-catalogue-asset strings.dae9ed705a.js \
  reports/perf/raw/live-desktop-2.json reports/perf/raw/live-phone-2.json
```

Deployment evidence was read with `gh run list -R Grahammmm/skippercast --workflow deploy-cloudflare.yml --limit 100`, `gh run view <id> -R Grahammmm/skippercast --json status,conclusion,jobs`, `gh run view <id> --log --job <report|deploy job id>`, `gh api --paginate repos/Grahammmm/skippercast/commits/<sha>/check-runs?check_name=Cloudflare%20deploy` and `GET https://skippercast.com/api/health` (one script, read-only; the same script ran before and after).

Host: shared 24-core machine, not dedicated; `/proc/loadavg` read after measuring was 21.6 / 30.4 / 25.9 (the 5 and 15 minute figures include a local `build-worker` run that followed the measurement). Other work ran concurrently, so absolute times carry host noise. Each group has 3 runs: min-max below is the whole spread, not a confidence interval.

Group status: brief/desktop/cold 3 ok/0 error/0 unsettled, brief/desktop/warm 3 ok/0 error/0 unsettled, brief/phone/cold 3 ok/0 error/0 unsettled, brief/phone/warm 3 ok/0 error/0 unsettled, landing/desktop/cold 3 ok/0 error/0 unsettled, landing/desktop/warm 3 ok/0 error/0 unsettled, landing/phone/cold 3 ok/0 error/0 unsettled, landing/phone/warm 3 ok/0 error/0 unsettled, map-home/desktop/cold 3 ok/0 error/0 unsettled, map-home/desktop/warm 3 ok/0 error/0 unsettled, map-home/phone/cold 3 ok/0 error/0 unsettled, map-home/phone/warm 3 ok/0 error/0 unsettled.

## 3. Results by group (new vs the baseline's same group)

Baseline columns come from the committed `raw/summary.json` (`*_all` arrays); baseline JS, ds582, catalogue and Aerial figures are derived by `compare_2.py` from the baseline raw runs. Medians of 3. "unmeasured" is null, not zero. The baseline had no separate Spanish table (one string file held both languages), so its Spanish column is not applicable. Inline data:/blob: URLs excluded as in `summarize.py`; bytes are recorded transferred bytes.

### brief / desktop / cold

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 252 (236-476), n=3 | 164 (152-176), n=3 | +88 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 1320 (948-1712), n=3 | 268 (232-276), n=3 | +1052 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 215 (205-612), n=3 | 11631 (11624-12148), n=3 | -11416 |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 474 (311-663), n=3 | 253 (217-259), n=3 | +221 **worse** |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 132 (128-132), n=3 | 135 (135), n=3 | -3 |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 4647912 (3690963-4653143), n=3 | 19437722 (19437645-19440097), n=3 | -14789810 |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 764869 (764815-764898), n=3 | 767186 (767115-767292), n=3 | -2317 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 70 (70), n=3 | 63 (63), n=3 | +7 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 1 (1), n=3 | 2 (2), n=3 | -1 |
| string catalogue bytes, English/shared file | SC1407-09 | 51664 (51618-51666), n=3 | 85370 (85369-85376), n=3 | -33706 |
| string catalogue requests, English/shared file | SC1407-09 | 1 (1), n=3 | 1 (1), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 6 (6), n=3 | 15 (15), n=3 | -9 |
| imagery.nationalmap.gov bytes | SC1407-07 | 1149535 (628979-1149562), n=3 | 895710 (895709-895722), n=3 | +253825 **worse** |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 851 (837-18994), n=3 | 588 (558-602), n=3 | +263 **worse** |

### brief / desktop / warm

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 124 (124-228), n=3 | 68 (56-152), n=3 | +56 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 268 (228-272), n=3 | 144 (120-152), n=3 | +124 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 220 (178-254), n=3 | 11375 (11265-11800), n=3 | -11155 |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 258 (209-259), n=3 | 130 (107-135), n=3 | +128 **worse** |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 132 (129-133), n=3 | 135 (135), n=3 | -3 |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 2022737 (1670442-2038901), n=3 | 17081556 (16453620-17091464), n=3 | -15058819 |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 0 (0), n=3 | 0 (0), n=3 | +0 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 70 (70), n=3 | 63 (63), n=3 | +7 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 2 (1-2), n=3 | 2 (2), n=3 | +0 |
| string catalogue bytes, English/shared file | SC1407-09 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue requests, English/shared file | SC1407-09 | 1 (1), n=3 | 1 (1), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 6 (6), n=3 | 15 (15), n=3 | -9 |
| imagery.nationalmap.gov bytes | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 562 (518-585), n=3 | 338 (327-340), n=3 | +224 **worse** |

### brief / phone / cold

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 1952 (1952-1956), n=3 | 1680 (1572-1740), n=3 | +272 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 1952 (1952-1956), n=3 | 1680 (1572-1740), n=3 | +272 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 956 (824-966), n=3 | 448 (365-461), n=3 | +508 **worse** |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 3289 (3204-3319), n=3 | 3110 (3032-3144), n=3 | +179 **worse** |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 129 (128-129), n=3 | 131 (131), n=3 | -2 |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 4432690 (4431776-4432858), n=3 | 12878229 (12838886-12914451), n=3 | -8445539 |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 765017 (765007-765071), n=3 | 767113 (726933-767204), n=3 | -2096 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 70 (70), n=3 | 63 (63), n=3 | +7 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 2 (1-2), n=3 | 2 (2), n=3 | +0 |
| string catalogue bytes, English/shared file | SC1407-09 | 51611 (51604-51666), n=3 | 85367 (84560-85373), n=3 | -33756 |
| string catalogue requests, English/shared file | SC1407-09 | 1 (1), n=3 | 1 (1), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 4 (4), n=3 | 12 (12), n=3 | -8 |
| imagery.nationalmap.gov bytes | SC1407-07 | 1146449 (1146448-1146746), n=3 | 576102 (576081-576144), n=3 | +570347 **worse** |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 8947 (8847-8982), n=3 | 9665 (9600-9686), n=3 | -718 |

### brief / phone / warm

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 340 (292-340), n=3 | 256 (236-432), n=3 | +84 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 828 (692-952), n=3 | 432 (416-432), n=3 | +396 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 1702 (1619-2732), n=3 | 407 (372-751), n=3 | +1295 **worse** |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 848 (710-946), n=3 | 438 (421-443), n=3 | +410 **worse** |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 129 (129-132), n=3 | 131 (131), n=3 | -2 |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 2034837 (2034754-2377817), n=3 | 12551536 (12545415-12559346), n=3 | -10516699 |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 0 (0), n=3 | 0 (0), n=3 | +0 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 70 (70), n=3 | 63 (63), n=3 | +7 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 2 (2), n=3 | 2 (2), n=3 | +0 |
| string catalogue bytes, English/shared file | SC1407-09 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue requests, English/shared file | SC1407-09 | 1 (1), n=3 | 1 (1), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 4 (4), n=3 | 12 (12), n=3 | -8 |
| imagery.nationalmap.gov bytes | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 2056 (1763-2382), n=3 | 1047 (987-1176), n=3 | +1009 **worse** |

### landing / desktop / cold

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 572 (176-888), n=3 | 156 (152-376), n=3 | +416 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 572 (176-888), n=3 | 156 (152-376), n=3 | +416 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 0 (0), n=3 | 80 (0-112), n=3 | -80 |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | unmeasured | unmeasured |  |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 130 (130), n=3 | 121 (121), n=3 | +9 **worse** |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 1617159 (1600942-1618216), n=3 | 1602268 (1601383-1602368), n=3 | +14891 **worse** |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 495172 (481003-495337), n=3 | 526992 (526991-527017), n=3 | -31820 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 55 (55), n=3 | 53 (53), n=3 | +2 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue bytes, English/shared file | SC1407-09 | 51607 (50776-51617), n=3 | 85375 (85368-85441), n=3 | -33768 |
| string catalogue requests, English/shared file | SC1407-09 | 1 (1), n=3 | 1 (1), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| imagery.nationalmap.gov bytes | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | unmeasured | unmeasured |  |

### landing / desktop / warm

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 92 (72-120), n=3 | 64 (52-64), n=3 | +28 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 92 (72-120), n=3 | 64 (52-64), n=3 | +28 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 237 (195-281), n=3 | 138 (131-158), n=3 | +99 **worse** |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | unmeasured | unmeasured |  |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 130 (130), n=3 | 121 (121), n=3 | +9 **worse** |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 506479 (506305-506584), n=3 | 504016 (504016-504421), n=3 | +2463 **worse** |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 0 (0), n=3 | 0 (0), n=3 | +0 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 55 (55), n=3 | 53 (53), n=3 | +2 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue bytes, English/shared file | SC1407-09 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue requests, English/shared file | SC1407-09 | 1 (1), n=3 | 1 (1), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| imagery.nationalmap.gov bytes | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | unmeasured | unmeasured |  |

### landing / phone / cold

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 952 (864-1220), n=3 | 864 (764-900), n=3 | +88 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 952 (864-1220), n=3 | 864 (764-900), n=3 | +88 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 231 (169-231), n=3 | 31 (22-31), n=3 | +200 **worse** |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | unmeasured | unmeasured |  |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 128 (128), n=3 | 119 (119), n=3 | +9 **worse** |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 1615012 (1598823-1615738), n=3 | 1600875 (1599596-1601240), n=3 | +14137 **worse** |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 495289 (480290-495325), n=3 | 527079 (527038-527134), n=3 | -31790 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 55 (55), n=3 | 53 (53), n=3 | +2 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue bytes, English/shared file | SC1407-09 | 51664 (50840-51666), n=3 | 85370 (85366-85373), n=3 | -33706 |
| string catalogue requests, English/shared file | SC1407-09 | 1 (1), n=3 | 1 (1), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| imagery.nationalmap.gov bytes | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | unmeasured | unmeasured |  |

### landing / phone / warm

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 280 (236-356), n=3 | 212 (208-300), n=3 | +68 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 280 (236-356), n=3 | 212 (208-300), n=3 | +68 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 32 (26-281), n=3 | 0 (0), n=3 | +32 **worse** |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | unmeasured | unmeasured |  |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 128 (128), n=3 | 119 (119), n=3 | +9 **worse** |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 551202 (550864-551330), n=3 | 549183 (548988-549204), n=3 | +2019 **worse** |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 0 (0), n=3 | 0 (0), n=3 | +0 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 55 (55), n=3 | 53 (53), n=3 | +2 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue bytes, English/shared file | SC1407-09 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue requests, English/shared file | SC1407-09 | 1 (1), n=3 | 1 (1), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| imagery.nationalmap.gov bytes | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | unmeasured | unmeasured |  |

### map-home / desktop / cold

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 548 (543-638), n=3 | 812 (368-863), n=3 | -264 |
| LCP ms | SC1407-03/-04/-08/-10 combined | 1444 (1219-1474), n=3 | 812 (368-863), n=3 | +632 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 986 (181-1123), n=3 | 12047 (11670-17099), n=3 | -11061 |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 547 (529-616), n=3 | 815 (369-875), n=3 | -268 |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 205 (205), n=3 | 201 (201), n=3 | +4 **worse** |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 4660118 (4651223-4661399), n=3 | 19440827 (19437953-19444592), n=3 | -14780709 |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 765014 (764866-765121), n=3 | 767240 (767198-767304), n=3 | -2226 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 134 (134), n=3 | 120 (120), n=3 | +14 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 1 (1), n=3 | 2 (2), n=3 | -1 |
| string catalogue bytes, English/shared file | SC1407-09 | 51669 (51668-51672), n=3 | 85373 (85369-85389), n=3 | -33704 |
| string catalogue requests, English/shared file | SC1407-09 | 2 (2), n=3 | 2 (2), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 6 (6), n=3 | 15 (15), n=3 | -9 |
| imagery.nationalmap.gov bytes | SC1407-07 | 1149729 (1149555-1149825), n=3 | 895766 (895724-895773), n=3 | +253963 **worse** |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 1038 (1009-1044), n=3 | 1096 (681-1182), n=3 | -58 |

### map-home / desktop / warm

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 392 (386-401), n=3 | 223 (209-413), n=3 | +169 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 392 (386-401), n=3 | 223 (209-413), n=3 | +169 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 1325 (1047-1509), n=3 | 11772 (11351-12041), n=3 | -10447 |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 377 (364-391), n=3 | 242 (230-422), n=3 | +135 **worse** |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 206 (206), n=3 | 201 (201), n=3 | +5 **worse** |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 2024980 (2012981-2043145), n=3 | 17086486 (17079247-17096696), n=3 | -15061506 |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 0 (0), n=3 | 0 (0), n=3 | +0 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 134 (134), n=3 | 120 (120), n=3 | +14 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 2 (2), n=3 | 2 (2), n=3 | +0 |
| string catalogue bytes, English/shared file | SC1407-09 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue requests, English/shared file | SC1407-09 | 2 (2), n=3 | 2 (2), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 6 (6), n=3 | 15 (15), n=3 | -9 |
| imagery.nationalmap.gov bytes | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 768 (751-778), n=3 | 444 (379-800), n=3 | +324 **worse** |

### map-home / phone / cold

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 3745 (3580-4326), n=3 | 3373 (3373-3454), n=3 | +372 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 3745 (3700-4326), n=3 | 3454 (3453-3457), n=3 | +291 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 778 (657-890), n=3 | 273 (270-296), n=3 | +505 **worse** |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 3787 (3722-4402), n=3 | 3480 (3479-3482), n=3 | +307 **worse** |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 201 (201), n=3 | 197 (197), n=3 | +4 **worse** |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 4438415 (4438072-4438618), n=3 | 12867761 (12867682-12919967), n=3 | -8429346 |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 764983 (764646-765154), n=3 | 767189 (767187-767297), n=3 | -2206 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 134 (134), n=3 | 120 (120), n=3 | +14 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 1 (1), n=3 | 2 (2), n=3 | -1 |
| string catalogue bytes, English/shared file | SC1407-09 | 51670 (51616-51672), n=3 | 85371 (85369-85412), n=3 | -33701 |
| string catalogue requests, English/shared file | SC1407-09 | 2 (2), n=3 | 2 (2), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 4 (4), n=3 | 12 (12), n=3 | -8 |
| imagery.nationalmap.gov bytes | SC1407-07 | 1146450 (1146446-1146459), n=3 | 576175 (576095-576177), n=3 | +570275 **worse** |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 9420 (9326-9885), n=3 | 10022 (9970-10101), n=3 | -602 |

### map-home / phone / warm

| metric | SC1407 unit | new: median (min-max), runs | baseline: median (min-max), runs | delta of medians |
|---|---|---|---|---|
| FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 1238 (876-1619), n=3 | 677 (674-759), n=3 | +561 **worse** |
| LCP ms | SC1407-03/-04/-08/-10 combined | 1238 (1172-2127), n=3 | 757 (750-759), n=3 | +481 **worse** |
| TBT ms | SC1407-03/-04/-08/-10 combined | 2179 (1957-6152), n=3 | 367 (352-510), n=3 | +1812 **worse** |
| brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 1256 (1165-2210), n=3 | 782 (776-783), n=3 | +474 **worse** |
| requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 202 (202), n=3 | 197 (197), n=3 | +5 **worse** |
| bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 2040519 (2026495-2040937), n=3 | 12548754 (12547027-12565506), n=3 | -10508235 |
| JS bytes | SC1407-08/-10 (also -03/-04/-09) | 0 (0), n=3 | 0 (0), n=3 | +0 |
| JS requests | SC1407-08/-10 (also -03/-04/-09) | 134 (134), n=3 | 120 (120), n=3 | +14 **worse** |
| ds582 boundary requests (URL has `biosds582`) | SC1407-06 | 2 (2), n=3 | 2 (2), n=3 | +0 |
| string catalogue bytes, English/shared file | SC1407-09 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| string catalogue requests, English/shared file | SC1407-09 | 2 (2), n=3 | 2 (2), n=3 | +0 |
| string catalogue bytes, Spanish table | SC1407-09 | 0 (0), n=3 | unmeasured |  |
| imagery.nationalmap.gov requests | SC1407-07 | 4 (4), n=3 | 12 (12), n=3 | -8 |
| imagery.nationalmap.gov bytes | SC1407-07 | 0 (0), n=3 | 0 (0), n=3 | +0 |
| first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 2511 (2364-5128), n=3 | 1345 (1337-1454), n=3 | +1166 **worse** |

### Per load: ds582, catalogue and Aerial figures (every load, nothing de-duplicated)

| page | profile | pass | run | ds582 | string file (English) B | string file requests | Spanish table B | Aerial requests | Aerial B | first Aerial tile received ms | Aerial failed / no response end | Aerial from cache |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| brief | desktop | cold | 1 | 1 | 51666 | 1 | 0 | 6 | 628979 | 18994 | 0 / 4 | 0 |
| brief | desktop | cold | 2 | 1 | 51618 | 1 | 0 | 6 | 1149535 | 851 | 0 / 0 | 0 |
| brief | desktop | cold | 3 | 1 | 51664 | 1 | 0 | 6 | 1149562 | 837 | 0 / 0 | 0 |
| brief | desktop | warm | 1 | 2 | 0 | 1 | 0 | 6 | 0 | 585 | 0 / 4 | 2 |
| brief | desktop | warm | 2 | 1 | 0 | 1 | 0 | 6 | 0 | 562 | 0 / 0 | 6 |
| brief | desktop | warm | 3 | 2 | 0 | 1 | 0 | 6 | 0 | 518 | 0 / 0 | 6 |
| brief | phone | cold | 1 | 2 | 51604 | 1 | 0 | 4 | 1146746 | 8982 | 0 / 0 | 0 |
| brief | phone | cold | 2 | 1 | 51611 | 1 | 0 | 4 | 1146449 | 8947 | 0 / 0 | 0 |
| brief | phone | cold | 3 | 2 | 51666 | 1 | 0 | 4 | 1146448 | 8847 | 0 / 0 | 0 |
| brief | phone | warm | 1 | 2 | 0 | 1 | 0 | 4 | 0 | 1763 | 0 / 0 | 4 |
| brief | phone | warm | 2 | 2 | 0 | 1 | 0 | 4 | 0 | 2056 | 0 / 0 | 4 |
| brief | phone | warm | 3 | 2 | 0 | 1 | 0 | 4 | 0 | 2382 | 0 / 0 | 4 |
| landing | desktop | cold | 1 | 0 | 50776 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | desktop | cold | 2 | 0 | 51607 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | desktop | cold | 3 | 0 | 51617 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | desktop | warm | 1 | 0 | 0 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | desktop | warm | 2 | 0 | 0 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | desktop | warm | 3 | 0 | 0 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | phone | cold | 1 | 0 | 50840 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | phone | cold | 2 | 0 | 51666 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | phone | cold | 3 | 0 | 51664 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | phone | warm | 1 | 0 | 0 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | phone | warm | 2 | 0 | 0 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| landing | phone | warm | 3 | 0 | 0 | 1 | 0 | 0 | 0 | unavailable | 0 / 0 | 0 |
| map-home | desktop | cold | 1 | 1 | 51668 | 2 | 0 | 6 | 1149729 | 1044 | 0 / 0 | 0 |
| map-home | desktop | cold | 2 | 1 | 51669 | 2 | 0 | 6 | 1149825 | 1038 | 0 / 0 | 0 |
| map-home | desktop | cold | 3 | 1 | 51672 | 2 | 0 | 6 | 1149555 | 1009 | 0 / 0 | 0 |
| map-home | desktop | warm | 1 | 2 | 0 | 2 | 0 | 6 | 0 | 751 | 0 / 0 | 6 |
| map-home | desktop | warm | 2 | 2 | 0 | 2 | 0 | 6 | 0 | 778 | 0 / 0 | 6 |
| map-home | desktop | warm | 3 | 2 | 0 | 2 | 0 | 6 | 0 | 768 | 0 / 0 | 6 |
| map-home | phone | cold | 1 | 1 | 51616 | 2 | 0 | 4 | 1146446 | 9420 | 0 / 0 | 0 |
| map-home | phone | cold | 2 | 1 | 51672 | 2 | 0 | 4 | 1146459 | 9885 | 0 / 0 | 0 |
| map-home | phone | cold | 3 | 1 | 51670 | 2 | 0 | 4 | 1146450 | 9326 | 0 / 0 | 0 |
| map-home | phone | warm | 1 | 2 | 0 | 2 | 0 | 4 | 0 | 5128 | 0 / 0 | 4 |
| map-home | phone | warm | 2 | 2 | 0 | 2 | 0 | 4 | 0 | 2364 | 0 / 0 | 4 |
| map-home | phone | warm | 3 | 2 | 0 | 2 | 0 | 4 | 0 | 2511 | 0 / 0 | 4 |

Cold-load string file: strings.en.generated.5db58dd7c4.js (baseline: strings.dae9ed705a.js, one file for both languages). Spanish table `strings.es.generated.c14f910685.js` was requested in 0 of 36 English-locale loads (its identity is known, so zero is a measured zero). map-home requests the string file twice per load, as the baseline did (the client redirect to the saved home follows the first document): in the new cold loads the first request carries the bytes (e.g. run 1: 51,668 B) and the second, after the redirect, is recorded with 0 bytes and status 200. Both requests are counted; none is de-duplicated.

Observed in the per-load table (no cause claimed): ds582 boundary requests per load were cold: brief [1, 2], landing [0], map-home [1]; warm: brief [1, 2], landing [0], map-home [2] (baseline: 2 on every brief and map-home load, 0 on landing). Aerial requests per /map-type load were brief/desktop [6], brief/phone [4], map-home/desktop [6], map-home/phone [4] (baseline: 15 desktop, 12 phone), with more bytes per request than before. In brief/desktop/cold run 1, 4 of 6 Aerial requests have no recorded response end (shown as unavailable, not as a time); the first-tile figure for that load uses the 2 that completed (18994 ms). In brief/desktop/warm run 1, 4 of 6 Aerial requests have no recorded response end (shown as unavailable, not as a time); the first-tile figure for that load uses the 2 that completed (585 ms).

## 4. Every metric whose median got worse

A metric is listed when the new group median is higher than the baseline group median (for every metric above, higher is worse; request, byte and ds582 counts included). Lab numbers from 3 runs each; many of these ranges overlap the baseline's or are inside run-to-run noise of a shared host, so no cause is claimed and no threshold is applied.

| group | metric | SC1407 unit | baseline median | new median | delta |
|---|---|---|---|---|---|
| brief/desktop/cold | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 164 | 252 | +88 |
| brief/desktop/cold | LCP ms | SC1407-03/-04/-08/-10 combined | 268 | 1320 | +1052 |
| brief/desktop/cold | brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 253 | 474 | +221 |
| brief/desktop/cold | JS requests | SC1407-08/-10 (also -03/-04/-09) | 63 | 70 | +7 |
| brief/desktop/cold | imagery.nationalmap.gov bytes | SC1407-07 | 895710 | 1149535 | +253825 |
| brief/desktop/cold | first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 588 | 851 | +263 |
| brief/desktop/warm | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 68 | 124 | +56 |
| brief/desktop/warm | LCP ms | SC1407-03/-04/-08/-10 combined | 144 | 268 | +124 |
| brief/desktop/warm | brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 130 | 258 | +128 |
| brief/desktop/warm | JS requests | SC1407-08/-10 (also -03/-04/-09) | 63 | 70 | +7 |
| brief/desktop/warm | first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 338 | 562 | +224 |
| brief/phone/cold | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 1680 | 1952 | +272 |
| brief/phone/cold | LCP ms | SC1407-03/-04/-08/-10 combined | 1680 | 1952 | +272 |
| brief/phone/cold | TBT ms | SC1407-03/-04/-08/-10 combined | 448 | 956 | +508 |
| brief/phone/cold | brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 3110 | 3289 | +179 |
| brief/phone/cold | JS requests | SC1407-08/-10 (also -03/-04/-09) | 63 | 70 | +7 |
| brief/phone/cold | imagery.nationalmap.gov bytes | SC1407-07 | 576102 | 1146449 | +570347 |
| brief/phone/warm | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 256 | 340 | +84 |
| brief/phone/warm | LCP ms | SC1407-03/-04/-08/-10 combined | 432 | 828 | +396 |
| brief/phone/warm | TBT ms | SC1407-03/-04/-08/-10 combined | 407 | 1702 | +1295 |
| brief/phone/warm | brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 438 | 848 | +410 |
| brief/phone/warm | JS requests | SC1407-08/-10 (also -03/-04/-09) | 63 | 70 | +7 |
| brief/phone/warm | first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 1047 | 2056 | +1009 |
| landing/desktop/cold | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 156 | 572 | +416 |
| landing/desktop/cold | LCP ms | SC1407-03/-04/-08/-10 combined | 156 | 572 | +416 |
| landing/desktop/cold | requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 121 | 130 | +9 |
| landing/desktop/cold | bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 1602268 | 1617159 | +14891 |
| landing/desktop/cold | JS requests | SC1407-08/-10 (also -03/-04/-09) | 53 | 55 | +2 |
| landing/desktop/warm | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 64 | 92 | +28 |
| landing/desktop/warm | LCP ms | SC1407-03/-04/-08/-10 combined | 64 | 92 | +28 |
| landing/desktop/warm | TBT ms | SC1407-03/-04/-08/-10 combined | 138 | 237 | +99 |
| landing/desktop/warm | requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 121 | 130 | +9 |
| landing/desktop/warm | bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 504016 | 506479 | +2463 |
| landing/desktop/warm | JS requests | SC1407-08/-10 (also -03/-04/-09) | 53 | 55 | +2 |
| landing/phone/cold | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 864 | 952 | +88 |
| landing/phone/cold | LCP ms | SC1407-03/-04/-08/-10 combined | 864 | 952 | +88 |
| landing/phone/cold | TBT ms | SC1407-03/-04/-08/-10 combined | 31 | 231 | +200 |
| landing/phone/cold | requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 119 | 128 | +9 |
| landing/phone/cold | bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 1600875 | 1615012 | +14137 |
| landing/phone/cold | JS requests | SC1407-08/-10 (also -03/-04/-09) | 53 | 55 | +2 |
| landing/phone/warm | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 212 | 280 | +68 |
| landing/phone/warm | LCP ms | SC1407-03/-04/-08/-10 combined | 212 | 280 | +68 |
| landing/phone/warm | TBT ms | SC1407-03/-04/-08/-10 combined | 0 | 32 | +32 |
| landing/phone/warm | requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 119 | 128 | +9 |
| landing/phone/warm | bytes | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 549183 | 551202 | +2019 |
| landing/phone/warm | JS requests | SC1407-08/-10 (also -03/-04/-09) | 53 | 55 | +2 |
| map-home/desktop/cold | LCP ms | SC1407-03/-04/-08/-10 combined | 812 | 1444 | +632 |
| map-home/desktop/cold | requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 201 | 205 | +4 |
| map-home/desktop/cold | JS requests | SC1407-08/-10 (also -03/-04/-09) | 120 | 134 | +14 |
| map-home/desktop/cold | imagery.nationalmap.gov bytes | SC1407-07 | 895766 | 1149729 | +253963 |
| map-home/desktop/warm | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 223 | 392 | +169 |
| map-home/desktop/warm | LCP ms | SC1407-03/-04/-08/-10 combined | 223 | 392 | +169 |
| map-home/desktop/warm | brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 242 | 377 | +135 |
| map-home/desktop/warm | requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 201 | 206 | +5 |
| map-home/desktop/warm | JS requests | SC1407-08/-10 (also -03/-04/-09) | 120 | 134 | +14 |
| map-home/desktop/warm | first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 444 | 768 | +324 |
| map-home/phone/cold | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 3373 | 3745 | +372 |
| map-home/phone/cold | LCP ms | SC1407-03/-04/-08/-10 combined | 3454 | 3745 | +291 |
| map-home/phone/cold | TBT ms | SC1407-03/-04/-08/-10 combined | 273 | 778 | +505 |
| map-home/phone/cold | brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 3480 | 3787 | +307 |
| map-home/phone/cold | requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 197 | 201 | +4 |
| map-home/phone/cold | JS requests | SC1407-08/-10 (also -03/-04/-09) | 120 | 134 | +14 |
| map-home/phone/cold | imagery.nationalmap.gov bytes | SC1407-07 | 576175 | 1146450 | +570275 |
| map-home/phone/warm | FCP ms | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 677 | 1238 | +561 |
| map-home/phone/warm | LCP ms | SC1407-03/-04/-08/-10 combined | 757 | 1238 | +481 |
| map-home/phone/warm | TBT ms | SC1407-03/-04/-08/-10 combined | 367 | 2179 | +1812 |
| map-home/phone/warm | brief shown (readyMs) ms | SC1407-03/-04/-08/-10 combined | 782 | 1256 | +474 |
| map-home/phone/warm | requests | SC1407-03/-04/-08/-10 combined (also -06/-07/-09) | 197 | 202 | +5 |
| map-home/phone/warm | JS requests | SC1407-08/-10 (also -03/-04/-09) | 120 | 134 | +14 |
| map-home/phone/warm | first Aerial tile received ms (network proxy, not a draw time) | SC1407-07 | 1345 | 2511 | +1166 |

Total: 70 of 160 comparable group-metric pairs.

Context for the byte and TBT changes: the baseline summary records the 15 MB habitat export as loaded in brief/desktop/cold 3/3, brief/desktop/warm 3/3, brief/phone/cold 3/3, brief/phone/warm 3/3, map-home/desktop/cold 3/3, map-home/desktop/warm 3/3, map-home/phone/cold 3/3, map-home/phone/warm 3/3 (loaded/runs); in the new runs it was loaded in none of the groups. That is a data or code difference outside the SC1407 units and is not attributed to any of them. Code, data and third-party provider changes landed between 2026-11-07 and the shipped SHA, so the comparison is not a controlled experiment of the seven units.

## 5. Baseline replay of `compare_2.py` (the new script run on the committed baseline raw files)

`compare_2.py` run on `raw/live-phone.json` and `raw/live-desktop.json` with `--baseline-summary raw/summary.json --catalogue-asset strings.dae9ed705a.js` reproduced what those files hold (read 2026-11-09): 36 loads (3 pages x 2 profiles x cold/warm x 3 runs): ds582 = [2] in all 24 brief and map-home loads and [0] in all 12 landing loads; strings.dae9ed705a.js 84560-85441 B on all 18 cold loads and [0] B on the 18 warm loads (zero observed, request still counted: [1, 2] requests per load); imagery.nationalmap.gov requests per /map load: phone [12], desktop [15], landing [0]. Its group medians and ranges equal the committed `summary.json` (0 mismatches). Approximate size: the baseline string file is 84,560-85,441 B on the 18 cold loads of the three pages (about 85 KB), not an exact 85,000-byte value.

## 6. Not measured here

- **Time-dock step duration**: no harness in `reports/perf` measures it. SC1407-05's tests check one recompute per settled hour, not how long it takes.
- **Aerial first draw**: no harness. "first Aerial tile received" is the earliest `imagery.nationalmap.gov` response end from the request list, a network proxy; it is not a draw time, and it is not map readiness.
- **phone-wifi** profile, the **layer pages** and the **readiness frames** (`run-ready.sh` needs two private research servers and was not run).
- `canvasQuietMs` and `readyMs` stay what the harness defines (a canvas-quiet proxy and the brief-text proxy); they are not renamed into the missing measurements.

## 7. Limits

One host, shared and busy; 3 runs per group; the unit attribution column (ds582 sharing -> SC1407-06; catalogue bytes -> SC1407-09; Aerial requests/bytes/network receipt -> SC1407-07; FCP/LCP/TBT/brief and JS/load totals -> SC1407-03/-04/-08/-10, also -06/-07/-09) says which unit a metric belongs to, not that the unit caused a change. No thresholds, tests, app code, workflows, `measure.mjs`, `summarize.py` or existing raw file changed.
