# NASA GIBS VIIRS / MODIS true-colour imagery tiles

- **id:** `nasa-gibs-truecolor`
- **Priority:** 7
- **Status:** can ingest now (free/open)
- **Test download (2026-11-19):** PASS
- **Provider:** NASA EOSDIS GIBS

## What it measures
Daily corrected-reflectance true-colour satellite images (what the sea and clouds looked like), plus hundreds of other imagery layers.

**Variables:** VIIRS_NOAA20_CorrectedReflectance_TrueColor, VIIRS_SNPP_CorrectedReflectance_TrueColor, MODIS_Aqua_CorrectedReflectance_TrueColor (layer names)

## Coverage and timing
- Resolution: 250 m
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global; Central Coast
- Temporal resolution: Daily (one overpass per satellite)
- Latency: ~3-5 h after overpass (NRT)
- Forecast horizon: Observation only

## Format, licence, cost
- Format: JPEG/PNG tiles via WMTS (EPSG:4326 / 3857) or WMS GetMap
- Licence / attribution: NASA open data, no restrictions; credit 'NASA EOSDIS GIBS / Worldview'.
- Cost: Free

## Endpoints
- https://nasa-gibs.github.io/gibs-api-docs/
- https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_NOAA20_CorrectedReflectance_TrueColor/default/{date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg
- https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi

## Auth
None

**Rate limits:** No key; NASA asks for reasonable use — cache tiles in R2.

## Who uses it
- Apps: Fishare (NASA VIIRS true colour 250 m); BlueFronts (satellite imagery); Salty Offshore (water clarity/true colour)
- SkipperCast layer: Raw base / satellite imagery (also shows fog banks, plumes, red tide colour)

## Connect and download
```bash
D=2026-11-18
curl -o tc.png "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=VIIRS_NOAA20_CorrectedReflectance_TrueColor&CRS=EPSG:4326&BBOX=34,-123.5,37,-119.5&WIDTH=800&HEIGHT=600&FORMAT=image/png&TIME=$D"
# MapLibre raster source (no download needed):
# tiles: ["https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_NOAA20_CorrectedReflectance_TrueColor/default/2026-11-18/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg"], maxzoom 9
```

**Cadence:** Daily at 14:00 PT; prefetch z5-9 tiles for the region into R2 for offline packs.

**Pipeline fit:** No pipeline needed for online use (direct raster source). For offline packs, add a tile prefetch job like the existing goes-frames job.

**Sample on box:** samples/gibs_wms_truecolor_centralcoast_2026-11-18.png (800x600; cloudy day) and samples/gibs_viirs_noaa20_truecolor_2026-11-18.jpg (one WMTS tile)
