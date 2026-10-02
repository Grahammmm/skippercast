# PGE_Mid native shelf coverage

Qualify seven original CSUMB grids from [NOAA's PGE_Mid archive](https://www.ngdc.noaa.gov/ships/ventresca/PGE_Mid_mb.html): Block C and D at 1 m, C/D/E at 2 m, and C/E at 5 m. One 1,469,944,696-byte original archive (SHA256 `731fd34e4f3cb0b976ecccbb53a07953e65d54b3b06af1f1939e76a56b75c851`) supplies these products. The normalized grids retain their actual resolution, valid masks and original checksums. They are overlapping products from a shared acquisition family, not seven independent surveys.

Block C/D metadata combines 2009–2011 acquisition dates; the catalog's latest year is not a per-cell date. These products retain NAVD88 Geoid09; Block E is the 2009 survey with NAVD88 Geoid03. No chart-datum conversion or per-cell uncertainty is invented. Producer gridding uses decimation and AverageGridder; measured/interpolated pixel masks and total quantitative uncertainty remain unavailable. A 1 m grid cell is not a 1 m accuracy claim. The 5 m products add deep shelf context; they do not establish small rock-pile detail.

The [CSUMB producer policy](https://csumb.edu/undersea/sfml-data-library/) permits credited noncommercial use under the reviewed profile. Navigation use remains excluded and for-profit permission has not been obtained. Original archives and private recovery files are not committed; the source-only receipts record provenance and restrictions.

## Measured outcome

Process the two actual intersecting reaches, morro-bay-r07 and r08, through the normal runner. Recompute their baseline using the immediate parent catalog, including prior reviewed releases, rather than comparing with the old rollout ledger. Keep existing source-selection order and rules, and clip valid depths to the nominal 0–91.44 m coverage band. The habitat extraction rules and whole-polygon exclusions are unchanged.

| Reach | Selected valid km² before → after | Physical before → after | Screened before → after | Habitat km² before → after |
| --- | --- | --- | --- | --- |
| morro-bay-r07 | 55.907729 → 55.921422 | 689 → 702 | 417 → 436 | 6.222787 → 3.370612 |
| morro-bay-r08 | 19.712855 → 53.610140 | 477 → 1026 | 468 → 997 | 3.873308 → 7.124017 |

Net selected measured support increases **33.910978 km²**, physical candidates increase **562**, passing areas increase **548**, and passing habitat area increases **0.398533 km²**. Tier 1 planning-cell area increases 38.704375 km²; that cell statistic is not the measured survey footprint. Finer native source selection materially reshapes r07 habitat and reduces its area; the gain is not a sum of input footprints or an assumption that more pixels mean better habitat.

The source worker separately measured 37.894404 km² of additional original shallow-footprint union against prior physical sources, including private sources. That diagnostic uses a different denominator from the pipeline's selected eligible footprint and must not be added to it. The seven shallow source footprints overlap; their areas must not be summed as new geographic coverage.

Final local output contains 1,728 physical candidates, **1,433 passing and 295 held**. All passing polygons have zero intersections or boundary touches with the verified CDFW, NOAA and security exclusions. Habitat depth bounds and species-fit values 1–3 pass. The retained October 2 05:30 UTC screen is current for this local proof; production performs a fresh screen. Held geometry stays private. Local results are not proof of public deployment or fish presence.

## Reproduction and release

Use the standard source qualification/import path and the existing `seafloor run --reach ...` commands. Private receipts preserve original/normalized identities, current-parent baselines, run output hashes, per-reach metrics and screen verification. The production workflow owns generated ledger and public archive updates; this source PR does not replace them manually. Validate the manifest, native coverage, tiled habitat, source rights and screen contracts, then run platform regeneration and repository/web checks. Independent source review and exact-head CI precede protected merge; verify public manifests and archive range responses after publication.

Local validation completed: 72 tests and 3,601 subtests passed; platform regeneration, 2,328-file repository/privacy checks and website checks passed. These are local source/pipeline checks, not a deployment receipt.
