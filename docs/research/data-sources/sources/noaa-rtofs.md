# NOAA Global RTOFS (HYCOM-based operational ocean forecast)

- **id:** `noaa-rtofs`
- **Priority:** 5
- **Status:** can ingest now (free/open)
- **Test download (2026-11-19):** PASS
- **Provider:** NOAA NCEP, AWS Open Data bucket noaa-nws-rtofs-pds

## What it measures
Operational ocean forecast: SSH, barotropic currents, mixed-layer and surface boundary-layer thickness (2D); temperature, salinity, currents at depth on a US-West subdomain (3D).

**Variables:** 2ds diag: ssh, u_barotropic_velocity, v_barotropic_velocity, surface_boundary_layer_thickness, mixed_layer_thickness. 3dz US_west: temperature, salinity, u, v on z levels (6-hourly)

## Coverage and timing
- Resolution: 1/12 deg tripolar (curvilinear Latitude/Longitude 2D arrays)
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; US_west subdomain file for 3D
- Temporal resolution: Hourly (2ds), 6-hourly (3dz)
- Latency: Daily 00Z run on S3 by the following day
- Forecast horizon: n-hindcast plus f000-f192 (8 days); f192 confirmed in rtofs.20261118/

## Format, licence, cost
- Format: NetCDF4 (HDF5), ~195 MB per 2D global hour, ~280 MB per 3D US_west 6-hourly file
- Licence / attribution: NOAA, public domain. Credit NOAA/NCEP RTOFS.
- Cost: Free (AWS Open Data, no egress fee to you)

## Endpoints
- https://registry.opendata.aws/noaa-rtofs/
- https://noaa-nws-rtofs-pds.s3.amazonaws.com/?list-type=2&prefix=rtofs.YYYYMMDD/ (listing)
- https://noaa-nws-rtofs-pds.s3.amazonaws.com/rtofs.YYYYMMDD/rtofs_glo_2ds_fHHH_diag.nc
- https://noaa-nws-rtofs-pds.s3.amazonaws.com/rtofs.YYYYMMDD/rtofs_glo_3dz_fHHH_6hrly_hvr_US_west.nc

## Auth
None (anonymous S3 / HTTPS)

**Rate limits:** S3, none practical. Read with byte-range (fsspec) to avoid pulling whole files.

## Who uses it
- Apps: PredictWind (RTOFS current GRIBs); Salty Offshore (NOAA current models, unverified which)
- SkipperCast layer: Currents, mixed-layer depth (Subsurface), SSH

## Connect and download
```bash
import fsspec, xarray as xr, numpy as np
url = "https://noaa-nws-rtofs-pds.s3.amazonaws.com/rtofs.20261118/rtofs_glo_2ds_f024_diag.nc"
ds = xr.open_dataset(fsspec.open(url, block_size=4*2**20).open(), engine="h5netcdf")
# Central Coast index window found by a coarse search (stable for this grid): Y 1940:2020, X 2020:2100
sub = ds[["ssh","mixed_layer_thickness","u_barotropic_velocity","v_barotropic_velocity"]].isel(Y=slice(1940,2020), X=slice(2020,2100)).load()
sub.to_netcdf("rtofs_centralcoast.nc")   # ~110 KB, 4 s from this box
```

**Cadence:** Daily 06:00 PT for previous day's 00Z run; hours 0-192 step 3.

**Pipeline fit:** New adapter 'rtofs-s3': fsspec range-read + regrid curvilinear → regular 0.08 deg with xesmf or scipy griddata, then existing raster pipeline. Index window Y1940:2020 X2020:2100 covers 32.9-38.0N, 124.2-117.9W.

**Sample on box:** samples/rtofs_20261118_f024_diag_centralcoast.nc (111 KB; valid 2026-11-19T00Z; ssh 0.11-0.47 m)
