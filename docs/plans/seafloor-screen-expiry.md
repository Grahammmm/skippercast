# Seafloor screening expiry by region

## R1. Public manifest snapshot — 2026-11-21 UTC

| Indexed region | GET (UTC) | HTTP | `status` | `built_at` | `expires_at` | Days left (approx.) | Limiting receipt |
| --- | --- | ---: | --- | --- | --- | ---: | --- |
| big-sur-coast | 16:46:00 | 200 | `ready` | `2026-11-21T04:47:06.067553+00:00` | `2026-12-24T00:00:00+00:00` | 32.301 | Not named; 19 Nov UTC inferred |
| bodega-point-reyes | 16:46:03 | 404 | — | — | — | — | No manifest returned |
| cambria-san-simeon | 16:46:00 | 200 | `ready` | `2026-11-21T04:46:59.780428+00:00` | `2026-12-24T00:00:00+00:00` | 32.301 | Not named; 19 Nov UTC inferred |
| crescent-city | 16:45:00 | 403 at the edge | — | — | Not readable | — | Not readable |
| fort-bragg-point-arena | 16:45:00 | 403 at the edge | — | — | Not readable | — | Not readable |
| humboldt-bay-cape-mendocino | 16:45:00 | 403 at the edge | — | — | Not readable | — | Not readable |
| monterey-point-sur | 16:46:01 | 200 | `ready` | `2026-11-21T04:47:17.086581+00:00` | `2026-12-24T00:00:00+00:00` | 32.301 | Not named; 19 Nov UTC inferred |
| **morro-bay** | 16:45:27 | 200 | `ready` | `2026-11-21T04:51:29.790176+00:00` | `2026-12-24T00:00:00+00:00` | **32.302** | Not named; 19 Nov UTC inferred |
| point-arena-bodega | 16:45:00 | 403 at the edge | — | — | Not readable | — | Not readable |
| point-arguello-conception | 16:46:01 | 200 | `ready` | `2026-11-21T04:53:28.631115+00:00` | `2026-12-24T00:00:00+00:00` | 32.301 | Not named; 19 Nov UTC inferred |
| point-reyes-pigeon | 16:45:01 | 403 at the edge | — | — | Not readable | — | Not readable |
| santa-cruz-monterey-bay | 16:46:02 | 200 | `held` | `2026-11-21T04:54:12.112261+00:00` | `2026-11-21T04:54:12.112261+00:00` | −0.494 | None indicated; matches build-time fallback |
| shelter-cove-north-mendocino | 16:45:01 | 403 at the edge | — | — | Not readable | — | Not readable |
| south-big-sur-san-simeon | 16:46:02 | 200 | `ready` | `2026-11-21T04:56:56.279408+00:00` | `2026-12-24T00:00:00+00:00` | 32.301 | Not named; 19 Nov UTC inferred |
| southern-california | 16:46:03 | 404 | — | — | — | — | No manifest returned |
| trinidad-klamath | 16:45:01 | 403 at the edge | — | — | Not readable | — | Not readable |

**Evidence.** The table quotes all observed manifest fields from `GET https://skippercast.com/feeds/tiles/seafloor/manifest-<region>.json` (reproduce with `curl --disable -sS -i <URL>`). Times are UTC at request start, except Morro Bay uses the response `Date`. The first pass got `403` / `error code: 1010` with Python's HTTP client; nine URLs were retried with curl, yielding seven JSON bodies and two `404` / `Not found` responses. The 25-GET limit was reached. For the seven remaining HTTP 403s at the edge, `expires_at` was not readable; the cause is not established. These responses cannot distinguish a missing object from an edge rule. The inventory is all 16 IDs in `dist/regions/index.json:1` at `origin/main` `e2cfc500163c0551cda4458f738e68cec04af6b3`. The cited publication, Chart, alert, schedule and index anchors were unchanged from the card baseline (compare those paths with `git diff d52008bfba3a55529a4965c23243cf487838ffad origin/main -- <paths>`).

**How to read the clock.** Days left = (`expires_at` minus GET time) ÷ 24 hours, rounded to three decimals. The publisher uses the oldest contributing screen snapshot, layer check or security evidence date (at UTC midnight), plus 35 days. With no contributing dates it uses build time. It writes the result to the manifest and both export paths, but the manifest names neither the limiting reach nor the receipt; `reach_inputs` are input hashes. Subtracting 35 days from 24 Dec identifies a timestamp, not the identity or type of the receipt. Do not subtract 35 days from the held Santa Cruz build-time fallback (`src/skippercast/seafloor/publish.py:197–214,223–224,278–299,313–319`).

## R2. What visitors see

