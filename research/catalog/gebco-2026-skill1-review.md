# Skill 1 review: GEBCO_2026

Checked 2026-10-20. Metadata and terms only. The grid file was not downloaded. No layer was added. Publication waits for N-13.

Verdict: adopt-with-limits.

## 1. Rights and attribution (grid)

Checked on gebco.net, not from a secondary summary.

- Terms: https://www.gebco.net/data-products/gridded-bathymetry/terms-of-use
- Product: https://www.gebco.net/data-products-gridded-bathymetry-data/gebco2026-grid
- Download index: https://www.gebco.net/data-products/gridded-bathymetry-data
- DOI: https://doi.org/10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa

The terms page says the GEBCO Grid is in the public domain and may be used free of charge. Users may copy, publish, distribute, transmit, adapt and commercially exploit it. Users must acknowledge the source, must not suggest that GEBCO, the IHO or the IOC endorses the use, and must not misrepresent the grid. The disclaimer says the grid should not be used for navigation or for any other purpose involving safety at sea. It is provided as is. Resolution of a cell may differ from the underlying measurements.

That matches CI3 section 4: acknowledge, no implied endorsement, not for navigation.

Credit line to put in front of N-13, from the 2026 product page (the download index omits the publisher clause):

GEBCO Bathymetric Compilation Group 2026 (2026). The GEBCO_2026 Grid - a continuous terrain model for oceans and land at 15 arc-second intervals. NERC EDS British Oceanographic Data Centre NOC. doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa

A layer basis must also say not for navigation, and must not imply endorsement.

The download index still links one "more information" sentence to the 2025 grid page. The download table and the 2026 product page are the sources used here. Do not bind GEBCO_2025.

Official file, not downloaded this pass: https://dap.ceda.ac.uk/bodc/gebco/global/gebco_2026/ice_surface_elevation/netcdf/GEBCO_2026.zip?download=1 (published size 4 GB, 7.0 GB uncompressed). The TID grid is a separate file on the same index.

## 2. Undersea feature names

Checked https://www.gebco.net/data-products/undersea-feature-names on 2026-10-20.

Names may be shown as labels. The page asks for this citation when gazetteer data are used or reproduced in reports, presentations and other products:

IHO-IOC GEBCO Gazetteer of Undersea Feature Names, www.gebco.net

That citation is not the grid's public-domain grant. The terms page covers the GEBCO Grid and other GEBCO-derived information products. The gazetteer is a SCUFN name list hosted by the IHO Data Centre for Digital Bathymetry at NOAA NCEI. The page does not say the name list is public domain, and it does not grant commercial redistribution of the database.

The ArcGIS feature service metadata was retrieved the same day. Capabilities are Query and Extract. Layers are point, line and polygon. The copyrightText field is present on the service document; its exact wording was not re-read this pass, so no specific copyright sentence is claimed. No feature rows were downloaded, so no in-box count is claimed. Service: https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/Undersea_Features/FeatureServer

Limits on labels:

- Show the citation above. Do not add the grid public-domain sentence as if it covered the names.
- A point is a published position, not the extent of the canyon, bank or seamount, and not a surveyed name.
- Do not draw a gazetteer name inside a reviewed-survey extent when it conflicts with a surveyed name.
- IHO-IOC B-6 (edition 4.2.0, section I.A) limits international naming concern to features entirely or mainly (more than 50 percent) outside the territorial sea, not exceeding 12 nautical miles from the baselines. Source: https://iho.int/uploads/user/pubs/bathy/B-6_e4.2.0_EnglishKorean_2021.pdf. A gazetteer name inside that limit is not, by itself, an international name. Say "gazetteer name" rather than "chart name".
- Display of names waits for N-13, same as the grid.

## 3. Coverage, resolution, overlap

The published grid is global, 15 arc-second, pixel-centre, 43200 by 86400, elevation in metres, horizontal datum WGS84. Vertical values are assimilated as mean sea level. The product page says some shallow-water cells use another vertical datum.

15 arc-seconds is 463 m of latitude. Longitude spacing at the region latitudes is about 344 m at 42 N and about 391 m at 32.5 N. CI3's "~450 m" is the latitude figure, not a measured California cell size.

The 15 region packages and their bounds (west, south, east, north), read from regions/<id>/region.json on this branch:

