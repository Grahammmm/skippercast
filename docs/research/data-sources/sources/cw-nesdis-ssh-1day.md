# NOAA CoastWatch SSH anomaly + geostrophic currents (experimental)

- **id:** `cw-nesdis-ssh-1day`
- **Priority:** 13
- **Status:** can ingest now (free/open) but stale
- **Test download (2026-11-19):** PASS
- **Provider:** NOAA NESDIS / CoastWatch (PFEG ERDDAP)

## What it measures
Sea-level anomaly from altimetry and derived geostrophic currents (eddies, upwelling fronts).

**Variables:** sla (m), ugos, vgos (m/s)

## Coverage and timing
- Resolution: 0.25 deg
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; Central Coast (coastal cells masked)
- Temporal resolution: Daily
- Latency: Last time 2026-09-28 when read 2026-11-19 (52 days behind)
- Forecast horizon: Observation only

## Format, licence, cost
- Format: NetCDF via ERDDAP
- Licence / attribution: NOAA free to use/redistribute; labelled EXPERIMENTAL.
- Cost: Free

## Endpoints
- https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisSSH1day.html

## Auth
None

**Rate limits:** As PFEG ERDDAP.

## Who uses it
- Apps: Same apps as cmems-sealevel-nrt (altimetry layer)
- SkipperCast layer: Altimetry / eddies (fallback only)

## Connect and download
```bash
curl -g -o ssh.nc 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisSSH1day.nc?sla[(last)][(34.0):1:(37.0)][(-123.5):1:(-119.5)],ugos[(last)][(34.0):1:(37.0)][(-123.5):1:(-119.5)],vgos[(last)][(34.0):1:(37.0)][(-123.5):1:(-119.5)]'
```

**Cadence:** Weekly check; use only until CMEMS key exists.

**Pipeline fit:** erddap-grid adapter. Do not show as 'current' while it lags weeks.

**Sample on box:** samples/nesdisSSH1day_sla_centralcoast.nc, samples/nesdisSSH1day_ugos_centralcoast.nc (2026-09-28)
