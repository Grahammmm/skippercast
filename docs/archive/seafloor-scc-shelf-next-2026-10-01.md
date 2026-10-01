# Native outer Cambria and Arguello shelf batch

Inspect original SCC05, SCC15 and SCC23 archives, including the native SCC05
5 m bathymetry companion. Three archives total 387,645,839 bytes. Original
HTTP download links were fetched at the identical HTTPS host/path through the
checked downloader. No downloader prefix, source review, depth or rights guard
was relaxed.

| Native grid | Acquisition dates | Nominal 0–300 ft pixels |
| --- | --- | ---: |
| [csumb-scc-block05-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block05_mb.html) | 20100415, 20100427, 20100813, 20100818 | 6,731,576 |
| [csumb-scc-block05-5m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block05_mb.html) | 20100415, 20100427, 20100813, 20100818 | 150,210 |
| [csumb-scc-block15-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block15_mb.html) | 20100826 | 441,901 |
| [csumb-scc-block23-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block23_mb.html) | 20101017, 20101020, 20101021, 20101028 | 5,431,647 |

Exact inspected raster bounds, members, hashes and dates are in
`catalog/csumb-scc-shelf-next-native-sources.json`. Native metadata documents
NAVD88/Geoid09. Spacing is not sounding accuracy; per-cell uncertainty and
interpolation remain unknown. The 2 m and 5 m SCC05 grids share acquisition,
not independent corroboration. Native bathymetry was selected, never hillshade
or slope. No raw survey archive or private habitat geometry is committed.

## Actual processing and ownership

| Reach | Valid native km² before → after | Physical candidates before → after |
| --- | ---: | ---: |
| morro-bay-r05 | 19.861929 → 19.791558 | 145 → 148 |
| morro-bay-r06 | 60.023595 → 59.724631 | 412 → 415 |
| cambria-san-simeon-r02 | 8.584172 → 20.891791 | 60 → 108 |
| cambria-san-simeon-r01 | 36.387533 → 49.222894 | 361 → 361 |
| point-arguello-conception-r04 | 17.461749 → 37.388524 | 66 → 93 |

Selected valid area increased by **44.700419348 km²**;
planning Tier 1 by **47.163125000 km²**. Physical candidates
increased by **81 net**. Of 1,125 resulting candidates,
1,076 have supported lingcod/reef-rockfish ranks and 49 remain unknown.
Rank 3 is strongest in the existing species-specific rubric.

The 5 m companion owns 1.688537327 km² in northern Cambria/San Simeon after
standard finest/newest source selection. Its 150,210 shallow pixels are not
all additive coverage. SCC15 replaces portions of existing mapping (5 cells
in Morro r05 and 41 in r06); six changed candidates are not evidence of an
independent new fishing ground. The committed summary retains ownership
measurements, before/after totals and rank distributions without geometry.
All five runs completed. Baselines and candidate geometry remain privately
saved for diagnostic comparison. No new reach IDs are claimed in this batch.

## Publication and validation

All new rows/results remain physical-only. Explicit
[producer contract review](https://csumb.edu/undersea/sfml-data-library/),
retained checked physics adoption, current whole-polygon MPA/security screen,
regional archive/export and live UI verification remain required. Existing
public outputs are preserved. No new public or exportable locations.

1,050 Python tests passed; 14 allowlisted private-cache skips and 3,887
subtests. Strict skip report, platform regeneration, repository/web/diff
checks passed. App unchanged; prior hosted browser checks apply to it.
All earlier catalog rows remain unchanged. Reconcile onto fresh main,
independent review and exact-head CI before merge.

Next original batch: inspect SCC06, SCC14 and SCC24; use actual native
reference intersections to prioritize southern Morro/remaining shelf gaps.
Saved reach inventory is diagnostic, not independently verified public coverage.
The full Monterey–Point Conception objective remains active.
