# Native Cambria and Arguello shelf batch

Three inspected original CSUMB grids fill native shelf gaps without changing
science or publishing private habitat. The observed NOAA publisher pages use
HTTP archive links; only the same host/path over HTTPS was fetched by the
existing original-source downloader. No security prefix was relaxed.

| Source | Native spacing | Embedded acquisition dates | Original bytes |
| --- | --- | --- | ---: |
| [SCC_Block04](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block04_mb.html) | 2 m | 20100320, 20100417, 20100525, 20100526, 20100807, 20100808, 20100809, 20100810, 20100812 | 282,859,139 |
| [SCC_Block16](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block16_mb.html) | 2 m | 20100910, 20100915, 20100916, 20100917, 20110719, 20110721 | 166,763,795 |
| [SCC_Block22](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block22_mb.html) | 2 m | 20101028, 20101029, 20101031, 20101101 | 177,562,944 |

Exact inspected raster bounds, archive members and hashes are retained in
`catalog/csumb-scc-conception-native-sources.json`. Bounds schedule processing;
only actual valid pixels intersected with the reference cells count as coverage.
Original metadata documents NAVD88/Geoid09. SCC16 spans 2010 and 2011, so its
reviewed catalog year remains unknown. Grid spacing is not sounding accuracy;
per-cell uncertainty and interpolation remain unknown. Supplemental habitat,
accuracy and footprint ZIPs are unprocessed leads from the same acquisitions.

Source rows are physical-only. Neither NOAA hosting nor adapter success grants
public-domain rights. The [producer policy](https://csumb.edu/undersea/sfml-data-library/)
and explicit source-release contract must be reviewed before publication.
No private candidate geometry or raw archive is committed. Native bathymetry
was selected rather than hillshade, slope or rendered chart imagery.

The local multiprocessing launcher failed before workers started because macOS
spawn cannot reopen a stdin program. Switched to the existing CLI in bounded
subprocesses; baseline receipts were preserved and processing was not duplicated.
This was an orchestration issue, not a survey or scientific failure.

## Measured processing result

| Reach | Valid native km² before → after | Physical candidates before → after |
| --- | ---: | ---: |
| cambria-san-simeon-r02 | 7.091355 → 8.584172 | 61 → 60 |
| cambria-san-simeon-r01 | 11.159950 → 36.387533 | 156 → 361 |
| south-big-sur-san-simeon-r03 | 67.245018 → 68.276710 | 503 → 500 |
| point-arguello-conception-r01 | 9.007900 → 37.988570 | 325 → 846 |
| point-arguello-conception-r03 | 35.780866 → 41.445755 | 720 → 554 |
| point-arguello-conception-r04 | 0.000000 → 17.461749 | 0 → 66 |

Selected valid area increased by **79.859400661 km²**;
planning Tier 1 by **83.342500000 km²**. Physical candidates
increased by **622 net**. Rank 3 is strongest
in the existing species-specific rubric; unknown stays unknown. Details are
in the committed private-proof summary, without geometry. No fishing locations
were published. Recomputed neighboring counts can decrease when connected
patches and reach-wide thresholds change; changed outlines are not all new spots.

The formerly empty `point-arguello-conception-r04` now has actual source pixels
and habitat candidates. This does not prove all remaining Conception shelf
coverage: retain source gaps and assess the reference denominator per reach.

Validation: 1,050 Python tests passed; 14 allowlisted private-cache skips and
3,859 subtests. Strict skip report, platform regeneration, repository/web and
diff checks passed. Existing browser validation applies to the unchanged app.
Before merge, reconcile stacked source PRs with fresh main, preserve all rows,
obtain independent review and pass exact-head hosted checks. Before any public
map/export, explicitly qualify producer terms, adopt retained checked physics,
apply current whole-polygon MPA/security screens and verify publication and UI.

Next source batch: inspect SCC05, SCC15 and SCC23 originals for Cambria and
Point Sal/Arguello gaps; choose actual reference intersections, not titles.
