# Copernicus Marine L4 NRT sea level (DUACS): SLA, ADT, geostrophic currents

- **id:** `cmems-sealevel-nrt`
- **Priority:** 11
- **Status:** needs registration/API key (free)
- **Test download (2026-11-19):** UNTESTED - needs key (dataset IDs and variables verified anonymously with copernicusmarine describe)
- **Provider:** Copernicus Marine Service (CMEMS), product SEALEVEL_GLO_PHY_L4_NRT_008_046

## What it measures
Merged multi-satellite altimetry: sea-level anomaly and absolute dynamic topography, geostrophic currents. Shows eddies, upwelling fronts, the California Current meanders.

**Variables:** sla, adt, ugos, vgos, ugosa, vgosa, err_sla, err_ugosa, err_vgosa, flag_ice

## Coverage and timing
- Resolution: 0.125 deg (dataset cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.125deg_P1D); 0.25 deg version also
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; Central Coast (coast cells masked)
- Temporal resolution: Daily
- Latency: ~1 day (time axis ended 2026-11-19 per catalog)
- Forecast horizon: Observation only

## Format, licence, cost
- Format: NetCDF / Zarr (ARCO) via toolbox
- Licence / attribution: Copernicus Marine Service licence: free, commercial use allowed, attribution required ('Generated using E.U. Copernicus Marine Service Information; https://doi.org/<product DOI>').
- Cost: Free

## Endpoints
- https://data.marine.copernicus.eu/product/SEALEVEL_GLO_PHY_L4_NRT_008_046/description
- dataset_id cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.125deg_P1D

## Auth
1. Create a free account at https://data.marine.copernicus.eu/register (email + password; no fee; accept the Copernicus Marine licence, which allows commercial use with attribution).
2. pip install copernicusmarine   (tested here: version 2.5.1)
3. copernicusmarine login   (stores credentials in ~/.copernicusmarine; or set env COPERNICUSMARINE_SERVICE_USERNAME / COPERNICUSMARINE_SERVICE_PASSWORD in the job's secrets — never commit them)
4. Run the subset command below. Docs: https://help.marine.copernicus.eu/en/articles/7970514-copernicus-marine-toolbox-installation

**Rate limits:** No hard published quota for subset; keep bbox small.

## Who uses it
- Apps: RipVision AI (Copernicus SSH altimetry); SeaLegs/DeepCast (altimetry for eddies); FishTrack (daily altimetry); BlueFronts (altimetry); Salty Offshore (SSHa); SkeeterCast (SSH anomaly); Fishare (CMEMS)
- SkipperCast layer: Altimetry / eddies / upwelling proxy (currents layer overlay)

## Connect and download
```bash
copernicusmarine subset --dataset-id cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.125deg_P1D \
  -v sla -v adt -v ugos -v vgos -x -123.5 -X -119.5 -y 34 -Y 37 \
  -t $(date -u -d '3 days ago' +%Y-%m-%d) -T $(date -u +%Y-%m-%d) -o . -f cmems_ssh.nc
# python
import copernicusmarine
ds = copernicusmarine.open_dataset(dataset_id="cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.125deg_P1D", variables=["sla","ugos","vgos"], minimum_longitude=-123.5, maximum_longitude=-119.5, minimum_latitude=34, maximum_latitude=37)
```

**Cadence:** Daily 08:00 PT.

**Pipeline fit:** New adapter 'cmems-toolbox' (shared by all CMEMS entries) writing NetCDF → existing raster pipeline. Repo has 0 copernicus/cmems references today.

**Sample on box:** none (needs key)
