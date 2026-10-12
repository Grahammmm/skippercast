> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `research/spatial-review.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Spatial source review

Verified October 1, 2026. Implementation: `src/providers/spatial.ts`; offline checks: `tests/spatial.test.ts`; live receipt: `research/spatial-live-validation.json`.

## Sea surface temperature

[NASA JPL MUR v4.1 product](https://podaac.jpl.nasa.gov/dataset/MUR-JPL-L4-GLOB-v4.1) is the original producer's daily merged Level 4 foundation temperature analysis. [NOAA CoastWatch ERDDAP metadata](https://coastwatch.pfeg.noaa.gov/erddap/info/jplMURSST41/index.html) provides public CSV access, native 0.01-degree spacing, open-sea/land/lake/ice masks and estimated analysis-error standard deviation in Celsius. Satellite and in-situ inputs are interpolated into an analysis. Grid spacing does not establish independent measurements at every grid point or actual nearshore visibility, bottom temperature or currents.

We request every second native grid point: 0.02-degree sampled spacing, approximately 2.2 km north/south and 1.8 km east/west at SLO latitude. The map should label **Surface temperature analysis**, show `analysedAt` and uncertainty, and avoid implying a live buoy reading or forecast. Nominal field reference time is not a publication time. No `issuedAt` is invented from that reference clock or HTTP headers.

The NOAA metadata permits free use and redistribution under JPL PO.DAAC policy, with JPL/NASA MEaSUREs acknowledgment. Production attribution should credit NASA JPL, NASA MEaSUREs and NOAA CoastWatch delivery. Dataset access requires no key. Daily fetch is sufficient; the provider says the most recent seven days are usually revised daily. Policy rejects nominal analyses older than 72 hours or over five minutes into the future. Parsed dates require valid UTC calendar dates. All raw rows must form the complete requested Cartesian lattice; truncated, duplicate, off-grid and mixed-date rows fail. Only exact open-sea mask 1 and valid non-fill temperature/error survive. Blank values remain missing. Temperature uses Celsius-to-Fahrenheit offset; uncertainty uses scale only. Large valid uncertainty is preserved.

Live validation accepted the September 30 09:00 UTC field, 2,990 raw lattice rows and 1,971 sea samples; omitted rows were masked or unavailable. This spatial mask cannot guarantee that every sampled coastal pixel represents water at the swimmer's exact entry.

## Protected areas

[CDFW DS582 metadata](https://filelib.wildlife.ca.gov/public/BDB/GIS/BIOS/metadata/DS0582.html) explicitly licenses the GIS boundaries under CC BY 4.0 and credits the California Department of Fish and Wildlife Marine Region GIS Lab. [The public CDFW feature service](https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0) delivers the data. Source metadata revision is March 1, 2023 and export/project processing dates are January 9, 2024; neither is a current legal verification date. As-needed updates warrant a weekly refresh and a separately maintained current regulation link.

The county query uses a WGS84 envelope and requests full GeoJSON in EPSG4326; eight SLO-region features matched the separate count query. Count mismatches, transfer limits, duplicate identities, missing names, malformed/unclosed/degenerate rings, invalid coordinates and wholly unrelated envelopes fail. Full intersecting polygons legitimately extend beyond the query box. This is a display representation: exact legal definitions are in California Code of Regulations Title 14 Section 632. DS582 is not a navigation source or a complete species/season/method rules engine. Fetch time is retained; no legal effective time is invented.

## Verification and limits

Eight offline tests exercise units/uncertainty, sea masks, blank/fill readings, schema changes, duplicate/truncated/off-grid coverage, invalid/future/stale/mixed times, protected feature counts and geometry, provider failure and independent partial availability. A failed layer stays absent with its own error source, allowing the other validated layer to remain available. Requests have 15-second aborts and a 2 MB response cap. Root should retain attribution and analysis clocks in the map controls; access may fail without affecting the core report.
