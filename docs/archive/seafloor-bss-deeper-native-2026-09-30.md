# BSS deeper native companions — September 30, 2026

Three original 5 m bathymetry grids fill the deeper edge of already-qualified 2 m CSUMB survey blocks. The original archive bytes were reused and rechecked; no additional download, resampling, scientific threshold change, or separate-survey corroboration is claimed. This batch depends on the source catalog additions in PR #156.

Exact native envelopes, members, archive hashes, acquisition dates and shallow pixels are in `catalog/csumb-bss-deeper-native-sources.json`. All previous catalog rows remain unchanged. Original embedded metadata identifies 2011 acquisitions and NAVD88 Geoid09; the 91.44 m ceiling remains nominal in that datum. Sounding accuracy and interpolation masks remain unknown.

[Producer terms](https://csumb.edu/undersea/sfml-data-library/) permit noncommercial public use with acknowledgment, prohibit navigation use and require express for-profit permission. Each source preserves its dated hash-bound review and credit. NOAA archive hosting grants no government public-domain license.

| Block | Shallow native source pixels | Original archive |
| --- | --- | --- |
| csumb-bss-block03-5m-native | 272096 | [Original](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block03/multibeam/data/version2/products/BSS_Block03_additional_products.tar.gz) |
| csumb-bss-block08-5m-native | 45462 | [Original](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block08/multibeam/data/version2/products/BSS_Block08_additional_products.tar.gz) |
| csumb-bss-block12-5m-native | 12700 | [Original](https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block12/multibeam/data/version2/products/BSS_Block12_additional_products.tar.gz) |

Source pixels are not deduplicated geographic area. Both 2 m and 5 m products come from the same acquisition; the shared source-selection algorithm retains the finest supported cells.

## Ordinary-run measured proof

| Reach | Selected valid km²: before → after | Screened candidates: before → after |
| --- | --- | --- |
| south-big-sur-san-simeon-r02 | 53.117068 → 55.452019 | 543 → 556 |
| south-big-sur-san-simeon-r01 | 35.825691 → 35.920569 | 313 → 314 |
| big-sur-coast-r06 | 22.423225 → 22.668965 | 237 → 239 |
| big-sur-coast-r05 | 23.739810 → 23.761611 | 162 → 164 |

Combined selected-valid footprint: 135.105794485 → 137.803164244 km² (+2.697369759). Tier 1 planning-cell area: 143.755 → 146.969375 km² (+3.214375). Screened habitat area: 25.163712049 → 25.338007336 km² (+0.174295287). Physical candidates: 1,404 → 1,426 (+22); screened: 1,255 → 1,273 (+18); held: 149 → 153. All four intersecting reaches processed successfully, and their current whole-polygon screens passed for the reported release candidates.

These are local processed results. Generated ledger and private candidate geometry are excluded from this source PR. No new live locations are claimed. Required source/rights/ArcInfo adapter checks passed: 26 tests and 3,112 subtests. Full Python suite: 1,046 passed, 14 allowed private-cache skips, 3,844 subtests passed. Platform regeneration, repository, web and diff checks passed. Exact-head hosted CI, independent review and normal production publication remain required.
