# NOAA RRFS (Rapid Refresh Forecast System, NAM/HRRR successor)

- **id:** `noaa-rrfs`
- **Priority:** 21
- **Status:** can ingest now (free/open) — layout unverified
- **Test download (2026-11-19):** UNTESTED - bucket exists, rrfs_a/rrfs.20261118/ was empty
- **Provider:** NOAA NCEP, AWS bucket noaa-rrfs-pds

## What it measures
3 km regional weather model replacing NAM.

**Variables:** Wind, gust, etc. (GRIB2)

## Coverage and timing
- Resolution: 3 km
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): North America
- Temporal resolution: Hourly
- Latency: Unknown
- Forecast horizon: Up to 60-84 h (NOAA)

## Format, licence, cost
- Format: GRIB2
- Licence / attribution: NOAA public domain
- Cost: Free

## Endpoints
- https://noaa-rrfs-pds.s3.amazonaws.com/?list-type=2&delimiter=/&prefix=rrfs_a/

## Auth
None

**Rate limits:** None

## Who uses it
- Apps: Salty Offshore (NOAA RRFS replacing NAM); PredictWind (RRFS)
- SkipperCast layer: Wind / Weather

## Connect and download
```bash
curl 'https://noaa-rrfs-pds.s3.amazonaws.com/?list-type=2&delimiter=/&prefix=rrfs_a/'
```

**Cadence:** Revisit when operational files appear.

**Pipeline fit:** Same GRIB byte-range path as HRRR. Use HRRR until then.

**Sample on box:** none
