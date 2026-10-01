# Native middle Morro Bay batch — October 1, 2026

Qualify six original native depth-band grids from NOAA-hosted CSUMB SCC10–13 archives. All prior 427 catalog records are unchanged; 433 total. Original archives total **928,361,755 bytes**. Retain original hashes, actual native footprints, acquisition dates and source grid spacing in `catalog/csumb-scc-midcoast-native-sources.json`.

| Original source | Spacing | Valid nominal 0–300 ft pixels | 200–300 ft pixels |
| --- | ---: | ---: | ---: |
| [SCC_Block10](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block10_mb.html) | 2 m | 4,537,986 | 1,163,853 |
| [SCC_Block10](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block10_mb.html) | 5 m | 162,392 | 162,392 |
| [SCC_Block11](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block11_mb.html) | 2 m | 6,744,160 | 1,738,753 |
| [SCC_Block11](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block11_mb.html) | 5 m | 59,727 | 59,727 |
| [SCC_Block13](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block13_mb.html) | 2 m | 6,481,676 | 1,624,291 |
| [SCC_Block12](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block12_mb.html) | 2 m | 7,915,642 | 711,797 |

Native acquisition dates agree with per-block 2010 abstracts. Processing specifies NAVD88/Geoid09. Separate uncertainty and interpolation masks remain unknown; native grid spacing is not sounding accuracy. The 2 m/5 m depth-band companions share acquisition lineage and are not independent evidence. SCC12 uses the observed singular bathygrid archive name; hillshade and slope are excluded. SCC12 and SCC13 reach only 76.02 and 74.59 m; they do not cover the entire 300-foot depth band. SCC10/11 have native 5 m outer-band support; only valid positive depths <=91.44 m enter processing.

## Actual measured result

| Reach | Selected valid km² before → after | Physical candidates before → after |
| --- | ---: | ---: |
| morro-bay-r02 | 55.062084 → 54.170952 | 792 → 803 |
| morro-bay-r03 | 30.873398 → 30.351222 | 208 → 333 |
| morro-bay-r04 | 11.812959 → 11.854559 | 76 → 287 |

Selected measured footprint **97.748440548 → 96.376732896 km² (-1.371707652)**; Tier 1 unchanged at 100.713125 km². Physical candidates **1,076 → 1,423 (+347 net)**; 1,339 supported fits and 84 unknown. This is detail refinement in three existing reaches, not new geographic expansion. Finer/newer per-cell ownership changes selected masks and patch segmentation; preserve the negative coverage result. Existing species-specific 1–3 suitability ranking is unchanged (3 strongest). No fish presence or confirmed rock substrate asserted.

All three runs completed, no incomplete terrain, every candidate private/nonexportable and checked within the nominal depth limit. No raw archive, original metadata bodies or private geometry committed. **Zero new live or exportable locations.**

## Validation and release

Full GIS suite and strict skip report passed; platform generation, repository/web checks and diff checks passed. Source-only change; no app, adapter or science threshold changes. Exact statistics remain in private test receipts. Depends on #172; reconcile onto fresh main and obtain independent review/exact-head checks before merging. Producer rights and current whole-polygon MPA/security screening remain required before publication/export. #160 is now merged on main; this does not itself release the physical-only rows.

Next: finish useful SCC10–13 intersections in morro-bay-r01/r05, then inspect SCC12 habitat/accuracy companions to add substrate and quantified quality where justified. Review original-mask versus selected-mask gaps before classifying any coastline as genuinely unavailable. Release reconciliation and live verification remain unfinished; Monterey–Point Conception goal stays active.
