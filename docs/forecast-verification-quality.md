# Local forecast verification

SkipperCast measures the errors of forecasts it actually collected before their valid time. This pipeline does not reconstruct old forecasts from today's weather API. It reports evidence about particular models, stations and forecast horizons; it does not calibrate catch probability, certify a comfortable trip or apply an automatic forecast correction.

`src/skippercast/pipeline/verification.py` implements `prospective-v2`. Existing version-one archive rows remain immutable and readable; storage migrates to a small version-two manifest with bounded gzip shards, described below. New forecast rows record station and grid coordinates, model availability/modification clocks, native timestep and physical anemometer height. Observation rows add actual retrieval time, source, provisional quality and measurement basis. Missing legacy metadata stays unknown. A later station manifest can locate a legacy station/grid comparison, but cannot recover its historical observation quality or collection receipt.

## What is collected

| Input | Role and qualification |
|---|---|
| NOAA GFS / ECMWF IFS, explicitly selected through Open-Meteo | Prospective 10 m wind speed, actual returned grid, initialization, acquisition and published data end. |
| NOAA GFS Wave / ECMWF WAM, explicitly selected through Open-Meteo | Prospective significant wave height. Directional components, period and currents require their own future verification contracts; these errors do not verify them. |
| NDBC standard realtime observations | Significant wave height, and raw wind only where configured. These observations pass provider realtime automated checks, not the stronger final archive review. |
| NDBC `derived2/<station>.dmv` WSPD10 | Optional provider-derived 10 m wind estimate. The adapter preserves its units and method; it never performs its own height adjustment. Sensor height remains recorded separately from the 10 m reference height. |

