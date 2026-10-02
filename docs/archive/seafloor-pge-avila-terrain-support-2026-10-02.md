# Avila native terrain support — October 2, 2026

Bind the original Block I and J rough/smooth classifications to their exact 2 m depth grids. Block I remains usable under credited noncommercial terms; Block J retains its private status and quality hold. This adds **zero new measured coverage** and changes no application thresholds, depth limits or ranks formula.

## Evidence and limitations

The source receipt `research/receipts/seafloor-pge-avila-native-terrain-review.json` pins the original archive, grid members, XML hashes and native alignment. It preserves the producer-reported 2009 NAVD88 GEOID03 metadata for I and the unknown date/datum for the exact J 2 m depth member. The separately documented 5 m product does not establish J 2 m metadata. No matching 5 m class is bound.

Block I's original metadata report a 0.0003 rugosity threshold and 96/100 agreement, with nine rough reference points. J's accuracy table reports 100/100 agreement but includes only one rough reference point; its summary instead repeats I's 96/100 result and reports 0.0003. That internal inconsistency is retained. Sampling design and reference independence are unverified; these are not habitat-confidence percentages. The classifications derive from the same bathymetry and include subjective artifact handling, not an independent substrate survey or comprehensive artifact mask.

## Public comparison

The comparison includes every shared-calibration contributor, not only features attributed to I. Valid measured cells are identical. Across three previously processed reaches, physical outlines change 1,382 → 1,138 and screened outlines 1,336 → 1,111. Eligible habitat area changes 12.752006222 → 5.744093091 km². These are interpretation refinements, not new survey acquisitions or loss of measured depth. The southern reach still has measured coverage even though no supported habitat patch survives.

| Reach | Selected valid km², unchanged | Physical before → after | Screened before → after |
| --- | ---: | ---: | ---: |
| morro-bay-r08 | 60.95992344 | 1022 → 992 | 984 → 967 |
| morro-bay-r09 | 29.619600544 | 200 → 146 | 198 → 144 |
| morro-bay-r10 | 6.040838581 | 160 → 0 | 154 → 0 |

All 1,111 eligible polygons have zero intersections with current configured CDFW, NOAA and security exclusions. Species fit 1–3 and nominal product depth limits were checked. The committed public ledger is untouched; the production workflow owns its refresh.

## Private comparison

All four affected private reaches were compared against the integrated Mid/South source state. Their physical candidate count changes from 3,131 to 2,004. A separate native check covers all 162 direct I candidates in these private outputs, with three additional visual samples; identical counts do not imply identical geometry. J produces no direct candidate. Their valid depth cells and measured selection are identical; every physical candidate stays held and non-exportable. The public and private tables overlap geographically and must not be added as coverage.

| Reach | Selected valid km², unchanged | Private physical before → after | Public candidates |
| --- | ---: | ---: | ---: |
| morro-bay-r08 | 112.082476716 | 1050 → 1012 | 0 → 0 |
| morro-bay-r09 | 35.781702324 | 201 → 146 | 0 → 0 |
| morro-bay-r10 | 59.241373997 | 1003 → 0 | 0 → 0 |
| point-arguello-conception-r01 | 71.241712598 | 877 → 846 | 0 → 0 |

## Native review

All 162 direct Block I physical candidates received native numeric checks. Eighteen deterministic samples on six pages show localized ridges, outcrops and margins, with no inferred independent substrate observation. Native class NoData is not used as habitat support. The review does not establish exhaustive artifact absence, depth accuracy or fish presence. Block J remains private with its existing quality hold.

The minimum native-center rough-support fraction is 0.992424; all selected centers have class data. Checked source-native depths span 6.71–30.43 m. The research-only audit helper checks original cells without resampling. Private diagnostic geometry/images are retained outside the repository. Original caches were reused; a missing local South cache was restored from a checked local clone, not downloaded again.

The combined `research/receipts/seafloor-pge-avila-terrain-binding-review.json` records before/after measurements, all contributing-source counts, hashes and screen checks. Publication requires the normal current source/right/spatial gates and verified public read-back.
