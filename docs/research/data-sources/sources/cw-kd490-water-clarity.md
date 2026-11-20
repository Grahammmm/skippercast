# Water clarity Kd490 (MODIS West US 0.0125 deg, VIIRS 4 km, DINEOF gap-filled 2 km)

- **id:** `cw-kd490-water-clarity`
- **Priority:** 9
- **Status:** can ingest now (free/open)
- **Test download (2026-11-19):** PASS
- **Provider:** NOAA CoastWatch (PFEG ERDDAP)

## What it measures
Diffuse attenuation at 490 nm: how fast light fades = water clarity / 'blue vs green water'.

**Variables:** k490 (erdMWk4901day), kd_490 (nesdisVHNkd490Daily, noaacwNPPN20S3AkdSCIDINEOF2kmDaily)

## Coverage and timing
- Resolution: 0.0125 deg (~1.4 km) MODIS West US; 4 km VIIRS; 2 km gap-filled
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): US West Coast / global; Central Coast
- Temporal resolution: Daily (also 3/8/14-day composites erdMWk4903day, erdMWk4908day)
- Latency: MODIS 2026-11-17 (2 d); VIIRS 2026-11-12 (7 d); DINEOF 2026-11-05 (14 d) when read 2026-11-19
- Forecast horizon: Observation only

## Format, licence, cost
- Format: NetCDF via ERDDAP
- Licence / attribution: NOAA: free to use and redistribute (dataset licence text).
- Cost: Free

## Endpoints
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/erdMWk4901day.html
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/erdMWk4903day.html
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisVHNkd490Daily.html
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/noaacwNPPN20S3AkdSCIDINEOF2kmDaily.html

## Auth
None

**Rate limits:** As PFEG ERDDAP.

## Who uses it
- Apps: Salty Offshore (water clarity); SatFish / RipCharts / ROFFS show clarity layers without credits (unverified source)
- SkipperCast layer: Chlorophyll / water-colour family (clarity)

## Connect and download
```bash
# erdMWk4901day has an altitude dim and 0-360 longitudes
curl -g -o k490.nc 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/erdMWk4903day.nc?k490[(last)][(0.0)][(34.0):1:(37.0)][(236.5):1:(240.5)]'
curl -g -o kd490_viirs.nc 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisVHNkd490Daily.nc?kd_490[(last)][(0.0)][(34.0):1:(37.0)][(-123.5):1:(-119.5)]'
```

**Cadence:** Daily; use the 3-day composite for display (daily is often fully clouded).

**Pipeline fit:** Existing 'erddap-grid' adapter; new catalog entries only.

**Sample on box:** samples/erdMWk4901day_k490_centralcoast.nc (2026-11-17, 100% cloud) and samples/nesdisVHNkd490Daily_kd_490_centralcoast.nc (2026-11-12, 0.02-1.68 m^-1, 8% valid)
