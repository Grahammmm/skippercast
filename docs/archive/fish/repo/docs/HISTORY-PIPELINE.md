> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/HISTORY-PIPELINE.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Buoy history pipeline

Implemented and live-collected October 1, 2026 Pacific time (October 2 UTC). This pipeline supplies recorded environmental context, not a calibrated fishing model or forecast correction.

## Actual collection and coverage

All **65 annual standard-meteorological archives** advertised by the two official station catalogs were fetched, hashed, parsed and checkpointed:

| Station | Official annual years collected | Current role |
| --- | --- | --- |
| 46215 Diablo Canyon | 2004–2025, 22 files | Local waves and surface water temperature; no wind/air-temperature record in the collected history |
| 46028 Cape San Martin | 1983–2025, 43 files | Offshore wind, gust, waves, air and surface water temperature; exposure differs from SLO nearshore |

The latest live artifact has 1,080 measured UTC-hour bins out of 1,081 requested bins per station (99.91% coverage), with a one-hour gap at the partially elapsed current edge of the window. This **does not mean every variable is complete**. Per-metric hourly counts show missing readings. The seasonal distributions retain each metric's count, expected calendar hours, coverage fraction, actual contributing years, raw sample count and quantiles. Individual annual archives can contain partial years or deployment gaps; missing periods remain absent. The successful final artifacts are roughly 600 KB. Sixty-five compressed annual files totaled approximately 12 MB, decoding to 81 MB; these receipts remain outside public assets.

Use `public/data/slo-history.json` as the website asset. Source links, bytes and SHA-256 hashes are public provenance; local filesystem locations and raw checkpoint files are not exposed. `generatedAt` dates the bundle, while recent observation clocks retain their original times. At initial collection both stations were fresh; this ages normally and does not promise ongoing refresh.

## Primary sources and meaning

