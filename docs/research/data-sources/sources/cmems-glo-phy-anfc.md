# Copernicus Marine global physics analysis + 10-day forecast (Mercator 1/12 deg)

- **id:** `cmems-glo-phy-anfc`
- **Priority:** 12
- **Status:** needs registration/API key (free)
- **Test download (2026-11-19):** UNTESTED - needs key (IDs verified)
- **Provider:** CMEMS product GLOBAL_ANALYSISFORECAST_PHY_001_024

## What it measures
Ocean model: currents, temperature and salinity at depth, mixed-layer depth, bottom temperature, SSH. This is the 'Mercator' current GRIB that PredictWind uses.

**Variables:** Hourly surface (cmems_mod_glo_phy_anfc_0.083deg_PT1H-m): uo, vo, thetao, so, zos. Daily 2D (cmems_mod_glo_phy_anfc_0.083deg_P1D-m): mlotst (mixed layer), tob (bottom temp), sob, zos, pbo. Daily 3D: thetao (…thetao_anfc_0.083deg_P1D-m), so (…so_anfc…P1D-m), uo/vo (…cur_anfc…P1D-m, PT6H-i), wo (wcur).

## Coverage and timing
- Resolution: 1/12 deg (~8 km), 50 depth levels
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; Central Coast
- Temporal resolution: Hourly (surface), 6-hourly, daily
- Latency: Daily update
- Forecast horizon: 10 days (time axis extended to ~2026-11-28 when read 2026-11-19)

## Format, licence, cost
- Format: NetCDF / Zarr via toolbox
- Licence / attribution: Copernicus Marine Service licence: free, commercial use allowed, attribution required ('Generated using E.U. Copernicus Marine Service Information; https://doi.org/<product DOI>').
- Cost: Free

## Endpoints
- https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_PHY_001_024/description

## Auth
1. Create a free account at https://data.marine.copernicus.eu/register (email + password; no fee; accept the Copernicus Marine licence, which allows commercial use with attribution).
2. pip install copernicusmarine   (tested here: version 2.5.1)
3. copernicusmarine login   (stores credentials in ~/.copernicusmarine; or set env COPERNICUSMARINE_SERVICE_USERNAME / COPERNICUSMARINE_SERVICE_PASSWORD in the job's secrets — never commit them)
4. Run the subset command below. Docs: https://help.marine.copernicus.eu/en/articles/7970514-copernicus-marine-toolbox-installation

**Rate limits:** As above.

## Who uses it
- Apps: Fishare (Copernicus Marine salinity 1/12 deg daily, subsurface temperature); RipVision AI (CMEMS mixed-layer depth and surface currents); SeaLegs/DeepCast (CMEMS currents); PredictWind (Mercator ocean-current GRIBs); Salty Offshore (mixed-layer depth, salinity)
- SkipperCast layer: Subsurface (temperature at depth, thermocline/MLD, bottom temp), Salinity, Currents (forecast)

## Connect and download
```bash
copernicusmarine subset --dataset-id cmems_mod_glo_phy_anfc_0.083deg_PT1H-m -v uo -v vo -v thetao -v so \
  -x -123.5 -X -119.5 -y 34 -Y 37 -z 0 -Z 1 -t $(date -u +%Y-%m-%d) -T $(date -u -d '+5 days' +%Y-%m-%d) -o . -f cmems_phy_surface.nc
copernicusmarine subset --dataset-id cmems_mod_glo_phy_anfc_0.083deg_P1D-m -v mlotst -v tob -x -123.5 -X -119.5 -y 34 -Y 37 -o . -f cmems_mld.nc
copernicusmarine subset --dataset-id cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m -v thetao -x -123.5 -X -119.5 -y 34 -Y 37 -z 0 -Z 300 -o . -f cmems_temp_0_300m.nc
```

**Cadence:** Daily 10:00 PT.

**Pipeline fit:** cmems-toolbox adapter; depth slices feed the Subsurface layer, MLD feeds thermocline view.

**Sample on box:** none (needs key)
