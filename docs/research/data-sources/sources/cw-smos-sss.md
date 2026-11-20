# SMOS satellite sea-surface salinity

- **id:** `cw-smos-sss`
- **Priority:** 16
- **Status:** can ingest now (free/open), low value
- **Test download (2026-11-19):** PASS
- **Provider:** ESA SMOS via NOAA CoastWatch (PFEG ERDDAP)

## What it measures
Sea surface salinity from L-band radiometer.

**Variables:** sss, sss_dif

## Coverage and timing
- Resolution: 0.25 deg
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global, but land contamination masks ~40-60 km from the coast
- Temporal resolution: Daily / 3-day
- Latency: 2 days
- Forecast horizon: Observation only

## Format, licence, cost
- Format: NetCDF via ERDDAP
- Licence / attribution: NOAA/ESA free (dataset licence text).
- Cost: Free

## Endpoints
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/coastwatchSMOSv662SSS1day.html
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/coastwatchSMOSv662SSS3day.html

## Auth
None

**Rate limits:** As PFEG ERDDAP.

## Who uses it
- Apps: Fishare (salinity); Salty Offshore (salinity)
- SkipperCast layer: Salinity (offshore only)

## Connect and download
```bash
curl -g -o sss.nc 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/coastwatchSMOSv662SSS3day.nc?sss[(last)][(0.0)][(34.0):1:(37.0)][(-123.5):1:(-119.5)]'
```

**Cadence:** Daily.

**Pipeline fit:** erddap-grid; only 1% of the Central Coast box had data in the test. Prefer CMEMS/HYCOM model salinity for the map.

**Sample on box:** samples/coastwatchSMOSv662SSS1day_sss_centralcoast.nc (32.2-33.0 psu, 1% valid)
