# SCC09–12 native source release

This batch qualifies seven existing original CSUMB depth rows in place, preserving catalog order, archive and normalized hashes, native masks, requested windows, dates, datum and adapter reviews. SCC09–11 retain their original 2 m and 5 m grids; SCC12 has only an original 2 m grid. No 5 m grid was invented from generic producer descriptions. [NOAA Block09](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block09_mb.html), [Block10](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block10_mb.html), [Block11](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block11_mb.html), and [Block12](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block12_mb.html) are the original distribution records. Source-only review receipts retain exact archive, metadata and raster identities.

These are existing private survey measurements, so **new measured area is zero**. The seven changes affect only reviewed noncommercial rights, status and notes. The original 2010 metadata records NAD83/UTM10N and NAVD88 Geoid09. Producer approximate horizontal/vertical figures remain depth-dependent estimates without a confidence level; no per-cell uncertainty or measured-versus-interpolated mask exists. Native spacing is not positioning accuracy or chart-depth qualification. Multiple resolutions share the same survey lineage.

## Reproducible local result

The previous eligible source configuration was recomputed on the current parent before comparing these same three reaches. This avoids crediting the already qualified SCC07–08 contribution to the new batch. Normal processing was used because source-only parity does not prove the whole-reach private cache has unchanged inputs. No numerical thresholds, source ordering, exclusions or force-rebuild behavior changed.

| Reach | Selected valid km² before → after | Physical before → after | Screened before → after | Habitat km² before → after |
| --- | --- | --- | --- | --- |
| morro-bay-r01 | 43.720556 → 43.135427 | 464 → 461 | 377 → 378 | 4.522069 → 4.850465 |
| morro-bay-r02 | 55.277639 → 54.170952 | 789 → 803 | 753 → 756 | 10.502448 → 10.912568 |
| morro-bay-r03 | 30.873398 → 30.352066 | 208 → 286 | 205 → 260 | 4.273268 → 4.537233 |

Net: +89 physical candidates, +59 screened areas and +1.002481 km² habitat. The selected valid footprint decreases 2.213149 km² because existing native sources replace portions of a broader previously selected product; this is not lost original measurements or new surveyed area. Tier 1 planning-cell area is unchanged.

Final output: 1,550 physical candidates, 1,394 passing and 156 held. Every passing polygon was checked against the current complete CDFW, NOAA and security exclusion geometries; none intersects or touches them. Retained nominal depth bounds and 1–3 habitat-fit constraints passed. Held geometry stays private. The fresh spatial snapshot was retrieved October 2 at 05:30 UTC. This is local proof, not a claim of public deployment.

45 offline tests and 3,510 subtests passed, plus platform regeneration, repository links/privacy and website checks. The workflow owns ledger and public artifact updates; this source PR does not hand-edit generated coverage. [CSUMB attribution and noncommercial restrictions](https://csumb.edu/undersea/sfml-data-library/) remain attached; for-profit use still requires producer permission and the data are not for navigation.
