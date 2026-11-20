# SkipperCast data sources from 36 competitor apps

Checked 2026-11-19 (PT). Sources come from the 36 apps in [competitors.json](../competitors/competitors.json): their own pages, App Store text and help pages. The page-fetch archive from that pass (`research/evidence.json` on the research box) is not in this repository. They were cross-checked against github.com/Grahammmm/skippercast (`catalog/sources.json`, `catalog/candidates/`, `src/skippercast/`).
Every source marked PASS was downloaded on 2026-11-19. Copernicus Marine dataset IDs were checked with `copernicusmarine describe`, which needs no login. The samples were cut to 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception). Those sample files are not in this repository. A source marked UNTESTED needs a free account or did not answer from the research box.

Status values: already ingested · can ingest now (free/open) · needs registration/API key (free) · paid/licensed · proprietary/not available.

## Ingest priority (new sources)

| # | Source | Status | Test | Layer | Apps that use it | Doc |
|---|---|---|---|---|---|---|
| 1 | GOES-West (GOES-18) ACSPO hourly SST + fronts | can ingest now (free/open) | PASS | SST | BigBlue, Fishare, SkeeterCast, Salty Offshore | [sources/cw-goes-west-sst-hourly.md](sources/cw-goes-west-sst-hourly.md) |
| 2 | NOAA ACSPO L3S-LEO daily super-collated SST (VIIRS + AVHRR) | can ingest now (free/open); already a repo candidate | PASS | SST | FishTrack, Fishare, BigBlue, Salty Offshore | [sources/cw-acspo-l3s-leo-daily.md](sources/cw-acspo-l3s-leo-daily.md) |
| 3 | NOAA HRRR 3 km weather model | can ingest now (free/open) | PASS | Wind / Weather | Windy, PredictWind, Buoyweather, SkeeterCast | [sources/noaa-hrrr.md](sources/noaa-hrrr.md) |
| 4 | HYCOM ESPC-D-V02 global ocean forecast (US Navy) | can ingest now (free/open) | PASS | Currents | Fishare, Salty Offshore, PredictWind | [sources/hycom-espc-d-v02.md](sources/hycom-espc-d-v02.md) |
| 5 | NOAA Global RTOFS (HYCOM-based operational ocean forecast) | can ingest now (free/open) | PASS | Currents, mixed-layer depth | PredictWind, Salty Offshore | [sources/noaa-rtofs.md](sources/noaa-rtofs.md) |
| 6 | Open-Meteo extra models: DWD ICON, ECMWF AIFS, UK Met Office, Canadian GEM | can ingest now (free/open) via existing adapter | PASS | Wind / Weather | Windy, PredictWind, SeaLegs AI, Orca | [sources/open-meteo-more-models.md](sources/open-meteo-more-models.md) |
| 7 | NASA GIBS VIIRS / MODIS true-colour imagery tiles | can ingest now (free/open) | PASS | Raw base / satellite imagery | Fishare, BlueFronts, Salty Offshore | [sources/nasa-gibs-truecolor.md](sources/nasa-gibs-truecolor.md) |
| 8 | NOAA MRMS radar mosaic (NEXRAD) + nowCOAST radar WMS | can ingest now (free/open) | PASS | Weather | SkeeterCast, Windy | [sources/noaa-mrms-radar.md](sources/noaa-mrms-radar.md) |
| 9 | Water clarity Kd490 (MODIS West US 0.0125 deg, VIIRS 4 km, DINEOF gap-filled 2 km) | can ingest now (free/open) | PASS | Chlorophyll / water-colour family | Salty Offshore, SatFish / RipCharts / ROFFS show clarity layers without credits | [sources/cw-kd490-water-clarity.md](sources/cw-kd490-water-clarity.md) |
| 10 | CeNCOOS ERDDAP shore stations (Cal Poly Pier, Morro Bay, Monterey Bay) | can ingest now (free/open) | PASS | Subsurface / in-situ ground truth | Fish or Pass | [sources/cencoos-erddap-stations.md](sources/cencoos-erddap-stations.md) |
| 11 | Copernicus Marine L4 NRT sea level (DUACS): SLA, ADT, geostrophic currents | needs registration/API key (free) | UNTESTED | Altimetry / eddies / upwelling proxy | RipVision AI, SeaLegs/DeepCast, FishTrack, BlueFronts, Salty Offshore, SkeeterCast, Fishare | [sources/cmems-sealevel-nrt.md](sources/cmems-sealevel-nrt.md) |
| 12 | Copernicus Marine global physics analysis + 10-day forecast (Mercator 1/12 deg) | needs registration/API key (free) | UNTESTED | Subsurface | Fishare, RipVision AI, SeaLegs/DeepCast, PredictWind, Salty Offshore | [sources/cmems-glo-phy-anfc.md](sources/cmems-glo-phy-anfc.md) |
| 13 | NOAA CoastWatch SSH anomaly + geostrophic currents (experimental) | can ingest now (free/open) but stale | PASS | Altimetry / eddies | Same apps as cmems-sealevel-nrt | [sources/cw-nesdis-ssh-1day.md](sources/cw-nesdis-ssh-1day.md) |
| 14 | Copernicus GlobColour chlorophyll: OLCI 300 m daily + gap-free 4 km daily | needs registration/API key (free) | UNTESTED | Chlorophyll | Fishare, Salty Offshore, FishTrack | [sources/cmems-oc-chl.md](sources/cmems-oc-chl.md) |
| 15 | NASA PACE OCI ocean colour (hyperspectral) L3 daily | needs registration/API key (free) | UNTESTED | Chlorophyll | BigBlue | [sources/nasa-pace-oci.md](sources/nasa-pace-oci.md) |
| 16 | SMOS satellite sea-surface salinity | can ingest now (free/open), low value | PASS | Salinity | Fishare, Salty Offshore | [sources/cw-smos-sss.md](sources/cw-smos-sss.md) |
| 17 | SCCOOS ERDDAP (Southern California shore stations, HABs, gliders) | can ingest now (free/open) — not reachable from test box | UNTESTED | Subsurface / in-situ ground truth | Fish or Pass | [sources/sccoos-erddap.md](sources/sccoos-erddap.md) |
| 18 | Copernicus Marine global biogeochemistry forecast (oxygen, productivity) | needs registration/API key (free) | UNTESTED | Subsurface | Salty Offshore | [sources/cmems-glo-bgc-anfc.md](sources/cmems-glo-bgc-anfc.md) |
| 19 | Sentinel-1 SAR imagery (Copernicus Data Space) | needs registration/API key (free) | PARTIAL | Satellite imagery | BlueFronts | [sources/cdse-sentinel-1.md](sources/cdse-sentinel-1.md) |
| 20 | AVISO+ FSLE (Finite-Size Lyapunov Exponents) — Lagrangian fronts | paid/licensed (registration; free only for scientific/non-profit per handbook) | UNTESTED | Fronts | Salty Offshore | [sources/aviso-fsle.md](sources/aviso-fsle.md) |
| 21 | NOAA RRFS (Rapid Refresh Forecast System, NAM/HRRR successor) | can ingest now (free/open) — layout unverified | UNTESTED | Wind / Weather | Salty Offshore, PredictWind | [sources/noaa-rrfs.md](sources/noaa-rrfs.md) |
| 22 | NOAA CO-OPS tidal current predictions | can ingest now (free/open) — no usable Central Coast stations | FAIL | Currents | Navionics / Aqua Map / Savvy Navvy | [sources/noaa-coops-current-predictions.md](sources/noaa-coops-current-predictions.md) |

