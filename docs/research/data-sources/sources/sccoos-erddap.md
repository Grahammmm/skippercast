# SCCOOS ERDDAP (Southern California shore stations, HABs, gliders)

- **id:** `sccoos-erddap`
- **Priority:** 17
- **Status:** can ingest now (free/open) — not reachable from test box
- **Test download (2026-11-19):** UNTESTED - erddap.sccoos.org timed out from this box (HTTP 000)
- **Provider:** SCCOOS (Southern California Coastal Ocean Observing System)

## What it measures
Shore station temperature/salinity/chl, harmful algal bloom monitoring; south edge of the box (Pt Conception / Santa Barbara Channel).

**Variables:** Station-specific

## Coverage and timing
- Resolution: Points
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Southern California; overlaps only the southern edge of the Central Coast box
- Temporal resolution: Minutes
- Latency: Minutes
- Forecast horizon: Observation only

## Format, licence, cost
- Format: ERDDAP CSV/NetCDF
- Licence / attribution: IOOS free and open
- Cost: Free

## Endpoints
- https://erddap.sccoos.org/erddap/index.html

## Auth
None

**Rate limits:** ERDDAP

## Who uses it
- Apps: Fish or Pass (credits SCCOOS)
- SkipperCast layer: Subsurface / in-situ ground truth

## Connect and download
```bash
curl 'https://erddap.sccoos.org/erddap/search/index.csv?searchFor=temperature'
```

**Cadence:** Every 30 min.

**Pipeline fit:** Same tabledap path as CeNCOOS; retest from the production network.

**Sample on box:** none
