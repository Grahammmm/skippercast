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
| morro-bay-r01 | 43.155482 → 43.135427 | 462 → 461 |
| morro-bay-r05 | 19.298671 → 19.302560 | 338 → 339 |

All five useful SCC10–13 intersections completed. Selected measured footprint **160.202593626 → 158.814720102 km² (-1.387873524)**; Tier 1 unchanged at 166.517500 km². Physical candidates **1,876 → 2,223 (+347 net)**; 2,119 supported fits and 104 unknown. This is detail refinement, not geographic expansion. Finer/newer per-cell ownership changes masks and patch segmentation; retain the negative coverage result. Species-specific 1–3 ranking is unchanged (3 strongest); no fish presence or confirmed rock substrate asserted.

All five private runs completed with no incomplete terrain. Every candidate is nonexportable and checked within the nominal depth limit. No raw archive, original metadata bodies or private geometry committed. **Zero new live or exportable locations.**

### SCC12 companion assessment

[Original publisher](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block12_mb.html) supplies two native 2 m classification grids and 100-point visual accuracy assessment. Exact members, hashes, footprints and observed code counts are retained in `scc12-companion-assessment-2026-10-01.json`. The rough/smooth layer derives from the same bathymetry, using VRM threshold 0.0006 and a hand-drawn artifact mask. The 99% agreement compares this classification with visual interpretation of the same hillshade; it is not depth error, video/sample ground truth, confirmed hard substrate or independent corroboration. Do not convert smooth to verified sand or rough to verified rock. Retain as terrain cross-check, with confidence unchanged.

## Validation and release

Full GIS suite: 1,050 passed, 14 allowlisted skips, 4,048 subtests; strict skip report passed; platform generation, repository/web checks and diff checks passed. Source-only change; no app, adapter or science threshold changes. Exact statistics remain in private test receipts. Depends on #172; reconcile onto fresh main and obtain independent review/exact-head checks before merging. Producer rights and current whole-polygon MPA/security screening remain required before publication/export. #160 is now merged on main; this does not itself release the physical-only rows.

Next: reconcile four already computed reach receipts with rights-only source-row changes using the existing verified adoption path; inspect remaining coverage gaps against actual native masks. Seek independent backscatter/video/sample evidence for substrate instead of treating SCC12 DEM-derived labels as field truth. Review original-mask versus selected-mask gaps before classifying any coastline as genuinely unavailable. Release reconciliation and live verification remain unfinished; Monterey–Point Conception goal stays active.
