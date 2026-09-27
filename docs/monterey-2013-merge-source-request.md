# Monterey 300 ft original-source acquisition request

Prepared for NOAA Office for Coastal Management; **not sent**. This is a source-data request, not a fishing-site or navigation claim.

SkipperCast is auditing original measured seafloor cells between Monterey and Point Conception before publishing 200–300 ft fishing targets. The two highest-priority Offshore Monterey research outlines, `usgs-OffshoreMonterey-8ca813f1-023` and `-046`, overlap the 2013 Coastal California TopoBathy Merge (`m2612`) class-13 acoustic points. Both outlines' sampled COPC points carry source ID **12241**. We need the original source and positional/vertical accuracy trail for that ID, not another copy of the merged DEM.

Please identify whether the following delivered project artifacts are available for download or a bounded extract covering the Offshore Monterey area:

1. `Full_DataInventory.xlsx`, including the row and original acquisition/processing source corresponding to point-source ID 12241.
2. The acoustic-source extent geodatabase and seamline/source-priority polygons, with field definitions and lineage from source ID to final point and raster cells.
3. The tiled vertical-accuracy raster and vector layer, void mask, and metadata for the Monterey tiles; specify which values are RMSE, generalized BAG uncertainty, or undefined, and how any confidence level applies.
4. The contributing survey's original soundings, tide/vertical datum, NAD83 realization and epoch, horizontal registration or check-line residuals, CUBE/TPU or other uncertainty product, and transformation method to the final NAVD88/Geoid09 merge.
5. Redistribution and public-map derivative terms for a derived, generalized habitat footprint. No raw vessel track or individual fisher location is requested.

The local audit has paginated all 16,050 objects in the public Geoid18 `2612/` distribution and checked the two published `2612/supplemental/` S3 prefixes. No listed file is the requested accuracy, inventory or acoustic-source-extent deliverable as of September 27, 2026. The [access receipt](../dist/data/monterey-2013-merge-public-asset-access.json) and [lineage gap](../dist/data/monterey-2013-merge-lineage-gap.json) preserve the exact evidence. These listings are not assumed to cover other NOAA holdings.

Acceptance after receipt: match source ID 12241 to its original measured swath and survey dates; establish native depth datum and a defensible upper error across each entire candidate footprint; propagate a documented NAVD88-to-MLLW transformation and its uncertainty; test horizontal source-to-USGS registration; then redo full-area MPA, federal, security, chart, approach and return checks. A source-reported RMSE or missing accuracy pixel is not automatically an upper depth bound. Independent in-situ bottom observations and effort-linked fish records remain separate requirements for a predictive fishing rank.

Public sources: [NOAA InPort m2612](https://www.fisheries.noaa.gov/inport/item/49649), [NOAA/Dewberry 2013 processing report](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/2612/supplemental/ca2013_noaa_topobathy_merge_m2612_final_report.pdf), [USGS Offshore Monterey bathymetry metadata](https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/metadata/Bathymetry_2m_OffshoreMonterey_metadata.xml).