- **Chart:** The screened Seafloor overlay is hidden and emptied, and a selected `seafloor:` card is closed. The Chart itself and other layers are not removed. With Seafloor on, the legend says “Seafloor screening has expired and is being refreshed” for a ready manifest at or past its expiry, “Seafloor habitat is held for screening review” for a held manifest, and “No seafloor publication for this region” for a missing (404) manifest. A failed read is unavailable, with retries for transient states. An already open Chart schedules a recheck at expiry or sooner if the timer limit requires it; it clears old features before the refresh and checks the clock before drawing. The message is not proof that a publisher is running (`dist/seafloor-data.js:24–52`; `web/map/seafloor.ts:52–56,389–449,454–457`; `web/map/chart.ts:83–95,274–276`; `web/app/Legend.tsx:107–125,472`). The server also blocks expired or not-ready archive/export requests with `503`, even if the manifest JSON can still be read (`server/feeds.ts:324–346`).
- **Terrain:** The terrain surface and its options remain; this is not a blank map. Chart's screened Seafloor overlay is Chart-only. Terrain has a separate reviewed-reef layer: on a failed habitat check it clears reef outlines, pins, ranks and the target card; the rail shows “Reviewed reefs withheld: source binding or current screening unavailable.” Explore is disabled; separately admitted shore context can still draw. On this main, the Terrain renderer still asks for the old reviewed assets through the retired bridge, which returns `410`. Thus renewing a regional Chart manifest alone does **not** restore Terrain's reviewed reef pins. This is a source trace, not a live browser test (`web/map/layers.ts:142–144,185–187`; `web/app/Legend.tsx:129–139,472`; `web/app/LayerRail.tsx:133–150,180–181`; `packages/coast/src/coast3d/viewer.ts:78,247–253,267,273`; `packages/coast/src/map/habitat-lifecycle.ts:28–48`; `packages/coast/src/transport.ts:2–13`; `server/coast-data.ts:311–317`).
- **Coast-data alarm:** It watches Morro Bay, Cambria–San Simeon, Monterey–Point Sur and Point Arguello–Conception, not all indexed regions. A watched HTTP 200 that isn't ready, isn't for that region, or has missing, invalid or expired expiry reports `<path> habitat unavailable 200`. Non-200s are reported separately (e.g. `refused 403`); the alarm retries failed paths once and keeps the issue open until all watched paths recover. Santa Cruz's held manifest is not in this alarm's watch list (`.github/workflows/feed-freshness.yml:123–135`; `scripts/site_uptime_alert.py:73–86,95–100,112–139`).

## R3. Did the latest runs move expiry?

The configured schedule is 10:23 UTC daily (`.github/workflows/seafloor.yml:1–5`). Read on 2026-11-21 at 16:43 UTC with `gh run list -R Grahammmm/skippercast --workflow seafloor.yml --limit 8` and again with `--event schedule --limit 4`. Quoted result fields (UTC):

