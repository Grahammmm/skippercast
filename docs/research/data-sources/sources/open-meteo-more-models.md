# Open-Meteo extra models: DWD ICON, ECMWF AIFS, UK Met Office, Canadian GEM

- **id:** `open-meteo-more-models`
- **Priority:** 6
- **Status:** can ingest now (free/open) via existing adapter
- **Test download (2026-11-19):** PASS
- **Provider:** Open-Meteo (redistributing DWD, ECMWF, UKMO, ECCC)

## What it measures
Additional global wind/weather models for multi-model comparison (the 'model spread' view Windy and PredictWind sell).

**Variables:** Any Open-Meteo hourly variable, e.g. wind_speed_10m, wind_gusts_10m (AIFS returned null gusts), wind_direction_10m, pressure_msl

## Coverage and timing
- Resolution: ICON ~13 km global (icon_seamless), AIFS 0.25 deg, UKMO ~10 km global, GEM ~15 km
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global incl. Central Coast
- Temporal resolution: Hourly
- Latency: Per model, 3-8 h
- Forecast horizon: ICON 7.5 d, AIFS ~15 d, UKMO ~7 d, GEM ~10 d (Open-Meteo docs; verify per model page)

## Format, licence, cost
- Format: JSON
- Licence / attribution: Open-Meteo CC BY 4.0; free API is non-commercial. Same terms as existing open-meteo-api register entry; commercial plan needed if SkipperCast charges.
- Cost: Free (non-commercial) / paid API plan for commercial

## Endpoints
- https://api.open-meteo.com/v1/forecast?models=icon_seamless,ecmwf_aifs025_single,ukmo_seamless,gem_seamless
- https://open-meteo.com/en/docs

## Auth
None (commercial plan uses an apikey param)

**Rate limits:** 10,000 calls/day free tier

## Who uses it
- Apps: Windy (ICON, UKV); PredictWind (ICON, UKMO, AIFS); SeaLegs AI (ICON); Orca (ICON)
- SkipperCast layer: Wind / Weather (model comparison)

## Connect and download
```bash
curl 'https://api.open-meteo.com/v1/forecast?latitude=35.37&longitude=-120.86&hourly=wind_speed_10m,wind_gusts_10m&models=icon_seamless,ecmwf_aifs025_single,ukmo_seamless&forecast_days=3&wind_speed_unit=kn'
```

**Cadence:** Same as current Open-Meteo jobs.

**Pipeline fit:** One-line change: extend models list in the open-meteo adapter; add catalog entries dwd-icon, ecmwf-aifs, ukmo-global.

**Sample on box:** samples/openmeteo_icon_aifs_ukmo_morrobay.json