### Why this order
1. **GOES-West hourly SST** and **2. ACSPO daily SST**: biggest visible gap against BigBlue, Fishare and FishTrack (hourly and sharp observed SST plus fronts). Zero new code, because the existing `erddap-grid` adapter covers both.
3. **HRRR**: a one-line Open-Meteo model addition gives nearshore wind detail that Windy, PredictWind and Buoyweather all show.
4–5. **HYCOM ESPC and RTOFS**: free current, depth-temperature and MLD forecasts with no key needed today. They stand in until the CMEMS key exists.
6–10. Cheap wins: extra Open-Meteo models, GIBS true colour and radar (direct raster sources, no pipeline), Kd490 clarity, and the CeNCOOS pier sensors for ground truth.
11–12, 14. **Copernicus Marine** (free account): altimetry (eddies), Mercator physics (subsurface, salinity, MLD) and 300 m / gap-free chlorophyll. These are the layers the premium offshore apps advertise. Register once, then one `cmems-toolbox` adapter serves all of them.
15+. PACE (Earthdata login), SMOS, BGC oxygen, Sentinel-1, FSLE (licence), RRFS (not live) and CO-OPS currents (no stations).

## Accounts to create (all free)
- Copernicus Marine: https://data.marine.copernicus.eu/register. Then `pip install copernicusmarine && copernicusmarine login`. Unlocks cmems-sealevel-nrt, cmems-glo-phy-anfc, cmems-oc-chl and cmems-glo-bgc-anfc.
- NASA Earthdata Login: https://urs.earthdata.nasa.gov/users/new. Put it in `~/.netrc` and use the `earthaccess` package. Unlocks PACE, plus OSCAR and GHRSST L2P if wanted later.
- Copernicus Data Space: https://dataspace.copernicus.eu/ (Sentinel-1, low priority).
- AVISO+: registration form, but the licence must be checked for commercial use (FSLE). Computing FSLE in-house from CMEMS currents is the better path.
Keep credentials in the job secret store (Cloudflare/GitHub secrets), never in the repo.

