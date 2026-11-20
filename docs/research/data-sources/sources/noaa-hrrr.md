# NOAA HRRR 3 km weather model

- **id:** `noaa-hrrr`
- **Priority:** 3
- **Status:** can ingest now (free/open)
- **Test download (2026-11-19):** PASS
- **Provider:** NOAA NCEP; AWS bucket noaa-hrrr-bdp-pds; also served by Open-Meteo (model ncep_hrrr_conus)

## What it measures
Convection-allowing short-range weather: 10 m wind, gusts, visibility, precipitation, fog, cloud.

**Variables:** UGRD/VGRD 10 m, GUST surface, TMP 2 m, VIS, PRATE, TCDC and ~170 more fields per wrfsfc file

## Coverage and timing
- Resolution: 3 km Lambert grid
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): CONUS incl. Central Coast and nearshore waters
- Temporal resolution: Hourly output, new run every hour
- Latency: ~1-1.5 h after cycle
- Forecast horizon: 18 h (48 h for 00/06/12/18Z)

## Format, licence, cost
- Format: GRIB2 with .idx sidecar (byte-range fetch per variable) / JSON via Open-Meteo
- Licence / attribution: NOAA public domain. Open-Meteo route: same terms as SkipperCast's existing open-meteo-api entry (CC BY 4.0; free tier non-commercial).
- Cost: Free

## Endpoints
- https://registry.opendata.aws/noaa-hrrr-pds/
- https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcfFF.grib2 (+ .idx)
- https://api.open-meteo.com/v1/forecast?models=ncep_hrrr_conus

## Auth
None

**Rate limits:** S3: none. Open-Meteo: free tier 10,000 calls/day (their published limit) — reuse SkipperCast's existing Open-Meteo budget.

## Who uses it
- Apps: Windy; PredictWind; Buoyweather (NAM + HRRR); SkeeterCast
- SkipperCast layer: Wind / Weather (nearshore, short-range detail around points and bays)

## Connect and download
```bash
T=$(date -u +%Y%m%d); U=https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.$T/conus/hrrr.t00z.wrfsfcf01.grib2
curl -s $U.idx | grep -E 'UGRD:10 m above|VGRD:10 m above'      # gives byte offsets
curl -r <start_of_UGRD>-<byte_before_next_after_VGRD> -o hrrr_wind10m.grib2 $U
python -c "import xarray as xr; print(xr.open_dataset('hrrr_wind10m.grib2', engine='cfgrib'))"
# Easiest route (existing adapter):
curl 'https://api.open-meteo.com/v1/forecast?latitude=35.37&longitude=-120.86&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m&models=ncep_hrrr_conus&forecast_days=2&wind_speed_unit=kn'
```

**Cadence:** Hourly (point forecasts via Open-Meteo); gridded GRIB every 3 h is enough for a map layer.

**Pipeline fit:** Fastest: add 'ncep_hrrr_conus' to the model list of the existing open-meteo adapter (src/skippercast/forecast). Gridded map layer: byte-range fetch like the existing GFS_AWS path in src/skippercast/forecast/fetch.py.

**Sample on box:** samples/hrrr_20261119_t00z_f01_wind10m.grib2 (4.8 MB, u10/v10 CONUS) and samples/openmeteo_hrrr_morrobay.json (48 h, knots)
