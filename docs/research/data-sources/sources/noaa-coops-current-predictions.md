# NOAA CO-OPS tidal current predictions

- **id:** `noaa-coops-current-predictions`
- **Priority:** 22
- **Status:** can ingest now (free/open) — no usable Central Coast stations
- **Test download (2026-11-19):** FAIL
- **Provider:** NOAA CO-OPS

## What it measures
Predicted tidal current speed/direction, slack times.

**Variables:** Velocity_Major, flood/ebb/slack times

## Coverage and timing
- Resolution: Point stations
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Only 3 subordinate stations in the box (PCT0156 Point Pinos, PCT0161 Point Santa Cruz, PCT0166 Ano Nuevo)
- Temporal resolution: 6-min / max-slack
- Latency: Predictions
- Forecast horizon: Years

## Format, licence, cost
- Format: JSON/CSV
- Licence / attribution: NOAA public domain
- Cost: Free

## Endpoints
- https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=currentpredictions
- https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=currents_predictions

## Auth
None

**Rate limits:** CO-OPS asks for an application= parameter.

## Who uses it
- Apps: Navionics / Aqua Map / Savvy Navvy (tidal current arrows)
- SkipperCast layer: Currents (tidal)

## Connect and download
```bash
curl 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=currents_predictions&station=PCT0156&begin_date=20261119&range=48&interval=MAX_SLACK&units=english&time_zone=lst_ldt&format=json&application=skippercast'   # returned 'Currents predictions are not available from the requested station.'
```

**Cadence:** n/a

**Pipeline fit:** Gap: Central Coast tidal currents are weak and poorly covered; use WCOFS/HF radar (already ingested). Inside harbours, consider CDIP/WCOFS.

**Sample on box:** none (API refused)
