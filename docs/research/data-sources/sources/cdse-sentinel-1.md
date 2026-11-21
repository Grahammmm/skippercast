# Sentinel-1 SAR imagery (Copernicus Data Space)

- **id:** `cdse-sentinel-1`
- **Priority:** 19
- **Status:** needs registration/API key (free)
- **Test download (2026-11-19):** PARTIAL - STAC search works without login; download needs account
- **Provider:** ESA / Copernicus Data Space Ecosystem

## What it measures
Radar backscatter images through cloud and at night: vessels, oil platforms, slicks, wind streaks, fronts.

**Variables:** GRD VV/VH backscatter (COG)

## Coverage and timing
- Resolution: 10 m (IW GRD)
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Central Coast imaged every few days (S1C/S1D; latest scene 2026-11-19 01:50Z)
- Temporal resolution: Every 2-6 days
- Latency: Hours
- Forecast horizon: Observation only

## Format, licence, cost
- Format: Cloud-optimised GeoTIFF (COG) in SAFE
- Licence / attribution: Copernicus open licence: free, commercial use with attribution ('Contains modified Copernicus Sentinel data <year>').
- Cost: Free

## Endpoints
- https://stac.dataspace.copernicus.eu/v1/collections/sentinel-1-grd
- https://stac.dataspace.copernicus.eu/v1/search
- https://dataspace.copernicus.eu/

## Auth
Free account at https://dataspace.copernicus.eu/ ; get an OAuth token (client credentials) for S3/HTTPS downloads.

**Rate limits:** CDSE quotas apply per account (see their docs).

## Who uses it
- Apps: BlueFronts (Sentinel-1 imagery for rigs)
- SkipperCast layer: Satellite imagery (raw base), vessel/rig detection

## Connect and download
```bash
curl "https://stac.dataspace.copernicus.eu/v1/search?collections=sentinel-1-grd&bbox=-123.5,34,-119.5,37&limit=5&sortby=-datetime"
# then download assets with a CDSE token
```

**Cadence:** On new scene.

**Pipeline fit:** Low priority; large files. SkipperCast already has AIS for vessels.

**Sample on box:** samples/cdse_s1_stac_search.json (metadata only)