## Already ingested by SkipperCast (no action)

| Repo source ids | Layer | Competitor apps using the same data |
|---|---|---|
| open-meteo (noaa-gfs, ecmwf-ifs, noaa-gfs-wave, ecmwf-wam, open-meteo-api) | Wind, weather, waves | Go or No, Fish or Pass, Fishare, Windy, PredictWind, SeaLegs, Orca, SkeeterCast |
| ECMWF open data + GFS direct from AWS (src/skippercast/forecast/fetch.py ECMWF_AWS/ECMWF_PORTAL/GFS_AWS) | Wind, weather | Windy, PredictWind, SeaLegs, Orca |
| ndbc-buoys, ndbc-history | Wind, gusts, waves, water temp | SeaStatus, BlueFronts, Go or No |
| cdip-mop (candidate) | Nearshore waves | Surfline/Buoyweather class apps |
| noaa-tides (CO-OPS) | Tides | SeaStatus, Go or No, Cobia, Navionics, Aqua Map |
| nws-weather (api.weather.gov, marine warnings) | Weather / warnings | SeaStatus, Pathr, SkeeterCast |
| mur-sst, noaa-blended-sst (Geo-Polar 5 km) | SST | RipVision (MUR 0.02), Salty (GHRSST), FishTrack, BigBlue |
| modis-chlorophyll, noaa-viirs-merged-chlorophyll | Chlorophyll | RipVision, BigBlue, Salty, FishTrack, SkeeterCast |
| ioos-hfr, noaa-hfr-thredds, noaa-ndbc-hfr-uswc-6km | HF-radar surface currents | BlueFronts, Salty (currents) |
| noaa-wcofs, regional-roms (candidate) | Model currents / temperature | Salty (NOAA current models, unverified) |
| noaa-gefs-members, noaa-gefs-wave-prob | Ensembles | PredictWind/Windy (ensembles) |
| noaa-goes-nowcoast (GOES imagery) | Satellite imagery | SkeeterCast, Fishare |
| gebco-2026-grid, gmrt, noaa-bluetopo, noaa-bag, CUDEM, CoNED, USGS surveys | Bathymetry | RipVision (GEBCO), Salinity (NOAA survey relief), SkeeterCast, Fish or Pass, Cobia |
| noaa-enc-display, noaa-cusp-shoreline, osm-tiles, protomaps-basemap, usgs-naip | Charts / base map | Pathr, BoatNGo, Fishing Points, Aqua Map, Cobia |
| kelpwatch (candidate), cdfw-kelp-2016 | Kelp canopy | Fish or Pass |
| noaa-ais, aisstream, gfw-effort | AIS / fishing effort | Salty Offshore (AIS) |
| cdfw-mpas, cdfw-rules, recfin, obis | Regulations, MPAs, catch | Fish or Pass, Fishbrain |

## Proprietary / not available

| Source | Apps | Note |
|---|---|---|
| SiriusXM Marine / OceanBytes analyses | SiriusXM Fish Mapping | Satellite-radio delivered SST/chl/altimetry/'fish mapping' — proprietary feed |
| Hilton's RT-Nav analyses | Hilton's | Proprietary hand-drawn/automated break analysis |
| ROFFS analyses | ROFFS | Paid expert analysis charts |
| Terrafin / RipCharts / Rigline / GulfWire / SatFish / Fishdope imagery | RipCharts, Rigline, GulfWire, SatFish, Fishdope | Unattributed composites; underlying data likely NOAA/NASA/CMEMS (same sources above) |
| PredictWind PWG / PWE / PWAi | PredictWind | In-house models |
| Surfline LOTUS / Buoyweather wave model | Surfline, Buoyweather, FishTrack | In-house wave model |
| Navionics / C-MAP / Garmin charts & SonarChart | Navionics, Savvy Navvy, DECKEE, Fishbrain, Wavve | Licensed chart vendors |
| meteoblue | Windy | Commercial weather API (paid) |
| SkeeterCast AI / SeaLegs AI / RipVision AI scoring | SkeeterCast, SeaLegs, RipVision | Derived products on public data |
| Himawari-9 | Fishare | Not relevant to California (West Pacific satellite) |

