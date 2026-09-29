# Forecast data: SkipperCast's own NOAA and ECMWF tiles

SkipperCast builds its wind and wave forecasts directly from NOAA and ECMWF open data. It no longer depends on the Open-Meteo API, whose free tier is licensed for non-commercial use only.

## Models

| Model id | Source | Grid | Hours | Fields |
| --- | --- | --- | --- | --- |
| `gfs_global` | NOAA GFS ([AWS open data](https://registry.opendata.aws/noaa-gfs-bdp-pds/)) | native ~13 km for wind and temperature; 0.25° gust, visibility, precipitation, cloud regridded onto it | hourly to 72 h, 3-hourly to 192 h | wind, gust, visibility, precipitation, 2 m temperature, cloud |
| `ecmwf_ifs025` | ECMWF IFS [open data](https://www.ecmwf.int/en/forecasts/datasets/open-data) | 0.25° | 3-hourly to 144 h, 6-hourly to 192 h | wind, gust, precipitation, 2 m temperature, cloud (no visibility) |
| `ncep_gfswave016` | NOAA GFS-Wave, US West Coast grid | 0.16° | hourly to 72 h, 3-hourly to 192 h | total sea, wind waves, primary and secondary swell (height, period, direction) |
| `ecmwf_wam` | ECMWF WAM open data | 0.25° | as IFS | total sea (height, mean and peak period, direction); no swell partitions |

NOAA data are U.S. public domain. ECMWF open data are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): credit "ECMWF" wherever the data appear. Both allow commercial use.

## Pipeline

1. `scripts/publish_forecasts.sh` runs inside every live-conditions cycle (every 30 minutes).
2. `python -m skippercast.forecast.build` finds each model's newest complete cycle. If it is already published, it reuses the tiles in seconds. Otherwise it downloads only the needed fields for every forecast hour: one HTTP range request per field, using NOAA's `.idx` and ECMWF's `.index` files. ECMWF downloads fall back between ECMWF's AWS mirror and its own portal.
3. Fields are cut to the California box (32–43° N, 127–116° W) and written as 1-degree tiles with a one-cell margin. Only tiles that contain sea are kept. Values are stored as int16 with a per-field scale, and missing values as -32768.
4. The tiles are force-pushed as a single commit to the `forecasts` branch, so the repository does not grow. A model that fails keeps its previous tiles and raises a warning.

Layout on the `forecasts` branch: `index.json` (per-model status), `<model>/manifest.json` (cycle, times, tiles, Open-Meteo-style `meta`), `<model>/tiles/<lat>_<lon>.json`.

## GEFS wind ensemble

The regional "Forecast range & uncertainty" card uses the 31 members of NOAA's Global Ensemble Forecast System (control `gec00` and perturbations `gep01`–`gep30`), read directly from [NOAA's GEFS bucket on AWS](https://registry.opendata.aws/noaa-gefs/) (U.S. public domain).

- `python -m skippercast.forecast.ensemble` runs in `scripts/publish_forecasts.sh` after the tiles. It waits until both the control and the last member publish the final step, then reads `gefs.YYYYMMDD/HH/atmos/pgrb2sp25/<member>.tHHz.pgrb2s.0p25.fFFF` for steps 0–192 h every 3 h. Only `UGRD`/`VGRD` at 10 m (one range request for the adjacent pair) and surface `GUST` are downloaded, located through each file's `.idx`, with the same retry and backoff as the tiles.
- It keeps no grid. Each regional forecast point (every region whose `intelligence.wind_ensemble_model` is `gfs025`) is sampled at the nearest sea cell within 30 km, using the land mask (`LAND`) of the same-cycle GFS 0.25° analysis, which is on the same grid. Points with no sea cell in range stay empty; nothing is filled.
- Output on the `forecasts` branch: `ncep_gefs025/manifest.json` (cycle, Open-Meteo-style `meta`, and an upstream receipt: bucket prefix, message count, bytes, a SHA-256 over every message's URL, offset and hash, the land-mask hash, and any missing member-steps) and `ncep_gefs025/regions/<region>.json` (per point: sampled grid cell, distance, and member × step wind speed and gust in m/s). More than 10% missing member-steps fails the build; a failed build keeps the previous one.
- `pipeline/intelligence.py` reads that build (locally in the live job, otherwise from the branch), records a receipt with the file's SHA-256, checks cycle, members, units, time axis and point coordinates, and linearly interpolates each member to hourly frames in knots. A member with a missing neighbouring step is left out of that hour, and gusts below the wind are dropped.
- Cost: about 6,000 range requests (≈4 GB) and 6,000 small decodes per 6-hour cycle, a few minutes on a runner; unchanged cycles are reused in seconds.

## Sampling: what we emulate from Open-Meteo

`server/model-api.js` is the one sampler. The Worker serves it at `/api/om/v1/forecast`, `/api/om/v1/marine` and `/api/om/data/<model>/static/meta.json`, and the Python pipeline runs it through `scripts/model_api.mjs`.

- **Space:** bilinear interpolation between the four surrounding cells. Marine queries and `cell_selection=sea` use sea cells only, renormalizing the weights, and fall back to the nearest sea cell. The reported latitude and longitude are the dominant grid cell, as in Open-Meteo.
- **Time:** monotone cubic (Fritsch–Carlson) interpolation from native steps to hourly values. The curve passes through every model value with no overshoot. Wind is interpolated as u/v components, and wave directions as unit vectors. ECMWF precipitation is converted from accumulation to the amount in each preceding hour.
- **Output:** Open-Meteo's response format, including multi-point arrays, `_<model>` suffixes when several models are requested, time zones, `unixtime`, units (`kn`, `ft`, `°F`, `inch`) and derived WMO weather codes.

On September 28, 2026, against Open-Meteo for the same Central Coast points and cycles, GFS wind speed agreed within 0.1–0.4 kn on average. GFS-Wave height agreed within 0.05 ft, and ECMWF wind within 0.1 kn.

## Known differences and follow-ups

- ECMWF open data has no visibility and no swell partitions, so those values are null. ECMWF waves are 0.25°; Open-Meteo shows a 9 km WAM grid.
- Nothing calls Open-Meteo at runtime any more. The app's surface currents come from NOAA WCOFS samples that the regional pipeline publishes with the shared forecast (`currents` in `/api/forecast`), and the legacy personal monitor (`monitor/collector.py`) requests `/api/om`.
- Gap: there is no hourly sea-surface temperature forecast in the app's weather layers (Météo-France SST was dropped with the Open-Meteo currents). NOAA WCOFS temperature forecasts remain in the habitat layers.
