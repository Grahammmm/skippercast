# Why the daily feed kept old chlorophyll

- On November 21 the public feed still carried November 7 chlorophyll cells, **337.34 hours old** (see §1).
- NOAA answered the catalogue request, but the loader rejected the file date. The daily feed then copied the old cells without checking their age again (see §2).
- **Recommendation:** Check the daily fallback against the existing 96-hour observation window. Keep the failure reason and last successful retrieval visible, but stop sending expired cells (see §4).

Source and site paths checked at `origin/main` commit `e2cfc500163c0551cda4458f738e68cec04af6b3` (`git rev-parse origin/main`). This is a read-only diagnosis, not a deployed fix.

## 1. What the feed shows

[Public daily feed](https://skippercast.com/feeds/data/latest.json), fetched November 21, 2026 at **13:27:31 UTC** (HTTP 200, response `Date`). The file says `region_id: "morro-bay"`, `run_id: "44904588210"`, and `published_at: "2026-11-21T13:22:35Z"`. The saved response's SHA-256 is `a9e4b06528e1b04586b3ef5de992ed403b93ba5f6ac8cd856af1e469bc65468e` (`sha256sum feed.json`); `latest.json` can change during later checks.

| Grid source | Status | Issue (verbatim) | `last_success_at` | Observation age when checked |
| --- | --- | --- | --- | --- |
| `chlorophyll` — NOAA NPP/NOAA-20 merged OCI chlorophyll, near real time | `retained` | `ValueError: Latest NOAA VIIRS chlorophyll file is stale` | `2026-11-11T23:55:13Z` | **337.34 h**, from `data.sample_at: "2026-11-07T12:00:00Z"` to `checked_at: "2026-11-21T13:20:24Z"` |

That is the only row with `kind: "grid"` and status `retained` or `failed`. The other two grid rows are `sst: ok` and `currents: missing`. Age is calculated from the quoted clocks, not a literal age field or time since download (`scripts/check_feed_freshness.py:118–130`). The chlorophyll row quotes `max_age_hours: 96` and still includes `975` total cells, `673` valid. The freshness checker reports a degraded grid as advisory, not a publish veto (`catalog/feed-health.json:3`; `scripts/check_feed_freshness.py:141–159,204–228`). The sample was about two weeks old; that is not two weeks since the last successful retrieval or proof that every intervening run published a snapshot (see §2).

## 2. Why the chlorophyll fetch fails

1. The daily workflow loads the previous published output and invokes the regional collector (`.github/workflows/daily-data.yml:69–82`). The collector reads the previous snapshot for that region, with the top-level file as a fallback for the default region (`scripts/refresh_regions.py:24,100–108`). It passes the old chlorophyll row to `source()` (`src/skippercast/pipeline/collect.py:277–291,328–334`).
2. Morro Bay binds chlorophyll to `noaa-viirs-merged-chlorophyll` (`regions/morro-bay/region.json:514`). Settings pick up the catalogue request and adapter (`src/skippercast/pipeline/settings.py:6–19`; `catalog/sources.json:1979–1988,2007–2016`); `grid_loader()` calls `noaa_chlorophyll.fetch()` (`src/skippercast/pipeline/collect.py:199–208`).
3. The public row records one request, an HTTP `200` from the NOAA XML catalogue at `2026-11-21T13:21:58Z`. The exact error in §1 is raised when the newest matching filename's **UTC midnight** is more than **120 hours** old (`src/skippercast/pipeline/noaa_chlorophyll.py:13–18,25–48`). This happens before the loader asks for any regional cells (`:148–156`). This is a catalogue-date rejection, not evidence of a failing cell download or of cloud cover. The 120-hour filename guard is separate from the daily collector's configured **96-hour observation** check on returned data (`src/skippercast/pipeline/collect.py:171–181`). **UNVERIFIED:** the rejected filename's exact date and why NOAA did not present a newer eligible filename; the feed records a request receipt, not the XML entries.
4. The exception path writes the issue and starts with `failed` and `data: null`. If there is previous data, it replaces those with `retained` and the previous data and carries the original retrieval and success times forward. There is no age check in that path (`src/skippercast/pipeline/collect.py:187–196`). The workflow can then publish that snapshot (`.github/workflows/daily-data.yml:113–162`).

**Workflow evidence since the last recorded success.** Read-only command for each run below: `gh run view RUN_ID --repo Grahammmm/skippercast --log`. The table quotes the first chlorophyll result where present, or a line from the step that prevented collection. For older logs GitHub labeled the step `UNKNOWN STEP`; the collection command is `python scripts/refresh_regions.py daily --output var/daily --previous-root var/published` (workflow lines 78–82). The collector prints only source ID and status, not the exception (`src/skippercast/pipeline/collect.py:355–358`).

| Run | UTC log excerpt | What it establishes |
| --- | --- | --- |
| `43295090799` | `2026-11-12T19:55:49.6778998Z chlorophyll: retained` | The later upload step logged `data upload failed; no partial snapshot is committed (a lost final acknowledgment may have committed a complete release)`. |
| `43494892058` | `2026-11-13T19:43:53.3908857Z chlorophyll: retained` | Same upload error as November 12. |
| `43624553994` | `2026-11-14T18:05:02.6449685Z chlorophyll: retained` | Public snapshot verified in the log. |
| `43749175701` | `2026-11-15T18:52:34.3264741Z chlorophyll: retained` | Public snapshot verified in the log. |
| `43966487502` | `2026-11-16T22:05:12.1499560Z chlorophyll: retained` | The refresh later logged `##[error]default/active region failed: morro-bay`. This line does not blame chlorophyll. |
| `44157086776` | `2026-11-17T19:18:22.2544607Z chlorophyll: retained` | Public snapshot verified in the log. |
| `44174615684` | `2026-11-17T20:58:05.6741654Z ModuleNotFoundError: No module named 'pytest'` | The parser test step failed before collection; no chlorophyll result in the log. |
| `44392204247` | `2026-11-18T20:48:03.8646898Z ModuleNotFoundError: No module named 'pytest'` | The parser test step failed before collection; no chlorophyll result in the log. |
| `44610824772` | `2026-11-19T20:39:45.8230281Z chlorophyll: retained` | Public snapshot verified in the log. |
| `44626137478` | `2026-11-19T22:23:17.9663372Z chlorophyll: retained` | Public snapshot verified in the log. |
| `44810865284` | `2026-11-20T20:23:54.3208045Z chlorophyll: retained` | Public snapshot verified in the log. |
| `44904588210` | `2026-11-21T13:20:31.4680487Z chlorophyll: retained` | In **Collect and validate public sources**. The later verify step logged `Verified: public feed serves run 44904588210 (published 2026-11-21T13:22:35Z) after 1 attempt(s)`. Separate discussion steps recorded errors. |

**UNVERIFIED:** the exact chlorophyll exception in earlier runs and outcomes of runs outside the table. `retained` alone does not distinguish a stale catalogue from another loader error. In the November 21 run the reason is verified by that run's public JSON, not by a traceback in the log.

## 3. What the site shows for a retained grid

This is a source trace at the commit above. Actual browser rendering on the live site and other regions' current feed contents are **UNVERIFIED**.

| View or layer | What it reads and shows |
| --- | --- |
| **Data status page** | Reads the exact top-level feed in §1 (`dist/status.html:39`; `dist/status-page.js:225–239`). It makes a row for each grid and marks a retained row degraded. The displayed age and timestamp are for `last_success_at`, **not the sample date**. It shows the row past its expected age; it does not read or draw cells (`dist/status-page.js:42–50,62–89,126–136,209–215`). |
| **Brief and spearfishing clarity estimate** | The Brief uses the regional daily feed (`web/brief/Brief.tsx:65–68,246–252,540–546`), produced by the same collector (`scripts/refresh_regions.py:100–116,173–175`). Both Brief paths reject `retained` outright before sampling nearby cells (`web/brief/model.ts:209–225,234–242,247–250,306`). A usable value carries the sample time into the clarity calculation, which uses its own 96-hour check and reports the estimate as unknown when that input is missing; it does not print the chlorophyll date in the clarity result (`packages/coast/src/daily.ts:176`; `packages/coast/src/spear.ts:47,145–174`). |
| **Reports and charter grounds** | Reports reads the regional daily feed and charter grounds uses the legacy daily-feed loader, but both display landing-report evidence, not the grid (`web/reports.ts:68–87,146–163`; `dist/charter-grounds.js:154–167`; `dist/bite-evidence.js:72–94,96–158`). Separately, the exported legacy **Ocean context** renderer would show a usable retained value and the cell's own date as **Stale context**; age changes the label, not whether it displays the value (`dist/bite-evidence.js:161–210,254–283`). `git grep -n -e evidenceHTML -- dist web server packages` finds the definition only; a mounted page using that renderer is **UNVERIFIED**. |
| **Public Chart chlorophyll, including the rail and legend** | This is a **different feed**, the regional habitat manifest and its tiles (`web/app/MapStage.tsx:218`; `web/map/habitat-feed.ts:70–75,267–275,315–339`). It checks the observation's own sample time against the manifest's limit and withholds cells at the limit, even if the manifest marks the layer retained. A drawn observation displays its sample time and age. One that ages out while open is removed and its last sample noted; a stale observation refused on load is shown as no fresh observation (`web/map/chlorophyll.ts:26–35,79–97`; `web/app/Legend.tsx:192–196`). |
| **Private map-style preview** | The builder uses the same NOAA reader or an explicitly supplied local receipt, not the daily-feed fallback. It puts the sample date and existing 96-hour window in the image metadata (`scripts/build_chlorophyll_layer.py:2–13,211–235`). The private layer displays the sample date and withholds or removes the image when it is too old (`web/map/preview/chlorophyll.ts:29–47`). |

## 4. Smallest fix

**One follow-up, two files; estimate 60–90 minutes (UNVERIFIED until built).** In `src/skippercast/pipeline/collect.py:187–196`, limit the change to the `chlorophyll` grid's exception fallback. Reuse the `max_age` argument from the existing daily configuration (`:289–291`; `catalog/sources.json:2011–2015`) and apply the same observation-time rule used for a newly loaded sample (`:175–179`). Compare the previous grid's `sample_at`, not its retrieval time or this run's time stamp. With a valid sample still within that window, keep today's `retained` response. If the sample is too old, missing, or unreadable, leave `status: failed` and `data: null`. Preserve the original failure reason and historical `last_success_at` (including across consecutive failures); do not stamp a new success. The existing source validator allows a failed row without data, and the Data status page can still show its last successful retrieval (`src/skippercast/pipeline/collect.py:435–440`; `dist/status-page.js:74–89`).

**One focused offline test** in `tests/unit/test_source_postprocess_failure.py`, alongside the existing retained-path test (`:12–13,32–39`). Use a fixed clock and a loader that raises; give it a previous chlorophyll row with a recent retrieval but an expired sample. Assert `failed`, `data: null`, the original issue, and the unchanged success time; feed that failed row into a second failed attempt and check that the historical time is still there. In the same test, use an in-window sample as a control and assert that it still returns `retained` with the original cells and clocks. The expired case catches the current bug even if the old grid was retrieved recently.

No map, preview, workflow or catalogue change is proposed. Any new age limit, threshold, or schedule change **needs the owner's word** and is out of this build. This fix removes expired fallback cells; it does not make newer NOAA observations available (see §2).