- [46215 archive catalog](https://www.ndbc.noaa.gov/station_history.php?station=46215), [46028 archive catalog](https://www.ndbc.noaa.gov/station_history.php?station=46028). Discovery parses station-specific `hYYYY.txt.gz` links, not a fabricated year range. Missing years are not silently filled.
- Recent 45-day files: [46215](https://www.ndbc.noaa.gov/data/realtime2/46215.txt), [46028](https://www.ndbc.noaa.gov/data/realtime2/46028.txt).
- Annual original files: `https://www.ndbc.noaa.gov/data/historical/stdmet/{station}h{year}.txt.gz`.
- [NDBC data index](https://www.ndbc.noaa.gov/faq/dataindex.shtml): recent cumulative files are automated-QC observations; historical files are post-processed archives. Current-year monthly files and wave spectra are distinct products, not yet backfilled by this standard-meteorological annual pipeline. The previous month's QC file is generally posted around the fifteenth; recent records can later be corrected in archives.
- [Measurement descriptions](https://www.ndbc.noaa.gov/faq/measdes.shtml) establish UTC and source SI units, wave height as significant height and `DPD` as dominant period. Missing recent values use `MM`; historical sentinels vary by field.
- [NDBC format changes](https://www.ndbc.noaa.gov/faq/mods.shtml) document legacy schemas and the addition of explicit unit headers. The collector supports old hourly/two-digit-year records and modern minute records. The observed 46028/2000 file includes 2,800 rows lacking only its unused trailing TIDE column; these retain valid measured columns and increment `trailingMissingRows`. Truncation of required columns fails that row.
- [NDBC QC](https://www.ndbc.noaa.gov/faq/qc.shtml) distinguishes automated checks from archival review. This adapter adds parser/range checks; it does not invent per-row producer quality flags or claim independent instrument verification.

[NWS data policy](https://www.weather.gov/disclaimer/) allows use of its public information with original attribution, without implied endorsement or presenting modified content as official. Credit NOAA/NDBC; 46215 also credits the original CDIP/Scripps measurement program. Existing reviewed CDIP metadata permits unrestricted data redistribution. This import copies factual standard-met measurements and does not reuse logos, station photos or another publisher's presentation. New partner station types require original-producer rights review.

## Contracts and aggregation

`src/history-types.ts` defines `HistoryBundle`, `StationHistory`, `RecentHistory`, `HistoricalHour`, `MonthlyDistribution`, `HistorySource` and `HistoryQC`. `src/providers/history.ts` supplies parsing, index discovery, bounded fetch/decode, hashing, hourly aggregation, seasonal summaries and a small reusable `collectHistory(county)` binding. That live binding collects recent data plus the latest complete annual reference; the script builds the full discovered history used by this site's artifact.

The six metrics are `waterTempF`, `airTempF`, `windKnots`, `gustKnots`, `waveFt`, and `periodS`. UTC-hour means are calculated from **only valid samples**; each hour has raw sample count and per-metric counts. All hours receive equal weight in seasonal distributions, avoiding an artificial increase in influence after ten-minute sampling replaced hourly records. This is an arithmetic mean of reported dominant periods and reported gust values, not a spectral-wave calculation or each hour's worst gust. Do not use these descriptive history values as operating limits.

Monthly distributions pool actual UTC-hour means for the same calendar month across collected archive years. The p10/median/p90 use linear interpolation between sorted hourly values. Expected hours include leap years and missing archive intervals. Years with no valid observations for a metric do not become zero-valued data. `yearsWithData` exposes the actual contributors. One collected year is a **recorded year reference**; several years are **recorded seasonal history**, not a standardized climatology. Sensor changes, observing height, station relocations and temporal dependence prevent interpreting these as independent random trials. Current station coordinates are reference positions; historical deployments may differ within the station identity.

Recent history includes original first/last observed time, current staleness (>3 hours since the last valid measurement), observed/expected hours, maximum missing-hour run and sparse hourly values. There are no interpolated samples. Charts should draw gaps where timestamps skip or a metric is null. A full any-variable coverage fraction cannot be used as the completeness of every metric. The seasonality band is descriptive recorded context, not a forecast confidence interval, percentile-based catch probability or buoy forecast bias correction. Future forecasts may be compared only to prospective forecasts archived before their valid time; this retrospective history cannot establish that verification.

## Repeatable bounded backfill

For routine updates after the initial backfill, run `npm run refresh:history:recent`. This command uses the same reviewed `refreshRecentHistory` helper as the Worker, requests only the two recent NOAA files, and verifies that every annual baseline, archive catalog and non-recent source receipt is unchanged before publishing. It writes the attempt separately to `data/last-recent-history-refresh-attempt.json`. A complete outage leaves the public file bytes and generation clock untouched; a partial success retains the failed station's original observations. It requires an existing matching county snapshot. The backfill command below is for initial collection or an explicitly reviewed annual revision.

```sh
node --import tsx scripts/refresh-history.mjs --all-years --max-files=80 --concurrency=2
```

The command discovers current catalogs, fetches recent observations, checks an explicit annual-file budget, and uses two concurrent annual requests. Each request aborts at 15 seconds; compressed/raw response cap is 2 MB and decoded gzip cap is 16 MB. Index/recent failures and annual failures remain explicit. The artifact includes collected years separately from advertised available years. Without `--all-years`, only the latest complete annual file is selected for a small reference. `--county=...` supports reviewed county buoy configuration; there is no copied SLO station fallback for new counties.

`artifacts/buoy-history/{county}-checkpoint.json` tracks URL, role, year, original fetch time, hash, byte counts, parsing outcome and logical object key. Every successful raw receipt is content-addressed under `ndbc/stdmet/{station}/{year}/{sha256}.bin`. A resumed run verifies bytes against SHA-256 before reusing them. Corrupt/missing receipts are refetched. Failed entries are retried. Checkpoint and public output writes use temporary files plus atomic rename. `--revalidate` explicitly refetches annual archives when post-processing corrections should be checked. Cache reuse keeps original fetched times.

The command publishes a **local asset**, not cloud data or a running schedule. Raw receipt/checkpoint directories are ignored by Git. An annual archive can be copied to R2 using its logical object key without changing provenance, with its matching receipt and normalized schema version. No R2 uploader or credentials are configured here. For production: a separate bounded backfill job stores raw/hash/normalized annual shards in R2 and a D1 job checkpoint; hourly scheduled work refreshes recent observations and reuses the reviewed seasonal reference. Annual/index revision checks can run monthly. Avoid re-downloading decades for each visitor or each report refresh.

## Verification

Nine offline tests cover real index selection, SI conversion/unit changes, legacy years, documented missing trailing fields, sentinels, invalid/future dates, conflicting duplicates, hourly sampling normalization, seasonal coverage, gaps/stale observations, gzip/hash integrity and all-source failures. Tests do not contact NOAA. The full live collection fetched all advertised annual stdmet files with no resource failures, and type checks pass.

Read-only SkipperCast reuse review confirmed the same two verification stations and its distinction between prospective verification and environmental history in `docs/regional-intelligence.md`, `catalog/data-needs.json` and `regions/morro-bay/region.json`. No SkipperCast code, private trip logs or existing forecast-verification state was imported or modified.
