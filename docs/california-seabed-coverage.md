# California seabed coverage and promotion gate

SkipperCast can browse the California coast, but precise, species-specific fishing grounds require finer evidence than statewide map visibility. Do not label a catalog-linked survey, a rectangular metadata bound, or a filename as a target.

The automated source inventory now reads the [USGS California State Waters Map Series catalog](https://pubs.usgs.gov/ds/781/) and the [NOAA NCEI survey catalog](https://www.ncei.noaa.gov/products/bathymetry/hydrographic-surveys). At the 2026-09-23 audit, the USGS catalog exposed 20 map-block catalogs. Seventeen linked both bathymetry and seafloor-character products; 35 original XML metadata records had parseable geographic bounds. Character products span selected blocks between approximately 34.058°–34.482° N near the Santa Barbara Channel and 37.230°–38.640° N around Point Reyes and San Francisco. These bounds are *not* continuous coverage; no claim is made for missing pixels or the rest of the coast. NOAA's separate discovery inventory linked 427 original BAG files across 183 survey leads. All 427 links answered an HTTP HEAD check on 2026-09-23. A survey lead may cover a harbor or bay rather than outer-coast fishing grounds: a BAG linked to the broad Point Reyes–Pigeon sector was titled “San Francisco Bay” in its native metadata.

The USGS San Gregorio character metadata is a useful example of evidence quality: it documents 2 m pixels, video-supervised classification and substrate classes including fine/medium smooth sediment, mixed sediment and rock, rugose rock and boulder, and coarser mobile sediment. [Original XML](https://pubs.usgs.gov/ds/781/OffshoreSanGregorio/metadata/SeafloorCharacter_OffshoreSanGregorio_metadata.xml). Its classification is still historical and does not establish a present fish aggregation or a navigable route.

The reusable promotion sequence for every new coast sector is:

1. Discover official product URLs, dates, rights and download health. Publish explicit gaps and failures.
2. Read original XML and native raster/BAG, record acquisition date, geographic bounds, raster footprint and no-data pixels, horizontal and vertical datum, resolution and uncertainty. Do not infer coverage from a block name or bounding box.
3. Extract seabed classes, depth and terrain metrics at the native resolution; validate against observations where possible. Keep original file hash, metadata hash and provenance on each derived feature.
4. Apply the appropriate region-specific species habitat model, depth rules, season, MPA geometry, closures, security areas and export restrictions. An unverified rule leaves the target pending.
5. Review sample polygons and point placement before publication. Separate historical habitat suitability from dynamic temperature, current and weather evidence; show confidence and freshness on the map.

The daily [data pipeline](../.github/workflows/daily-data.yml) refreshes discovery and metadata inventories about monthly and republishes health to the public data branch. The inventories do **not** automatically promote fishing spots. This conservative boundary prevents stale or mislocated government datasets from silently becoming “best spots” when expanding statewide.