## Samples downloaded on 2026-11-19

The files named below are the research-box pulls. They are not in this repository.

| File | Source | Notes |
|---|---|---|
| goes_west_sea_surface_temperature_centralcoast.nc | GOES-West hourly SST | 2026-11-19 14Z, 1% valid (cloudy night) |
| noaacwLEOACSPOSSTL3SnrtCDaily_sea_surface_temperature_centralcoast.nc | ACSPO L3S daily | 2026-11-17, 44% valid |
| hycom_espc_uv_surface_centralcoast.nc | HYCOM ESPC-D-V02 | surface u/v 2026-11-19 12Z |
| rtofs_20261118_f024_diag_centralcoast.nc | RTOFS | ssh, MLD, barotropic u/v |
| hrrr_20261119_t00z_f01_wind10m.grib2 | HRRR (AWS) | 10 m u/v CONUS (byte-range) |
| openmeteo_hrrr_morrobay.json, openmeteo_icon_aifs_ukmo_morrobay.json | Open-Meteo | point forecasts at Morro Bay |
| gibs_wms_truecolor_centralcoast_2026-11-18.png, gibs_viirs_noaa20_truecolor_2026-11-18.jpg | NASA GIBS | true colour |
| nowcoast_radar_centralcoast.png, mrms_MergedBaseReflectivityQC_latest.grib2.gz | nowCOAST / MRMS | radar |
| erdMWk4901day_k490_centralcoast.nc, nesdisVHNkd490Daily_kd_490_centralcoast.nc | Kd490 | clarity (latest MODIS day fully cloudy) |
| erdMBchla1day_chlorophyll_centralcoast.nc | MODIS 0.025 deg Pacific chl (alt. to the existing chl source) | 2026-11-17, fully cloudy |
| cencoos_calpoly_pier_shore.csv, cencoos_morro_bay_wq.csv | CeNCOOS ERDDAP | 3 days of pier/bay sensors |
| nesdisSSH1day_sla/ugos_centralcoast.nc | CoastWatch SSH | stale (2026-09-28) |
| coastwatchSMOSv662SSS1day_sss_centralcoast.nc | SMOS salinity | 1% valid near coast |
| cdse_s1_stac_search.json | Sentinel-1 STAC | metadata only |

## Gaps and caveats
- **Failed tests.** CDIP THREDDS and SCCOOS ERDDAP timed out from this box. They are not known to be down, so retest from production. The ASCAT wind dataset (erdQMwind1day) returned 503 twice. CO-OPS refused current predictions for the 3 Central Coast stations. RRFS bucket paths were empty.
- **Daily satellite fields are often fully clouded** (chlorophyll and Kd490 on 2026-11-17). Show composites (3/8-day) or the CMEMS gap-free products.
- **Licence mapping.** The repo schema allows only public-domain, CC0-1.0, CC-BY-4.0, CC-BY-NC-4.0 or facts-only. Map NOAA/NASA/HYCOM sources to public-domain. Copernicus Marine and Sentinel need a new 'attribution-required free licence' mapping, or CC-BY-4.0-equivalent after an owner/legal decision. Add each source to docs/legal/data-rights-register.md before activation.
- **Open-Meteo free tier is non-commercial.** This applies to HRRR, ICON and the other models routed through it, the same as SkipperCast's existing Open-Meteo use.
- **App credits are partial.** Many apps (SiriusXM, ROFFS, RipCharts, SatFish, Fishdope, Hilton's) do not name their sources. Their layers map to the same NOAA/NASA/CMEMS products listed here, but which product each one uses is unverified.
- **Not pursued.** Himawari (wrong hemisphere), OSCAR (0.25 deg; not credited by any app), CalCOFI (cruise data; no app uses it), USGS river gauges (Cobia; minor on the Central Coast).

## Files in this folder
- README.md (this file)
- [sources.json](sources.json) (machine-readable, all fields)
- sources/<id>.md (one per source, self-contained)

The research box also had `samples/` (the test downloads), `research/` (app page fetches and evidence) and `build_sources.py` (the generator). Those were not added here.