| Run | `event` | `createdAt` | `updatedAt` | `conclusion` |
| --- | --- | --- | --- | --- |
| [44861981513](https://github.com/Grahammmm/skippercast/actions/runs/44861981513) | `push` | 21 Nov 03:36:16 | 21 Nov 05:03:50 | `failure` |
| [44860209890](https://github.com/Grahammmm/skippercast/actions/runs/44860209890) | `push` | 21 Nov 03:15:52 | 21 Nov 03:36:17 | `cancelled` |
| [44859333090](https://github.com/Grahammmm/skippercast/actions/runs/44859333090) | `push` | 21 Nov 03:05:48 | 21 Nov 04:29:22 | `failure` |
| [44794816494](https://github.com/Grahammmm/skippercast/actions/runs/44794816494) | `schedule` | 20 Nov 18:39:22 | 20 Nov 19:18:00 | `success` |
| [44627970613](https://github.com/Grahammmm/skippercast/actions/runs/44627970613) | `push` | 19 Nov 22:22:13 | 20 Nov 00:06:09 | `success` |
| [44594235629](https://github.com/Grahammmm/skippercast/actions/runs/44594235629) | `schedule` | 19 Nov 19:03:06 | 19 Nov 20:10:51 | `success` |
| [44374647253](https://github.com/Grahammmm/skippercast/actions/runs/44374647253) | `schedule` | 18 Nov 18:53:48 | 18 Nov 20:28:24 | `cancelled` |

`gh run view -R Grahammmm/skippercast <run> --json jobs` (read 2026-11-21 16:47 UTC) returned these regional `publish (<region>)` outcomes. For all nine other indexed regions, these four runs listed **no** regional publish job. That is not proof about their live manifests.

| Region | 19 Nov schedule | 20 Nov schedule | 21 Nov 03:05 push | 21 Nov 03:36 push | Observed expiry movement |
| --- | --- | --- | --- | --- | --- |
| big-sur-coast | `success` | `success` | `success` | `failure` | No prior expiry in the evidence; current 24 Dec |
| cambria-san-simeon | `success` | `success` | `failure` | `failure` | 15 → 24 Dec (+9 days between samples) |
| monterey-point-sur | `success` | `success` | `failure` | `failure` | 15 → 24 Dec (+9 days between samples) |
| morro-bay | `success` | `success` | `failure` | `failure` | 15 → 24 Dec (+9 days between samples) |
| point-arguello-conception | `success` | `success` | `failure` | `failure` | 15 → 24 Dec (+9 days between samples) |
| santa-cruz-monterey-bay | `success` | `success` | `success` | `success` | Currently held; no usable extension shown |
| south-big-sur-san-simeon | `success` | `success` | `failure` | `failure` | No prior expiry in the evidence; current 24 Dec |

The 15 Dec values are public service-host observations from 14 Nov (`docs/scb-07-c-manifest-probe.md:3–13`); 24 Dec is this report's custom-domain GET. They prove a later observed expiry for four controls, **not** which run moved it or whether it moved on each daily run. All seven current manifest build times fall inside the newest push's matching regional job windows (compare R1 against `jobs[].startedAt` and `completedAt` from the same run view). The logged Morro Bay job said “finish: retained publication receipt morro-bay” at 05:01:46 UTC and “ValueError: Public PMTiles range/expiry gate is not deployed correctly” at 05:01:50 (`gh run view -R Grahammmm/skippercast 44861981513 --job 136734431920 --log`, read 21 Nov 16:47 UTC). This error is thrown after matching the public ready manifest's archive descriptor, when a bounded archive range check fails; neither a newer `built_at` nor an overall job conclusion tells us the prior `expires_at` (`src/skippercast/seafloor/verify.py:9–14,28–48`; `.github/workflows/seafloor.yml:157–203`).

**No attribution for seven regions:** The edge 403s left `expires_at` unreadable for `crescent-city`, `fort-bragg-point-arena`, `humboldt-bay-cape-mendocino`, `point-arena-bodega`, `point-reyes-pigeon`, `shelter-cove-north-mendocino`, and `trinidad-klamath`. For those regions, there is no observed expiry to compare or attribute to a scheduled run (R1).

**Closest to lapse:** Santa Cruz–Monterey Bay is already held, not a ready release about to lapse. All six observed ready releases tie at 24 Dec 00:00 UTC (about 32.3 days from the reads); the order of the GETs does not break that tie. The seven refused reads cannot be ranked, and the two 404s have no measured margin (R1).

## R4. Cheapest action for the Morro Bay release

**Owner: SkipperCast seafloor release operator.** Re-read the Morro Bay manifest before release and compare its expiry to the end of the release window, not just launch. If it covers the window and the public archive readback passes, there is no reason to rebuild just to change the date. If the expiry does not cover the window, resolve the failing public range check and confirm that the limiting screening evidence has advanced; only then, if already authorized, use the existing **Map, screen and publish seafloor** manual action with `region=morro-bay`, `max_new=0`, and `reach` blank. It refreshes existing reaches, reuses checked physical outputs, and reduces the scope rather than adding new reaches. Allow time before the cutoff: prepare sets selected aliases to `updating` and can leave them `held` when refresh fails. Verify the resulting public `ready` manifest has the correct region and an expiry after the release window, and that the existing PMTiles check returns `206` with the expected range, R2 source and `no-store`. If Terrain reef pins are a release requirement, separately verify them rather than counting a fresh Chart manifest as Terrain readiness. No dispatch, publication, cache change or hold release was performed for this report (`.github/workflows/seafloor.yml:1–18,69–80,157–203`; `src/skippercast/seafloor/jobs.py:347–365`; `docs/seafloor.md:18–26`; `src/skippercast/seafloor/verify.py:31–48`; R1–R3).

**Open question for the SkipperCast seafloor release operator:** For the seven dated 403s in R1, were the manifest objects absent or did an edge rule refuse the reads? Any retained before-and-after public expiry receipts would help identify which scheduled run, if any, moved an expiry (R3).

**One separately scoped follow-up, estimate 60–90 minutes:** Put `built_at`, `expires_at`, and ready/held in the per-region job summary, separate from public archive verification. Today the publish summary writes published paths, while the archive verifier's receipt contains the region, URL, archive hash and range status, not the expiry (`.github/workflows/seafloor.yml:167–175,197`; `src/skippercast/seafloor/verify.py:47–48`). Files: `.github/workflows/seafloor.yml`, a small pure formatter in `src/skippercast/seafloor/verify.py`, and `tests/gis/test_seafloor_publish.py`. Offline check: `python -m unittest tests.gis.test_seafloor_publish -v`, adding fixtures that distinguish a new build with unchanged expiry, a real expiry extension, and a held result; retain the existing archive refusal test. No new timer or relaxed gate is needed. This would document future changes, not recover past expiry values or fix the retired Terrain bridge.
