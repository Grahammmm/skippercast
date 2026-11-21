# Copernicus GlobColour chlorophyll: OLCI 300 m daily + gap-free 4 km daily

- **id:** `cmems-oc-chl`
- **Priority:** 14
- **Status:** needs registration/API key (free)
- **Test download (2026-11-19):** UNTESTED - needs key (IDs verified)
- **Provider:** CMEMS OCEANCOLOUR_GLO_BGC_L3_NRT_009_101 and _L4_NRT_009_102

## What it measures
Chlorophyll-a at 300 m from Sentinel-3 OLCI (sharper than MODIS 4 km) and a cloud-free interpolated daily map.

**Variables:** CHL, CHL_uncertainty, flags (L3 OLCI 300 m: cmems_obs-oc_glo_bgc-plankton_nrt_l3-olci-300m_P1D); CHL (L4 gapfree: cmems_obs-oc_glo_bgc-plankton_nrt_l4-gapfree-multi-4km_P1D); also transp (KD490/ZSD clarity) datasets

## Coverage and timing
- Resolution: 300 m / 4 km
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; Central Coast
- Temporal resolution: Daily
- Latency: ~1 day; L3 300 m keeps a rolling window (~1 week) in NRT
- Forecast horizon: Observation only

## Format, licence, cost
- Format: NetCDF / Zarr
- Licence / attribution: Copernicus Marine Service licence: free, commercial use allowed, attribution required ('Generated using E.U. Copernicus Marine Service Information; https://doi.org/<product DOI>').
- Cost: Free

## Endpoints
- https://data.marine.copernicus.eu/product/OCEANCOLOUR_GLO_BGC_L3_NRT_009_101/description
- https://data.marine.copernicus.eu/product/OCEANCOLOUR_GLO_BGC_L4_NRT_009_102/description

## Auth
1. Create a free account at https://data.marine.copernicus.eu/register (email + password; no fee; accept the Copernicus Marine licence, which allows commercial use with attribution).
2. pip install copernicusmarine   (tested here: version 2.5.1)
3. copernicusmarine login   (stores credentials in ~/.copernicusmarine; or set env COPERNICUSMARINE_SERVICE_USERNAME / COPERNICUSMARINE_SERVICE_PASSWORD in the job's secrets — never commit them)
4. Run the subset command below. Docs: https://help.marine.copernicus.eu/en/articles/7970514-copernicus-marine-toolbox-installation

**Rate limits:** As above.

## Who uses it
- Apps: Fishare (CMEMS); Salty Offshore (phytoplankton); FishTrack (chlorophyll)
- SkipperCast layer: Chlorophyll (high-res + gap-free)

## Connect and download
```bash
copernicusmarine subset --dataset-id cmems_obs-oc_glo_bgc-plankton_nrt_l4-gapfree-multi-4km_P1D -v CHL -x -123.5 -X -119.5 -y 34 -Y 37 -o . -f chl_gapfree.nc
copernicusmarine subset --dataset-id cmems_obs-oc_glo_bgc-plankton_nrt_l3-olci-300m_P1D -v CHL -x -123.5 -X -119.5 -y 34 -Y 37 -o . -f chl_olci300.nc
```

**Cadence:** Daily.

**Pipeline fit:** cmems-toolbox adapter. Gap-free product solves the 'all cloud' days seen in the MODIS sample.

**Sample on box:** none (needs key)
