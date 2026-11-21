# HYCOM ESPC-D-V02 global ocean forecast (US Navy)

- **id:** `hycom-espc-d-v02`
- **Priority:** 4
- **Status:** can ingest now (free/open)
- **Test download (2026-11-19):** PASS
- **Provider:** HYCOM consortium / US Navy NRL (ESPC-D-V02), tds.hycom.org + ncss.hycom.org

## What it measures
Model ocean currents, temperature and salinity at 40 depth levels, sea surface elevation. HYCOM-class model used by apps for 'subsurface temperature' and currents.

**Variables:** water_u, water_v (m/s); water_temp (degC); salinity (psu); surf_el (m); 40 depth levels 0-5000 m

## Coverage and timing
- Resolution: 1/12 deg (~8 km) horizontal
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; Central Coast covered (coastline cells masked)
- Temporal resolution: 3-hourly (FMRC 'best' time series)
- Latency: Daily run; the ssh aggregate ended 2026-11-17T11:00Z when read 2026-11-19, the FMRC best uv aggregate served 2026-11-19T12:00Z (forecast)
- Forecast horizon: About 7-8 days forecast (FMRC runs)

## Format, licence, cost
- Format: NetCDF4 via THREDDS NCSS / OPeNDAP
- Licence / attribution: US Government work, free; credit 'HYCOM.org / US Navy ESPC'. hycom.org asks users not to bulk-mirror; subset by bbox.
- Cost: Free

## Endpoints
- https://www.hycom.org/dataserver/espc-d-v02/global-analysis
- https://tds.hycom.org/thredds/catalog.html
- https://ncss.hycom.org/thredds/ncss/grid/FMRC_ESPC-D-V02_uv3z/FMRC_ESPC-D-V02_uv3z_best.ncd/dataset.html
- https://ncss.hycom.org/thredds/ncss/grid/ESPC-D-V02/ssh/dataset.html
- https://tds.hycom.org/thredds/dodsC/ESPC-D-V02/ssh (OPeNDAP)

## Auth
None

**Rate limits:** NCSS requests took ~40 s; keep to a bbox and few times. Other aggregates: ESPC-D-V02 t3z, s3z, ts3z, uv3z, ssh, ice (see catalog).

## Who uses it
- Apps: Fishare (subsurface temperature, HYCOM-class model); Salty Offshore (three NOAA/Navy current models, unverified which); PredictWind (ocean-current GRIBs)
- SkipperCast layer: Currents (surface + depth), Subsurface temperature/thermocline, Salinity

## Connect and download
```bash
T=$(date -u +%Y-%m-%dT12:00:00Z)
curl -o hycom_uv.nc "https://ncss.hycom.org/thredds/ncss/grid/FMRC_ESPC-D-V02_uv3z/FMRC_ESPC-D-V02_uv3z_best.ncd?var=water_u&var=water_v&north=37&south=34&west=-123.5&east=-119.5&vertCoord=0&time=$T&accept=netcdf4"
# Time range instead of one time: &time_start=2026-11-19T00:00:00Z&time_end=2026-11-26T00:00:00Z
# Temperature at depth: FMRC_ESPC-D-V02_t3z / ESPC-D-V02 t3z, var=water_temp, drop vertCoord to get all depths
```

**Cadence:** Daily after ~18:00 PT; keep latest run's 0-168 h.

**Pipeline fit:** New adapter 'thredds-ncss' (simple HTTP GET with query params → NetCDF). Output to the same COG/PMTiles path as WCOFS currents. Use as a back-up when WCOFS is late and for depth layers offshore of WCOFS domain.

**Sample on box:** samples/hycom_espc_uv_surface_centralcoast.nc (56 KB; 2026-11-19T12:00Z surface water_u -0.63..0.61 m/s)