| Region | West (offshore edge) | South | East | North | East-west span |
| --- | --- | --- | --- | --- | --- |
| crescent-city | -124.75 | 41.55 | -124.05 | 42.0 | 0.70 deg |
| humboldt-bay-cape-mendocino | -124.8 | 40.1667 | -123.9 | 40.95 | 0.90 deg |
| shelter-cove-north-mendocino | -124.8 | 39.45 | -123.6 | 40.1667 | 1.20 deg |
| fort-bragg-point-arena | -124.4 | 38.9583 | -123.25 | 39.45 | 1.15 deg |
| point-arena-bodega | -124.2 | 38.4 | -122.85 | 39.0 | 1.35 deg |
| bodega-point-reyes | -123.7 | 37.95 | -122.7 | 38.5 | 1.00 deg |
| point-reyes-pigeon | -123.3 | 37.1833 | -122.28 | 37.95 | 1.02 deg |
| santa-cruz-monterey-bay | -122.75 | 36.6 | -121.6 | 37.1833 | 1.15 deg |
| monterey-point-sur | -122.35 | 36.3 | -121.65 | 36.625 | 0.70 deg |
| big-sur-coast | -122.2 | 35.9 | -121.45 | 36.3 | 0.75 deg |
| south-big-sur-san-simeon | -122.0 | 35.66 | -121.2 | 35.9 | 0.80 deg |
| cambria-san-simeon | -121.95 | 35.45 | -120.95 | 35.66 | 1.00 deg |
| morro-bay | -121.95 | 34.95 | -120.55 | 35.85 | 1.40 deg |
| point-arguello-conception | -121.25 | 34.45 | -120.35 | 35.07 | 0.90 deg |
| southern-california | -121.0 | 32.5 | -117.05 | 34.45 | 3.95 deg |

Union of those bounds: -124.8, 32.5, -117.05, 42.0. Every region box sits inside the global grid. The west value is the offshore edge of the package, not fishing_bounds. Whether a 4800 ft contour falls inside a given box is a later contour job. This review does not claim that it does.

Reviewed shelf grids stay first. CI6-13 draws shelf contours only from reviewed survey grids and noaa-bluetopo, and stops where that reviewed coverage ends. noaa-bluetopo is still a catalog candidate, not an approved source. surveys.json is an inventory, not a statewide measured mask. This review does not invent that mask.

Overlap rules for the follow-up contour card:

1. A reviewed shelf cell wins. Do not draw a GEBCO contour inside a cell CI6-13 treats as reviewed survey or source-reviewed BlueTopo.
2. GEBCO starts at the outer edge of that reviewed valid-cell extent and runs to the region bounds. It does not stop at fishing_bounds, and it does not cross into a neighbour's package.
3. Do not blend, average or feather elevations across the join. Clip the line. Do not smooth it across the two sources.
4. Each line carries its source. A GEBCO line names GEBCO_2026, 15 arc-second, mean sea level (not MLLW, not NAVD88), and the TID class.
5. TID 10-17 are direct measurements at the grid spacing, still not a survey substitute. TID 40, 41, 70 and 71 are predicted, interpolated or unknown. Omit them, or draw them as estimated and never as surveyed depth.
6. State the datum break at the join. Do not connect a GEBCO contour to an MLLW or NAVD88 contour as one line.
7. Do not fill a reviewed-grid nodata hole with GEBCO. Those holes stay gaps.
8. GEBCO does not qualify a fishing target, an image or an export.
9. Use the ice-surface elevation release for California. The sub-ice release differs in Greenland and Antarctica, not here. Do not adopt the test multi-resolution product.
10. Replace the product when a later GEBCO grid is current. Do not keep drawing GEBCO_2026 after the catalog points at a successor without a new Skill 1 check.

## 4. Verdict

adopt-with-limits.

The grid may be used for offshore depth context past reviewed shelf grids, with the credit line, the no-endorsement line, and the not-for-navigation line. It must not replace a reviewed shelf grid, must not be treated as chart datum, and must not be drawn from predicted cells as if they were soundings.

Gazetteer names may be shown as labels with the citation in section 2, and not under the grid's public-domain grant.

This adopt does not publish anything. N-13 still has to record display yes/no, offline-pack caching yes/no, and the credit text, separately for the grid and for the names, before the contour card or the label card is created.

Unpublished candidates, not approved sources:

- catalog/candidates/gebco-2026-grid.json
- catalog/candidates/gebco-undersea-feature-names.json
