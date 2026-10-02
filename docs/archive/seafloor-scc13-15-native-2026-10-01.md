# SCC13–15 native source release

Qualify three existing original CSUMB 2 m rows in place, preserving source order, original/normalized checksums, native masks, requested windows, survey dates and datum. [NOAA Block13](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block13_mb.html), [Block14](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block14_mb.html) and [Block15](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block15_mb.html) distribute these original products. No original 5 m bathymetry grid was found in these archives; generic producer depth-range text was not treated as such a product.

These are existing private measurements, so **new measured area is zero**. Only reviewed rights, status and notes change. Native 2 m spacing, NAVD88 Geoid09 and original 2010 metadata remain; producer depth-dependent accuracy estimates have no stated confidence level and are not per-cell uncertainty. Missing uncertainty and measured/interpolated masks remain unknown. Source-only receipts retain exact provenance and credited noncommercial terms.

## Bounded processing and evidence

Process r04–r06 as the three-reach batch and refresh the already processed r03 boundary separately because Block13 overlaps it. Compare all four with the current parent source configuration, not the older rollout ledger. Normal processing is required when the complete source set differs; no thresholds or exclusions change.

| Reach | Selected valid km² before → after | Physical before → after | Screened before → after | Habitat km² before → after |
| --- | --- | --- | --- | --- |
| morro-bay-r03 | 30.352066 → 30.351222 | 286 → 333 | 260 → 305 | 4.537233 → 5.417559 |
| morro-bay-r04 | 12.000923 → 11.854559 | 57 → 287 | 56 → 278 | 0.802624 → 2.315563 |
| morro-bay-r05 | 19.861929 → 19.302560 | 145 → 339 | 144 → 318 | 0.960831 → 3.373913 |
| morro-bay-r06 | 60.023595 → 59.525159 | 412 → 415 | 379 → 383 | 9.015918 → 8.931421 |

Net: +474 physical candidates, +445 screened areas, +4.721851 km² habitat. Selected valid footprint decreases 1.205012 km² under the retained source-selection rules; Tier 1 planning-cell area is unchanged. This is improved detail and release of existing survey evidence, not new surveyed geography.

Final output: 1,374 physical candidates, 1,284 passing and 90 held. Every passing polygon has zero intersections or boundary touches with current CDFW, NOAA and security exclusions; depth and 1–3 habitat-fit checks also pass. The October 2 05:30 UTC snapshot is retained. Held geometry remains private. No public deployment is claimed by this local result.

Offline validation: 45 passed, 15 warnings, 3510 subtests passed in 2.14s. Private batch receipts retain the exact commands and checksums. Platform outputs were regenerated, and repository/privacy and website checks passed. The scheduled production workflow owns ledger and public archive updates. Source promotion never grants navigation or for-profit permission; [CSUMB noncommercial terms and credit](https://csumb.edu/undersea/sfml-data-library/) remain enforced.
