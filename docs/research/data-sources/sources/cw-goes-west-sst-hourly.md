# GOES-West (GOES-18) ACSPO hourly SST + fronts

- **id:** `cw-goes-west-sst-hourly`
- **Priority:** 1
- **Status:** can ingest now (free/open)
- **Test download (2026-11-19):** PASS
- **Provider:** NOAA NESDIS STAR / CoastWatch, served by NOAA CoastWatch West Coast Node (PFEG) ERDDAP

## What it measures
Observed sub-skin sea surface temperature from geostationary GOES-18 ABI, every hour, cloud-masked.

**Variables:** sea_surface_temperature (degC), quality_level, l2p_flags, sses_bias, sses_standard_deviation, dt_analysis, or_number_of_pixels, satellite_zenith_angle

## Coverage and timing
- Resolution: 0.02 deg (~2 km) grid
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): GOES-West disk, covers all of California. Central Coast fully inside.
- Temporal resolution: Hourly
- Latency: Last time stamp 2026-11-19T14:00Z when read at about 18:00Z, so roughly 2-4 h
- Forecast horizon: Observation only (no forecast)

## Format, licence, cost
- Format: NetCDF / CSV / PNG via ERDDAP griddap
- Licence / attribution: GHRSST: free and open. Credit 'NOAA NESDIS STAR / CoastWatch, GOES-18 ACSPO'.
- Cost: Free

## Endpoints
- https://coastwatch.pfeg.noaa.gov/erddap/info/goes_west/index.html
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/goes_west.html
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/goes_west_Lon0360.html

## Auth
None

**Rate limits:** ERDDAP has no published hard quota. Keep requests small (one bbox, one time step); this node returned HTTP 503 on another dataset during testing, so retry with backoff.

## Who uses it
- Apps: BigBlue (hourly GOES SST); Fishare (GOES hourly passes); SkeeterCast (GOES-19 imagery, east coast); Salty Offshore (GHRSST SST)
- SkipperCast layer: SST (hourly observed, fills the gap between daily MUR / Geo-Polar analyses); also front detection

## Connect and download
```bash
# Latest hour, Central Coast. Latitude is stored north-to-south, so ask (37):(34)
curl -g -o goes_west_latest.nc 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/goes_west.nc?sea_surface_temperature[(last)][(37.0):1:(34.0)][(-123.5):1:(-119.5)]'
# Last 24 hours, every hour, 0.04 deg (stride 2)
curl -g -o goes_west_24h.nc 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/goes_west.nc?sea_surface_temperature[(last-23):1:(last)][(37.0):2:(34.0)][(-123.5):2:(-119.5)]'
# python
import xarray as xr
ds = xr.open_dataset('goes_west_latest.nc'); sst = ds.sea_surface_temperature.where(ds.quality_level>=4) if 'quality_level' in ds else ds.sea_surface_temperature
```

**Cadence:** Hourly at :20 past; keep a rolling 72 h; build a 'last cloud-free value' composite every hour.

**Pipeline fit:** Fits the existing 'erddap-grid' adapter (same as mur-sst / modis-chlorophyll). Add a catalog/sources.json entry with adapter erddap-grid, dataset goes_west, allowed_hosts coastwatch.pfeg.noaa.gov. Data rights row needed in docs/legal/data-rights-register.md.

**Sample on box:** samples/goes_west_sea_surface_temperature_centralcoast.nc (130 KB; 2026-11-19T14:00Z; 17.2-21.1 degC; only 1% of cells valid because it was a cloudy night. Expect gaps; composite over hours.)