The adjusted wind adapter is enabled for 46028 in the central regions and 46053, 46054, 46025 and 46086 in Southern California. Derived winds have adjustment and source-rounding uncertainty. They are a more appropriate reference for a 10 m forecast than pretending a 3–4 m buoy anemometer directly measures the same quantity. If a configured derived source fails, the pipeline records the failure; it does not silently substitute raw wind. [NDBC measurement definitions](https://www.ndbc.noaa.gov/faq/measdes.shtml), [NDBC derived-data directory](https://www.ndbc.noaa.gov/data/derived2/), [NDBC realtime versus archive quality control](https://www.ndbc.noaa.gov/faq/qc.shtml).

## Time, position and sample safeguards

1. A forecast must be acquired after initialization and before its valid time. Provider availability must not be later than acquisition. A documented ten-minute provider update settling interval is withheld from the prospective archive. Acquisition is never called model initialization or issue time. The existing collector checks metadata again after collecting the response. Provider metadata still cannot independently certify the run of every returned value. [Open-Meteo timing and consistency documentation](https://open-meteo.com/en/docs/model-updates).
2. Keep the earliest acquired value for a physical model/run/station/valid-time/variable sample. Alternative row IDs and repeated polling do not increase the matched count. Forecast revisions never overwrite their earlier archived values. Preserve the prior conditions branch before every refresh.
3. Convert explicit source units, reject non-finite numbers, booleans, negative scalar speeds/heights, missing sentinels, bad quality states and inconsistent raw gusts. Broad gross-error bounds reject implausible observation values; they are not comfort thresholds. Zero remains a real measurement. NDBC provisional quality is not relabeled final. [NDBC automated QC handbook](https://www.ndbc.noaa.gov/publications/NDBCHandbookofAutomatedDataQualityControl2023.pdf).
4. Compare the actual model grid to the configured station using great-circle distance. The default 30 km limit is a SkipperCast screening policy for these regional grids, not a NOAA accuracy guarantee. A reviewed station may specify `max_grid_distance_km`. Distance alone cannot resolve island shelter, coastline orientation, bathymetry or a moving buoy. Missing geometry permits only explicitly limited legacy reporting.
5. Match observations within 30 minutes, selecting the nearest and preferring the earlier observation on a tie. The observation must itself postdate forecast acquisition. A half-hour observation fitting two hours is used only once within the same model run. Different runs may legitimately verify against the same weather hour, so the report also counts distinct valid times, days and runs.
6. Preserve documented observation revisions and their actual retrieval times. Revisions may change retrospective verification metrics; they cannot change the original forecast or invent an earlier observation receipt. The source's latest observation revision is used, with revision count and any changed reference basis recorded.
7. Coverage denominators include matured, spatially eligible forecasts, including those with no matching observation. Future forecasts do not count as failures. A valid hour whose 30-minute match window has not finished is pending unless already matched. A missing match has null errors, never zero error.

These are explicit operational choices, not claims that each pair is an independent scientific experiment. Hourly API values can be interpolated from a coarser native timestep; the native step is retained. Several buoys or adjacent hours may share the same storm and model grid.

## Error, support and comparison

Bias is forecast minus observation; a positive value means overprediction. MAE is average absolute error. RMSE gives more weight to large errors. All retain the measured quantity's units (knots or feet). NOAA's verification guidance distinguishes these error measures from reference-based skill and probabilistic calibration. [NWS verification refresher](https://www.weather.gov/media/owp/oh/rfcdev/docs/JDemargne_verification_refresher_RFCworkshop_Nov08_Part1.pdf).

Results stay separate by station, model, variable and initialization lead: 0–12, 12–24, 24–48, 48–72 and 72–168 hours. Only the final upper boundary is inclusive. Acquisition lead is separately reported: a forecast initialized 12 hours ago and acquired an hour before its valid time is not a 12-hour advance warning delivered to this app.

Local descriptive support requires all of:

- At least 30 **distinct valid times**, seven UTC dates and three distinct initialization cycles.
- At least 70% matching coverage for matured, spatially eligible forecasts.
- Known grid/station distance, recognized observation quality and comparable measurement height for wind.
- Current collection: a relevant observation within three hours and an archived forecast acquisition within 36 hours.

These thresholds are product evidence gates, not a statistical significance test. Adequate history does not erase the limitations of a regional grid. A seven-day early sample does not capture a seasonal climatology. Model-to-model comparisons use the **same station, initialization, valid time and observation**. They report the common-case fraction of each model's available matched sample. A lower-error model is named only after support thresholds and at least 70% common-case coverage; this is descriptive, not a significant or permanent model winner. Raw unequal model sample averages must not be used as a leaderboard.

No predictive probability, confidence interval, ensemble calibration or adaptive weighting is fitted in this release. The next defensible step would use a substantially longer archive, prespecified seasonal/lead strata, a training/validation split by weather episode and untouched future evaluation. Vessel comfort feedback would need its own outcome and exposure model; buoy wave-height error alone cannot calibrate a Parker's comfort rating.

## Public output contract

`intelligence.json.verification` retains `status`, `groups`, `archived_forecasts`, `matched_samples` and `limitations` for existing readers. It adds:

| Field | Meaning |
|---|---|
| `method_version` | `prospective-v2`; storage supports v1 JSON and v2 gzip-shard manifests. |
| `summary` | Plain-language status/action, supported groups, distinct station/variable/valid-time count, matched coverage, actual collection ages, archive horizon, and explicit `calibrated_probability: false`. |
| `groups[].distinct_valid_times` | Repeated forecast runs do not create additional weather hours. |
| `groups[].eligible_forecasts`, `unmatched_forecasts`, `future_forecasts`, `awaiting_observations` | Separate missing evidence from future/pending samples. |
| `groups[].spatial_match` | Grid-distance range, unknown geometry count and excluded forecasts. |
| `groups[].observation_quality`, `measurement_comparison` | Distinguish provisional measurements, provider-derived 10 m estimates and unadjusted raw wind. |
| `groups[].collection` | Station observation age, model acquisition age, actual populated forecast end and freshness. |
| `groups[].acquisition_lead_hours`, `match_time_offset_minutes` | Actual delivery lead and temporal mismatch ranges. |
| `groups[].support` | Actionable evidence status and whether current descriptive model comparison is supported. |
| `comparisons` | Matched common-case empirical errors, sample support and coverage; no calibrated probabilities. |
| `diagnostics`, `collection_issues` | Duplicate, rejected, distant, out-of-horizon and acquisition/provider failures. |

Errors are null when no match exists. Coverage is null when no forecast is yet due. An empty archive says “collecting history,” not “zero error.” A forecast caught inside the documented provider update settling window is deferred with its reason and retried on a later scheduled collection; it does not enter the archive. This expected coverage gap does not fail an otherwise successful publication. Invalid clocks, malformed data, failed access and corrupt archives remain operational failures. Readers must handle both v1 feeds during deployment and v2 feeds after the first refreshed conditions run.

## Repeatable regional rollout

Add reviewed station coordinates, source URL, variables and physical sensor heights in `regions/<id>/region.json`. Use `wind_verification: "ndbc-derived-10m"` only after verifying that station's official derived product. A newly enabled variable begins archiving **future** forecasts; historical observations are not used to invent historical predictions. Other height-adjusted providers require an explicit adapter, validation and a declared method.

The existing twice-hourly live conditions job fetches these observations, preserves the public prior state, performs verification and atomically publishes the regional feed. The archive retains 30 days of public environmental samples. Never copy private trip logs into this archive. Missing source access or an attribution/settling failure is recorded in pipeline health. The UI can show descriptive errors immediately but must retain the evidence gate and source-age limitations.

## Archive storage and publication

`verification_archive.py` reads both the original `{schema_version: 1, forecasts: [...], observations: [...]}` and the new manifest. The returned in-memory shape remains version one, keeping the matching logic independent of storage. A first write migrates the old archive without dropping forecasts. It also converts the prior generation into shards, avoiding another large legacy JSON file.

The version-two `verification-state.json` has `storage: "gzip-shards-v1"`, region identity, total row counts, generation time and shard entries. Immutable filenames include the SHA-256 of deterministic gzip bytes. Forecasts are partitioned by station, model and initialization day; observations by station and observation day. Each shard has at most 2,000 rows and **2 MiB expanded JSON**, with an explicit compressed-byte bound. Large groups split deterministically. No subsampling, averaging or thinning is introduced. Bounded expansion, checksums, region/model/station/date identity, counts and safe relative paths are verified on every read. Missing or corrupt shards fail the run; they cannot silently create an empty archive.

Both `verification-state.json` and `verification-state.previous.json` reference complete generations. Publication writes all immutable shards before switching manifests. Only after both references validate does `prune_archive(region_directory)` remove unreferenced, strictly named archive blobs. Unmanaged files are left alone. An archive write must succeed before a new regional `intelligence.json` is written. The workflow's existing atomic Git publication does not run if collection fails, so prior app feeds remain published.

After collecting a fresh output directory, the publication workflow must copy the complete region tree, including `verification-archive/` and both manifests, and then prune the **destination** region directory. A plain recursive copy leaves obsolete blobs behind. For example:

```python
from pathlib import Path
from skippercast.pipeline.verification_archive import prune_archive
for region_dir in Path('var/live-published/regions').iterdir():
    if region_dir.is_dir():
        prune_archive(region_dir)
```

Copy and prune happen before the single public Git commit. Include `src/skippercast/pipeline/verification_archive.py` in workflow path triggers. The current and previous manifest generations must travel together; a manifest alone is not a backup. This removes the single-file growth limit while retaining a straightforward future move to object storage. Wider coastal coverage still requires monitoring total branch size and collection time; gzip sharding does not make those costs disappear.

Regression checks:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_forecast_verification.py
PYTHONPATH=src python -m unittest discover -s tests -p test_pipeline_intelligence.py
PYTHONPATH=src python -m unittest discover -s tests -p test_verification_archive.py
```

As a dated baseline, the public conditions snapshot generated **2026-09-22 16:29:49 UTC** contained 3,018 forecast rows and 132 matches in each central region, but only one observed day. Southern California had 2,212 archived wave forecasts and 28 model/buoy matches, representing only two valid hours at seven buoys. Those counts did not justify a model winner. V2 reprocessing preserved the 132/28 actual matches while revealing only 36/14 distinct station/variable valid-time cases, respectively. The newly enabled Southern wind archive starts prospectively on deployment.
