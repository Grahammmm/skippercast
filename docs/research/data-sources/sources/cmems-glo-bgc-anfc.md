# Copernicus Marine global biogeochemistry forecast (oxygen, productivity)

- **id:** `cmems-glo-bgc-anfc`
- **Priority:** 18
- **Status:** needs registration/API key (free)
- **Test download (2026-11-19):** UNTESTED - needs key (IDs verified)
- **Provider:** CMEMS GLOBAL_ANALYSISFORECAST_BGC_001_028

## What it measures
Model dissolved oxygen and net primary production at depth; also nutrients, pH, plankton.

**Variables:** o2, nppv (cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m); no3/po4/si (nut); ph/dissic (car); chl/phyc (pft)

## Coverage and timing
- Resolution: 0.25 deg
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; coarse near coast
- Temporal resolution: Daily
- Latency: Daily
- Forecast horizon: 10 days

## Format, licence, cost
- Format: NetCDF / Zarr
- Licence / attribution: Copernicus Marine Service licence: free, commercial use allowed, attribution required ('Generated using E.U. Copernicus Marine Service Information; https://doi.org/<product DOI>').
- Cost: Free

## Endpoints
- https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_BGC_001_028/description

## Auth
1. Create a free account at https://data.marine.copernicus.eu/register (email + password; no fee; accept the Copernicus Marine licence, which allows commercial use with attribution).
2. pip install copernicusmarine   (tested here: version 2.5.1)
3. copernicusmarine login   (stores credentials in ~/.copernicusmarine; or set env COPERNICUSMARINE_SERVICE_USERNAME / COPERNICUSMARINE_SERVICE_PASSWORD in the job's secrets — never commit them)
4. Run the subset command below. Docs: https://help.marine.copernicus.eu/en/articles/7970514-copernicus-marine-toolbox-installation

**Rate limits:** As above.

## Who uses it
- Apps: Salty Offshore (dissolved oxygen, phytoplankton)
- SkipperCast layer: Subsurface (oxygen / hypoxia)

## Connect and download
```bash
copernicusmarine subset --dataset-id cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m -v o2 -v nppv -x -123.5 -X -119.5 -y 34 -Y 37 -z 0 -Z 200 -o . -f cmems_o2.nc
```

**Cadence:** Daily.

**Pipeline fit:** cmems-toolbox adapter. Low priority; 0.25 deg is coarse for bays — validate against CeNCOOS DO sensors.

**Sample on box:** none (needs key)
