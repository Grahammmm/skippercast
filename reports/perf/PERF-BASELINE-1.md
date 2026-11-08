# PERF-BASELINE-1: SkipperCast speed baseline, root causes, ranked proposals

Cards t_90731da3 (opus-coder, archived mid-run) and t_18f59404 (sonnet-coder, finishing it) (G 2026-11-07: "Figure
out why loading is slow and determine everything we can do to make the site load faster and give a better
experience."). **Measure and propose only.** No product code was changed. This report, its measuring scripts and the
raw JSON are the only files added (`reports/perf/`).

Authorship: the measuring script, the measurements and the first draft are opus-coder's (Claude Opus). sonnet-coder
(Claude Sonnet) did not re-measure; it waited for the still-running measurement job to finish, regenerated the
medians and the live tables (A.3 to A.6) from the final raw files (the phone rows of the seven live layer pages had
been partial in the draft), and independently re-checked the headline facts against the live site on 2026-11-07
(see A.0). Measured 2026-11-07 between 21:35 UTC and 23:23 UTC against the live site (skippercast.com, build
`app.d390f02cdc.js`, origin/main `7b99b6db`) and against local research test pages.

---

## Summary in plain words

The site is slow mainly because of one file. Every brief and every map view downloads the full Morro Bay reef
export (`habitat-export.geojson.gz`, **15.4 MB** compressed, **53.6 MB** of JSON, 1.09 million coordinates). It is
sent `no-store`, so it is downloaded again on every visit. Once it arrives, the browser spends **about 11.5 s of
main-thread time** checking each reef outline against protected areas. On a desktop the page freezes for about 13 s.
On a phone on slow 4G the file never finishes: the app gives up after 60 s, having used **9–10.5 MB of data**, and
the reef ranking never appears. Everything else (the code, the brief data, the base map) is reasonably sized and
already well cached and compressed. A handful of smaller problems add up: a large layout jump as the brief header
arrives on desktop, more data also sent `no-store`, seafloor tiles over 1 MB at wide zoom, a 2.3 MB uncompressed
temperature grid in the test pages, and a page that shows nothing until all its JavaScript has run.

Top 5 causes and top 10 proposals are at the end of this report (§D).

---

## A. Baseline (measured, before any change)

### A.0 Independent re-check of the headline facts (sonnet-coder, 2026-11-07 ~15:30 PST, one GET or HEAD each, no load)

| claim in this report | re-check on skippercast.com | result |
|---|---|---|
| reef export is 15.4 MB and `no-store` | `HEAD /feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz`: `content-length: 15414929`, `cache-control: no-store`, `content-type: application/gzip`; one GET returned 15,414,929 bytes in 0.57 s from this host | confirmed |
| brief payload 228 KB decoded | `GET /api/daily?part=brief&region=morro-bay`: 227,699 bytes decoded, `cache-control: public, max-age=300, s-maxage=300`, gzip | confirmed |
| `/api/coast/ocean` and `/api/coast/report` never cached | both `cache-control: no-store` | confirmed |
| no static port page | `GET /ports/morro-bay`: HTTP 404 | confirmed |
| the pages the card names | landing, brief, saved-home map and the layer views are measured live (A.3 to A.6); the private layers are measured on local test pages (A.7) | see the note below |

**Private layers: what "private" means here.** The in-app owner-only "Private previews" group (MAPLIVE-1, PR #1766 merged
2026-11-07: seafloor medium relief with 2 m shallow bathymetry, wind trails, HF-radar currents, SST,
chlorophyll) needs an owner/admin session (`/api/session` `is_admin`) and reads private `var/` files that are not on the
public site. The card says no logins, and the real wind crop is not on this machine (the wind page ran on a synthetic
grid, the SST page on a 2026-09-20 analysis), so the in-app layers were **not measured**. The nearest measurable stand-ins are the research test pages that the same layer code
was built from (A.7); their numbers show data and tile cost, not the in-app shell around them. There is no tide
preview layer in the app; "tide" is measured as the public Stations layer (live, `layers=stations`) and as the
research `layer-tide` page. Anything about the in-app private layers beyond this is **ESTIMATED**.

### A.1 Method

* **Browser:** Playwright 1.5x driving full Chromium 156.0.8078.4 (new headless mode), one page at a time, never in
  parallel, service workers blocked (so the warm pass shows the HTTP cache only; the site registers `/sw.js` only after
  a user saves something offline, so a normal visitor has none either).
* **Profiles** (Chrome DevTools Protocol emulation):
  * **phone**: 412×915 at 2.625×, touch, Android Chrome UA, **CPU 4× slowdown**, **slow 4G**: 1.6 Mbit/s down,
    750 kbit/s up, 150 ms RTT (Lighthouse's mobile preset).
  * **desktop**: 1350×940 at 1×, no CPU or network throttling (this host's wired connection).
  * **phone-wifi** (extra): the phone CPU with no network throttling. Added because on slow 4G the reef export times
    out, which hides its main-thread cost.
* **Cold and warm:** each run uses a fresh browser context with the HTTP cache cleared, loads the page (cold), goes to
  `about:blank`, then loads it again in the same context (warm). **3 runs; every number below is the median of 3.**
* **When a load is "done":** no network activity for 3 s (2 s on the local pages) with nothing pending, or 9 s of
  quiet with long-lived streams open, capped at 90 s desktop / 150 s phone.
* **Metrics:**
  * *FCP* first contentful paint; *LCP* largest contentful paint (PerformanceObserver).
  * *Brief shown*: the brief panel (`aside.app-brief, .app-sheet-brief`) holds more than 80 characters including a digit.
  * *Map canvas*: a canvas larger than 150×150 px is on screen. It says nothing about whether any style, tile or layer
    data has loaded.
  * *Canvas quiet (proxy)*: the first moment after the map canvas that is followed by 1 s with no long task (a TTI-style
    definition applied to the canvas). **This is a proxy for responsiveness, not "map usable".** It never checks that the
    map style, tiles or layer data are loaded or that a tap would be answered. Content/interaction readiness
    (`contentReadyMs`) is **not measured** in this baseline. The only content checks that exist are *brief shown* (live
    pages) and, for the SST test page, *layer data finished* (the end of the large data request in the waterfall,
    A.7). Earlier drafts called the proxy "map usable"; every figure labelled "map usable" there is this proxy.
  * *TBT to proxy*: sum of (long task − 50 ms) between FCP and the canvas-quiet proxy. Long tasks after the proxy are
    not counted, so on a page whose data arrives later (slow-4G phone, SST) it understates blocking.
  * *CLS*: sum of layout-shift values without recent input.
  * *Requests / bytes*: every request the CDP Network domain saw, bytes = encoded (wire) length; for a stream the page
    cancels, the bytes that arrived.
  * *JS main-thread*: CDP `Performance.getMetrics` ScriptDuration accumulated over the load; *heap* = JSHeapUsedSize at
    the end. **No duty cycle (script time per second) is reported.** In the runs in this baseline the counters were read
    after `page.evaluate`, which waits for a busy main thread, so the counter window is longer than the network-settle
    window (`settledMs`): phone-wifi brief cold has 23.09–23.57 s of script against 12.20–12.29 s of settle time, and the
    canvas-quiet proxy is later than `settledMs` (16.1–16.8 s). `measure.mjs` now reads the counters at the settle
    instant and records `metricsWindowS` (the CDP monotonic clock over the same window); the runs here pre-date that, and
    ScriptDuration under CPU throttling is not validated either, so script time is reported as an accumulated total only.
  * *Requests / bytes exclude inline `data:`/`blob:` URLs* (not network transfers). Earlier tables included them: the
    three local `layer-base-medium` desktop cold runs counted a 275,177-byte inline PNG in 3.86 MB; the network total is
    3.58 MB. Tables and heaviest-request lists below were regenerated from the raw requests with those excluded.
  * *Requests before first useful pixel*: requests started at or before LCP (also before FCP in `raw/extras.json`).
* **Pages (live site, public read only):**
  * `landing` = `/` (no saved state).
  * `brief` = `/map?region=morro-bay&ui=v2` (a shared region link: the brief and the Chart for Morro Bay).
  * `map-home` = `/map` with a saved home port (`skippercast-home-port-v1 = morro-bay`); the app redirects to the
    home region, so these times include that client-side redirect.
  * `live-layer-<id>` = the brief link with one Chart rail layer on (`&layers=<id>`): `none` (empty rail),
    `swell` (carries wind), `currents`, `stations` (carries tide), `water-temp`, `chlorophyll`, `seafloor`.
  * There is no static port page to measure: `/ports/<id>` answers 404 on the live site today.
* **Private layers (local only, never deployed):** the private wind, current, tide, SST, chlorophyll and 2 m
  bathymetry layers exist only as research test pages (`research/scripts/map_style/*-test.html`) with data under the
  ignored `var/`. They were served by `research/scripts/map_style/serve_range.py` (a range-capable static server
  with **no compression and no cache headers**, so their byte counts are upper bounds and warm passes re-fetch
  tiles). All at the same camera (zoom 9.5 off Morro Bay; the 2 m page also at zoom 12 over the harbour).
  * checkout A, origin/main `7b99b6db`, port 18772: `wind-test.html` (a synthetic 17×13 wind grid with the real GFS
    crop's shape, from `reports/perf/wind_fixture.py`; the real 2026-11-07 crop is not on disk) and `sst-test.html`
    (the retained 2026-09-20 SST analysis; the page clock is set to 2026-09-20T12:00Z so it is not hidden as stale).
  * checkout B, branch `claude/mapstyle-2-relief` tip, port 18781: `bathy-deep-test.html` with the medium seafloor
    archive (base), plus chlorophyll, HF-radar currents, the tide layer, and the 2 m shallow archive.
* **Payload sizes:** `reports/perf/feed_sizes.sh` (one GET per payload, wire bytes with `Accept-Encoding: zstd, br,
  gzip`, decoded bytes with `identity`). **PMTiles anatomy:** `pmtiles_sizes.mjs` reads only headers and
  directories. **Reef export anatomy:** `export_anatomy.py` on one downloaded copy. **WebP trial:**
  `webp_trial.mjs` re-encodes 40 sampled PNG tiles with Chromium's encoder. **CPU attribution:** `profile.mjs`
  and `diag.mjs` (desktop, unthrottled, sampled profiler + layout-shift sources).

### A.2 Exact commands (repeatable)

From the repository root, with `npm ci` done (Playwright's Chromium at
`~/.cache/ms-playwright/chromium-1248/`, override with `PW_CHROMIUM=`):

```sh
# live site: desktop, then phone, then phone CPU on fast network (sequential, ~100 min)
sh reports/perf/run-live.sh
# private layer test pages (start the two servers first, see the comments in the script)
python3 research/scripts/map_style/serve_range.py 18772            # in checkout A (origin/main)
python3 research/scripts/map_style/serve_range.py 18781            # in checkout B (claude/mapstyle-2-relief)
python3 reports/perf/wind_fixture.py                               # checkout A: the synthetic wind grid
sh reports/perf/run-layers.sh
# medians and tables
python3 reports/perf/compact_raw.py reports/perf/raw/live-*.json reports/perf/raw/layers-*.json  
python3 reports/perf/summarize.py reports/perf/raw/live-*.json reports/perf/raw/layers-*.json > tables.md
python3 reports/perf/extras.py reports/perf/raw/live-*.json reports/perf/raw/layers-*.json > reports/perf/raw/extras.json
for s in live-main live-kinds live-extras heaviest layers-main layers-kinds layers-extras; do python3 reports/perf/make_tables.py $s; done   # the tables in A.3 to A.7
python3 reports/perf/check_runs.py                                  # every group must report 3 runs, all settled
# payloads, archives, export, diagnostics
sh reports/perf/feed_sizes.sh > reports/perf/raw/feed-sizes.tsv
node reports/perf/pmtiles_sizes.mjs https://skippercast.com/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles \
  https://skippercast.com/feeds/tiles/basemap/ca-coast-20261011.pmtiles <local archives...> > reports/perf/raw/pmtiles-sizes.json
python3 reports/perf/export_anatomy.py habitat-export.geojson.gz > reports/perf/raw/export-anatomy.json
node reports/perf/webp_trial.mjs var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles 11   # >> raw/webp-trial.jsonl
node reports/perf/profile.mjs 'https://skippercast.com/map?region=morro-bay&ui=v2' reports/perf/raw/cpu-profile-brief-desktop.json
node reports/perf/diag.mjs 'https://skippercast.com/map?region=morro-bay&ui=v2' reports/perf/raw/diag-brief-desktop.json
python3 reports/perf/waterfall.py reports/perf/raw/live-phone.json brief phone cold 3 40000   # waterfall excerpt
```

Raw numbers: `reports/perf/raw/` — `live-desktop.json`, `live-phone.json`, `live-phone-wifi.json`,
`layers-{relief,main}-{desktop,phone}.json` (every request of every run; inline `data:` URLs cut to 64 characters; plain JSON because the repository check refuses binary files),
`summary.json` (medians of 3 for all 76 groups), `extras.json`,
`feed-sizes.tsv`, `pmtiles-sizes.json`, `export-anatomy.json`, `webp-trial.jsonl`, `compress-sizes.txt`,
`cpu-profile-brief-desktop.json`, `diag-brief-desktop.json`.

### A.3 Live site: timings, blocking, layout shift, requests, memory (medians of 3)

"15 MB export loaded" counts the runs in which the reef export was requested (on phone slow 4G it is requested every
time but aborted at 60 s; see A.6).

**Read "canvas quiet (proxy)" and "TBT to proxy" with A.1 in mind:** they are not time-to-usable. Example: on the
local SST page (A.7) the phone reaches the proxy at 6.4 s, but the SST data request runs 14.1 → 25.5 s, so the layer
is not shown until ~25.5 s (LCP 25.7 s). `contentReadyMs` is not measured. The "brief shown" column is the one content
check for the live pages.

| page | profile | pass | FCP | LCP | brief shown | canvas quiet (proxy) | TBT to proxy | CLS | longest task | JS script time | JS heap | requests | bytes | req. ≤ LCP | PMTiles req / bytes | export loaded |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| landing | desktop | cold | 156 ms | 156 ms | – | 1.43 s | 80 ms | 0.056 | 162 ms | 158 ms | 19.66 MB | 121 | 1.60 MB | 27 | 8 / 128 KB | 0/3 |
| landing | desktop | warm | 64 ms | 64 ms | – | 927 ms | 138 ms | 0.056 | 188 ms | 152 ms | 17.60 MB | 121 | 504 KB | 27 | 8 / 81 KB | 0/3 |
| landing | phone | cold | 864 ms | 864 ms | – | 6.33 s | 31 ms | 0.194 | 237 ms | 347 ms | 15.80 MB | 119 | 1.60 MB | 27 | 6 / 125 KB | 0/3 |
| landing | phone | warm | 212 ms | 212 ms | – | 710 ms | 0 ms | 0.108 | 261 ms | 324 ms | 15.94 MB | 119 | 549 KB | 27 | 6 / 125 KB | 0/3 |
| brief | desktop | cold | 164 ms | 268 ms | 253 ms | 13.59 s | 11.63 s | 0.718 | 3.22 s | 11.48 s | 301.22 MB | 135 | 19.44 MB | 73 | 17 / 1.24 MB | 3/3 |
| brief | desktop | warm | 68 ms | 144 ms | 130 ms | 13.30 s | 11.38 s | 0.761 | 3.28 s | 11.26 s | 614.60 MB | 135 | 17.08 MB | 73 | 17 / 1.20 MB | 3/3 |
| brief | phone | cold | 1.68 s | 1.68 s | 3.11 s | 9.43 s | 448 ms | 0.026 | 1.53 s | 1.63 s | 82.12 MB | 131 | 12.88 MB | 63 | 18 / 1.46 MB | 3/3 |
| brief | phone | warm | 256 ms | 432 ms | 438 ms | 3.12 s | 407 ms | 0.000 | 1.46 s | 2.04 s | 85.13 MB | 131 | 12.55 MB | 73 | 18 / 1.46 MB | 3/3 |
| brief | phone-wifi | cold | 372 ms | 580 ms | 580 ms | 16.37 s | 13.98 s | 0.000 | 13.08 s | 23.17 s | 345.75 MB | 133 | 19.25 MB | 73 | 18 / 1.46 MB | 3/3 |
| brief | phone-wifi | warm | 128 ms | 316 ms | 322 ms | 16.03 s | 14.05 s | 0.000 | 13.10 s | 23.48 s | 309.47 MB | 133 | 17.30 MB | 73 | 18 / 1.41 MB | 3/3 |
| map-home | desktop | cold | 812 ms | 812 ms | 815 ms | 14.52 s | 12.05 s | 0.718 | 3.34 s | 11.71 s | 318.99 MB | 201 | 19.44 MB | 139 | 17 / 1.24 MB | 3/3 |
| map-home | desktop | warm | 223 ms | 223 ms | 242 ms | 13.64 s | 11.77 s | 0.758 | 3.25 s | 11.34 s | 484.14 MB | 201 | 17.09 MB | 139 | 17 / 1.20 MB | 3/3 |
| map-home | phone | cold | 3.37 s | 3.45 s | 3.48 s | 9.78 s | 273 ms | 0.000 | 1.62 s | 1.70 s | 82.12 MB | 197 | 12.87 MB | 139 | 18 / 1.46 MB | 3/3 |
| map-home | phone | warm | 677 ms | 757 ms | 782 ms | 3.37 s | 367 ms | 0.000 | 1.59 s | 1.66 s | 82.10 MB | 197 | 12.55 MB | 139 | 18 / 1.46 MB | 3/3 |
| map-home | phone-wifi | cold | 816 ms | 894 ms | 920 ms | 16.61 s | 13.99 s | 0.000 | 13.08 s | 22.93 s | 333.11 MB | 199 | 19.27 MB | 139 | 18 / 1.46 MB | 3/3 |
| map-home | phone-wifi | warm | 434 ms | 518 ms | 546 ms | 16.17 s | 13.97 s | 0.000 | 13.10 s | 23.05 s | 321.57 MB | 199 | 16.70 MB | 139 | 18 / 1.40 MB | 3/3 |
| live-layer-none | desktop | cold | 176 ms | 292 ms | 277 ms | 13.22 s | 11.18 s | 0.680 | 3.28 s | 11.23 s | 90.51 MB | 123 | 17.96 MB | 73 | 8 / 64 KB | 3/3 |
| live-layer-none | desktop | warm | 64 ms | 128 ms | 112 ms | 12.51 s | 11.09 s | 0.718 | 3.28 s | 11.15 s | 207.85 MB | 123 | 15.61 MB | 73 | 8 / 21 KB | 3/3 |
| live-layer-none | phone | cold | 1.73 s | 1.73 s | 3.13 s | 9.45 s | 377 ms | 0.026 | 199 ms | 1.14 s | 16.03 MB | 116 | 12.89 MB | 63 | 6 / 63 KB | 3/3 |
| live-layer-none | phone | warm | 440 ms | 440 ms | 456 ms | 3.28 s | 560 ms | 0.000 | 158 ms | 1.08 s | 16.10 MB | 116 | 12.56 MB | 73 | 6 / 63 KB | 3/3 |
| live-layer-swell | desktop | cold | 272 ms | 364 ms | 351 ms | 13.33 s | 11.46 s | 0.731 | 3.24 s | 11.54 s | 278.20 MB | 125 | 17.97 MB | 75 | 8 / 64 KB | 3/3 |
| live-layer-swell | desktop | warm | 56 ms | 128 ms | 119 ms | 12.90 s | 11.51 s | 0.716 | 3.23 s | 11.50 s | 451.40 MB | 125 | 15.62 MB | 75 | 8 / 21 KB | 3/3 |
| live-layer-swell | phone | cold | 1.84 s | 1.84 s | 3.19 s | 9.56 s | 423 ms | 0.026 | 262 ms | 1.48 s | 17.24 MB | 121 | 12.89 MB | 66 | 6 / 63 KB | 3/3 |
| live-layer-swell | phone | warm | 248 ms | 448 ms | 452 ms | 3.60 s | 846 ms | 0.000 | 245 ms | 1.21 s | 17.30 MB | 121 | 12.55 MB | 76 | 6 / 63 KB | 3/3 |
| live-layer-currents | desktop | cold | 308 ms | 464 ms | 449 ms | 13.05 s | 11.26 s | 0.707 | 3.25 s | 11.34 s | 317.87 MB | 124 | 18.19 MB | 73 | 8 / 64 KB | 3/3 |
| live-layer-currents | desktop | warm | 76 ms | 144 ms | 127 ms | 12.58 s | 11.10 s | 0.758 | 3.23 s | 11.23 s | 214.59 MB | 124 | 15.87 MB | 73 | 8 / 21 KB | 3/3 |
| live-layer-currents | phone | cold | 1.86 s | 1.86 s | 3.23 s | 9.66 s | 444 ms | 0.026 | 229 ms | 2.31 s | 20.13 MB | 120 | 12.90 MB | 66 | 6 / 63 KB | 3/3 |
| live-layer-currents | phone | warm | 244 ms | 460 ms | 468 ms | 3.78 s | 742 ms | 0.000 | 190 ms | 2.13 s | 20.17 MB | 120 | 12.56 MB | 76 | 6 / 63 KB | 3/3 |
| live-layer-stations | desktop | cold | 176 ms | 324 ms | 312 ms | 12.95 s | 11.14 s | 0.673 | 3.23 s | 11.17 s | 343.52 MB | 123 | 17.97 MB | 73 | 8 / 64 KB | 3/3 |
| live-layer-stations | desktop | warm | 64 ms | 120 ms | 106 ms | 12.78 s | 11.07 s | 0.669 | 3.25 s | 11.11 s | 437.27 MB | 123 | 15.62 MB | 73 | 8 / 21 KB | 3/3 |
| live-layer-stations | phone | cold | 1.84 s | 1.84 s | 3.21 s | 9.86 s | 465 ms | 0.026 | 248 ms | 1.58 s | 17.79 MB | 119 | 12.89 MB | 66 | 6 / 63 KB | 3/3 |
| live-layer-stations | phone | warm | 288 ms | 556 ms | 569 ms | 4.03 s | 1.40 s | 0.000 | 264 ms | 1.56 s | 16.45 MB | 119 | 12.55 MB | 76 | 6 / 63 KB | 3/3 |
| live-layer-water-temp | desktop | cold | 352 ms | 436 ms | 421 ms | 13.24 s | 11.50 s | 0.687 | 3.36 s | 11.52 s | 221.93 MB | 123 | 17.96 MB | 73 | 8 / 64 KB | 3/3 |
| live-layer-water-temp | desktop | warm | 132 ms | 132 ms | 121 ms | 12.57 s | 11.05 s | 0.678 | 3.21 s | 11.12 s | 376.58 MB | 123 | 15.61 MB | 73 | 8 / 21 KB | 3/3 |
| live-layer-water-temp | phone | cold | 1.84 s | 1.84 s | 3.29 s | 15.76 s | 1.67 s | 0.026 | 352 ms | 1.73 s | 16.89 MB | 119 | 12.90 MB | 66 | 6 / 63 KB | 3/3 |
| live-layer-water-temp | phone | warm | 320 ms | 512 ms | 575 ms | 4.27 s | 1.74 s | 0.000 | 350 ms | 1.88 s | 16.97 MB | 119 | 12.55 MB | 76 | 6 / 63 KB | 3/3 |
| live-layer-chlorophyll | desktop | cold | 188 ms | 252 ms | 238 ms | 12.77 s | 10.98 s | 0.704 | 3.21 s | 11.08 s | 337.68 MB | 132 | 17.97 MB | 74 | 8 / 64 KB | 3/3 |
| live-layer-chlorophyll | desktop | warm | 60 ms | 136 ms | 121 ms | 12.63 s | 11.11 s | 0.691 | 3.19 s | 11.15 s | 191.89 MB | 132 | 15.61 MB | 74 | 8 / 21 KB | 3/3 |
| live-layer-chlorophyll | phone | cold | 1.86 s | 1.86 s | 3.31 s | 10.51 s | 760 ms | 0.026 | 295 ms | 1.73 s | 16.88 MB | 128 | 12.88 MB | 66 | 6 / 63 KB | 3/3 |
| live-layer-chlorophyll | phone | warm | 268 ms | 472 ms | 539 ms | 3.68 s | 1.14 s | 0.000 | 233 ms | 1.45 s | 16.86 MB | 128 | 12.53 MB | 76 | 6 / 63 KB | 3/3 |
| live-layer-seafloor | desktop | cold | 272 ms | 348 ms | 326 ms | 13.64 s | 11.63 s | 0.721 | 3.31 s | 11.41 s | 485.41 MB | 134 | 19.13 MB | 73 | 17 / 1.24 MB | 3/3 |
| live-layer-seafloor | desktop | warm | 56 ms | 128 ms | 112 ms | 13.76 s | 12.00 s | 0.754 | 3.38 s | 11.77 s | 424.52 MB | 134 | 16.81 MB | 73 | 17 / 1.20 MB | 3/3 |
| live-layer-seafloor | phone | cold | 1.92 s | 1.92 s | 3.32 s | 10.04 s | 628 ms | 0.026 | 2.13 s | 1.64 s | 78.05 MB | 133 | 12.92 MB | 66 | 18 / 1.46 MB | 3/3 |
| live-layer-seafloor | phone | warm | 288 ms | 480 ms | 493 ms | 3.77 s | 954 ms | 0.000 | 1.97 s | 1.53 s | 80.95 MB | 133 | 12.55 MB | 76 | 18 / 1.46 MB | 3/3 |

**Build changed during the phone batch (found when the tables were regenerated).** `raw/live-phone.json` shows the
site was redeployed while it was being measured: landing, brief, map-home and `live-layer-none` (phone) loaded
`app.d390f02cdc.js`; the other six phone layer pages (`swell`, `currents`, `stations`, `water-temp`, `chlorophyll`,
`seafloor`) loaded `app.fe397e7c4f.js` (3 more JS requests, 66 vs 63; same 312 KB MapLibre, same reef export). Desktop
and phone-on-Wi-Fi are entirely on `d390f02cdc`. `python3 reports/perf/builds.py reports/perf/raw/live-*.json`
prints the build per run. The two builds differ by under 1 % in bytes and the headline numbers (reef export,
requests, canvas quiet ~9.4 to 10.5 s) agree, so no conclusion changes, but compare those six phone rows with care.
**`live-layer-water-temp` on the phone is unstable:** canvas quiet (proxy) 10.1 s, 15.8 s and 16.4 s in its three cold runs
(TBT 0.8 s, 1.7 s, 3.5 s) against 9.3 to 12.9 s for every other layer; the reported median (15.76 s) is the middle of
a bimodal result. The cause is not established here (the same layer on desktop is normal at 13.2 s), so it is **not**
ranked as a root cause; re-run it alone before acting on it.

### A.4 Live site: bytes (requests) by type (medians of 3)

`tiles` includes the PMTiles range requests, the map glyphs and the reef export (it lives under `/feeds/tiles/`);
`other` is mostly the 15 USGS NAIP aerial images (fetched, not `<img>`), the SVG poster, and module scripts
Chromium reports as type "Other" (all `.js` together: 62 requests / 767 KB on the brief, 88 / 777 KB on the landing).

| page | profile | pass | html | js | css | json | tiles | fonts | images | other |
|---|---|---|---|---|---|---|---|---|---|---|
| landing | desktop | cold | 4 KB (1) | 527 KB (53) | 18 KB (6) | 540 KB (12) | 214 KB (10) | 38 KB (1) | 0 B (0) | 262 KB (38) |
| landing | desktop | warm | 4 KB (1) | 0 B (53) | 0 B (6) | 418 KB (12) | 82 KB (10) | 0 B (1) | 0 B (0) | 0 B (38) |
| landing | phone | cold | 4 KB (1) | 527 KB (53) | 18 KB (6) | 541 KB (12) | 211 KB (8) | 38 KB (1) | 0 B (0) | 262 KB (38) |
| landing | phone | warm | 4 KB (1) | 0 B (53) | 0 B (6) | 419 KB (12) | 126 KB (8) | 0 B (1) | 0 B (0) | 0 B (38) |
| brief | desktop | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 874 KB (20) | 16.78 MB (24) | 71 KB (2) | 0 B (0) | 906 KB (17) |
| brief | desktop | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 437 KB (20) | 16.64 MB (24) | 0 B (2) | 0 B (0) | 2 KB (17) |
| brief | phone | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 802 KB (19) | 10.61 MB (24) | 71 KB (2) | 0 B (0) | 586 KB (14) |
| brief | phone | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 535 KB (19) | 12.01 MB (24) | 0 B (2) | 0 B (0) | 2 KB (14) |
| brief | phone-wifi | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 802 KB (20) | 16.98 MB (25) | 71 KB (2) | 0 B (0) | 585 KB (14) |
| brief | phone-wifi | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 437 KB (20) | 16.85 MB (25) | 0 B (2) | 0 B (0) | 1 KB (14) |
| map-home | desktop | cold | 8 KB (2) | 767 KB (120) | 40 KB (12) | 877 KB (22) | 16.77 MB (24) | 71 KB (4) | 0 B (0) | 906 KB (17) |
| map-home | desktop | warm | 7 KB (2) | 0 B (120) | 0 B (12) | 439 KB (22) | 16.64 MB (24) | 0 B (4) | 0 B (0) | 2 KB (17) |
| map-home | phone | cold | 8 KB (2) | 767 KB (120) | 40 KB (12) | 804 KB (21) | 10.59 MB (24) | 71 KB (4) | 0 B (0) | 586 KB (14) |
| map-home | phone | warm | 7 KB (2) | 0 B (120) | 0 B (12) | 537 KB (21) | 12.00 MB (24) | 0 B (4) | 0 B (0) | 2 KB (14) |
| map-home | phone-wifi | cold | 8 KB (2) | 767 KB (120) | 40 KB (12) | 804 KB (22) | 17.00 MB (25) | 71 KB (4) | 0 B (0) | 585 KB (14) |
| map-home | phone-wifi | warm | 7 KB (2) | 0 B (120) | 0 B (12) | 440 KB (22) | 16.25 MB (25) | 0 B (4) | 0 B (0) | 1 KB (14) |
| live-layer-none | desktop | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 605 KB (19) | 15.57 MB (13) | 71 KB (2) | 0 B (0) | 906 KB (17) |
| live-layer-none | desktop | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 168 KB (19) | 15.44 MB (13) | 0 B (2) | 0 B (0) | 2 KB (17) |
| live-layer-none | phone | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 531 KB (18) | 10.89 MB (10) | 71 KB (2) | 0 B (0) | 586 KB (14) |
| live-layer-none | phone | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 265 KB (18) | 12.28 MB (10) | 0 B (2) | 0 B (0) | 2 KB (14) |
| live-layer-swell | desktop | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 605 KB (21) | 15.57 MB (13) | 71 KB (2) | 0 B (0) | 906 KB (17) |
| live-layer-swell | desktop | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 168 KB (21) | 15.45 MB (13) | 0 B (2) | 0 B (0) | 2 KB (17) |
| live-layer-swell | phone | cold | 4 KB (1) | 774 KB (66) | 40 KB (8) | 531 KB (20) | 10.89 MB (10) | 71 KB (2) | 0 B (0) | 586 KB (14) |
| live-layer-swell | phone | warm | 4 KB (1) | 0 B (66) | 0 B (8) | 264 KB (20) | 12.28 MB (10) | 0 B (2) | 0 B (0) | 2 KB (14) |
| live-layer-currents | desktop | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 875 KB (20) | 15.57 MB (13) | 71 KB (2) | 0 B (0) | 906 KB (17) |
| live-layer-currents | desktop | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 437 KB (20) | 15.43 MB (13) | 0 B (2) | 0 B (0) | 2 KB (17) |
| live-layer-currents | phone | cold | 4 KB (1) | 774 KB (66) | 40 KB (8) | 802 KB (19) | 10.62 MB (10) | 71 KB (2) | 0 B (0) | 586 KB (14) |
| live-layer-currents | phone | warm | 4 KB (1) | 0 B (66) | 0 B (8) | 535 KB (19) | 12.02 MB (10) | 0 B (2) | 0 B (0) | 2 KB (14) |
| live-layer-stations | desktop | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 605 KB (19) | 15.57 MB (13) | 71 KB (2) | 0 B (0) | 906 KB (17) |
| live-layer-stations | desktop | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 168 KB (19) | 15.44 MB (13) | 0 B (2) | 0 B (0) | 2 KB (17) |
| live-layer-stations | phone | cold | 4 KB (1) | 774 KB (66) | 40 KB (8) | 531 KB (18) | 10.88 MB (10) | 71 KB (2) | 0 B (0) | 586 KB (14) |
| live-layer-stations | phone | warm | 4 KB (1) | 0 B (66) | 0 B (8) | 265 KB (18) | 12.28 MB (10) | 0 B (2) | 0 B (0) | 2 KB (14) |
| live-layer-water-temp | desktop | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 605 KB (19) | 15.57 MB (13) | 71 KB (2) | 0 B (0) | 906 KB (17) |
| live-layer-water-temp | desktop | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 168 KB (19) | 15.44 MB (13) | 0 B (2) | 0 B (0) | 2 KB (17) |
| live-layer-water-temp | phone | cold | 4 KB (1) | 774 KB (66) | 40 KB (8) | 531 KB (18) | 10.89 MB (10) | 71 KB (2) | 0 B (0) | 586 KB (14) |
| live-layer-water-temp | phone | warm | 4 KB (1) | 0 B (66) | 0 B (8) | 264 KB (18) | 12.28 MB (10) | 0 B (2) | 0 B (0) | 2 KB (14) |
| live-layer-chlorophyll | desktop | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 629 KB (28) | 15.55 MB (13) | 71 KB (2) | 0 B (0) | 906 KB (17) |
| live-layer-chlorophyll | desktop | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 168 KB (28) | 15.44 MB (13) | 0 B (2) | 0 B (0) | 2 KB (17) |
| live-layer-chlorophyll | phone | cold | 4 KB (1) | 774 KB (66) | 40 KB (8) | 555 KB (27) | 10.86 MB (10) | 71 KB (2) | 0 B (0) | 586 KB (14) |
| live-layer-chlorophyll | phone | warm | 4 KB (1) | 0 B (66) | 0 B (8) | 266 KB (27) | 12.26 MB (10) | 0 B (2) | 0 B (0) | 2 KB (14) |
| live-layer-seafloor | desktop | cold | 4 KB (1) | 767 KB (63) | 40 KB (8) | 605 KB (19) | 16.77 MB (24) | 71 KB (2) | 0 B (0) | 906 KB (17) |
| live-layer-seafloor | desktop | warm | 4 KB (1) | 0 B (63) | 0 B (8) | 168 KB (19) | 16.64 MB (24) | 0 B (2) | 0 B (0) | 2 KB (17) |
| live-layer-seafloor | phone | cold | 4 KB (1) | 774 KB (66) | 40 KB (8) | 531 KB (18) | 10.92 MB (24) | 71 KB (2) | 0 B (0) | 586 KB (14) |
| live-layer-seafloor | phone | warm | 4 KB (1) | 0 B (66) | 0 B (8) | 265 KB (18) | 12.28 MB (24) | 0 B (2) | 0 B (0) | 2 KB (14) |

### A.5 Live site: cache, third parties, script time (medians of 3)

The earlier "script ms per s" duty-cycle column is withdrawn (A.1: the CPU-counter window and the settle window differ);
script time and the settle window are shown side by side instead, and must not be divided.
`network req/bytes` = requests that were not answered from the browser cache. On a **warm** pass that is what the
cache headers fail to keep. `no-store` = bytes of responses marked `Cache-Control: no-store`.

| page | profile | pass | network req / bytes | no-store req / bytes | third-party req / bytes | req. ≤ FCP | JS script time | network-settle window (not the CPU-counter window) |
|---|---|---|---|---|---|---|---|---|
| landing | desktop | cold | 95 / 1.60 MB | 4 / 417 KB | 2 / 769 B | 27 | 158 ms | 10.62 s |
| landing | desktop | warm | 18 / 504 KB | 4 / 416 KB | 2 / 769 B | 27 | 152 ms | 9.82 s |
| landing | phone | cold | 92 / 1.60 MB | 4 / 418 KB | 2 / 776 B | 27 | 347 ms | 18.81 s |
| landing | phone | warm | 17 / 549 KB | 4 / 418 KB | 2 / 774 B | 27 | 324 ms | 12.70 s |
| brief | desktop | cold | 134 / 19.44 MB | 19 / 17.04 MB | 18 / 992 KB | 63 | 11.48 s | 19.64 s |
| brief | desktop | warm | 40 / 17.08 MB | 19 / 17.03 MB | 18 / 0 B | 63 | 11.26 s | 19.60 s |
| brief | phone | cold | 129 / 12.88 MB | 21 / 10.88 MB | 15 / 672 KB | 63 | 1.63 s | 72.36 s |
| brief | phone | warm | 45 / 12.55 MB | 22 / 12.37 MB | 15 / 97 KB | 63 | 2.04 s | 69.80 s |
| brief | phone-wifi | cold | 131 / 19.25 MB | 21 / 17.25 MB | 15 / 672 KB | 63 | 23.17 s | 12.27 s |
| brief | phone-wifi | warm | 41 / 17.30 MB | 21 / 17.27 MB | 15 / 0 B | 63 | 23.48 s | 12.07 s |
| map-home | desktop | cold | 200 / 19.44 MB | 21 / 17.05 MB | 19 / 992 KB | 139 | 11.71 s | 20.34 s |
| map-home | desktop | warm | 44 / 17.09 MB | 21 / 17.05 MB | 19 / 0 B | 139 | 11.34 s | 19.84 s |
| map-home | phone | cold | 195 / 12.87 MB | 23 / 10.87 MB | 16 / 672 KB | 129 | 1.70 s | 72.82 s |
| map-home | phone | warm | 49 / 12.55 MB | 24 / 12.36 MB | 16 / 97 KB | 130 | 1.66 s | 70.04 s |
| map-home | phone-wifi | cold | 197 / 19.27 MB | 23 / 17.27 MB | 16 / 672 KB | 130 | 22.93 s | 12.54 s |
| map-home | phone-wifi | warm | 45 / 16.70 MB | 23 / 16.67 MB | 16 / 0 B | 130 | 23.05 s | 12.07 s |
| live-layer-none | desktop | cold | 122 / 17.96 MB | 7 / 15.57 MB | 18 / 992 KB | 63 | 11.23 s | 20.91 s |
| live-layer-none | desktop | warm | 28 / 15.61 MB | 7 / 15.56 MB | 18 / 0 B | 63 | 11.15 s | 21.60 s |
| live-layer-none | phone | cold | 114 / 12.89 MB | 6 / 10.89 MB | 15 / 672 KB | 63 | 1.14 s | 72.33 s |
| live-layer-none | phone | warm | 30 / 12.56 MB | 7 / 12.37 MB | 15 / 97 KB | 66 | 1.08 s | 69.81 s |
| live-layer-swell | desktop | cold | 124 / 17.97 MB | 7 / 15.57 MB | 18 / 992 KB | 63 | 11.54 s | 21.90 s |
| live-layer-swell | desktop | warm | 28 / 15.62 MB | 7 / 15.57 MB | 18 / 0 B | 63 | 11.50 s | 22.10 s |
| live-layer-swell | phone | cold | 118 / 12.89 MB | 6 / 10.89 MB | 15 / 672 KB | 66 | 1.48 s | 72.59 s |
| live-layer-swell | phone | warm | 30 / 12.55 MB | 7 / 12.36 MB | 15 / 97 KB | 66 | 1.21 s | 69.80 s |
| live-layer-currents | desktop | cold | 123 / 18.19 MB | 8 / 15.84 MB | 18 / 992 KB | 63 | 11.34 s | 22.16 s |
| live-layer-currents | desktop | warm | 29 / 15.87 MB | 8 / 15.83 MB | 18 / 0 B | 63 | 11.23 s | 21.85 s |
| live-layer-currents | phone | cold | 118 / 12.90 MB | 7 / 10.89 MB | 15 / 672 KB | 66 | 2.31 s | 72.61 s |
| live-layer-currents | phone | warm | 31 / 12.56 MB | 8 / 12.38 MB | 15 / 97 KB | 66 | 2.13 s | 69.80 s |
| live-layer-stations | desktop | cold | 122 / 17.97 MB | 7 / 15.57 MB | 18 / 992 KB | 63 | 11.17 s | 22.13 s |
| live-layer-stations | desktop | warm | 28 / 15.62 MB | 7 / 15.57 MB | 18 / 0 B | 63 | 11.11 s | 21.86 s |
| live-layer-stations | phone | cold | 117 / 12.89 MB | 6 / 10.88 MB | 15 / 672 KB | 66 | 1.58 s | 72.58 s |
| live-layer-stations | phone | warm | 30 / 12.55 MB | 7 / 12.36 MB | 15 / 97 KB | 66 | 1.56 s | 70.06 s |
| live-layer-water-temp | desktop | cold | 122 / 17.96 MB | 7 / 15.56 MB | 18 / 992 KB | 63 | 11.52 s | 22.16 s |
| live-layer-water-temp | desktop | warm | 28 / 15.61 MB | 7 / 15.57 MB | 18 / 0 B | 73 | 11.12 s | 21.85 s |
| live-layer-water-temp | phone | cold | 117 / 12.90 MB | 6 / 10.89 MB | 15 / 672 KB | 66 | 1.73 s | 72.60 s |
| live-layer-water-temp | phone | warm | 30 / 12.55 MB | 7 / 12.37 MB | 15 / 97 KB | 66 | 1.88 s | 69.87 s |
| live-layer-chlorophyll | desktop | cold | 131 / 17.97 MB | 7 / 15.55 MB | 18 / 992 KB | 63 | 11.08 s | 21.65 s |
| live-layer-chlorophyll | desktop | warm | 28 / 15.61 MB | 7 / 15.57 MB | 18 / 0 B | 63 | 11.15 s | 21.85 s |
| live-layer-chlorophyll | phone | cold | 126 / 12.88 MB | 6 / 10.86 MB | 15 / 672 KB | 66 | 1.73 s | 72.67 s |
| live-layer-chlorophyll | phone | warm | 31 / 12.53 MB | 7 / 12.34 MB | 15 / 97 KB | 66 | 1.45 s | 69.82 s |
| live-layer-seafloor | desktop | cold | 133 / 19.13 MB | 18 / 16.77 MB | 18 / 992 KB | 63 | 11.41 s | 19.94 s |
| live-layer-seafloor | desktop | warm | 39 / 16.81 MB | 18 / 16.77 MB | 18 / 0 B | 63 | 11.77 s | 19.84 s |
| live-layer-seafloor | phone | cold | 131 / 12.92 MB | 20 / 10.92 MB | 15 / 672 KB | 66 | 1.64 s | 72.71 s |
| live-layer-seafloor | phone | warm | 44 / 12.55 MB | 21 / 12.36 MB | 15 / 97 KB | 66 | 1.53 s | 69.81 s |

### A.6 The 10 heaviest requests (the median run)

**landing · desktop · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 312 KB | js | 264 → 339 ms | `/assets/maplibre-gl.4f81424288.js` |
| 2 | 269 KB | json | 361 → 679 ms | `/api/coast/ocean` |
| 3 | 142 KB | json | 738 → 861 ms | `/api/coast/report` |
| 4 | 99 KB | other | 228 → 273 ms | `/assets/app.d390f02cdc.js` |
| 5 | 90 KB | json | 737 → 777 ms | `/api/forecast?…` |
| 6 | 85 KB | js | 95 → 148 ms | `/assets/strings.dae9ed705a.js` |
| 7 | 84 KB | tiles | 777 → 802 ms | `/basemap/glyphs/dm-sans-medium/0-255.pbf` |
| 8 | 38 KB | fonts | 147 → 175 ms | `/assets/dm-sans-latin.17cf521964.woff2` |
| 9 | 37 KB | tiles | 520 → 918 ms | `/feeds/tiles/basemap/ca-coast-20261011.pmtiles` |
| 10 | 35 KB | tiles | 521 → 1041 ms | `/feeds/tiles/basemap/ca-coast-20261011.pmtiles` |

**landing · phone · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 312 KB | js | 2049 → 6234 ms | `/assets/maplibre-gl.4f81424288.js` |
| 2 | 270 KB | json | 6291 → 9539 ms | `/api/coast/ocean` |
| 3 | 143 KB | json | 3661 → 5799 ms | `/api/coast/report` |
| 4 | 99 KB | other | 1911 → 4168 ms | `/assets/app.d390f02cdc.js` |
| 5 | 89 KB | json | 3659 → 5277 ms | `/api/forecast?…` |
| 6 | 85 KB | js | 275 → 1471 ms | `/assets/strings.dae9ed705a.js` |
| 7 | 84 KB | tiles | 8626 → 9639 ms | `/basemap/glyphs/dm-sans-medium/0-255.pbf` |
| 8 | 38 KB | fonts | 832 → 1371 ms | `/assets/dm-sans-latin.17cf521964.woff2` |
| 9 | 37 KB | tiles | 7857 → 8616 ms | `/feeds/tiles/basemap/ca-coast-20261011.pmtiles` |
| 10 | 35 KB | tiles | 7857 → 9131 ms | `/feeds/tiles/basemap/ca-coast-20261011.pmtiles` |

**brief · desktop · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.42 MB | tiles | 355 → 1005 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 609 KB | tiles | 1235 → 2620 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 3 | 312 KB | js | 279 → 348 ms | `/assets/maplibre-gl.4f81424288.js` |
| 4 | 269 KB | json | 440 → 712 ms | `/api/coast/ocean` |
| 5 | 196 KB | tiles | 1235 → 2439 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 6 | 174 KB | tiles | 1235 → 1856 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 7 | 152 KB | other | 508 → 640 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 8 | 146 KB | other | 508 → 632 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 145 KB | other | 507 → 626 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 10 | 145 KB | other | 507 → 615 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |

**brief · phone · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 9.03 MB | tiles | 3280 → 63404 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 609 KB | tiles | 11783 → 25342 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 3 | 312 KB | js | 3383 → 9121 ms | `/assets/maplibre-gl.4f81424288.js` |
| 4 | 271 KB | json | 9196 → 21001 ms | `/api/coast/ocean` |
| 5 | 196 KB | tiles | 11783 → 21365 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 6 | 174 KB | tiles | 11782 → 20607 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 7 | 151 KB | tiles | 11781 → 19499 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 8 | 145 KB | other | 9384 → 17189 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 142 KB | json | 3380 → 7462 ms | `/api/coast/report` |
| 10 | 142 KB | other | 9384 → 17060 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |

**brief · phone-wifi · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.40 MB | tiles | 720 → 2122 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 609 KB | tiles | 3011 → 5470 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 3 | 312 KB | js | 667 → 729 ms | `/assets/maplibre-gl.4f81424288.js` |
| 4 | 271 KB | json | 879 → 1152 ms | `/api/coast/ocean` |
| 5 | 196 KB | tiles | 3011 → 5279 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 6 | 174 KB | tiles | 3010 → 4007 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 7 | 151 KB | tiles | 3009 → 3325 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 8 | 145 KB | other | 1217 → 1364 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 142 KB | json | 664 → 1150 ms | `/api/coast/report` |
| 10 | 142 KB | other | 1218 → 1375 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |

**map-home · desktop · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.41 MB | tiles | 940 → 1531 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 609 KB | tiles | 1731 → 3242 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 3 | 312 KB | js | 833 → 900 ms | `/assets/maplibre-gl.4f81424288.js` |
| 4 | 269 KB | json | 1060 → 1341 ms | `/api/coast/ocean` |
| 5 | 196 KB | tiles | 1731 → 3035 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 6 | 174 KB | tiles | 1731 → 2232 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 7 | 152 KB | other | 1120 → 1233 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 8 | 146 KB | other | 1120 → 1210 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 145 KB | other | 1120 → 1225 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 10 | 145 KB | other | 1119 → 1240 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |

**map-home · phone · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 9.02 MB | tiles | 3651 → 63827 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 609 KB | tiles | 12154 → 25692 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 3 | 312 KB | js | 3770 → 9442 ms | `/assets/maplibre-gl.4f81424288.js` |
| 4 | 271 KB | json | 9518 → 21250 ms | `/api/coast/ocean` |
| 5 | 196 KB | tiles | 12154 → 21722 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 6 | 174 KB | tiles | 12153 → 20907 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 7 | 151 KB | tiles | 12152 → 19806 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 8 | 145 KB | other | 9736 → 17430 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 142 KB | json | 3766 → 7762 ms | `/api/coast/report` |
| 10 | 142 KB | other | 9737 → 17281 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |

**map-home · phone-wifi · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.40 MB | tiles | 800 → 2172 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 609 KB | tiles | 3077 → 4796 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 3 | 312 KB | js | 753 → 808 ms | `/assets/maplibre-gl.4f81424288.js` |
| 4 | 271 KB | json | 889 → 1078 ms | `/api/coast/ocean` |
| 5 | 196 KB | tiles | 3076 → 4649 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 6 | 174 KB | tiles | 3075 → 3678 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 7 | 151 KB | tiles | 3075 → 3206 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 8 | 145 KB | other | 1132 → 1279 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 143 KB | json | 750 → 918 ms | `/api/coast/report` |
| 10 | 142 KB | other | 1133 → 1334 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |

**live-layer-none · desktop · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.41 MB | tiles | 541 → 1470 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 303 → 355 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 152 KB | other | 660 → 808 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 146 KB | other | 660 → 819 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 5 | 145 KB | other | 660 → 786 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 145 KB | other | 659 → 793 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 143 KB | json | 303 → 496 ms | `/api/coast/report` |
| 8 | 142 KB | other | 660 → 811 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 101 KB | json | 313 → 350 ms | `/data/protected-areas.geojson` |
| 10 | 99 KB | js | 102 → 174 ms | `/assets/app.d390f02cdc.js` |

**live-layer-none · phone · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 10.74 MB | tiles | 3315 → 63465 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 3441 → 9106 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 145 KB | other | 9407 → 13770 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 142 KB | json | 3438 → 7454 ms | `/api/coast/report` |
| 5 | 142 KB | other | 9407 → 13733 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 118 KB | other | 9408 → 13319 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 101 KB | json | 3470 → 6810 ms | `/data/protected-areas.geojson` |
| 8 | 99 KB | js | 209 → 2941 ms | `/assets/app.d390f02cdc.js` |
| 9 | 96 KB | json | 3468 → 6861 ms | `https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?…` |
| 10 | 89 KB | json | 3436 → 6681 ms | `/api/forecast?…` |

**live-layer-swell · desktop · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 14.68 MB | tiles | 527 → 1221 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 431 → 483 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 152 KB | other | 752 → 908 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 146 KB | other | 752 → 868 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 5 | 145 KB | other | 752 → 901 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 145 KB | other | 751 → 893 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 142 KB | json | 430 → 595 ms | `/api/coast/report` |
| 8 | 142 KB | other | 751 → 913 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 101 KB | json | 441 → 471 ms | `/data/protected-areas.geojson` |
| 10 | 99 KB | js | 231 → 306 ms | `/assets/app.d390f02cdc.js` |

**live-layer-swell · phone · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 10.73 MB | tiles | 3364 → 63741 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 3511 → 9198 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 145 KB | other | 9518 → 13875 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 142 KB | json | 3508 → 7610 ms | `/api/coast/report` |
| 5 | 142 KB | other | 9519 → 13839 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 118 KB | other | 9520 → 13432 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 101 KB | json | 3542 → 6888 ms | `/data/protected-areas.geojson` |
| 8 | 100 KB | js | 207 → 2991 ms | `/assets/app.fe397e7c4f.js` |
| 9 | 96 KB | json | 3539 → 6845 ms | `https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?…` |
| 10 | 89 KB | json | 3194 → 6259 ms | `/api/forecast?…` |

**live-layer-currents · desktop · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.42 MB | tiles | 558 → 1175 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 503 → 605 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 269 KB | json | 633 → 1015 ms | `/api/coast/ocean` |
| 4 | 152 KB | other | 697 → 829 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 5 | 146 KB | other | 697 → 775 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 145 KB | other | 697 → 840 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 145 KB | other | 696 → 796 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 8 | 142 KB | json | 502 → 696 ms | `/api/coast/report` |
| 9 | 142 KB | other | 696 → 879 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 10 | 101 KB | json | 512 → 584 ms | `/data/protected-areas.geojson` |

**live-layer-currents · phone · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 10.50 MB | tiles | 3709 → 63880 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 3652 → 9321 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 271 KB | json | 9399 → 16609 ms | `/api/coast/ocean` |
| 4 | 145 KB | other | 9617 → 14720 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 5 | 143 KB | json | 3647 → 7662 ms | `/api/coast/report` |
| 6 | 142 KB | other | 9617 → 14670 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 118 KB | other | 9618 → 14120 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 8 | 101 KB | json | 3684 → 7047 ms | `/data/protected-areas.geojson` |
| 9 | 100 KB | js | 357 → 3142 ms | `/assets/app.fe397e7c4f.js` |
| 10 | 96 KB | json | 3682 → 7018 ms | `https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?…` |

**live-layer-stations · desktop · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.42 MB | tiles | 403 → 958 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 240 → 286 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 152 KB | other | 445 → 566 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 146 KB | other | 445 → 590 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 5 | 145 KB | other | 445 → 573 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 145 KB | other | 445 → 580 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 142 KB | json | 236 → 375 ms | `/api/coast/report` |
| 8 | 142 KB | other | 445 → 583 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 101 KB | json | 253 → 287 ms | `/data/protected-areas.geojson` |
| 10 | 99 KB | js | 69 → 131 ms | `/assets/app.d390f02cdc.js` |

**live-layer-stations · phone · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 10.73 MB | tiles | 3386 → 63694 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 3513 → 9199 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 145 KB | other | 9510 → 13869 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 142 KB | json | 3509 → 7517 ms | `/api/coast/report` |
| 5 | 142 KB | other | 9511 → 13832 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 118 KB | other | 9512 → 13411 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 101 KB | json | 3546 → 6938 ms | `/data/protected-areas.geojson` |
| 8 | 100 KB | js | 214 → 2998 ms | `/assets/app.fe397e7c4f.js` |
| 9 | 96 KB | json | 3543 → 6909 ms | `https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?…` |
| 10 | 90 KB | json | 3506 → 6759 ms | `/api/forecast?…` |

**live-layer-water-temp · desktop · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.42 MB | tiles | 779 → 1361 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 447 → 505 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 152 KB | other | 665 → 782 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 146 KB | other | 665 → 785 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 5 | 145 KB | other | 665 → 792 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 145 KB | other | 664 → 796 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 142 KB | json | 446 → 635 ms | `/api/coast/report` |
| 8 | 142 KB | other | 664 → 773 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 101 KB | json | 457 → 515 ms | `/data/protected-areas.geojson` |
| 10 | 99 KB | js | 212 → 261 ms | `/assets/app.d390f02cdc.js` |

**live-layer-water-temp · phone · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 10.74 MB | tiles | 3431 → 63625 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 3555 → 9241 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 145 KB | other | 9743 → 14132 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 142 KB | json | 3551 → 7575 ms | `/api/coast/report` |
| 5 | 142 KB | other | 9744 → 14061 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 118 KB | other | 9745 → 13639 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 101 KB | json | 3589 → 6967 ms | `/data/protected-areas.geojson` |
| 8 | 100 KB | js | 214 → 2998 ms | `/assets/app.fe397e7c4f.js` |
| 9 | 96 KB | json | 3586 → 6975 ms | `https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?…` |
| 10 | 90 KB | json | 3548 → 6630 ms | `/api/forecast?…` |

**live-layer-chlorophyll · desktop · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.39 MB | tiles | 479 → 983 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 234 → 280 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 152 KB | other | 369 → 459 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 146 KB | other | 369 → 466 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 5 | 145 KB | other | 368 → 463 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 145 KB | other | 368 → 453 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 142 KB | json | 230 → 405 ms | `/api/coast/report` |
| 8 | 142 KB | other | 368 → 469 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 101 KB | json | 245 → 282 ms | `/data/protected-areas.geojson` |
| 10 | 99 KB | js | 60 → 134 ms | `/assets/app.d390f02cdc.js` |

**live-layer-chlorophyll · phone · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 10.71 MB | tiles | 3411 → 63650 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 312 KB | js | 3549 → 9343 ms | `/assets/maplibre-gl.4f81424288.js` |
| 3 | 145 KB | other | 9802 → 14178 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 4 | 142 KB | json | 3546 → 7677 ms | `/api/coast/report` |
| 5 | 142 KB | other | 9802 → 14128 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 6 | 118 KB | other | 9802 → 13720 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 101 KB | json | 3612 → 7091 ms | `/data/protected-areas.geojson` |
| 8 | 100 KB | js | 206 → 2993 ms | `/assets/app.fe397e7c4f.js` |
| 9 | 96 KB | json | 3606 → 7063 ms | `https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query?…` |
| 10 | 89 KB | json | 3542 → 6740 ms | `/api/forecast?…` |

**live-layer-seafloor · desktop · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 15.42 MB | tiles | 473 → 1031 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 609 KB | tiles | 1239 → 2464 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 3 | 312 KB | js | 358 → 455 ms | `/assets/maplibre-gl.4f81424288.js` |
| 4 | 196 KB | tiles | 1239 → 2322 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 5 | 174 KB | tiles | 1239 → 1587 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 6 | 152 KB | other | 576 → 714 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 7 | 146 KB | other | 576 → 711 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 8 | 145 KB | other | 575 → 686 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 9 | 145 KB | other | 575 → 720 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 10 | 142 KB | json | 357 → 652 ms | `/api/coast/report` |

**live-layer-seafloor · phone · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 9.34 MB | tiles | 3677 → 63845 ms | `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` |
| 2 | 609 KB | tiles | 11932 → 24436 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 3 | 312 KB | js | 3610 → 9287 ms | `/assets/maplibre-gl.4f81424288.js` |
| 4 | 196 KB | tiles | 11932 → 20430 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 5 | 174 KB | tiles | 11930 → 19614 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 6 | 151 KB | tiles | 11929 → 18592 ms | `/feeds/tiles/seafloor/seafloor-morro-bay.pmtiles` |
| 7 | 145 KB | other | 9691 → 16188 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 8 | 142 KB | json | 3609 → 7635 ms | `/api/coast/report` |
| 9 | 142 KB | other | 9692 → 16017 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |
| 10 | 118 KB | other | 9694 → 14830 ms | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?…` |

**layer-base-medium · desktop · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 12 → 16 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 71 → 73 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 97 KB | tiles | 203 → 207 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 4 | 96 KB | tiles | 221 → 224 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 5 | 95 KB | tiles | 150 → 156 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 6 | 94 KB | tiles | 150 → 152 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 7 | 94 KB | tiles | 151 → 158 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 8 | 93 KB | tiles | 150 → 155 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 9 | 91 KB | tiles | 220 → 223 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 10 | 90 KB | tiles | 151 → 157 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |

**layer-base-medium · phone · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 853 → 6238 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 6505 → 11566 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 95 KB | tiles | 6918 → 13704 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 4 | 94 KB | tiles | 6915 → 9427 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 5 | 94 KB | tiles | 6918 → 14448 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 6 | 93 KB | tiles | 6916 → 12710 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 7 | 90 KB | tiles | 6918 → 14134 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 8 | 88 KB | tiles | 6915 → 9835 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 9 | 87 KB | tiles | 6916 → 10035 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 10 | 84 KB | tiles | 6918 → 13153 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |

**layer-wind · desktop · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 15 → 19 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 97 KB | tiles | 213 → 217 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 3 | 96 KB | tiles | 215 → 220 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 4 | 95 KB | tiles | 156 → 163 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 5 | 94 KB | tiles | 156 → 158 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 6 | 94 KB | tiles | 156 → 164 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 7 | 93 KB | tiles | 156 → 162 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 8 | 91 KB | tiles | 215 → 219 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 9 | 90 KB | tiles | 156 → 164 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 10 | 88 KB | tiles | 156 → 159 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |

**layer-wind · phone · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 830 → 6153 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 95 KB | tiles | 6579 → 12418 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 3 | 94 KB | tiles | 6576 → 8750 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 4 | 94 KB | tiles | 6579 → 12969 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 5 | 93 KB | tiles | 6579 → 11910 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 6 | 90 KB | tiles | 6579 → 12468 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 7 | 88 KB | tiles | 6577 → 9393 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 8 | 87 KB | tiles | 6578 → 9593 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 9 | 84 KB | tiles | 6579 → 11996 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 10 | 83 KB | css | 168 → 818 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.css` |

**layer-current · desktop · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 10 → 13 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 61 → 63 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 97 KB | tiles | 151 → 154 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 4 | 96 KB | tiles | 167 → 172 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 5 | 95 KB | tiles | 85 → 92 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 6 | 94 KB | tiles | 85 → 87 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 7 | 94 KB | tiles | 85 → 93 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 8 | 93 KB | tiles | 85 → 91 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 9 | 91 KB | tiles | 167 → 170 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 10 | 90 KB | tiles | 85 → 93 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |

**layer-current · phone · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 841 → 6225 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 6512 → 11567 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 95 KB | tiles | 6921 → 13734 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 4 | 94 KB | tiles | 6918 → 9429 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 5 | 94 KB | tiles | 6921 → 14449 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 6 | 93 KB | tiles | 6920 → 12726 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 7 | 90 KB | tiles | 6921 → 14121 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 8 | 88 KB | tiles | 6919 → 9851 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 9 | 87 KB | tiles | 6919 → 10051 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 10 | 84 KB | tiles | 6920 → 13140 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |

**layer-tide · desktop · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 13 → 16 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 71 → 72 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 97 KB | tiles | 196 → 199 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 4 | 96 KB | tiles | 213 → 217 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 5 | 95 KB | tiles | 146 → 155 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 6 | 94 KB | tiles | 145 → 148 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 7 | 94 KB | tiles | 146 → 156 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 8 | 93 KB | tiles | 146 → 153 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 9 | 91 KB | tiles | 213 → 216 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 10 | 90 KB | tiles | 146 → 156 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |

**layer-tide · phone · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 844 → 6229 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 6489 → 11829 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 95 KB | tiles | 6937 → 13817 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 4 | 94 KB | tiles | 6935 → 9590 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 5 | 94 KB | tiles | 6938 → 14576 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 6 | 93 KB | tiles | 6937 → 13409 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 7 | 90 KB | tiles | 6938 → 14247 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 8 | 88 KB | tiles | 6936 → 9891 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 9 | 87 KB | tiles | 6936 → 10942 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 10 | 84 KB | tiles | 6937 → 13446 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |

**layer-sst · desktop · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 2.28 MB | json | 234 → 251 ms | `/var/maplayer-sst-1/sst-preview.json` |
| 2 | 1.08 MB | js | 14 → 18 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 3 | 97 KB | tiles | 168 → 171 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 4 | 96 KB | tiles | 186 → 189 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 5 | 95 KB | tiles | 122 → 129 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 6 | 94 KB | tiles | 122 → 124 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 7 | 94 KB | tiles | 122 → 131 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 8 | 93 KB | tiles | 122 → 128 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 9 | 91 KB | tiles | 185 → 187 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 10 | 90 KB | tiles | 122 → 130 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |

**layer-sst · phone · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 2.28 MB | json | 14080 → 25541 ms | `/var/maplayer-sst-1/sst-preview.json` |
| 2 | 1.08 MB | js | 854 → 6153 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 3 | 95 KB | tiles | 6590 → 12403 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 4 | 94 KB | tiles | 6588 → 8777 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 5 | 94 KB | tiles | 6590 → 12975 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 6 | 93 KB | tiles | 6590 → 11931 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 7 | 90 KB | tiles | 6590 → 12446 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 8 | 88 KB | tiles | 6588 → 9392 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 9 | 87 KB | tiles | 6589 → 9599 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |
| 10 | 84 KB | tiles | 6590 → 11995 ms | `/var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles` |

**layer-chlorophyll · desktop · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 13 → 17 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 69 → 71 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 97 KB | tiles | 208 → 211 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 4 | 96 KB | tiles | 211 → 216 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 5 | 95 KB | tiles | 149 → 156 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 6 | 94 KB | tiles | 148 → 151 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 7 | 94 KB | tiles | 149 → 158 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 8 | 93 KB | tiles | 149 → 155 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 9 | 91 KB | tiles | 209 → 215 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 10 | 90 KB | tiles | 149 → 157 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |

**layer-chlorophyll · phone · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 846 → 6229 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 6494 → 11558 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 95 KB | tiles | 6902 → 13690 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 4 | 94 KB | tiles | 6900 → 9412 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 5 | 94 KB | tiles | 6903 → 14447 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 6 | 93 KB | tiles | 6902 → 12688 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 7 | 90 KB | tiles | 6902 → 14119 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 8 | 88 KB | tiles | 6901 → 9813 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 9 | 87 KB | tiles | 6901 → 10021 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |
| 10 | 84 KB | tiles | 6902 → 13132 ms | `/var/seafloor/tiles/medium/morro-bay-seafloor-deep.pmtiles` |

**layer-bathy-2m · desktop · cold** (run 2):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 14 → 19 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 66 → 68 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 98 KB | tiles | 194 → 198 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 4 | 97 KB | tiles | 221 → 223 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 5 | 95 KB | tiles | 142 → 150 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 6 | 95 KB | tiles | 141 → 144 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 7 | 95 KB | tiles | 142 → 152 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 8 | 94 KB | tiles | 142 → 148 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 9 | 92 KB | tiles | 211 → 214 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 10 | 91 KB | tiles | 142 → 151 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |

**layer-bathy-2m · phone · cold** (run 3):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 848 → 6231 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 6494 → 11537 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 95 KB | tiles | 6903 → 13804 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 4 | 95 KB | tiles | 6901 → 9449 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 5 | 95 KB | tiles | 6903 → 14463 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 6 | 94 KB | tiles | 6903 → 12796 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 7 | 91 KB | tiles | 6903 → 14133 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 8 | 89 KB | tiles | 6901 → 9871 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 9 | 88 KB | tiles | 6902 → 10028 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 10 | 85 KB | tiles | 6903 → 13204 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |

**layer-bathy-2m-z12 · desktop · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 12 → 16 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 54 → 55 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 132 KB | tiles | 185 → 187 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 4 | 126 KB | tiles | 134 → 139 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 5 | 93 KB | tiles | 135 → 141 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 6 | 87 KB | tiles | 134 → 140 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 7 | 83 KB | css | 3 → 7 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.css` |
| 8 | 75 KB | tiles | 133 → 137 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 9 | 70 KB | tiles | 133 → 137 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 10 | 67 KB | tiles | 133 → 136 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |

**layer-bathy-2m-z12 · phone · cold** (run 1):

| # | bytes | type | start → end | URL |
|---|---|---|---|---|
| 1 | 1.08 MB | js | 849 → 6236 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.mjs` |
| 2 | 208 KB | other | 6496 → 11170 ms | `/var/chlorophyll/central-coast/chlorophyll.png` |
| 3 | 126 KB | tiles | 6910 → 11907 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 4 | 83 KB | css | 174 → 828 ms | `/node_modules/maplibre-gl/dist/maplibre-gl.css` |
| 5 | 75 KB | tiles | 6909 → 10291 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 6 | 70 KB | tiles | 6909 → 10549 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 7 | 67 KB | tiles | 6909 → 9418 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 8 | 66 KB | tiles | 6910 → 11471 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 9 | 51 KB | tiles | 6908 → 8560 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |
| 10 | 49 KB | tiles | 6907 → 8159 ms | `/var/seafloor/tiles-2m/morro-bay-seafloor-deep.pmtiles` |

### A.7 Private layers (local test pages, medians of 3)

Served without compression or cache headers (see A.1): bytes are upper bounds, warm passes re-fetch tiles, and the
1.08 MB `maplibre-gl.mjs` here is the uncompressed module (the live site ships a 312 KB compressed build).
Request and byte columns exclude the inline `data:` URLs (the 275 KB inline PNG on `layer-base-medium`; see A.1).
"Canvas quiet (proxy)" is not layer readiness: on `layer-sst` the phone reaches it at 6.38 s but the 2.28 MB SST grid
is requested at 14.07 s and finishes at 25.53 s (median of 3 cold runs: 14.07 → 25.53 s; runs 14.06–14.08 →
25.53–25.54 s); `layer-wind`, `layer-current`, `layer-tide`, `layer-chlorophyll` readiness is likewise not measured.

| page | profile | pass | FCP | LCP | canvas quiet (proxy) | TBT to proxy | CLS | longest task | JS script time | JS heap | requests | bytes | req. ≤ LCP | PMTiles req / bytes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| layer-base-medium | desktop | cold | 20 ms | 20 ms | 360 ms | 22 ms | 0.000 | 72 ms | 44 ms | 10.10 MB | 43 | 3.58 MB | 6 | 33 / 2.14 MB |
| layer-base-medium | desktop | warm | 12 ms | 12 ms | 278 ms | 13 ms | 0.000 | 63 ms | 27 ms | 6.24 MB | 43 | 2.14 MB | 7 | 33 / 2.14 MB |
| layer-base-medium | phone | cold | 848 ms | 848 ms | 6.69 s | 49 ms | 0.000 | 235 ms | 144 ms | 8.36 MB | 28 | 2.66 MB | 3 | 18 / 1.22 MB |
| layer-base-medium | phone | warm | 32 ms | 32 ms | 273 ms | 23 ms | 0.000 | 241 ms | 97 ms | 11.84 MB | 28 | 1.22 MB | 6 | 18 / 1.22 MB |
| layer-wind | desktop | cold | 24 ms | 24 ms | 78 ms | 0 ms | 0.006 | 0 ms | 3.64 s | 38.92 MB | 40 | 3.34 MB | 5 | 33 / 2.14 MB |
| layer-wind | desktop | warm | 36 ms | 36 ms | 75 ms | 0 ms | 0.006 | 0 ms | 3.97 s | 54.67 MB | 40 | 2.14 MB | 7 | 33 / 2.14 MB |
| layer-wind | phone | cold | 844 ms | 844 ms | 6.43 s | 45 ms | 0.038 | 150 ms | 4.50 s | 26.84 MB | 25 | 2.42 MB | 5 | 18 / 1.22 MB |
| layer-wind | phone | warm | 124 ms | 124 ms | 211 ms | 23 ms | 0.015 | 136 ms | 4.09 s | 27.45 MB | 25 | 1.22 MB | 7 | 18 / 1.22 MB |
| layer-current | desktop | cold | 28 ms | 328 ms | 432 ms | 31 ms | 0.002 | 72 ms | 56 ms | 9.82 MB | 43 | 3.58 MB | 43 | 33 / 2.14 MB |
| layer-current | desktop | warm | 24 ms | 292 ms | 381 ms | 31 ms | 0.002 | 69 ms | 40 ms | 8.58 MB | 43 | 2.14 MB | 43 | 33 / 2.14 MB |
| layer-current | phone | cold | 844 ms | 15.97 s | 6.70 s | 50 ms | 0.016 | 235 ms | 207 ms | 9.24 MB | 28 | 2.66 MB | 28 | 18 / 1.22 MB |
| layer-current | phone | warm | 32 ms | 6.62 s | 221 ms | 21 ms | 0.016 | 250 ms | 128 ms | 6.97 MB | 28 | 1.22 MB | 28 | 18 / 1.22 MB |
| layer-tide | desktop | cold | 24 ms | 168 ms | 351 ms | 23 ms | 0.000 | 73 ms | 39 ms | 10.01 MB | 45 | 3.65 MB | 28 | 33 / 2.14 MB |
| layer-tide | desktop | warm | 20 ms | 120 ms | 259 ms | 10 ms | 0.000 | 60 ms | 25 ms | 6.52 MB | 45 | 2.14 MB | 28 | 33 / 2.14 MB |
| layer-tide | phone | cold | 856 ms | 856 ms | 6.67 s | 45 ms | 0.000 | 241 ms | 155 ms | 7.51 MB | 30 | 2.73 MB | 5 | 18 / 1.22 MB |
| layer-tide | phone | warm | 32 ms | 32 ms | 281 ms | 24 ms | 0.000 | 239 ms | 95 ms | 5.80 MB | 30 | 1.22 MB | 6 | 18 / 1.22 MB |
| layer-sst | desktop | cold | 28 ms | 352 ms | 101 ms | 0 ms | 0.007 | 0 ms | 61 ms | 22.66 MB | 39 | 5.61 MB | 39 | 33 / 2.14 MB |
| layer-sst | desktop | warm | 36 ms | 272 ms | 85 ms | 0 ms | 0.007 | 0 ms | 40 ms | 8.28 MB | 39 | 4.42 MB | 39 | 33 / 2.14 MB |
| layer-sst | phone | cold | 864 ms | 25.74 s | 6.38 s | 48 ms | 0.034 | 99 ms | 206 ms | 8.34 MB | 24 | 4.69 MB | 24 | 18 / 1.22 MB |
| layer-sst | phone | warm | 32 ms | 17.52 s | 268 ms | 31 ms | 0.034 | 145 ms | 140 ms | 17.94 MB | 24 | 3.50 MB | 24 | 18 / 1.22 MB |
| layer-chlorophyll | desktop | cold | 20 ms | 20 ms | 365 ms | 21 ms | 0.000 | 71 ms | 42 ms | 9.11 MB | 43 | 3.58 MB | 6 | 33 / 2.14 MB |
| layer-chlorophyll | desktop | warm | 24 ms | 24 ms | 294 ms | 19 ms | 0.000 | 69 ms | 30 ms | 6.26 MB | 43 | 2.14 MB | 7 | 33 / 2.14 MB |
| layer-chlorophyll | phone | cold | 856 ms | 856 ms | 6.68 s | 51 ms | 0.000 | 242 ms | 169 ms | 9.80 MB | 28 | 2.66 MB | 5 | 18 / 1.22 MB |
| layer-chlorophyll | phone | warm | 36 ms | 36 ms | 353 ms | 33 ms | 0.000 | 235 ms | 115 ms | 12.10 MB | 28 | 1.22 MB | 6 | 18 / 1.22 MB |
| layer-bathy-2m | desktop | cold | 24 ms | 24 ms | 334 ms | 11 ms | 0.000 | 61 ms | 37 ms | 9.88 MB | 45 | 3.63 MB | 6 | 35 / 2.18 MB |
| layer-bathy-2m | desktop | warm | 16 ms | 16 ms | 284 ms | 20 ms | 0.000 | 70 ms | 28 ms | 6.25 MB | 45 | 2.18 MB | 7 | 35 / 2.18 MB |
| layer-bathy-2m | phone | cold | 848 ms | 848 ms | 6.68 s | 52 ms | 0.000 | 243 ms | 148 ms | 8.39 MB | 28 | 2.67 MB | 5 | 18 / 1.23 MB |
| layer-bathy-2m | phone | warm | 32 ms | 32 ms | 229 ms | 29 ms | 0.000 | 234 ms | 96 ms | 8.71 MB | 28 | 1.23 MB | 6 | 18 / 1.23 MB |
| layer-bathy-2m-z12 | desktop | cold | 28 ms | 28 ms | 303 ms | 21 ms | 0.000 | 71 ms | 35 ms | 8.74 MB | 30 | 2.50 MB | 6 | 20 / 1.05 MB |
| layer-bathy-2m-z12 | desktop | warm | 20 ms | 20 ms | 235 ms | 19 ms | 0.000 | 69 ms | 24 ms | 6.20 MB | 30 | 1.05 MB | 7 | 20 / 1.05 MB |
| layer-bathy-2m-z12 | phone | cold | 856 ms | 856 ms | 6.63 s | 48 ms | 0.000 | 235 ms | 128 ms | 8.54 MB | 21 | 2.06 MB | 5 | 11 / 613 KB |
| layer-bathy-2m-z12 | phone | warm | 32 ms | 32 ms | 263 ms | 23 ms | 0.000 | 237 ms | 76 ms | 11.05 MB | 21 | 613 KB | 6 | 11 / 613 KB |

| page | profile | pass | html | js | css | json | tiles | fonts | images | other |
|---|---|---|---|---|---|---|---|---|---|---|
| layer-base-medium | desktop | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-base-medium | desktop | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-base-medium | phone | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-base-medium | phone | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-wind | desktop | cold | 5 KB (1) | 1.10 MB (4) | 83 KB (1) | 4 KB (1) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 0 B (0) |
| layer-wind | desktop | warm | 0 B (1) | 0 B (4) | 0 B (1) | 4 KB (1) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 0 B (0) |
| layer-wind | phone | cold | 5 KB (1) | 1.10 MB (4) | 83 KB (1) | 4 KB (1) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 0 B (0) |
| layer-wind | phone | warm | 0 B (1) | 0 B (4) | 0 B (1) | 4 KB (1) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 0 B (0) |
| layer-current | desktop | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-current | desktop | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-current | phone | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-current | phone | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-tide | desktop | cold | 14 KB (1) | 1.12 MB (6) | 83 KB (1) | 86 KB (3) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-tide | desktop | warm | 0 B (1) | 0 B (6) | 0 B (1) | 0 B (3) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-tide | phone | cold | 14 KB (1) | 1.12 MB (6) | 83 KB (1) | 86 KB (3) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-tide | phone | warm | 0 B (1) | 0 B (6) | 0 B (1) | 0 B (3) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-sst | desktop | cold | 7 KB (1) | 1.10 MB (3) | 83 KB (1) | 2.28 MB (1) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 0 B (0) |
| layer-sst | desktop | warm | 0 B (1) | 0 B (3) | 0 B (1) | 2.28 MB (1) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 0 B (0) |
| layer-sst | phone | cold | 7 KB (1) | 1.10 MB (3) | 83 KB (1) | 2.28 MB (1) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 0 B (0) |
| layer-sst | phone | warm | 0 B (1) | 0 B (3) | 0 B (1) | 2.28 MB (1) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 0 B (0) |
| layer-chlorophyll | desktop | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-chlorophyll | desktop | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 2.14 MB (33) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-chlorophyll | phone | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-chlorophyll | phone | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 1.22 MB (18) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-bathy-2m | desktop | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 2.18 MB (35) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-bathy-2m | desktop | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 2.18 MB (35) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-bathy-2m | phone | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 1.23 MB (18) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-bathy-2m | phone | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 1.23 MB (18) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-bathy-2m-z12 | desktop | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 1.05 MB (20) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-bathy-2m-z12 | desktop | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 1.05 MB (20) | 0 B (0) | 0 B (0) | 0 B (1) |
| layer-bathy-2m-z12 | phone | cold | 14 KB (1) | 1.12 MB (5) | 83 KB (1) | 24 KB (2) | 613 KB (11) | 0 B (0) | 0 B (0) | 208 KB (1) |
| layer-bathy-2m-z12 | phone | warm | 0 B (1) | 0 B (5) | 0 B (1) | 0 B (2) | 613 KB (11) | 0 B (0) | 0 B (0) | 0 B (1) |

| page | profile | pass | network req / bytes | no-store req / bytes | third-party req / bytes | req. ≤ FCP | JS script time | network-settle window (not the CPU-counter window) |
|---|---|---|---|---|---|---|---|---|
| layer-base-medium | desktop | cold | 43 / 3.58 MB | 0 / 0 B | 0 / 0 B | 6 | 44 ms | 6.53 s |
| layer-base-medium | desktop | warm | 39 / 2.14 MB | 0 / 0 B | 0 / 0 B | 7 | 27 ms | 6.53 s |
| layer-base-medium | phone | cold | 28 / 2.66 MB | 0 / 0 B | 0 / 0 B | 3 | 144 ms | 22.22 s |
| layer-base-medium | phone | warm | 24 / 1.22 MB | 0 / 0 B | 0 / 0 B | 6 | 97 ms | 12.79 s |
| layer-wind | desktop | cold | 40 / 3.34 MB | 0 / 0 B | 0 / 0 B | 5 | 3.64 s | 6.28 s |
| layer-wind | desktop | warm | 39 / 2.14 MB | 0 / 0 B | 0 / 0 B | 8 | 3.97 s | 6.27 s |
| layer-wind | phone | cold | 25 / 2.42 MB | 0 / 0 B | 0 / 0 B | 5 | 4.50 s | 20.46 s |
| layer-wind | phone | warm | 24 / 1.22 MB | 0 / 0 B | 0 / 0 B | 8 | 4.09 s | 12.54 s |
| layer-current | desktop | cold | 43 / 3.58 MB | 0 / 0 B | 0 / 0 B | 6 | 56 ms | 6.52 s |
| layer-current | desktop | warm | 39 / 2.14 MB | 0 / 0 B | 0 / 0 B | 7 | 40 ms | 6.52 s |
| layer-current | phone | cold | 28 / 2.66 MB | 0 / 0 B | 0 / 0 B | 5 | 207 ms | 22.21 s |
| layer-current | phone | warm | 24 / 1.22 MB | 0 / 0 B | 0 / 0 B | 6 | 128 ms | 12.79 s |
| layer-tide | desktop | cold | 45 / 3.65 MB | 0 / 0 B | 0 / 0 B | 6 | 39 ms | 6.53 s |
| layer-tide | desktop | warm | 40 / 2.14 MB | 0 / 0 B | 0 / 0 B | 7 | 25 ms | 6.52 s |
| layer-tide | phone | cold | 30 / 2.73 MB | 0 / 0 B | 0 / 0 B | 5 | 155 ms | 22.47 s |
| layer-tide | phone | warm | 25 / 1.22 MB | 0 / 0 B | 0 / 0 B | 6 | 95 ms | 12.79 s |
| layer-sst | desktop | cold | 39 / 5.61 MB | 0 / 0 B | 0 / 0 B | 4 | 61 ms | 6.52 s |
| layer-sst | desktop | warm | 38 / 4.42 MB | 0 / 0 B | 0 / 0 B | 6 | 40 ms | 6.27 s |
| layer-sst | phone | cold | 24 / 4.69 MB | 0 / 0 B | 0 / 0 B | 4 | 206 ms | 31.98 s |
| layer-sst | phone | warm | 23 / 3.50 MB | 0 / 0 B | 0 / 0 B | 4 | 140 ms | 23.56 s |
| layer-chlorophyll | desktop | cold | 43 / 3.58 MB | 0 / 0 B | 0 / 0 B | 6 | 42 ms | 6.52 s |
| layer-chlorophyll | desktop | warm | 39 / 2.14 MB | 0 / 0 B | 0 / 0 B | 7 | 30 ms | 6.52 s |
| layer-chlorophyll | phone | cold | 28 / 2.66 MB | 0 / 0 B | 0 / 0 B | 5 | 169 ms | 22.22 s |
| layer-chlorophyll | phone | warm | 24 / 1.22 MB | 0 / 0 B | 0 / 0 B | 6 | 115 ms | 12.79 s |
| layer-bathy-2m | desktop | cold | 45 / 3.63 MB | 0 / 0 B | 0 / 0 B | 6 | 37 ms | 6.53 s |
| layer-bathy-2m | desktop | warm | 41 / 2.18 MB | 0 / 0 B | 0 / 0 B | 7 | 28 ms | 6.53 s |
| layer-bathy-2m | phone | cold | 28 / 2.67 MB | 0 / 0 B | 0 / 0 B | 5 | 148 ms | 22.22 s |
| layer-bathy-2m | phone | warm | 24 / 1.23 MB | 0 / 0 B | 0 / 0 B | 6 | 96 ms | 12.79 s |
| layer-bathy-2m-z12 | desktop | cold | 30 / 2.50 MB | 0 / 0 B | 0 / 0 B | 6 | 35 ms | 6.52 s |
| layer-bathy-2m-z12 | desktop | warm | 26 / 1.05 MB | 0 / 0 B | 0 / 0 B | 7 | 24 ms | 6.27 s |
| layer-bathy-2m-z12 | phone | cold | 21 / 2.06 MB | 0 / 0 B | 0 / 0 B | 5 | 128 ms | 18.71 s |
| layer-bathy-2m-z12 | phone | warm | 17 / 613 KB | 0 / 0 B | 0 / 0 B | 6 | 76 ms | 9.78 s |

### A.8 Payload sizes: the daily feed, the brief and the other data the first screen reads

Measured 2026-11-07 with `feed_sizes.sh` (`raw/feed-sizes.tsv`). The daily feed is already split into parts
(SC2222-02): `/api/daily` with no `part` answers 400, and one map load reads `brief` + `regulations`.

| payload | wire (zstd) | decoded | Cache-Control | read by |
|---|---|---|---|---|
| `/api/daily?part=brief` | 18.6 KB | 228 KB | public, max-age=14400, s-maxage=300 | brief, map |
| `/api/daily?part=regulations` | 10.1 KB | 41 KB | same | brief, map |
| `/api/daily?part=mpa-boundaries` | 100.5 KB | 279 KB | same | (not read on these pages) |
| `/api/daily?part=additional-closures` | 0.1 KB | 0.2 KB | same | (not read on these pages) |
| `/api/forecast?region=morro-bay` | 88.2 KB | 709 KB | public, max-age=14400, s-maxage=300 | landing, brief, map |
| `/api/coast/report` | 141.0 KB | 664 KB | **no-store** | landing, brief, map |
| `/api/coast/ocean` (the ~1.5 MB case) | 269.4 KB | **1,517 KB** | **no-store** | landing, brief, map |
| `/data/protected-areas.geojson` | 100.1 KB | 277 KB | public, max-age=0, must-revalidate | brief, map |
| `/regions/morro-bay/land-water-lines.json` | 73.0 KB | 279 KB | public, max-age=0, must-revalidate | brief, map (at ~7.2 s) |
| `/feeds/tiles/seafloor/regions/morro-bay/ledger.json` | 20.2 KB | 137 KB | **no-store** | brief, map |
| `/feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz` | **15,418 KB** (gzip file, sent as is) | **53,649 KB** | **no-store** | brief, map, every layer view |

The brief part itself is small (18.6 KB on the wire). The "1.49 MB" payload is `/api/coast/ocean`: 1.52 MB decoded,
269 KB on the wire, `no-store`, read on every page including the landing.

**Reef export anatomy** (`raw/export-anatomy.json`): 3,064 features (1,965 Polygon, 1,099 MultiPolygon), 1,085,970
vertices, 35 property keys.

| form of the export | JSON bytes | gzip-9 bytes |
|---|---|---|
| as published | 53,648,871 | 15,414,926 |
| properties only (no geometry) | 9,844,062 | 392,597 |
| geometry only | 43,672,856 | 14,439,367 |
| coordinates rounded to 6 dp (0.11 m) | 35,973,743 | 4,816,574 |
| coordinates rounded to 5 dp (1.1 m) | 33,801,218 | 3,359,159 |
| vertices closer than 5 m dropped, 6 dp | 20,613,947 | 2,762,210 |
| only the fields `loadReefTrip` keeps per target, no geometry | 6,306,922 | **342,427** |

Coordinates are written with ~15 decimal places (sample `-120.87915622800566`, i.e. femtometre precision); the
geometry is 94% of the compressed file.

### A.9 PMTiles: range requests and bytes per map view, archive tile budgets

Per map view (medians, from A.3 and A.7):

| view | profile | PMTiles range requests | PMTiles bytes |
|---|---|---|---|
| live brief / map-home (basemap + seafloor) | desktop | 17 | 1.24 MB |
| live brief / map-home | phone | 18 | 1.46 MB |
| live layer views without the seafloor layer (basemap only) | desktop | 8 | 64 KB cold / 21 KB warm |
| live landing (basemap only) | desktop / phone | 8 / 6 | 128 KB / 125 KB |
| local medium raster seafloor, zoom 9.5 | desktop / phone | 33 / 18 | 2.14 MB / 1.22 MB |
| local 2 m archive, zoom 9.5 | desktop / phone | 35 / 18 | 2.18 MB / 1.23 MB |
| local 2 m archive, zoom 12 harbour | desktop / phone | 20 / 11 | 1.05 MB / 613 KB |

Archive tile sizes (`raw/pmtiles-sizes.json`):

| archive | type | zooms | worst tiles |
|---|---|---|---|
| live `seafloor-morro-bay.pmtiles` (layers `cells`, `habitat`) | MVT, gzip | z8–15 | **z8 median 428 KB, max 774 KB; z9 max 1,144 KB; z10 median 508 KB, max 941 KB**; z11 max 826 KB. 6 tiles over 500 KB. z15 median 0.9 KB. |
| live `ca-coast-20261011.pmtiles` basemap | MVT, gzip | z0–14 | max 207 KB (z10); medians 1.6–86 KB. Healthy. |
| local medium raster seafloor | PNG | z8–13 | median 68–89 KB per tile at z11–13, max 143 KB |
| local 2 m raster seafloor | PNG | z8–15 | same as medium at z8–13 (the 2 m data adds only z14–15: 140 tiles, 9.9 MB) |

**WebP trial** (`raw/webp-trial.jsonl`, 40 tiles each): WebP quality 0.8 is **7.9–11.2 %** of the PNG bytes,
quality 0.9 is 13.8–17.9 %, quality 1.0 is 61–96 %. (Visual equivalence was not judged; see proposal P12.)

**Uncompressed test data** (`raw/compress-sizes.txt`): the SST preview grid is 2,276,571 bytes raw and 148,644 bytes
gzip-9 (−93 %); `maplibre-gl.mjs` 1,078,892 raw / 285,648 gzip-9; the chlorophyll PNG does not compress further
(208 KB → 206 KB).

---

## B. Root causes (what is on the critical path, with evidence)

Ranked by measured cost to the user.

### B1. The 15.4 MB reef export is downloaded on every brief and map view, `no-store`

* Requested by `dist/reef-trip-data.js` (`loadReefTrip`, via `web/ranking.ts` `loadReefPublication`) on the brief,
  map-home and every live layer view; never on the landing. `fetch(..., {cache: 'no-store', signal:
  AbortSignal.timeout(60000)})`; the Worker also answers `Cache-Control: no-store` for everything under
  `tiles/seafloor/` (`server/feeds.ts:187`), on purpose: the expiry gate must not be outlived by a saved copy.
* Desktop waterfall, brief cold run 3 (ms from navigation; requests ≥ 40 KB):
  ```
      0 →      85        3.8 KB  html   /map?region=morro-bay&ui=v2
     89 →     181       99.0 KB  js     /assets/app.d390f02cdc.js
    176   ── FCP ──
    259   ── brief shown ──
    276   ── LCP ──
    279 →     348      312.1 KB  js     /assets/maplibre-gl.4f81424288.js
    355 →    1005    15417.6 KB  tiles  /feeds/tiles/seafloor/regions/morro-bay/habitat-export.geojson.gz
    440 →     712      269.3 KB  json   /api/coast/ocean
    503   ── map canvas ──
   1235 →    2620      609.0 KB  tiles  /feeds/tiles/seafloor/seafloor-morro-bay.pmtiles
  13590   ── canvas quiet (proxy) ──
  requests=135 bytes=19.44 MB tbt=11631 longest task=3216 script=11476 ms
  ```
* It is **79 %** of a cold desktop brief's 19.4 MB (15.42 of 19.44 MB) and **~90 %** of what a warm desktop brief still
  fetches (15.41 of 17.08 MB network bytes, medians of 3). The other `no-store` responses (seafloor tiles 1.21 MB, the
  ocean feed, reports) make **all** `no-store` traffic 17.03 of 17.08 MB = 99.7 % of the warm brief (A.5): that 99.7 %
  describes `no-store` traffic as a whole, not the export.
* **Phone, slow 4G:** the export starts at ~3.3 s and is aborted by the 60 s timeout at ~63 s **in every run, cold
  and warm**, after 9.0 MB (cold) / 10.5 MB (warm) arrived. The reef ranking therefore never appears on a slow phone
  connection, while each visit costs ~9–10.5 MB of the user's data. It also shares the 1.6 Mbit/s link with
  everything after it: `maplibre-gl.js` takes 3.4 → 9.1 s and `/api/coast/ocean` 9.2 → 21.0 s:
  ```
   1680   ── FCP ──
   3110   ── brief shown ──
   3280 →   63404     9030.1 KB  tiles  …/habitat-export.geojson.gz  [net::ERR_ABORTED]
   3383 →    9121      312.1 KB  js     /assets/maplibre-gl.4f81424288.js
   9196 →   21001      270.6 KB  json   /api/coast/ocean
   9285   ── map canvas ──
   9427   ── canvas quiet (proxy) ──
  11781 →   25342      609.0 KB  tiles  /feeds/tiles/seafloor/seafloor-morro-bay.pmtiles
  ```
  The landing (same map, no export) has its map canvas on screen at 6.3 s on the same phone profile, against 9.3 s on
  the brief (canvas shown, not content-ready).
* Memory: the desktop brief ends with a **300–615 MB** JS heap (53.6 MB of JSON parsed into ~1.1 M coordinate
  arrays) against ~18 MB on the landing; on a phone that completes the download this is a tab-kill risk (ESTIMATED).

### B2. Protected-area screening of the export blocks the main thread for ~11.5 s

* CPU profile, desktop brief (`raw/cpu-profile-brief-desktop.json`): of 15.2 s sampled, **9.3 s self time in
  `geo-screen.js`**, called from the planner/ranking chunk (`depth-contours.*.js` Tn/Nn ← `app.js` gu) through the
  protected-area screen (`protected-areas.js` `geometryAllowed` / `pointAllowed`, `web/map/ranked.ts:81-82`).
* Long tasks, desktop brief (`raw/diag-brief-desktop.json`): **3.30 s, 2.66 s, 2.93 s, 2.77 s** (4 tasks, ~11.7 s);
  TBT 11.6 s to the canvas-quiet proxy: the main thread is blocked by long tasks from the first screen until 13.6 s
  (canvas on screen 0.5 s). Tap response itself was not measured.
* The same on every live layer view (TBT 11.0–12.0 s desktop): the cost is independent of which layer is on.
* Phone CPU on fast network (`phone-wifi`): brief cold: canvas on screen 1.07 s, canvas-quiet proxy **16.37 s**, TBT **13.98 s**, longest task 13.08 s, JS script time 23.17 s (accumulated; not a duty cycle, A.1), heap 346 MB, 19.3 MB transferred; map-home cold: canvas-quiet 16.61 s, TBT 13.99 s. A phone on good Wi-Fi gets the reef data and then freezes.
* On slow 4G the screen never runs (B1), which is why the phone TBT looks small (0.3–0.5 s): a slow phone is "fast"
  only because the feature fails. The window also ends at the canvas-quiet proxy (9.4 s), before the data would arrive,
  so that figure says nothing about blocking after it.

### B3. The first screen is rendered by JavaScript; nothing useful paints before ~60 modules load

* `/map` HTML is 3.8 KB with only "Loading the map shell." in `#app`; it lists **55 `modulepreload`** links.
  The brief needs 63 JS requests (767 KB wire) before it can render. Phone cold: FCP 1.68 s, brief shown 3.11 s,
  map-home (with its client-side redirect to the home region) brief shown 3.48 s.
* The landing `/` is static HTML (8.3 KB with text), so its FCP is 0.86 s on the phone, but it then loads 53 JS
  modules, the map, `/api/coast/ocean` (1.5 MB decoded, `no-store`), `/api/coast/report` and the forecast:
  1.6 MB cold for a page whose job is to send people to the map.

### B4. Large layout shift on desktop (CLS 0.67–0.76)

* `diag.mjs` layout-shift sources, desktop brief: one shift of **0.60–0.61 at ~0.3 s** moves `main.app-main`
  (y 330→355, height 611→586), `section.app-first-answer` (160→185) and `div.app-area` (74→131) when the area
  header fills in; then 0.02–0.04 shifts from `section.app-legend`, `div.app-tiles` and, at ~7.6 s, the legend
  rows (`li.app-legend-depth-contours`, `li.app-legend-mpa`) when the reef data lands.
* Phone CLS is low (0.0001–0.03) except the landing (0.19 cold, 0.11 warm).

### B5. Other `no-store` and short-lived data on every load

* `/api/coast/ocean` 269 KB wire (1.52 MB decoded) and `/api/coast/report` 141 KB (664 KB) are `no-store`, read
  even by the landing; on the phone `coast/ocean` is the last big request before the seafloor (9.2 → 21.0 s).
* Seafloor PMTiles (1.24–1.46 MB per view), its manifest and the 137 KB ledger are `no-store` (B1's rule).
* Basemap PMTiles are `max-age=300`; ~12 region JSON files are `max-age=0, must-revalidate` (one revalidation
  round-trip each on warm loads: at 150 ms RTT that is latency, not bytes).
* Result: a **warm** desktop brief still moves 40 requests / 17.1 MB, a warm phone brief 12.6 MB.

### B6. Seafloor vector tiles far over budget at wide zoom

* `seafloor-morro-bay.pmtiles` z8–z11 tiles are 400 KB–1.14 MB (A.9); one 609 KB tile is in every brief view
  (the default zoom), downloaded no-store. A common budget is ≤ 500 KB per tile, ideally ≤ 100–200 KB.
* The `habitat` layer in this archive carries the same reef outlines the export carries (B1), so the outlines
  travel twice.

### B7. Third-party requests on the critical path

* 15 USGS NAIP aerial image requests (`imagery.nationalmap.gov`, ~900 KB, `max-age=43200`) start with the map
  canvas; on the phone they share the slow link (9.4 → 17.2 s).
* `services2.arcgis.com …/biosds582_fpu/FeatureServer` (96 KB, `private, max-age=30`) is fetched straight from
  ArcGIS on every load (~0.3 → 0.9 s desktop).
* Cloudflare Web Analytics beacon (small).

### B8. Private-layer test pages: late, uncompressed data and a continuously running particle loop

* SST: the 2.28 MB uncompressed grid is fetched only after the map has loaded (phone cold 14.1 → 25.5 s), so
  **LCP is 25.7 s cold / 17.5 s warm on the phone** and the layer is not visible before ~25.5 s, although the
  canvas-quiet proxy says 6.4 s; gzip would make it 149 KB (MEASURED size; the time saving is ESTIMATED).
* Currents: LCP 16.0 s cold / 6.6 s warm on the phone (the current overlay paints after the tiles).
* Wind particles: the animation loop accumulates **3.6–4.1 s of script on desktop** (6.3 s network-settle window,
  6.2–6.5 s of total task time) and 4.5 s on the throttled phone (20.5 s window), against 40–70 ms (desktop) and
  0.2 s (phone) for the SST page; heap 39–55 MB desktop vs 6–10 MB for the static layers. These are accumulated
  totals; a per-second duty cycle is **not** claimed (A.1: window mismatch, unvalidated ScriptDuration under throttling).
* Raster seafloor tiles are PNG at 68–89 KB median; the zoom-9.5 view costs 18–33 range requests / 1.2–2.1 MB.
  WebP q0.8 would be 8–11 % of those bytes (A.9).
* These pages are not published; this is what the layers would cost if shipped as they stand.

### B9. Smaller items (measured, each under ~0.3 s)

* `maplibre-gl.js` 312 KB wire is loaded by the landing as well as the map.
* Map label glyphs `dm-sans-medium/0-255.pbf` 84 KB plus two WOFF2 fonts (38 KB + 33 KB).
* `region.f99051a072.js` was a Cloudflare MISS (`cf-cache-status`) in run 1; everything else under `/assets/` is
  HIT, zstd, `immutable`, HTTP/3 — static asset delivery is already good.

---

## C. Proposals, ranked

Gain: MEASURED = observed in this baseline (bytes or time already on the waterfall); ESTIMATED = derived, not yet
tried. Effort S/M/L. "Visible" = changes what users see. "Decision" = **safe-to-build-now** (repo code, reviewable
PR, normal CI/deploy) or **needs G** (changes what is published, deploy/hosting/DNS/Cloudflare settings, or money).

Each entry: **what** · why (cause) · expected gain · effort · risk · visible · decision.

### Tier 1: the reef export (B1, B2) — by far the largest win

**P1. Stop shipping reef geometry in the export the brief reads; send only the per-target fields.**
* What: publish a second, small file (or a `part`) with just what `loadReefTrip`/ranking keeps per target (ids,
  ranks, depths, labels, waypoint, screen result), and take the outlines from the seafloor PMTiles `habitat`
  layer that the map already draws. Keep the full export for the GPX/trip export path only, fetched on demand.
* Why: B1, B2, B6 (outlines travel twice).
* Gain: MEASURED bytes **15.4 MB → 0.34 MB per brief/map view (−98 %)** (A.8, "targets only"). ESTIMATED time:
  phone slow 4G map canvas ~9.3 s → ~6.3 s (the landing's figure, same map without the export) and the reef
  ranking appears instead of timing out; desktop heap 300–600 MB → ~20–40 MB.
* Effort M (publisher + loader + verify), risk M (the publication's integrity and expiry checks must cover the
  new file; ranking output must be byte-identical for equal inputs — testable).
* Visible: yes, positively (ranking now appears on slow phones); same content otherwise.
* Decision: **needs G** — it changes what is published under `/feeds/tiles/seafloor/` (new public file). The
  loader-side code change alone is safe to build once the file exists.

**P2. Do the protected-area screening at publish time, not in every browser.**
* What: compute `pointAllowed` / `geometryAllowed` for every target in the publisher (Python already holds the
  protected areas and the outlines) and publish the result with the target; keep the run-time screen only as a
  cheap point-in-polygon check on the few ranked marks shown (or behind a manifest hash check).
* Why: B2 (9.3 s self time in `geo-screen`, 4 long tasks of ~3 s).
* Gain: MEASURED current cost: desktop TBT 11.6 s and 4 long tasks (~11.7 s); phone CPU on Wi-Fi TBT 14.0 s (B2's
  phone-wifi line; ~1.2× the desktop figure, script time ~2×). ESTIMATED future gain: desktop TBT −11 s and the
  canvas-quiet proxy 13.6 s → ~1.5 s (the landing's 1.43 s); on the phone CPU the saving is of the same order as its
  14.0 s TBT, not several times larger. Not a measurement of the changed site.
* Effort M, risk M–H: this is a safety screen (#489); the publish-time result must be verified to match the
  run-time result on every target before the run-time path is relaxed (a parity test over the full export).
* Visible: no (faster, same marks). Decision: **needs G** (publication content, and it relaxes a run-time
  safety check); a parity-test-only PR is safe to build now.

**P3. If the screen must stay in the browser: move it to a Web Worker and simplify the geometry first.**
* What: run `geo-screen` in a worker over a pre-simplified copy; yield between targets; start it at idle after
  the map canvas is shown (content readiness is not measured here).
* Why: B2. Gain: ESTIMATED main-thread TBT −11 s (moved off thread; total CPU unchanged unless simplified;
  with 5 m thinning, vertices 1.09 M → 0.44 M, ~−60 % CPU ESTIMATED). Effort M, risk M (worker bundling,
  identical results). Visible: no. Decision: **safe-to-build-now** (client code only).

**P4. Quick fix inside the current file: round coordinates and drop sub-metre vertices.**
* What: write coordinates at 6 dp (0.11 m) — or 5 dp (1.1 m) — instead of ~15 dp; optionally drop vertices
  closer than 5 m to the previous one.
* Why: B1 (geometry is 94 % of the file; 15-digit coordinates). Gain: MEASURED **15.4 → 4.8 MB (6 dp), 3.4 MB
  (5 dp), 2.8 MB (6 dp + 5 m thinning)**. Effort S, risk L–M (6 dp is below every source's resolution; the 2 m
  layer's finest cell is 2 m). Visible: no (sub-metre changes). Decision: **needs G** (changes the published file).

**P5. Make the export cacheable between visits, without outliving the expiry gate.**
* What: version the URL by content hash from the manifest (`…/habitat-export.<sha>.geojson.gz`) and serve it
  `public, max-age=<until expires_at>, immutable`; the manifest (small, `no-store`) remains the gate. Same for the
  seafloor PMTiles and the ledger.
* Why: B1, B5 (a warm visit re-downloads 17 MB). Gain: MEASURED current cost, warm desktop brief (medians of 3): 17.08 MB
  from the network, of which the export is 15.41 MB, the seafloor PMTiles + manifest + ledger 1.21 MB (the files this
  proposal covers: 16.62 MB together) and ~0.46 MB other traffic (ocean feed, reports, region JSON) that P5 does not
  touch. ESTIMATED future gain: if those 16.62 MB became cacheable, the warm brief would re-fetch ~0.5 MB plus the
  small manifest revalidations; that is arithmetic on the measured bytes, not a demonstrated saving (browser cache
  behaviour of range requests on the PMTiles was not tested). ESTIMATED warm phone canvas-quiet proxy 3.1 s → ~2.5 s
  and up to ~12 MB less data per repeat visit.
* Effort M, risk M (expiry semantics: a stale object must never be served after `expires_at`; the manifest
  check makes that hold). Visible: no. Decision: **needs G** (cache policy of published feeds; Cloudflare edge
  behaviour).

**P6. Load the reef data only when it is needed, after the map canvas is on screen.**
* What: start `loadReefPublication` at `requestIdleCallback` once the map canvas is shown, or when the user opens ranking /
  trip / the seafloor layer — not in parallel with `maplibre-gl.js` and the tiles.
* Why: B1 (on the phone it holds the link for 60 s and delays maplibre to 9.1 s and `coast/ocean` to 21 s).
* Gain: ESTIMATED phone map canvas 9.3 s → ~6.3 s even before P1; on Save-Data/2G skip it entirely.
  Effort S, risk L. Visible: ranking marks arrive a moment later. Decision: **safe-to-build-now**.

**P7. Replace the fixed 60 s timeout with progress-aware loading and a clear message.**
* What: abort early when the projected time exceeds a budget (bytes/s after 5 s), show "Reef ranking needs
  15 MB — load on Wi-Fi?" with a button; never silently spend 10 MB then fail.
* Why: B1 (9–10.5 MB used, nothing shown, every phone run). Gain: MEASURED up to 10.5 MB data saved per slow
  visit. Effort S, risk L. Visible: yes (a message). Decision: **safe-to-build-now**.

### Tier 2: first screen and perceived speed (B3, B4)

**P8. Pre-render the first screen of `/map` (shell, brief header, home-port summary) at build/edge time.**
* What: render the brief header, the area name, the "first answer" and the static shell into the HTML (Preact
  `render-to-string` at build time per region, or at the Worker with the cached `part=brief`), hydrate after.
  Static pre-render of port pages (`/ports/<id>`, which 404 today) the same way.
* Why: B3 (HTML has only "Loading the map shell."; brief shown at 3.1 s on the phone, 0.25 s desktop).
* Gain: ESTIMATED phone FCP 1.68 s → ~0.9 s (the static landing's 0.86 s) and brief shown 3.1 s → ~1 s.
  Effort L, risk M (hydration mismatches, the brief's freshness rules must hold in the HTML). Visible: yes
  (text appears sooner). Decision: **needs G** for new public port pages (published content) and an edge
  render; the build-time shell for existing `/map` is safe to build now.

**P9. Show the last-known brief instantly from local storage, then refresh.**
* What: keep the last `part=brief` (18.6 KB wire, 228 KB decoded) for the home port in IndexedDB with its
  timestamp; paint it immediately with an "as of HH:MM, updating" line; replace when fresh data lands.
* Why: B3; map-home phone cold shows the brief at 3.48 s (includes the redirect).
* Gain: ESTIMATED repeat-visit phone "brief shown" → ~0.3–0.5 s. Effort S–M, risk M (stale data must look
  stale; the age line is already a product pattern). Visible: yes. Decision: **safe-to-build-now**
  (local-only storage, no personal data leaves the device).

**P10. Fix the desktop layout shift (CLS 0.67–0.76 → < 0.1).**
* What: reserve the area header's height (`div.app-area` grows 74→131 px; `main.app-main` shifts 25 px) with a
  fixed min-height / skeleton; reserve legend rows for the depth-contour and MPA entries before reef data lands.
* Why: B4 (one 0.60 shift at 0.3 s). Gain: ESTIMATED CLS −0.6 (from the measured shift values). Effort S,
  risk L. Visible: yes (no jump). Decision: **safe-to-build-now**. Also check the landing's 0.19 phone CLS.

**P11. Skeletons and named loading states.**
* What: skeleton blocks for the brief tiles and legend; a small status list ("Map ready · Seafloor loading ·
  Reef ranking on Wi-Fi only") instead of silent waits; progressive layer reveal (base map, then seafloor, then
  overlays). Why: B1/B3/B8. Gain: perceived only (ESTIMATED). Effort S–M, risk L. Visible: yes.
  Decision: **safe-to-build-now**.

### Tier 3: tiles and layer data (B6, B8)

**P12. Raster seafloor tiles as WebP (lossy q≈0.8–0.9) instead of PNG.**
* Why: B8. Gain: MEASURED on samples **−82 % to −92 % tile bytes** (q0.9 / q0.8): the zoom-9.5 view
  2.14 MB → ~0.2–0.35 MB desktop. Effort S–M (encoder in the tile build), risk M (colour-ramp banding and
  hillshade artefacts; needs a visual check). Visible: subtly. Decision: **needs G** before publishing (changes
  published tiles); trying it in the private test build is safe now.

**P13. A tile budget for the seafloor vector archive: generalise z8–z11.**
* What: at z8–11 drop or merge the `cells` layer (or aggregate cells into coarser hexes/contours), simplify
  `habitat` outlines with a zoom-dependent tolerance, quantise to the tile extent, cap tiles at 200 KB with a
  build check. Why: B6 (z9 max 1.14 MB; a 609 KB tile in every brief view).
* Gain: MEASURED tile sizes above; ESTIMATED brief view seafloor 1.24 MB → ~0.3 MB, phone ~1.5 s sooner
  seafloor paint. Effort M, risk M (coarse zooms must not mislead about depth/habitat). Visible: coarser at wide
  zoom. Decision: **needs G** (published tiles).

**P14. Level of detail by distance from shore (coastline, shore vectors, bathymetry).**
* What: build-time generalisation: full-resolution shoreline only within ~30 m (100 ft) of the water's edge;
  inland detail dropped or simplified by zoom (Douglas–Peucker / Visvalingam tolerance ≈ ½ pixel at each zoom);
  quantised coordinates; vector-tile generalisation per zoom; for bathymetry the 2 m data only at z14–15 where it
  is already confined (A.9), coarser overviews at wide zoom, contour interval by zoom (e.g. 50 ft at z9, 10 ft at
  z13+). Why: B6, and `land-water-lines.json` (73 KB / 279 KB) plus the reef outlines (B1).
* Gain: ESTIMATED 30–60 % fewer vertices in shore layers; the 2 m archive already adds no cost at z9.5 (MEASURED:
  2.18 MB vs 2.14 MB). Effort M–L, risk M (shoreline accuracy near ramps and harbour). Visible: subtly at wide
  zoom. Decision: **needs G** (published geometry).

**P15. Fetch layer data only when the layer is on, and in parallel with the map, not after it.**
* What: the SST page fetches its 2.28 MB grid after the map loads (14 → 25.5 s on the phone); start it with the
  map or on toggle, and never fetch an off layer. Live layer views already fetch only the base archive when a
  layer is off (8 range requests, 64 KB) — keep that as a test. Why: B8. Gain: MEASURED SST phone LCP 25.7 s →
  ESTIMATED ~12 s from parallel start; with P16 ~8 s. Effort S, risk L. Visible: faster. Decision:
  **safe-to-build-now** (private test pages; same rule for the product layers when they ship).

**P16. Compress and slim layer payloads (SST, currents, tide, wind).**
* What: serve JSON grids compressed (zstd/br; −93 % for SST, MEASURED), or encode grids as 8/16-bit PNG/WebP
  textures (decoded by the GPU), round values to sensor precision, drop repeated keys.
* Why: B8. Gain: MEASURED SST 2.28 MB → 149 KB gzip. Effort S, risk L. Visible: no.
  Decision: **safe-to-build-now** for the code; publishing a layer is G's call as it already is.

**P17. Range-request coalescing and directory prefetch for PMTiles.**
* What: the seafloor view issues 8–9 parallel range requests for adjacent byte ranges (e.g. 7355542–7651296 in
  4 requests); merge adjacent ranges (pmtiles `FetchSource` with a custom `getBytes` that coalesces within one
  frame), and cluster tiles by Hilbert order in the archive (already the PMTiles default). Why: B6, A.9.
* Gain: ESTIMATED −30–50 % range requests per view; at 150 ms RTT on HTTP/3 the win is small (requests are
  multiplexed): ~0.1–0.3 s. Effort S–M, risk L. Visible: no. Decision: **safe-to-build-now**.

**P18. Per-layer max zoom and overzoom.**
* What: stop each layer at the zoom where its data runs out (chlorophyll 300 m–1 km, currents 6 km, SST
  0.01°) and let the client overzoom instead of requesting more tiles; for raster layers that are a single image
  (chlorophyll PNG 208 KB) keep the single image. Why: A.9/B8. Gain: ESTIMATED fewer requests at high zoom.
  Effort S, risk L. Visible: no. Decision: **safe-to-build-now** (client/style) / **needs G** where tiles change.

### Tier 4: cache, network, third parties (B5, B7, B9)

**P19. Cache headers for `coast/ocean`, `coast/report`, region JSON and the basemap.**
* What: `/api/coast/ocean` and `/api/coast/report` `public, max-age=60–300, stale-while-revalidate=3600` (or
  versioned by data time); region JSON (`regions/morro-bay/*.json`, `data/*.json`) content-hashed and
  `immutable`, or `max-age=300, stale-while-revalidate`; basemap PMTiles (dated file name already) `max-age=1y,
  immutable`. Why: B5 (410 KB wire / 2.2 MB decoded re-fetched every load; ~12 revalidations; basemap 5 min).
* Gain: MEASURED ~410 KB less per warm load; ESTIMATED ~12 × 150 ms RTT of revalidations removed on phones
  (parallel, so ~0.2–0.5 s). Effort S, risk M (freshness of observation data must still show its age). Visible:
  no. Decision: **needs G** (Cloudflare/edge cache behaviour of public endpoints).

**P20. Conditional requests and delta updates for the daily data.**
* What: ETag / `If-None-Match` on `part=brief`, `forecast`, `coast/*` (304 instead of a body when unchanged);
  optional delta endpoint ("changes since <data time>") for the brief and stations. Why: B5. Gain: ESTIMATED
  −100–400 KB per refresh. Effort M, risk L. Visible: no. Decision: **needs G** (public API behaviour).

**P21. Per-region and per-layer endpoints; slim `/api/coast/ocean` (1.52 MB decoded).**
* What: split `coast/ocean` by region and by consumer (the landing needs a headline, not the whole ocean
  model); remove fields the first screen does not read; round floats. The daily feed is already split
  (`brief` 18.6 KB wire) — apply the same to `coast/ocean` and `forecast` (709 KB decoded).
* Why: B3/B5. Gain: ESTIMATED landing −300–400 KB wire, −2 MB decoded/parsed. Effort M, risk L–M.
  Visible: no. Decision: **needs G** (public endpoints).

**P22. Proxy or cache the third-party requests at our edge.**
* What: serve the NAIP aerial (~900 KB, 7 images) through cached tiles of our own (it is public-domain USGS
  imagery) or only when the aerial base is chosen; cache the ArcGIS `biosds582` query (96 KB, `max-age=30`)
  in the daily feed. Why: B7. Gain: ESTIMATED phone −0.9 MB competing with the map at 9–17 s; one fewer origin
  (no DNS/TLS to services2.arcgis.com). Effort M, risk M (USGS/ArcGIS terms). Visible: no.
  Decision: **needs G** (new published/proxied data, hosting).

**P23. `preconnect` / `dns-prefetch` for the third parties that remain.**
* What: `<link rel="preconnect" href="https://imagery.nationalmap.gov" crossorigin>` and the ArcGIS host.
  Why: B7. Gain: ESTIMATED 1 RTT (~150 ms phone) per origin. Effort S, risk L. Visible: no.
  Decision: **safe-to-build-now** (HTML head).

**P24. Fonts: subset, `font-display: swap`, and reuse for map labels.**
* What: the two WOFF2 files are already small (38 + 33 KB); make sure both use `swap`, preload only the one the
  brief header uses, and subset the 84 KB `dm-sans-medium/0-255.pbf` glyph range to the characters the labels use
  (or label with fewer glyph ranges). Why: B9. Gain: ESTIMATED −50–70 KB, ~0.3 s phone. Effort S, risk L.
  Visible: no. Decision: **safe-to-build-now**.

**P25. Images: modern formats and sizes.** The live pages fetch no `<img>` images on these paths (A.4,
`images` = 0); the og/apple-touch images are not on the critical path. Keep it that way with a budget (P30).
Effort —. Decision: no action.

**P26. Network stack and CDN.** MEASURED: assets are already HTTP/3, zstd, `immutable`, Cloudflare HIT.
No change needed beyond P19. Any Cloudflare setting change (Tiered Cache, Cache Rules, Early Hints) is
**needs G**. ESTIMATED gain of Early Hints for the 55 modulepreloads: ~1 RTT on cold phone loads.

### Tier 5: JavaScript and rendering (B3, B8, B9)

**P27. Code-split the map route: lazy-load every layer, the planner/ranking chunk and the particle renderer.**
* What: the brief loads 63 modules including `depth-contours` (22 KB), `trip` (24 KB), `tide-selection` (23 KB),
  `gpx`, `geo-screen`, `currents`, `surface-field`; load each on first use. Don't load `maplibre-gl.js` (312 KB)
  on the landing until the user scrolls to or taps the map (an image poster instead; the region poster SVG
  exists). Why: B3, B9. Gain: ESTIMATED −200–400 KB JS on first load, landing −312 KB; phone FCP/brief shown
  −0.3–0.8 s. Effort M, risk L–M. Visible: no. Decision: **safe-to-build-now**.

**P28. Defer non-critical work to idle time; break long tasks.**
* What: `requestIdleCallback`/`scheduler.yield()` between targets in ranking and between legend sections;
  parse big JSON in a worker (`JSON.parse` of 53 MB alone is seconds on a phone, ESTIMATED).
  Why: B2. Gain: see P3. Effort S–M, risk L. Visible: no. Decision: **safe-to-build-now**.

**P29. Particle and animation cost on phones (wind, currents).**
* What: cap the particle loop at 30 fps on phones and when `prefers-reduced-motion`; render particles at
  0.5–0.75× device pixel ratio (the phone profile is 2.625×); pause on `visibilitychange` (hidden tab) and when
  the map is off-screen (IntersectionObserver) or being dragged; reduce trail overdraw (fewer, shorter trails at
  wide zoom); share one WebGL context with MapLibre (custom layer) instead of a second canvas, to stay under
  mobile WebGL context limits. Why: B8 (wind script time). Gain: ESTIMATED −50 % main-thread script time and
  battery for the wind layer. Effort M, risk L. Visible: slightly smoother/lower-res particles.
  Decision: **safe-to-build-now** (private layer code).

### Tier 6: preload, offline and data saver (B1, B3)

**P30. Remember the home ground and warm it at idle.**
* What: after the first screen is usable, at idle, fetch the home port's brief part, the default-zoom tiles
  (the 17–18 range requests above) and enabled layer data; prefetch a region on hover/near-viewport of its link;
  `<link rel="prefetch">` the next likely route. Why: B3/B5. Gain: ESTIMATED repeat-visit phone canvas-quiet proxy
  3.1 s → ~1.5 s once P5/P19 make the data cacheable. Effort M, risk L (respect Save-Data and metered
  connections). Visible: no. Decision: **safe-to-build-now**, but only useful after P5/P19.

**P31. Service worker for the shell and the home region for every visitor (not only after a save).**
* What: today `/sw.js` registers only once something is saved (`web/trip.ts:356`). Register it for all
  visitors with a small precache (HTML shell + hashed assets, ~800 KB) and stale-while-revalidate for the home
  region's brief; keep the expiry gate rule that seafloor screening is never served from a saved copy.
* Why: B3/B5. Gain: ESTIMATED repeat-visit FCP ~0.2 s on phones and offline shell. Effort M, risk M (storage
  use for visitors who never asked; update flow). Visible: offline behaviour. Decision: **needs G** (product
  decision on storing data for every visitor; privacy wording).

**P32. Data-saver mode and offline behaviour.**
* What: honour `navigator.connection.saveData` / `effectiveType` (2g/3g): no reef export, no aerial imagery,
  basemap-only, lower particle counts; a visible "Data saver" toggle. Show the cached brief offline with its age.
  Why: B1/B7. Gain: MEASURED up to ~11 MB less per phone visit (export + aerial). Effort S–M, risk L.
  Visible: yes. Decision: **safe-to-build-now** (toggle default off); default-on is **needs G**.

**P33. Tap targets and thumb reach.** Not measured here (this card measured load). Recommend a separate
review of the phone sheet (detents, rail buttons ≥ 48 px, primary actions in the lower third). Effort S,
risk L, visible yes, **safe-to-build-now** as a review card.

### Tier 7: keep it fast (measurement going forward)

**P34. A performance budget with a CI check.**
* What: one small script in the existing fast PR tier (no new workflow — R12): fail if the built map route's
  initial JS > 850 KB wire or > 70 requests, the brief page's request count > 150, or any same-origin request on
  the brief path > 2 MB; and a nightly (main-only) Playwright run of `measure.mjs --runs 1` on the local build
  checking LCP and TBT on the brief page against thresholds. Why: all causes; this baseline found a 15 MB file no
  test flagged. Gain: prevents regressions. Effort S–M, risk L (thresholds need headroom to avoid flakes).
  Visible: no. Decision: PR-tier size check **safe-to-build-now**; a new nightly job needs the operator's OK
  per R12 ("never add a new workflow without operator OK").

**P35. Real-user timing without personal data.**
* What: extend the existing `/api/telemetry` beacon (204, `no-store`) with LCP, INP, CLS, a real content-ready time (the baseline measured only a canvas proxy),
  effective connection type and region id, rounded and with no user id, IP or location beyond the region; or
  rely on Cloudflare Web Analytics (already loaded) for Core Web Vitals.
* Why: emulation is not real devices (E). Gain: true field numbers. Effort S, risk L–M (privacy text must
  cover it). Visible: no. Decision: **needs G** (new data collected from users; privacy policy).

**P36. Re-run this baseline after each Tier 1 change.** `sh reports/perf/run-live.sh` and
`summarize.py`; compare medians. Effort S. **safe-to-build-now**.


---

## D. Top 5 causes and top 10 proposals (plain words)

**Top 5 causes**

1. Every brief and map view downloads a 15.4 MB reef file (53.6 MB unpacked), again on every visit because it is marked never-cache.
2. When that file arrives, checking every reef outline against protected areas freezes the page for about 11.5 s (long tasks keep the main thread blocked until 13.6 s on desktop; tap response was not measured).
3. On a slow phone connection the reef file never finishes: the app gives up after 60 s, having used 9–10.5 MB of data, and it slows the map code and other data behind it (map canvas on screen at 9.3 s vs 6.3 s on the landing).
4. The map page is drawn entirely by JavaScript (about 60 modules), so nothing useful shows until they load; on desktop the brief header then jumps the page (layout shift 0.67–0.76).
5. Other data is also never cached or barely cached (ocean data 1.5 MB unpacked, reports, seafloor tiles, region files), and seafloor tiles at wide zoom reach 0.4–1.1 MB each, so even a repeat visit moves 12–17 MB.

**Top 10 proposals**

1. P1: Send the brief only the reef fields it uses (0.34 MB instead of 15.4 MB) and draw the outlines from the seafloor tiles already loaded. Needs G (published file).
2. P2: Run the protected-area check once when publishing, not in every browser (removes ~11 s of freezing), with a parity test first. Needs G.
3. P6: Load reef data only after the map is ready, or when the user opens ranking or the seafloor layer. Safe to build now.
4. P7: On slow connections, stop early and offer "load reef ranking on Wi-Fi" instead of silently spending 10 MB. Safe to build now.
5. P5: Give the reef file and seafloor tiles versioned names so browsers can keep them until they expire, with the small manifest still checked every time. Needs G (feed cache policy).
6. P4: As a quick step, round reef coordinates to 6 decimals (15.4 MB down to 4.8 MB) or 5 decimals (3.4 MB). Needs G (published file).
7. P10: Reserve space for the brief header and legend rows so the page stops jumping (CLS about 0.7 down to under 0.1). Safe to build now.
8. P8 + P9: Put the first screen (brief header, home-port summary) into the HTML, and show the last brief instantly from the device, then refresh it. Shell and local copy are safe to build now; new public port pages need G.
9. P13 + P12: Shrink seafloor tiles: generalise wide zooms to under 200 KB per tile, and use WebP for the raster seafloor (82–92 % smaller in the trial). Needs G (published tiles).
10. P34: Add a size and request-count budget to the existing fast PR check so a 15 MB file cannot slip in again (a nightly speed run needs the operator's OK). Size check is safe to build now.

---

## E. Limits of this baseline

* Phone numbers are emulation on this host (CPU 4× slowdown of a fast x86 CPU, network shaping in Chromium), not a
  real Android device; they are good for ranking causes, not for absolute promises.
* Service workers were blocked; a user who saved an offline pack has `/sw.js`, which is network-first for data
  and would not change the cold numbers.
* The private layers were measured on local, uncompressed, uncached test pages, with a synthetic wind grid and an
  old (2026-09-20) SST analysis; wind and SST timings are about load cost, not data freshness.
* The live site was redeployed during the measurement (see the note after A.3): six phone layer groups are on a newer
  app build than the rest.
* The phone live-site passes ran in sequential batches. A duplicate phone process overlapped the phone map-home runs for
  about two minutes before it was stopped; the third map-home run's values match runs 1 and 2 and were kept, and the
  phone-on-Wi-Fi pass was repeated alone afterwards. Group run counts are in `raw/summary.json` (`runs`).
* "ESTIMATED" gains are arithmetic on measured bytes and timings, not a measurement of the changed site. In section C a
  gain labelled MEASURED is a current cost or size observed here (or a size trial); every time or traffic saving that
  depends on a change not yet made is ESTIMATED.
* Content/interaction readiness was **not measured** (no check that map style, tiles or layer data are drawn, no tap
  test). The canvas-quiet proxy and TBT to that proxy are the only responsiveness figures; see A.1.
* Script time is an accumulated total; the earlier per-second duty-cycle figures were withdrawn (counter window longer
  than the settle window; ScriptDuration under CPU throttling unvalidated).
* Corrected after review of PR #1767 (head 18b31a97): inline `data:` URLs removed from request/byte/heaviest figures
  (3.86 → 3.58 MB for the local base-medium desktop cold runs); the readiness proxy relabelled; B1/P2/P5 figures
  restated as above.
