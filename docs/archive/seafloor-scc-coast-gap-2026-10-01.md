# Native Cambria, Morro and Arguello shelf batch

Original SCC06, SCC14 and SCC24 archives total 549,156,605 bytes. Inspect
their native 2 m bathymetry grids through the existing bounded archive adapter.
Original HTTP links were fetched at identical HTTPS host/path through the
checked downloader. No source, datum, resolution, depth or rights guard relaxed.

| Native grid | Embedded acquisition dates | Nominal 0–300 ft pixels |
| --- | --- | ---: |
| [csumb-scc-block06-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block06_mb.html) | 20100324, 20100328, 20100329, 20100416, 20100528, 20100811, 20100812 | 7,065,502 |
| [csumb-scc-block14-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block14_mb.html) | 20100824, 20100825, 20100826 | 4,740,760 |
| [csumb-scc-block24-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block24_mb.html) | 20100918, 20101006, 20101012, 20101014, 20101015, 20101017 | 8,422,731 |

Exact bounds, members, original hashes and native metadata evidence are in
`catalog/csumb-scc-coast-gap-native-sources.json`. NAVD88/Geoid09 and actual
2010 dates are retained. Spacing is not sounding accuracy; per-cell uncertainty
and interpolation remain unknown. Only actual valid shallow pixels count.
No hillshade or slope was used, and no raw survey/private geometry committed.

## Actual measurements

| Reach | Valid native km² before → after | Physical candidates before → after |
| --- | ---: | ---: |
| morro-bay-r04 | 12.000923 → 11.812959 | 57 → 76 |
| morro-bay-r05 | 19.791558 → 19.298671 | 148 → 338 |
| morro-bay-r06 | 59.724631 → 59.525159 | 415 → 415 |
| cambria-san-simeon-r02 | 20.891791 → 46.423921 | 108 → 237 |
| cambria-san-simeon-r01 | 49.222894 → 49.222894 | 361 → 361 |
| point-arguello-conception-r04 | 37.388524 → 66.881588 | 93 → 104 |
| point-arguello-conception-r05 | 0.000000 → 2.143088 | 0 → 14 |

Selected valid coverage increased by **56.287958760 km²**,
planning Tier 1 by **59.359375000 km²** and physical candidates
by **363 net**. Of the resulting 1,545 candidates,
1,470 have supported lingcod/reef-rockfish rankings and 75 remain unknown.
Rank 3 is strongest in the existing species-specific rubric.

All seven runs completed. Arguello r05 previously had a successful run with
zero measured area/candidates; it now has 2.143088202 km² and 14 candidates.
This is new measured coverage, not a newly created reach ID. Fine/newest source
selection can reduce prior selected area while improving native source detail;
neither overlapping surveys nor changed outlines are independent fish grounds.
Before summaries and candidate geometry remain privately saved. Source ownership
and rank distributions are retained in the committed proof without geometry.

## Remaining southern Morro source gap

The SCC06/14/24 native windows do not prove coverage for Morro r09/r10. Do not
interpolate missing pixels or mark those reaches complete. Fresh
[USGS Point San Luis source metadata](https://pubs.usgs.gov/sim/3327/downloads/metadata/Contours_PointSanLuis_metadata_faq.html)
was HTTP 403 initially, then recovered HTTP 200 with a browser user agent.
It explicitly identifies original 2009 Morro–Avila 2 m/5 m grids and
2011 PGE update grids, with observed legacy CSUMB ZIP links. The old
CSUMB catalog currently has a hostname/certificate mismatch; no TLS bypass.

The official [NOAA Ventresca directory](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/)
responds HTTP 200 and lists CC_BlockA02/A03 and
[PGE_AvilaBay](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/PGE_AvilaBay/).
These are specific original-mirror leads, not native qualification or coverage.
Observe actual product links, inspect native masks/datum/date and compare exact
reference intersections next. USGS compiled contours also use NOAA DEM inputs;
they cannot substitute for original measured habitat or independent evidence.
Private access receipts are saved in this batch. No native access for these
leads is claimed here.

## Release and validation

All additions remain physical-only; no new live or exportable fishing locations.
Explicit [producer rights review](https://csumb.edu/undersea/sfml-data-library/),
checked retained-physics adoption, current whole-polygon MPA/security screens
and regional archive/export/live UI verification remain mandatory.
All previous catalog rows are unchanged.

1,050 Python tests passed; 14 allowlisted private-cache skips and 3,908
subtests. Strict skip report, platform regeneration, repository/web/diff
checks passed. App unchanged; prior hosted browser checks apply. Reconcile
stacked sources onto fresh main, independent review and exact-head CI before
merge. Next acquisition: observed CC_BlockA02/PGE_AvilaBay original products
and SCC25, prioritizing actual southern Morro and remaining Arguello gaps.
The full Monterey–Point Conception objective remains active.
