# NOAA MRMS radar mosaic (NEXRAD) + nowCOAST radar WMS

- **id:** `noaa-mrms-radar`
- **Priority:** 8
- **Status:** can ingest now (free/open)
- **Test download (2026-11-19):** PASS
- **Provider:** NOAA NSSL/NCEP MRMS on AWS (noaa-mrms-pds); NOAA nowCOAST GeoServer

## What it measures
Composite weather radar reflectivity (rain/showers approaching), every 2 minutes.

**Variables:** MergedBaseReflectivityQC_00.50 (dBZ), PrecipRate, MultiSensor_QPE_01H etc.

## Coverage and timing
- Resolution: 0.01 deg (~1 km)
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): CONUS; coastal radar coverage reaches ~100-200 km offshore (beam height limits)
- Temporal resolution: 2 min
- Latency: ~2-5 min
- Forecast horizon: Observation only

## Format, licence, cost
- Format: GRIB2.gz (MRMS) / PNG (WMS)
- Licence / attribution: NOAA public domain.
- Cost: Free

## Endpoints
- https://registry.opendata.aws/noaa-mrms-pds/
- https://noaa-mrms-pds.s3.amazonaws.com/?list-type=2&prefix=CONUS/MergedBaseReflectivityQC_00.50/YYYYMMDD/
- https://nowcoast.noaa.gov/geoserver/observations/weather_radar/ows?service=WMS&request=GetCapabilities (layer base_reflectivity_mosaic)

## Auth
None

**Rate limits:** None stated.

## Who uses it
- Apps: SkeeterCast (NEXRAD); Windy (radar)
- SkipperCast layer: Weather (radar overlay)

## Connect and download
```bash
curl -o radar.png "https://nowcoast.noaa.gov/geoserver/observations/weather_radar/ows?service=WMS&version=1.3.0&request=GetMap&layers=base_reflectivity_mosaic&styles=&crs=EPSG:4326&bbox=34,-123.5,37,-119.5&width=800&height=600&format=image/png&transparent=true"
K=$(curl -s "https://noaa-mrms-pds.s3.amazonaws.com/?list-type=2&prefix=CONUS/MergedBaseReflectivityQC_00.50/$(date -u +%Y%m%d)/" | grep -o '<Key>[^<]*</Key>' | sed 's/<[^>]*>//g' | tail -1)
curl -o mrms.grib2.gz https://noaa-mrms-pds.s3.amazonaws.com/$K
```

**Cadence:** Online: WMS directly in MapLibre (no ingest). Offline/animation: every 10 min keep last 2 h.

**Pipeline fit:** Direct WMS raster source; MRMS GRIB only if we want our own palette.

**Sample on box:** samples/nowcoast_radar_centralcoast.png and samples/mrms_MergedBaseReflectivityQC_latest.grib2.gz (850 KB CONUS)
