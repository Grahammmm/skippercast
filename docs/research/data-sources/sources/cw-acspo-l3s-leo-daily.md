# NOAA ACSPO L3S-LEO daily super-collated SST (VIIRS + AVHRR)

- **id:** `cw-acspo-l3s-leo-daily`
- **Priority:** 2
- **Status:** can ingest now (free/open); already a repo candidate
- **Test download (2026-11-19):** PASS
- **Provider:** NOAA NESDIS STAR; mirrored on CoastWatch PFEG ERDDAP

## What it measures
Observed daily SST merged from all polar orbiters (S-NPP, NOAA-20/21 VIIRS, MetOp AVHRR), with thermal fronts.

**Variables:** sea_surface_temperature (degC), sses_bias, sses_standard_deviation, l2p_flags, l3s_flags, sst_count, quality_level, sst_source

## Coverage and timing
- Resolution: 0.02 deg (~2 km)
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; Central Coast fully covered
- Temporal resolution: Daily (day+night collated)
- Latency: Last time 2026-11-14T12:00Z when read 2026-11-19, so about 4-5 days
- Forecast horizon: Observation only

## Format, licence, cost
- Format: NetCDF via ERDDAP
- Licence / attribution: GHRSST free and open (NOAA). Credit NOAA/NESDIS/STAR ACSPO.
- Cost: Free

## Endpoints
- https://coastwatch.pfeg.noaa.gov/erddap/info/noaacwLEOACSPOSSTL3SnrtCDaily/index.html
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/noaacwLEOACSPOSSTL3SnrtCDaily.html
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/noaacwLEOACSPOSSTL3SCWeeklyNRT.html (7-day composite)

## Auth
None

**Rate limits:** As for PFEG ERDDAP above.

## Who uses it
- Apps: FishTrack (AVHRR SST); Fishare (VIIRS/AVHRR passes, last 72 h); BigBlue (VIIRS/AVHRR); Salty Offshore (GHRSST)
- SkipperCast layer: SST (sharp observed field for fronts; 'chart-room' SST next to MUR)

## Connect and download
```bash
curl -g -o acspo_daily.nc 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/noaacwLEOACSPOSSTL3SnrtCDaily.nc?sea_surface_temperature[(last)][(37.0):1:(34.0)][(-123.5):1:(-119.5)]'
```

**Cadence:** Daily, poll at 12:00 and 20:00 PT.

**Pipeline fit:** The repo already has catalog/candidates/noaa-acspo-l3s-leo-daily.json and a review (adopt-with-limits, 2026-10-23). That review logged HTTP 404s from coastwatch.noaa.gov and AOML. The PFEG mirror above works (tested 2026-11-19), so point the candidate's allowed_hosts and URL at coastwatch.pfeg.noaa.gov. The review's licence-mapping blocker (licence string not in schemas/source.schema.json enum) still stands; map it to public-domain (NOAA product) after owner sign-off.

**Sample on box:** samples/noaacwLEOACSPOSSTL3SnrtCDaily_sea_surface_temperature_centralcoast.nc (130 KB; 2026-11-17T12:00Z; 16.2-23.4 degC; 44% valid)
