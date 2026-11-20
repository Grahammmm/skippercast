# NASA PACE OCI ocean colour (hyperspectral) L3 daily

- **id:** `nasa-pace-oci`
- **Priority:** 15
- **Status:** needs registration/API key (free)
- **Test download (2026-11-19):** UNTESTED - needs key (collection + granule URLs verified in NASA CMR without login)
- **Provider:** NASA OB.DAAC, collection PACE_OCI_L3M_BGC_NRT (C4184125829-OB_CLOUD), v3.2

## What it measures
Chlorophyll and other biogeochemical products from PACE's hyperspectral Ocean Color Instrument (successor to MODIS).

**Variables:** chlor_a, carbon_phyto, poc and others in the BGC suite (AOP suite: Rrs, Kd)

## Coverage and timing
- Resolution: 4 km and 0.1 deg mapped
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; Central Coast
- Temporal resolution: Daily, 8-day, monthly
- Latency: ~1 day (granule PACE_OCI.20261118.L3m.DAY.BGC.V3_2.4km.NRT.nc existed 2026-11-19)
- Forecast horizon: Observation only

## Format, licence, cost
- Format: NetCDF4
- Licence / attribution: NASA open data, no restrictions; credit NASA OB.DAAC.
- Cost: Free

## Endpoints
- https://oceancolor.gsfc.nasa.gov/data/pace/
- https://cmr.earthdata.nasa.gov/search/granules.json?concept_id=C4184125829-OB_CLOUD&bounding_box=-123.5,34,-119.5,37&sort_key=-start_date
- https://obdaac-tea.earthdatacloud.nasa.gov/ob-cumulus-prod-public/PACE_OCI.YYYYMMDD.L3m.DAY.BGC.V3_2.4km.NRT.nc

## Auth
1. Free NASA Earthdata Login: https://urs.earthdata.nasa.gov/users/new
2. pip install earthaccess; earthaccess.login(strategy='netrc') or put 'machine urs.earthdata.nasa.gov login <user> password <pass>' in ~/.netrc (chmod 600) in the job's secret store.
3. Download granules found via CMR (files are global, ~tens of MB; subset after download).

**Rate limits:** None stated; be gentle.

## Who uses it
- Apps: BigBlue (PACE)
- SkipperCast layer: Chlorophyll (next-gen; plankton community)

## Connect and download
```bash
import earthaccess, xarray as xr
earthaccess.login()   # uses ~/.netrc
res = earthaccess.search_data(short_name="PACE_OCI_L3M_BGC_NRT", bounding_box=(-123.5,34,-119.5,37), count=1, temporal=("2026-11-17","2026-11-19"))
files = earthaccess.download([r for r in res if '4km' in r['umm']['GranuleUR']][:1], "./pace")
ds = xr.open_dataset(files[0]).sel(lat=slice(37,34), lon=slice(-123.5,-119.5))
```

**Cadence:** Daily.

**Pipeline fit:** New 'earthdata' adapter (also unlocks OSCAR, GHRSST L2P, PO.DAAC). Repo has no PACE references.

**Sample on box:** none (needs Earthdata login)
