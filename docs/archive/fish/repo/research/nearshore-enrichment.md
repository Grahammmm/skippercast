> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `research/nearshore-enrichment.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Nearshore and beach-status enrichment

Implemented and live verified October 1, 2026. `src/providers/enrichment.ts` collects official nearshore wave guidance and county water-contact status independently from the core offshore forecast. The [source registry](source-registry.md) contains the broader producer and licensing audit.

## CDIP SLO nearshore guidance

The [official CDIP county page](https://cdip.ucsd.edu/mops/?moplist=San_Luis_Obispo_County&nav=documents&sub=faq) links these named model output points. Direct `.das` metadata and `.ascii` data returned HTTP200 for every binding.

| CDIP ID | Name | Assigned report area | Latitude | Longitude |
| --- | --- | --- | --- | --- |
| SL097 | Pismo Beach Pier | South | 35.13593 | −120.66090 |
| SL165 | Port San Luis | South | 35.16219 | −120.74368 |
| SL345 | Morro Rock | Central | 35.36503 | −120.87659 |
| SL400 | Cayucos Pier | Central | 35.43385 | −120.91185 |
| SL552 | San Simeon Beach | North | 35.58976 | −121.13583 |

Example source:

```text
https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/model/MOP_alongshore/SL345_forecast.nc.das
https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/model/MOP_alongshore/SL345_forecast.nc.ascii?waveTime,waveHs,waveTp,waveDp,waveFlagPrimary,waveFlagSecondary,metaLatitude,metaLongitude,metaWaterDepth,metaSiteLabel
```

The variable definitions come from the model metadata: significant wave height in meters, peak spectral wave period in seconds, and peak **from** direction in degrees true. The collector converts height to feet, keeps original valid timestamps and does not generate hourly samples. During verification, files had 80 samples at three-hour spacing; the returned report subset contains about 25 samples through 72 hours, including the most recent prior sample within three hours. Model guidance is not an observation of breaking waves or an entrance clearance.

The model publisher supplies explicit `date_issued`; this is copied into `issuedAt`. Missing `date_issued` stays null. Dataset creation, modification, HTTP Last-Modified and fetch time are never substituted. A publisher issue time does not independently establish the underlying wave-model initialization time; `modelInputCycleAt` stays null. File-level valid-through time is retained separately from the report's selected sample window. Issue timestamps older than 48 hours produce `freshness: stale`; absent timestamps produce `unknown`. Both remain distinguishable from a failed request.

The adapter requires the current documented metadata unit/direction/QC contract. Only primary `good` samples with usable secondary flags are accepted. Questionable, bad, missing and not-evaluated values remain null. `insufficient_input` masks all displayed values; `low_energy` retains good height while masking peak period/direction. Fill values and values outside metadata valid ranges remain null. Missing arrays, incomplete declarations, mismatched site identity/coordinates, changed units or nonmonotonic timestamps fail the individual source. Adjacent samples are not bridged with invented values.

Source metadata explicitly permits use and redistribution without restriction. Attribute Scripps CDIP and link the source. Point water depth is metadata describing the model output location relative to sea level, with no specific vertical datum supplied; it must not be labeled MLLW or treated as mapped bottom topography.

## Official SLO beach water-contact health

The [county program page](https://www.slocounty.ca.gov/departments/slo-health/public-health/environmental-health-services/all-environmental-health-services/recreational-health/beach-water-quality-monitoring) links SurfSafeSLO. Its dashboard references the county webmap, which exposes this public view:

```text
https://services6.arcgis.com/M6e56DqzbdJf20YO/arcgis/rest/services/SurfSafeSLO_Public_View/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=json
https://services6.arcgis.com/M6e56DqzbdJf20YO/arcgis/rest/services/SurfSafeSLO_Public_View/FeatureServer/0/query?where=1%3D1&returnCountOnly=true&f=json
```

The live view returned 19 sites, including health-advisory records. This can provide map status at the actual county sampling location, rather than only a link to a generic county page. The collector preserves `Status`, `AdvisoryMessage`, `AdvisoryNotes`, station ID/name and geometry. Some `Longitude` attributes are null even though geometry is valid; geometry returned in the requested EPSG:4326 is authoritative for placement. Nearest report-area assignment is editorial grouping, not an extension of a site's advisory footprint.

The public view has **no sample or advisory-effective timestamp**. Every `sampledAt` is null and `sampleDateAvailable` false. Display “Status checked [fetch time]; sample date unavailable.” Do not label it freshly sampled, extrapolate a sampling-site status along the whole coast or treat beach health as underwater visibility. The county describes weekly bacterial sampling and additional rain/sewage notifications. The adapter refuses transfer-limit truncation, count mismatches, duplicates, invalid CRS/coordinates and source errors. An empty or failed response never means all beaches are open.

The exact dataset's blanket commercial redistribution license was not established. This initial use consists of concise factual status, county attribution and a direct official link; images, dashboard design and full database republication are not included. Recheck terms before adding new uses.

## Runtime, tests and integration

All calls use standard `fetch`, a 12-second abort deadline, identifying User-Agent and a 750 KB response cap. Each CDIP source fetches two small text resources; the county source fetches records plus count. Independent calls use `Promise.allSettled`. Failed sites stay in `nearshore` with empty hours and `availability: error`, and have corresponding source errors. Beach failures return no status points with an explicit source error. Unconfigured counties return pending enrichment rather than SLO data under another county's name.

Six offline tests exercise native clocks, no issue-time substitution, units, quality/fill masks, truncation, source contract changes, correct geometry, missing sample dates, complete-count validation and failure behavior. `npm run check` and all enrichment tests passed after implementation. The live receipt is [enrichment-live-validation.json](enrichment-live-validation.json).

Integrate by calling `collectEnrichment(county)` alongside the core collector and attaching its `nearshore`, `waterQuality` and source records to the saved report. Report type/UI/storage integration belongs to the main implementation. Keep model sites and beach health sites as independently selectable layers. Charts use original sample times; a map point card should name its model site, sample time, source issue time, source freshness and forecast status. Hide unavailable values, preserve gaps and show explicit failed-source states. No current vectors or numeric dive visibility are produced by this enrichment.
